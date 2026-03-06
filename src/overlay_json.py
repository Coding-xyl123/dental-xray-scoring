# src/overlay_json.py
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional


def _utc_now_iso() -> str:
    # ISO-8601, always UTC, always ends with Z
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def build_overlay_record(
    *,
    case_id: str,
    run_id: str,
    landmarks: List[Dict[str, Any]],
    measurements: Optional[List[Dict[str, Any]]] = None,
    scores: Dict[str, Any],
    warnings: Optional[List[str]] = None,
    input_meta: Optional[Dict[str, Any]] = None,
    scale_meta: Optional[Dict[str, Any]] = None,
    pipeline: Optional[Dict[str, Any]] = None,
    provenance: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Build a machine-verifiable overlay record.

    PURE:
      - no file IO
      - no environment access
      - deterministic given inputs
    """

    # Normalize lists
    measurements = list(measurements or [])
    warnings = list(warnings or [])

    # Normalize landmarks (x/y should be ints)
    norm_landmarks: List[Dict[str, Any]] = []
    for lm in landmarks:
        lm2 = dict(lm)
        if "x" in lm2:
            lm2["x"] = int(lm2["x"])
        if "y" in lm2:
            lm2["y"] = int(lm2["y"])
        norm_landmarks.append(lm2)

    # Normalize scores (values should be ints)
    norm_scores: Dict[str, int] = {str(k): int(v) for k, v in scores.items()}

    record: Dict[str, Any] = {
        "schema_version": "1.1",
        "case_id": str(case_id),
        "run_id": str(run_id),
        "created_at": _utc_now_iso(),
        "landmarks": norm_landmarks,
        "measurements": measurements,
        "scores": norm_scores,
        "warnings": warnings,
    }

    # Optional blocks (backwards-compatible)
    if pipeline is not None:
        record["pipeline"] = dict(pipeline)

    if input_meta is not None:
        record["input"] = dict(input_meta)

    if scale_meta is not None:
        record["scale"] = dict(scale_meta)

    if provenance is not None:
        record["provenance"] = dict(provenance)

    return record