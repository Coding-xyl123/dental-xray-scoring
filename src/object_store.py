# src/object_store.py
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict

import cv2  # type: ignore


@dataclass(frozen=True)
class PutResult:
    key: str
    path: Path
    bytes_written: int


class ObjectStore:
    """
    A minimal, AWS-style storage abstraction.

    Today: Local filesystem.
    Tomorrow: S3 / GCS / any blob store.

    Contract:
      - Callers write artifacts via put_* methods.
      - The store owns path construction + directory creation.
      - Keys should be POSIX-like ("xray/overlays/case_id=123/run_id=abcd/overlay.png")
    """

    def __init__(self, root_dir: Path):
        self.root_dir = root_dir

    def _resolve(self, key: str) -> Path:
        # Normalize "s3-like" keys to a filesystem path
        safe_key = key.lstrip("/").replace("..", "__")
        return self.root_dir / safe_key

    def put_png(self, key: str, image_bgr) -> PutResult:
        path = self._resolve(key)
        path.parent.mkdir(parents=True, exist_ok=True)

        ok = cv2.imwrite(str(path), image_bgr)
        if not ok:
            raise RuntimeError(f"cv2.imwrite failed for path={path}")

        bytes_written = path.stat().st_size if path.exists() else 0
        return PutResult(key=key, path=path, bytes_written=bytes_written)

    def put_json(self, key: str, obj: Dict[str, Any]) -> PutResult:
        path = self._resolve(key)
        path.parent.mkdir(parents=True, exist_ok=True)

        data = json.dumps(obj, indent=2, ensure_ascii=False).encode("utf-8")
        path.write_bytes(data)
        return PutResult(key=key, path=path, bytes_written=len(data))
