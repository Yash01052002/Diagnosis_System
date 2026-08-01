#!/usr/bin/env python
"""Populate a running BlackBox instance with a realistic demo dataset.

`make seed` creates only the roles and the bootstrap admin, which leaves every
screen empty. This fills the platform with a fleet, a month of crash history, a
knowledge base and AI diagnoses, so the dashboard, analytics and alerting all
have something to show.

Everything goes through the public API — devices authenticate with real API
keys and crashes run the full ingest → parse → symbolize → group → alert
pipeline — so the result is data the platform actually produced, not rows
injected behind its back.

Usage::

    # against a local stack (make serve, or docker compose up)
    python scripts/seed_demo.py

    # elsewhere, or with different credentials
    python scripts/seed_demo.py --url https://blackbox.example.com \\
        --email admin@example.com --password 's3cret' --days 60

Re-running is safe: anything that already exists is skipped rather than
duplicated. Requires `httpx` (already a backend dependency).

NEVER point this at production — it creates users, devices and crash reports.
"""

from __future__ import annotations

import argparse
import random
import sys
from datetime import UTC, datetime, timedelta

try:
    import httpx
except ModuleNotFoundError:  # pragma: no cover - dependency hint
    sys.exit("httpx is required: pip install httpx (or run via backend/.venv/bin/python)")

DEFAULT_URL = "http://localhost:8000"
DEFAULT_EMAIL = "admin@blackbox.example.com"
DEFAULT_PASSWORD = "ChangeMe123!"
DEMO_PASSWORD = "Str0ng!Passw0rd"

USERS = [
    ("engineer@blackbox.example.com", ["engineer"], "Priya Raman"),
    ("viewer@blackbox.example.com", ["viewer"], "Sam Okafor"),
]

DEVICES = [
    ("STM32-F4-0001", "SN-2026-000123", "1.4.2", "STM32F407VG", "Lab A, Rack 3",
     ["field-trial", "eu-west"]),
    ("STM32-F4-0002", "SN-2026-000124", "1.4.2", "STM32F407VG", "Lab A, Rack 3",
     ["field-trial"]),
    ("STM32-F7-0007", "SN-2026-000210", "1.5.0", "STM32F746ZG", "Lab B",
     ["pilot", "us-east"]),
    ("STM32-H7-0011", "SN-2026-000311", "1.5.1", "STM32H743ZI", "Field site 4",
     ["production"]),
    ("STM32-L4-0021", "SN-2026-000412", "1.3.9", "STM32L476RG", "Field site 9",
     ["production", "low-power"]),
    ("STM32-F4-0033", "SN-2026-000513", "1.5.0", "STM32F407VG", "Lab C", ["qa"]),
]

DOCUMENTS = [
    (
        "HardFault troubleshooting — FreeRTOS stack overflow",
        "troubleshooting",
        (
            "A HardFault raised inside a FreeRTOS task such as the SensorTask is most often "
            "caused by a task stack overflow. When a task overflows its stack the memory "
            "access traps as a HardFault escalated from a bus fault. Check the CFSR and BFAR "
            "fault registers, enable configCHECK_FOR_STACK_OVERFLOW, and increase the "
            "SensorTask stack depth. A HardFault in a FreeRTOS task usually points at stack "
            "corruption or an invalid pointer dereference."
        ),
    ),
    (
        "Cortex-M4 fault status registers (CFSR/HFSR/BFAR)",
        "arm_cortex_m",
        (
            "The Cortex-M Configurable Fault Status Register (CFSR) records the cause of a "
            "HardFault escalation. A precise bus fault sets BFARVALID and latches the "
            "faulting address into BFAR. The MemManage fault status byte reports an MPU "
            "access violation. Read HFSR to confirm the fault was escalated (FORCED bit) "
            "before decoding CFSR."
        ),
    ),
    (
        "STM32 DMA and ADC interrupt ordering",
        "stm32_reference",
        (
            "When a DMA stream services the ADC, the transfer-complete interrupt can preempt "
            "the ADC end-of-conversion handler. Without a memory barrier the peripheral "
            "register write may be reordered, leaving the DMA stream pointing at a freed "
            "buffer. Disable the stream before reconfiguring it and use __DMB() after the "
            "control register write."
        ),
    ),
    (
        "Watchdog reset handling on STM32",
        "engineering_note",
        (
            "An independent watchdog (IWDG) reset means the refresh loop missed its deadline. "
            "Common causes are a blocking driver call inside a high-priority task and "
            "priority inversion on a shared mutex. Log the reset cause from RCC_CSR at boot "
            "and correlate with the last task that ran."
        ),
    ),
]

