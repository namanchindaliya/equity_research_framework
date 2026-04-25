"""Atomic filesystem I/O helpers.

All JSON writes go through write_json() which uses a temp-file + rename pattern
to avoid partial writes.  Markdown sidecars use write_md().  Append-only
change logs use append_jsonl() / read_jsonl().
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import TypeVar, Type

from pydantic import BaseModel

M = TypeVar("M", bound=BaseModel)


def read_json(path: Path, model: Type[M]) -> M:
    """Deserialise a JSON file into a Pydantic model."""
    return model.model_validate_json(path.read_text(encoding="utf-8"))


def write_json(path: Path, model: BaseModel) -> None:
    """Atomically write a Pydantic model as indented JSON.

    Writes to a sibling .tmp file first, then renames to the final path.
    This ensures readers never see a partial write.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(model.model_dump_json(indent=2), encoding="utf-8")
    tmp.rename(path)


def write_md(path: Path, content: str) -> None:
    """Write a markdown string, creating parent dirs as needed."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def append_jsonl(path: Path, model: BaseModel) -> None:
    """Append one JSON record to a .jsonl file (one object per line).

    The file is created if it does not exist.  Never truncates existing content.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(model.model_dump_json() + "\n")


def read_jsonl(path: Path, model: Type[M]) -> list[M]:
    """Read all records from a .jsonl file into a list of Pydantic models."""
    if not path.exists():
        return []
    records: list[M] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            records.append(model.model_validate_json(line))
    return records
