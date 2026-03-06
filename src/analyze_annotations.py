# src/analyze_annotations.py
# Analyze annotation quality from overlay JSON records written by click_and_score.py
#
# What it does:
# - Scans your local object store for overlay.json files
# - Extracts per-image hint deviation (dx px) + annotation_confidence
# - Prints summary stats + outliers
# - (Optional) saves simple histograms as PNGs into results/annotation_audit/
#
# Usage:
#   python -m src.analyze_annotations
#   python src/analyze_annotations.py
#
# Notes:
# - Expects overlay JSON records shaped like build_overlay_record(...)
# - Looks for: pipeline.hint_dx_px.upper/lower and pipeline.annotation_confidence

from __future__ import annotations

import json
import math
import statistics
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

import matplotlib.pyplot as plt  # matplotlib is commonly available; if not, pip install matplotlib


# -------------------------------
# Paths (edit if needed)
# -------------------------------

PROJECT_ROOT = Path(__file__).resolve().parents[1]
RESULTS_DIR = PROJECT_ROOT / "results"
OBJECT_STORE_ROOT = RESULTS_DIR / "object_store"

AUDIT_DIR = RESULTS_DIR / "annotation_audit"
AUDIT_DIR.mkdir(parents=True, exist_ok=True)


# -------------------------------
# Data model
# -------------------------------

@dataclass(frozen=True)
class AuditRow:
    json_path: Path
    case_id: str
    run_id: str
    dx_upper: int | None
    dx_lower: int | None
    annotation_confidence: str | None


# -------------------------------
# Helpers
# -------------------------------

def _safe_get(d: dict[str, Any], path: str) -> Any:
    """Safe nested dict getter: 'a.b.c'."""
    cur: Any = d
    for part in path.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return None
        cur = cur[part]
    return cur


def _coerce_int(x: Any) -> int | None:
    if x is None:
        return None
    try:
        return int(x)
    except Exception:
        return None


def find_overlay_jsons(root: Path) -> list[Path]:
    if not root.exists():
        return []
    # most specific pattern first; fallback to any overlay.json under root
    paths = list(root.rglob("overlay.json"))
    # deterministic order
    return sorted(paths, key=lambda p: str(p))


def parse_overlay_json(p: Path) -> AuditRow | None:
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None

    case_id = _safe_get(data, "case_id")
    run_id = _safe_get(data, "run_id")
    conf = _safe_get(data, "pipeline.annotation_confidence")

    dx_upper = _coerce_int(_safe_get(data, "pipeline.hint_dx_px.upper"))
    dx_lower = _coerce_int(_safe_get(data, "pipeline.hint_dx_px.lower"))

    # tolerate missing fields
    return AuditRow(
        json_path=p,
        case_id=str(case_id) if case_id is not None else p.parent.name,
        run_id=str(run_id) if run_id is not None else "unknown",
        dx_upper=dx_upper,
        dx_lower=dx_lower,
        annotation_confidence=str(conf) if conf is not None else None,
    )


def summarize_int(values: list[int]) -> dict[str, float]:
    """Return common summary stats for ints as floats."""
    if not values:
        return {}
    values_sorted = sorted(values)
    n = len(values_sorted)

    def pct(p: float) -> float:
        # inclusive percentile index
        if n == 1:
            return float(values_sorted[0])
        k = (n - 1) * p
        f = math.floor(k)
        c = math.ceil(k)
        if f == c:
            return float(values_sorted[int(k)])
        d0 = values_sorted[f] * (c - k)
        d1 = values_sorted[c] * (k - f)
        return float(d0 + d1)

    return {
        "n": float(n),
        "min": float(values_sorted[0]),
        "p50": pct(0.50),
        "p90": pct(0.90),
        "p95": pct(0.95),
        "max": float(values_sorted[-1]),
        "mean": float(statistics.mean(values_sorted)),
        "stdev": float(statistics.pstdev(values_sorted)) if n >= 2 else 0.0,
    }


def print_conf_breakdown(rows: list[AuditRow]) -> None:
    counts: dict[str, int] = {}
    for r in rows:
        k = (r.annotation_confidence or "missing").lower()
        counts[k] = counts.get(k, 0) + 1

    total = sum(counts.values()) or 1
    print("\nAnnotation confidence breakdown:")
    for k in sorted(counts.keys()):
        v = counts[k]
        pct = 100.0 * v / total
        print(f"  {k:>8}: {v:>5} ({pct:5.1f}%)")