#: (fault type, FreeRTOS task, program counter) triples. HardFault repeats so a
#: clear "top root cause" emerges in the grouped views.
FAULTS = [
    ("HardFault", "SensorTask", 0x08001A2C),
    ("HardFault", "SensorTask", 0x08001A2C),
    ("HardFault", "CommsTask", 0x08004F10),
    ("BusFault", "CommsTask", 0x08002000),
    ("UsageFault", "LoggerTask", 0x08003C44),
    ("StackOverflow", "SensorTask", 0x08001A2C),
    ("WatchdogReset", "IDLE", 0x0800BEEF),
    ("MemManageFault", "DisplayTask", 0x08005D08),
]


class Seeder:
    def __init__(self, client: httpx.Client, api: str) -> None:
        self.client = client
        self.api = api
        self.token = ""

    @property
    def auth(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.token}"}

    def login(self, email: str, password: str) -> None:
        base = self.api.removesuffix("/api/v1")
        try:
            response = self.client.post(
                f"{self.api}/auth/login", json={"email": email, "password": password}
            )
        except httpx.HTTPError as exc:
            sys.exit(f"cannot reach the API at {base}: {exc}\nIs the backend running?")
        if response.status_code != 200:
            sys.exit(
                f"login failed ({response.status_code}). Check --email/--password; the "
                f"bootstrap admin is created by `make seed`."
            )
        self.token = response.json()["access_token"]

    def seed_users(self) -> int:
        created = 0
        for email, roles, name in USERS:
            response = self.client.post(
                f"{self.api}/users",
                headers=self.auth,
                json={
                    "email": email,
                    "password": DEMO_PASSWORD,
                    "full_name": name,
                    "roles": roles,
                    "is_active": True,
                },
            )
            created += response.status_code == 201
        return created

    def seed_devices(self) -> dict[str, str]:
        """Register devices and issue an API key for each. Returns {device_id: key}."""
        keys: dict[str, str] = {}
        for device_id, serial, firmware, model, location, tags in DEVICES:
            response = self.client.post(
                f"{self.api}/devices",
                headers=self.auth,
                json={
                    "device_id": device_id,
                    "serial_number": serial,
                    "firmware_version": firmware,
                    "hardware_model": model,
                    "location": location,
                    "tags": tags,
                },
            )
            if response.status_code == 201:
                uuid = response.json()["id"]
            elif response.status_code == 409:
                # Already seeded: look the device up so we can still issue a key.
                found = self.client.get(
                    f"{self.api}/devices", headers=self.auth, params={"q": device_id}
                ).json()["items"]
                if not found:
                    continue
                uuid = found[0]["id"]
            else:
                continue

            key = self.client.post(
                f"{self.api}/devices/{uuid}/api-keys",
                headers=self.auth,
                json={"name": "demo-fleet"},
            )
            if key.status_code == 201:
                keys[device_id] = key.json()["api_key"]
        return keys

    def seed_documents(self) -> int:
        created = 0
        for title, source_type, content in DOCUMENTS:
            response = self.client.post(
                f"{self.api}/knowledge-base/documents",
                headers=self.auth,
                json={"title": title, "source_type": source_type, "content": content},
            )
            created += response.status_code == 201
        return created

    def seed_crashes(self, keys: dict[str, str], days: int, rng: random.Random) -> int:
        """Submit backdated crashes so the trend chart has a month of shape."""
        firmware_by_device = {d[0]: d[2] for d in DEVICES}
        now = datetime.now(UTC)
        submitted = 0

        for day in range(days - 1, -1, -1):
            # Weight recent days more heavily, so the trend visibly rises.
            recency = (days - day) // max(1, days // 4)
            count = rng.choices([0, 1, 2, 3, 5], weights=[3, 5, 4, 3, 1 + recency])[0]
            for _ in range(count):
                device_id = rng.choice(list(keys))
                fault, task, pc = rng.choice(FAULTS)
                when = now - timedelta(
                    days=day, hours=rng.randint(0, 23), minutes=rng.randint(0, 59)
                )
                response = self.client.post(
                    f"{self.api}/crashes",
                    headers={"X-API-Key": keys[device_id]},
                    json={
                        "firmware_version": firmware_by_device[device_id],
                        "build_version": "a1b2c3d",
                        "timestamp": when.isoformat().replace("+00:00", "Z"),
                        "fault_type": fault,
                        "task_name": task,
                        "pc": f"0x{pc:08X}",
                        "lr": f"0x{pc - 0x1D:08X}",
                        "sp": "0x20017FA0",
                        "registers": {
                            "r0": "0x00000000",
                            "r1": "0x20000100",
                            "cfsr": "0x00008200",
                            "bfar": "0x2001FFF0",
                            "xpsr": "0x61000000",
                        },
                        "stack": [f"0x{pc:08X}", "0x20017FB0", f"0x{pc - 0x40:08X}"],
                    },
                )
                submitted += response.status_code == 201
        return submitted

    def triage_and_diagnose(self, limit: int = 8) -> tuple[int, int]:
        """Give a few crashes a triage state, then run the RAG diagnosis on them."""
        items = self.client.get(
            f"{self.api}/crashes", headers=self.auth, params={"page": 1, "page_size": limit}
        ).json()["items"]

        triaged = 0
        for index, item in enumerate(items[:6]):
            if index % 3 == 0:
                body = {
                    "status": "investigating",
                    "notes": "Reproduced on the bench; suspect stack depth.",
                }
            elif index % 3 == 1:
                body = {"status": "resolved"}
            else:
                continue
            triaged += (
                self.client.patch(
                    f"{self.api}/crashes/{item['id']}", headers=self.auth, json=body
                ).status_code
                == 200
            )

        diagnosed = 0
        for item in items:
            response = self.client.post(
                f"{self.api}/crashes/{item['id']}/diagnose", headers=self.auth
            )
            diagnosed += response.status_code == 201
        return triaged, diagnosed

    def summary(self) -> dict:
        return self.client.get(f"{self.api}/analytics/summary", headers=self.auth).json()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Fill a running BlackBox instance with demo data.",
        epilog="Never run this against production.",
    )
    parser.add_argument("--url", default=DEFAULT_URL, help=f"API base URL [{DEFAULT_URL}]")
    parser.add_argument("--email", default=DEFAULT_EMAIL, help="Admin email")
    parser.add_argument("--password", default=DEFAULT_PASSWORD, help="Admin password")
    parser.add_argument("--days", type=int, default=30, help="Days of crash history [30]")
    parser.add_argument("--seed", type=int, default=7, help="RNG seed, for repeatability [7]")
    args = parser.parse_args()

    base = args.url.rstrip("/")
    rng = random.Random(args.seed)

    with httpx.Client(timeout=60.0) as client:
        seeder = Seeder(client, f"{base}/api/v1")

        print(f"→ {base}")
        seeder.login(args.email, args.password)
        print("  authenticated")

        print(f"  users .......... {seeder.seed_users()} created")
        keys = seeder.seed_devices()
        print(f"  devices ........ {len(keys)} with API keys")
        if not keys:
            sys.exit("no devices available to submit crashes with — aborting")
        print(f"  documents ...... {seeder.seed_documents()} indexed")

        print(f"  crashes ........ submitting {args.days} days of history...", flush=True)
        crashes = seeder.seed_crashes(keys, args.days, rng)
        print(f"  crashes ........ {crashes} ingested")

        triaged, diagnosed = seeder.triage_and_diagnose()
        print(f"  triaged ........ {triaged}")
        print(f"  diagnoses ...... {diagnosed} generated")

        stats = seeder.summary()
        print(
            "\nDone. {crashes} crashes across {devices} devices, "
            "{groups} crash group(s), health score {health}%.".format(
                crashes=stats["crashes"]["total"],
                devices=stats["devices"]["total"],
                groups=len(stats["top_root_causes"]),
                health=stats["device_health_score"],
            )
        )
        print(f"Open the app and sign in as {args.email}.")


if __name__ == "__main__":
    main()
