#!/usr/bin/env python
"""Generate a Mermaid ER diagram from the SQLAlchemy metadata.

The diagram is derived from the models, not hand-drawn, so it never drifts from
the schema. Run it after a model change to refresh the committed diagram::

    python scripts/generate_er_diagram.py > ../docs/architecture/er-diagram.md

With no output redirection it writes to that path directly.
"""

from __future__ import annotations

import sys
from pathlib import Path

# Importing the models package registers every table on Base.metadata.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import app.models  # noqa: E402,F401  (side effect: populate metadata)
from app.db.base import Base  # noqa: E402

DEFAULT_OUTPUT = Path(__file__).resolve().parents[2] / "docs/architecture/er-diagram.md"


def _type_name(column) -> str:  # type: ignore[no-untyped-def]
    """A short, Mermaid-safe type label for a column."""
    try:
        name = type(column.type).__name__
    except Exception:  # noqa: BLE001
        name = "unknown"
    return name.lower().replace(" ", "_")


def _mermaid() -> str:
    lines: list[str] = ["erDiagram"]

    for table in sorted(Base.metadata.tables.values(), key=lambda t: t.name):
        lines.append(f"    {table.name} {{")
        fk_columns = {
            col_name for fk in table.foreign_key_constraints for col_name in fk.column_keys
        }
        for column in table.columns:
            markers = []
            if column.primary_key:
                markers.append("PK")
            if column.name in fk_columns:
                markers.append("FK")
            suffix = f" {','.join(markers)}" if markers else ""
            lines.append(f"        {_type_name(column)} {column.name}{suffix}")
        lines.append("    }")

    # Relationships from foreign keys: parent ||--o{ child.
    seen: set[tuple[str, str, str]] = set()
    for table in sorted(Base.metadata.tables.values(), key=lambda t: t.name):
        for fk in table.foreign_key_constraints:
            parent = fk.referred_table.name
            child = table.name
            label = fk.name or "fk"
            key = (parent, child, label)
            if key in seen:
                continue
            seen.add(key)
            lines.append(f'    {parent} ||--o{{ {child} : "{label}"')

    return "\n".join(lines)


def _document(diagram: str) -> str:
    return (
        "# Entity-Relationship Diagram\n\n"
        "> Generated from the SQLAlchemy models by "
        "`backend/scripts/generate_er_diagram.py`. Do not edit by hand — re-run "
        "the script after a schema change.\n\n"
        f"Tables: **{len(Base.metadata.tables)}**\n\n"
        "```mermaid\n"
        f"{diagram}\n"
        "```\n"
    )


def main() -> None:
    document = _document(_mermaid())
    if sys.stdout.isatty():
        DEFAULT_OUTPUT.write_text(document)
        print(f"Wrote {DEFAULT_OUTPUT} ({len(Base.metadata.tables)} tables)")
    else:
        sys.stdout.write(document)


if __name__ == "__main__":
    main()