def top_outliers(
    rows: list[AuditRow],
    *,
    which: str,
    k: int = 15,
) -> list[AuditRow]:
    if which not in ("upper", "lower", "both_max"):
        raise ValueError("which must be 'upper', 'lower', or 'both_max'")

    def score(r: AuditRow) -> int:
        du = r.dx_upper if r.dx_upper is not None else -1
        dl = r.dx_lower if r.dx_lower is not None else -1
        if which == "upper":
            return du
        if which == "lower":
            return dl
        return max(du, dl)

    eligible = [r for r in rows if score(r) >= 0]
    return sorted(eligible, key=score, reverse=True)[:k]


def save_hist(values: list[int], title: str, out_path: Path) -> None:
    if not values:
        return
    plt.figure()
    plt.hist(values, bins=30)
    plt.title(title)
    plt.xlabel("dx (pixels)")
    plt.ylabel("count")
    plt.tight_layout()
    plt.savefig(out_path)
    plt.close()


# -------------------------------
# Main
# -------------------------------

def main() -> None:
    print("PROJECT_ROOT:", PROJECT_ROOT)
    print("OBJECT_STORE_ROOT:", OBJECT_STORE_ROOT)

    json_paths = find_overlay_jsons(OBJECT_STORE_ROOT)
    if not json_paths:
        print("[!] No overlay.json files found under:", OBJECT_STORE_ROOT)
        print("    Did you run click_and_score.py and generate overlays?")
        return

    rows: list[AuditRow] = []
    for p in json_paths:
        row = parse_overlay_json(p)
        if row is not None:
            rows.append(row)

    print(f"\nFound {len(rows)} overlay records.")

    # Gather dx lists
    dx_upper = [r.dx_upper for r in rows if r.dx_upper is not None]
    dx_lower = [r.dx_lower for r in rows if r.dx_lower is not None]
    dx_upper_i = [int(x) for x in dx_upper]
    dx_lower_i = [int(x) for x in dx_lower]

    # Stats
    print("\nHint deviation summary (pixels):")
    s_u = summarize_int(dx_upper_i)
    s_l = summarize_int(dx_lower_i)

    if s_u:
        print(
            "  upper dx: "
            f"n={int(s_u['n'])} min={s_u['min']:.0f} p50={s_u['p50']:.0f} "
            f"p90={s_u['p90']:.0f} p95={s_u['p95']:.0f} max={s_u['max']:.0f} "
            f"mean={s_u['mean']:.2f} stdev={s_u['stdev']:.2f}"
        )
    else:
        print("  upper dx: (missing)")

    if s_l:
        print(
            "  lower dx: "
            f"n={int(s_l['n'])} min={s_l['min']:.0f} p50={s_l['p50']:.0f} "
            f"p90={s_l['p90']:.0f} p95={s_l['p95']:.0f} max={s_l['max']:.0f} "
            f"mean={s_l['mean']:.2f} stdev={s_l['stdev']:.2f}"
        )
    else:
        print("  lower dx: (missing)")

    # Confidence breakdown
    print_conf_breakdown(rows)

    # Outliers
    print("\nTop outliers by max(upper, lower) dx:")
    for r in top_outliers(rows, which="both_max", k=15):
        du = r.dx_upper if r.dx_upper is not None else -1
        dl = r.dx_lower if r.dx_lower is not None else -1
        worst = max(du, dl)
        print(
            f"  case={r.case_id:<12} run={r.run_id:<10} "
            f"dx_upper={du:<4} dx_lower={dl:<4} worst={worst:<4} "
            f"conf={r.annotation_confidence or 'missing'}  json={r.json_path}"
        )

    # Optional: save histograms
    out_upper = AUDIT_DIR / "hist_dx_upper.png"
    out_lower = AUDIT_DIR / "hist_dx_lower.png"
    save_hist(dx_upper_i, "Upper midline hint deviation (dx px)", out_upper)
    save_hist(dx_lower_i, "Lower midline hint deviation (dx px)", out_lower)

    print("\nSaved plots (if matplotlib available):")
    print(" ", out_upper)
    print(" ", out_lower)
    print("\nDone.")


if __name__ == "__main__":
    main()
