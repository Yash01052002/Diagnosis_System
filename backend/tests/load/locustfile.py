"""Load test for the BlackBox API.

Two user profiles that mirror real traffic:

* ``FirmwareDevice`` — a fleet device POSTing crash reports with an API key.
  This is the write-heavy, latency-sensitive path (ingest → parse → symbolize).
* ``Engineer`` — a logged-in human browsing crashes, devices and the dashboard.
  This is the read path the analytics queries sit behind.

Run against a *non-production* stack that has been seeded with a device API key
and an engineer account::

    pip install locust
    BASE_URL=http://localhost:8000 \
    DEVICE_API_KEY=bbx_xxx_yyy \
    ENGINEER_EMAIL=engineer@example.com ENGINEER_PASSWORD='Str0ng!Passw0rd' \
    locust -f tests/load/locustfile.py --host "$BASE_URL"

Then open http://localhost:8089 to set the user count and ramp. A headless run::

    locust -f tests/load/locustfile.py --host "$BASE_URL" \
        --users 50 --spawn-rate 5 --run-time 2m --headless
"""

from __future__ import annotations

import os
import random

from locust import HttpUser, between, task

DEVICE_API_KEY = os.environ.get("DEVICE_API_KEY", "")
ENGINEER_EMAIL = os.environ.get("ENGINEER_EMAIL", "engineer@example.com")
ENGINEER_PASSWORD = os.environ.get("ENGINEER_PASSWORD", "Str0ng!Passw0rd")

FAULTS = ["HardFault", "BusFault", "UsageFault", "MemManageFault", "StackOverflow"]
TASKS = ["SensorTask", "CommsTask", "IDLE", "LoggerTask"]


def _crash_payload() -> dict:
    return {
        "firmware_version": f"1.{random.randint(3, 6)}.{random.randint(0, 9)}",
        "fault_type": random.choice(FAULTS),
        "task_name": random.choice(TASKS),
        "pc": f"0x0800{random.randint(0x1000, 0x9FFF):04X}",
        "lr": f"0x0800{random.randint(0x1000, 0x9FFF):04X}",
        "sp": "0x20017FA0",
        "registers": {"r0": "0x00000000", "xpsr": "0x61000000"},
        "stack": ["0x08001A2C", "0x20017FB0"],
    }


class FirmwareDevice(HttpUser):
    """Devices in the field POSTing crashes with an API key."""

    weight = 3
    wait_time = between(1, 5)

    @task
    def submit_crash(self) -> None:
        if not DEVICE_API_KEY:
            return
        self.client.post(
            "/api/v1/crashes",
            headers={"X-API-Key": DEVICE_API_KEY},
            json=_crash_payload(),
            name="/api/v1/crashes [ingest]",
        )


class Engineer(HttpUser):
    """A logged-in engineer browsing the platform."""

    weight = 1
    wait_time = between(2, 8)

    def on_start(self) -> None:
        self.token: str | None = None
        res = self.client.post(
            "/api/v1/auth/login",
            json={"email": ENGINEER_EMAIL, "password": ENGINEER_PASSWORD},
            name="/api/v1/auth/login",
        )
        if res.status_code == 200:
            self.token = res.json().get("access_token")

    @property
    def _auth(self) -> dict:
        return {"Authorization": f"Bearer {self.token}"} if self.token else {}

    @task(4)
    def list_crashes(self) -> None:
        self.client.get("/api/v1/crashes?page=1&page_size=20", headers=self._auth)

    @task(2)
    def dashboard(self) -> None:
        self.client.get("/api/v1/analytics/summary", headers=self._auth)

    @task(2)
    def crash_trend(self) -> None:
        self.client.get("/api/v1/analytics/crash-trend?days=30", headers=self._auth)

    @task(1)
    def list_devices(self) -> None:
        self.client.get("/api/v1/devices?page=1&page_size=20", headers=self._auth)

    @task(1)
    def list_groups(self) -> None:
        self.client.get("/api/v1/crash-groups", headers=self._auth)
