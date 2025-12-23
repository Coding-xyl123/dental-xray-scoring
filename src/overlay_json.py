# src/overlay_json.py
from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, Optional


def build_overlay_record(
    *,
    case_id: str,
    run_id: str,
    landmarks: list,
    measurements: list,
    scores: dict,
    warnings: list,
    input_meta: Optional[Dict[str, Any]] = None,
    scale_meta: Optional[Dict[str, Any]] = None,
    pipeline: Optional[Dict[str, Any]] = None,
    provenance: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Build a machine-verifiable overlay record.

    This function is PURE:
      - no file IO
      - no environment access
      - deterministic given inputs

    Storage is handled elsewhere (ObjectStore).
    """

    record: Dict[str, Any] = {
        "schema_version": "1.1",
        "case_id": case_id,
        "run_id": run_id,
        "created_at": datetime.utcnow().isoformat() + "Z",
        "landmarks": landmarks,
        "measurements": measurements,
        "scores": scores,
        "warnings": warnings,
    }

    # Optional blocks (backwards-compatible)
    if pipeline is not None:
        record["pipeline"] = pipeline

    if input_meta is not None:
        record["input"] = input_meta

    if scale_meta is not None:
        record["scale"] = scale_meta

    if provenance is not None:
        record["provenance"] = provenance

    return record
