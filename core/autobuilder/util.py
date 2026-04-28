"""Shared utility helpers for autopilot builder modules."""
from __future__ import annotations

import re
import time
from pathlib import Path
from typing import Any


def slugify(value: str, fallback: str = "autopilot") -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", str(value or "").lower()).strip("-")
    return slug or fallback


def now_ms() -> int:
    return int(time.time() * 1000)


def rel_path(path: str | Path, root: str | Path) -> str:
    try:
        return str(Path(path).resolve().relative_to(Path(root).resolve()))
    except Exception:
        return str(path)


def clean_list(values: Any) -> list[str]:
    if values is None:
        return []
    if isinstance(values, str):
        raw = re.split(r"[\n,]+", values)
    elif isinstance(values, (list, tuple, set)):
        raw = list(values)
    else:
        raw = [values]
    result = []
    seen = set()
    for item in raw:
        text = str(item).strip()
        if text and text not in seen:
            result.append(text)
            seen.add(text)
    return result


def normalized_box(value: Any) -> list[float]:
    if not isinstance(value, (list, tuple)) or len(value) != 4:
        raise ValueError("normalized box must contain 4 numbers")
    x1, y1, x2, y2 = (float(part) for part in value)
    if not (0 <= x1 < x2 <= 1 and 0 <= y1 < y2 <= 1):
        raise ValueError("normalized box must satisfy 0<=x1<x2<=1 and 0<=y1<y2<=1")
    return [round(x1, 6), round(y1, 6), round(x2, 6), round(y2, 6)]
