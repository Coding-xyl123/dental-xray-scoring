# src/eval_noise_sensitivity.py
from __future__ import annotations

import csv
import json
import random
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from object_store import ObjectStore
from scoring_core import compute_scores_from_points


PROJECT_ROOT = Path(__file__).resolve().parents[1]
OBJECT_STORE_ROOT = PROJECT_ROOT / "results" / "object_store"


# Use ObjectStore for ALL outputs (Step 2 consistency)
STORE = ObjectStore(OBJECT_STORE_ROOT)


@dataclass(frozen=True)
class Point:
    x: int
    y: int

    def jitter(self, delta: int) -> "Point":
        return Point(
            self.x + random.randint(-delta, delta),
            self.y + random.randint(-delta, delta),
        )


def load_overlay_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def find_latest_overlay_json(case_id: str) -> Path:
    # results/object_store/xray/overlays/case_id=1/run_id=XXXX/overlay.json
    base = OBJECT_STORE_ROOT / "xray" / "overlays" / f"case_id={case_id}"
    if not base.exists():
        raise FileNotFoundError(f"Case not found in object store: {base}")

    candidates = sorted(
        base.glob("run_id=*/overlay.json"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    if not candidates:
        raise FileNotFoundError(f"No overlay.json found under: {base}")
    return candidates[0]


def extract_points(record: dict[str, Any]) -> dict[str, Point]:
    pts: dict[str, Point] = {}
    for lm in record.get("landmarks", []):
        pts[lm["name"]] = Point(int(lm["x"]), int(lm["y"]))

    required = ["upper_mid", "lower_mid", "bone_left", "bone_right"]
    missing = [k for k in required if k not in pts]
    if missing:
        raise ValueError(f"Missing landmarks in JSON: {missing}")

    return pts


def main(case_id: str = "1", trials: int = 200, deltas: list[int] | None = None) -> None:
    if deltas is None:
        deltas = [0, 1, 2, 5]  # px jitter levels

    overlay_json_path = find_latest_overlay_json(case_id)
    record = load_overlay_json(overlay_json_path)

    pts = extract_points(record)

    # Required metadata
    img_w = int(record["input"]["width_px"])
    px_per_cm = float(record["scale"]["px_per_cm"])

    baseline = record["scores"]

    # Store paths
    run_id = uuid.uuid4().hex[:8]
    csv_key = f"xray/eval/noise_sensitivity/case_id={case_id}/run_id={run_id}/noise_sensitivity.csv"
    summary_key = f"xray/eval/noise_sensitivity/case_id={case_id}/run_id={run_id}/summary.json"

    rows: list[dict[str, Any]] = []
    flip_summary: list[dict[str, Any]] = []

    for delta in deltas:
        flips = 0

        for t in range(trials):
            j = {
                "upper_mid": pts["upper_mid"].jitter(delta),
                "lower_mid": pts["lower_mid"].jitter(delta),
                "bone_left": pts["bone_left"].jitter(delta),
                "bone_right": pts["bone_right"].jitter(delta),
            }

            scores = compute_scores_from_points(
                upper_mid=(j["upper_mid"].x, j["upper_mid"].y),
                lower_mid=(j["lower_mid"].x, j["lower_mid"].y),
                bone_left=(j["bone_left"].x, j["bone_left"].y),
                bone_right=(j["bone_right"].x, j["bone_right"].y),
                img_width_px=img_w,
                px_per_cm=px_per_cm,
                debug=False,
            )

            changed = (
                scores["col2_bone_balance"] != int(baseline["col2_bone_balance"])
                or scores["col3_upper_mid_center"] != int(baseline["col3_upper_mid_center"])
                or scores["col4_upper_lower_alignment"] != int(baseline["col4_upper_lower_alignment"])
            )

            if changed:
                flips += 1

            rows.append(
                {
                    "case_id": case_id,
                    "source_overlay_json": str(overlay_json_path),
                    "delta_px": delta,
                    "trial": t,
                    "baseline_c2": int(baseline["col2_bone_balance"]),
                    "baseline_c3": int(baseline["col3_upper_mid_center"]),
                    "baseline_c4": int(baseline["col4_upper_lower_alignment"]),
                    "c2": int(scores["col2_bone_balance"]),
                    "c3": int(scores["col3_upper_mid_center"]),
                    "c4": int(scores["col4_upper_lower_alignment"]),
                    "any_score_changed": int(changed),
                }
            )

        flip_rate = flips / float(trials)
        flip_summary.append(
            {"delta_px": int(delta), "trials": int(trials), "flips": int(flips), "flip_rate": float(flip_rate)}
        )
        print(f"[delta={delta:>2}px] flip_rate={flip_rate:.3f} ({flips}/{trials})")

    # ---- Write CSV into ObjectStore (no more results/eval direct writes) ----
    csv_path = OBJECT_STORE_ROOT / csv_key
    csv_path.parent.mkdir(parents=True, exist_ok=True)

    fieldnames = list(rows[0].keys()) if rows else []
    with csv_path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        for r in rows:
            w.writerow(r)

    # ---- Write small summary JSON (great for README / interview) ----
    summary = {
        "schema_version": "1.0",
        "case_id": case_id,
        "run_id": run_id,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "source_overlay_json": str(overlay_json_path),
        "img_width_px": img_w,
        "px_per_cm": px_per_cm,
        "deltas_px": deltas,
        "flip_summary": flip_summary,
        "artifacts": {
            "noise_sensitivity_csv_key": csv_key,
            "summary_json_key": summary_key,
        },
    }

    # Use ObjectStore JSON writer if you have it; otherwise write directly
    try:
        STORE.put_json(summary_key, summary)
        summary_path = OBJECT_STORE_ROOT / summary_key
    except Exception:
        summary_path = OBJECT_STORE_ROOT / summary_key
        summary_path.parent.mkdir(parents=True, exist_ok=True)
        summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")

    print(f"\nWrote: {csv_path}")
    print(f"Wrote: {summary_path}")


if __name__ == "__main__":
    # Example:
    #   python src/eval_noise_sensitivity.py
    # If you want fewer trials:
    #   main(case_id="1", trials=50)
    main()
