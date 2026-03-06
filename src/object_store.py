# src/object_store.py
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Union

import cv2  # type: ignore


@dataclass(frozen=True)
class PutResult:
    key: str
    path: Path


class ObjectStore:
    """
    A tiny local “S3-like” object store.

    - Keys are POSIX-style paths like:
        xray/overlays/case_id=1/run_id=abcd1234/overlay.png

    - Root dir is a local folder like:
        results/object_store/
    """

    def __init__(self, root_dir: Union[str, Path]):
        self.root_dir = Path(root_dir)
        self.root_dir.mkdir(parents=True, exist_ok=True)

    def _resolve_key(self, key: str) -> Path:
        # Normalize key -> local path under root_dir
        key = key.lstrip("/").replace("\\", "/")
        path = self.root_dir / Path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        return path

    def put_bytes(self, key: str, data: bytes, overwrite: bool = False) -> PutResult:
        path = self._resolve_key(key)
        if path.exists() and not overwrite:
            raise FileExistsError(f"Key already exists (immutable): {key}")
        path.write_bytes(data)
        return PutResult(key=key, path=path)

    def put_text(self, key: str, text: str, encoding: str = "utf-8") -> PutResult:
        path = self._resolve_key(key)
        path.write_text(text, encoding=encoding)
        return PutResult(key=key, path=path)

    def put_json(self, key: str, obj: Dict[str, Any], indent: int = 2) -> PutResult:
        path = self._resolve_key(key)
        with path.open("w", encoding="utf-8") as f:
            json.dump(obj, f, ensure_ascii=False, indent=indent)
        return PutResult(key=key, path=path)

    def put_png(self, key: str, bgr_image) -> PutResult:
        """
        Write an OpenCV image (BGR numpy array) as PNG.
        """
        path = self._resolve_key(key)
        ok = cv2.imwrite(str(path), bgr_image)
        if not ok:
            raise RuntimeError(f"cv2.imwrite failed for: {path}")
        return PutResult(key=key, path=path)
