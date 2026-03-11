# src/integrity.py
from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, Optional

from src.hashing import sha256_file, sha256_config, canonical_json_bytes

def atomic_write_json(data: dict, path: str) -> None:
    """Atomic JSON write to avoid partial/corrupt metadata."""
    d = os.path.dirname(path)
    os.makedirs(d, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", dir=d, delete=False, encoding="utf-8") as tmp:
        json.dump(data, tmp, indent=2, ensure_ascii=False)
        tmp_path = tmp.name
    os.replace(tmp_path, path)


def get_git_commit_hash() -> Optional[str]:
    """Best-effort git commit hash; returns None if not available."""
    try:
        import subprocess

        out = subprocess.check_output(["git", "rev-parse", "HEAD"], stderr=subprocess.DEVNULL)
        return out.decode("utf-8").strip()
    except Exception:
        return None


@dataclass(frozen=True)
class ArtifactRecord:
    path: str  # relative to run_dir
    sha256: str


def write_final_metadata(
    *,
    run_dir: str,
    run_id: str,
    input_path_in_run: str,
    config: Dict[str, Any],
    artifact_paths: Dict[str, str],  # name -> absolute path
    status: str = "SUCCESS",
    error_message: Optional[str] = None,
    schema_version: str = "1.0",
) -> str:
    """
    Writes runs/<run_id>/metadata.json LAST, after artifacts exist.
    Stores artifact SHA256 so verify_run can enforce invariants.
    Returns metadata_path.
    """
    run_dir = os.path.abspath(run_dir)
    meta_path = os.path.join(run_dir, "metadata.json")

    # Hash inputs
    input_sha = sha256_file(input_path_in_run)
    cfg_sha = sha256_config(config)

    # Hash artifacts
    artifacts: Dict[str, ArtifactRecord] = {}
    for name, abs_path in artifact_paths.items():
        abs_path = os.path.abspath(abs_path)
        if not abs_path.startswith(run_dir + os.sep):
            raise ValueError(f"Artifact must be inside run_dir. Got: {abs_path}")

        rel = os.path.relpath(abs_path, run_dir)
        artifacts[name] = ArtifactRecord(path=rel, sha256=sha256_file(abs_path))

    metadata: Dict[str, Any] = {
        "schema_version": schema_version,
        "run_id": run_id,
        "created_at": datetime.utcnow().isoformat() + "Z",
        "status": status,
        "code_version": get_git_commit_hash(),
        "inputs": {
            "image_path": os.path.relpath(os.path.abspath(input_path_in_run), run_dir),
            "image_sha256": input_sha,
            "config_sha256": cfg_sha,
            # Optional but very useful for audits:
            "config_canonical_json": canonical_json_bytes(config).decode("utf-8"),
        },
        "artifacts": {
            name: {"path": rec.path, "sha256": rec.sha256}
            for name, rec in artifacts.items()
        },
    }

    if error_message:
        metadata["error_message"] = error_message

    atomic_write_json(metadata, meta_path)
    return meta_path


def verify_run(run_dir: str) -> None:
    """
    Recompute hashes and fail if mismatch.
    This turns metadata into enforced invariants.
    """
    run_dir = os.path.abspath(run_dir)
    meta_path = os.path.join(run_dir, "metadata.json")
    if not os.path.exists(meta_path):
        raise FileNotFoundError(f"metadata.json not found: {meta_path}")

    with open(meta_path, "r", encoding="utf-8") as f:
        meta = json.load(f)

    # Verify artifacts
    artifacts = meta.get("artifacts", {})
    for name, rec in artifacts.items():
        rel = rec["path"]
        expected = rec["sha256"]
        abs_path = os.path.join(run_dir, rel)
        if not os.path.exists(abs_path):
            raise FileNotFoundError(f"Missing artifact '{name}': {rel}")
        actual = sha256_file(abs_path)
        if actual != expected:
            raise ValueError(
                f"Artifact hash mismatch: {name}\n"
                f"  path: {rel}\n"
                f"  expected: {expected}\n"
                f"  actual:   {actual}"
            )

    # Verify config hash if canonical JSON stored
    inputs = meta.get("inputs", {})
    if "config_canonical_json" in inputs and "config_sha256" in inputs:
        import hashlib

        canon = inputs["config_canonical_json"].encode("utf-8")
        actual_cfg = hashlib.sha256(canon).hexdigest()
        expected_cfg = inputs["config_sha256"]
        if actual_cfg != expected_cfg:
            raise ValueError(
                "Config hash mismatch\n"
                f"  expected: {expected_cfg}\n"
                f"  actual:   {actual_cfg}"
            )

    # Verify input image if it’s stored inside run_dir
    if "image_path" in inputs and "image_sha256" in inputs:
        image_rel = inputs["image_path"]
        image_abs = os.path.join(run_dir, image_rel)
        if os.path.exists(image_abs):
            actual_img = sha256_file(image_abs)
            expected_img = inputs["image_sha256"]
            if actual_img != expected_img:
                raise ValueError(
                    "Input image hash mismatch\n"
                    f"  expected: {expected_img}\n"
                    f"  actual:   {actual_img}"
                )
                
                
                
                
if __name__ == "__main__":
    import sys

    if len(sys.argv) != 2:
        print("Usage: python -m src.integrity <run_dir>")
        sys.exit(1)

    run_dir = sys.argv[1]
    verify_run(run_dir)
    print(f"verify_run passed: {run_dir}")