# src/hashing.py
from __future__ import annotations

import hashlib
import json
from typing import Any, Dict


def sha256_file(path: str) -> str:
    """Streaming SHA256 for any file."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def canonical_json_bytes(obj: Dict[str, Any]) -> bytes:
    """
    Canonical JSON:
    - sorted keys
    - stable separators (no whitespace variance)
    - UTF-8
    """
    s = json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return s.encode("utf-8")


def sha256_config(config: Dict[str, Any]) -> str:
    """SHA256 of canonicalized config JSON."""
    return hashlib.sha256(canonical_json_bytes(config)).hexdigest()