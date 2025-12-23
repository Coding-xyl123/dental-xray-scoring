# src/click_and_score.py
# NOTE ON SCALE:
# ----------------
# These images are JPEG/PNG exports without DICOM calibration metadata.
# That means we cannot recover the true physical centimeters of the anatomy.
#
# In this project, we estimate scale in two steps:
#   1. If the image has a trustworthy DPI in its metadata (e.g. >= 150 DPI),
#      we use it to convert pixels -> inches -> centimeters.
#   2. Otherwise, we assume a typical panoramic sensor width of 26 cm.
#
# The scoring rubric (1–5 for each column) depends on RELATIVE asymmetry
# and deviations, not on exact millimeter precision, so this approximate
# scale is sufficient for the intended use of this tool.

from __future__ import annotations

import csv
import platform
import subprocess
import sys
import uuid
from pathlib import Path
from typing import Tuple

import cv2  # type: ignore
import numpy as np
from PIL import Image

from object_store import ObjectStore
from overlay_json import build_overlay_record
from scoring_core import compute_scores_from_points

# ===============================
# SCALE CONFIG
# ===============================

DEFAULT_IMAGE_WIDTH_CM = 26.0   # assumed pano width if no trusted DPI
MIN_TRUSTED_DPI = 150           # below this we treat DPI is "screen" / untrusted


# ===============================
# PROJECT PATHS (repo root)
# ===============================

PROJECT_ROOT = Path(__file__).resolve().parents[1]  # repo root (one level above src)

DATA_DIR = PROJECT_ROOT / "data" / "images"
RESULTS_DIR = PROJECT_ROOT / "results"
RESULTS_DIR.mkdir(parents=True, exist_ok=True)

SCORES_CSV = RESULTS_DIR / "scores.csv"

# ObjectStore root (local “S3-like” layout)
STORE = ObjectStore(RESULTS_DIR / "object_store")


# ===============================
# PROVENANCE
# ===============================

def get_git_commit() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            stderr=subprocess.DEVNULL,
            cwd=str(PROJECT_ROOT),
        ).decode("utf-8").strip()
    except Exception:
        return "unknown"


# ===============================
# SCALE META (Step 4)
# ===============================

def estimate_scale_meta(image_path: Path, img_width_px: int) -> tuple[float, dict, list[str]]:
    """
    Returns:
      px_per_cm: float
      scale_meta: dict (method/confidence + optional dpi)
      warnings: list[str]
    """
    warnings: list[str] = []
    method = "assumed_sensor_width_cm"
    confidence = "low"

    width_cm = None
    dpi_used = None

    try:
        with Image.open(image_path) as pil_img:
            dpi = pil_img.info.get("dpi", None)
            if dpi is not None and dpi[0] >= MIN_TRUSTED_DPI:
                dpi_used = float(dpi[0])
                width_inch = img_width_px / dpi_used
                width_cm = width_inch * 2.54
                method = "dpi"
                confidence = "medium"
    except Exception:
        pass

    if width_cm is None:
        width_cm = DEFAULT_IMAGE_WIDTH_CM
        warnings.append("Scale is approximate (no trusted DPI; assumed pano width).")
    else:
        warnings.append("Scale is approximate (DPI-based; JPEG/PNG without DICOM).")

    px_per_cm = img_width_px / float(width_cm)

    scale_meta = {
        "px_per_cm": float(px_per_cm),
        "method": method,
        "confidence": confidence,
        "assumed_width_cm": float(DEFAULT_IMAGE_WIDTH_CM),
        "min_trusted_dpi": float(MIN_TRUSTED_DPI),
        "dpi_used": dpi_used,
    }
    return float(px_per_cm), scale_meta, warnings


# ===============================
# HEURISTIC SUGGESTIONS
# ===============================

def suggest_midline_x_in_band(img: np.ndarray, top_frac: float, bottom_frac: float) -> int:
    """
    Takes a vertical band [top_frac, bottom_frac] of the image
    and finds x where left/right halves are most symmetric.
    """
    h, w = img.shape[:2]
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    gray_blur = cv2.GaussianBlur(gray, (9, 9), 0)

    top = int(h * top_frac)
    bottom = int(h * bottom_frac)
    if bottom <= top:
        top = 0
        bottom = h

    band = gray_blur[top:bottom, :]

    center = w // 2
    window = 80
    best_x = center
    best_score = 1e9

    for x in range(center - window, center + window + 1):
        if x <= 0 or x >= w:
            continue

        left = band[:, :x]
        right = band[:, x:]
        right_flipped = cv2.flip(right, 1)

        min_width = min(left.shape[1], right_flipped.shape[1])
        if min_width < 40:
            continue

        left_crop = left[:, :min_width]
        right_crop = right_flipped[:, :min_width]
        diff = np.mean(np.abs(left_crop - right_crop))

        if diff < best_score:
            best_score = diff
            best_x = x

    return int(best_x)


def suggest_lines_and_endpoints(img: np.ndarray) -> tuple[int, int, Tuple[int, int], Tuple[int, int]]:
    """
    Heuristic hints for:
      - upper midline x
      - lower midline x
      - left bone endpoint (x, y)
      - right bone endpoint (x, y)

    These are ONLY visual hints, not used in scoring directly.
    """
    h, w = img.shape[:2]

    upper_x = suggest_midline_x_in_band(img, top_frac=0.25, bottom_frac=0.55)
    lower_x = suggest_midline_x_in_band(img, top_frac=0.50, bottom_frac=0.85)

    y_bone = int(h * 0.35)
    left_x = int(w * 0.12)
    right_x = int(w * 0.88)

    left_pt = (left_x, y_bone)
    right_pt = (right_x, y_bone)

    return upper_x, lower_x, left_pt, right_pt


# ===============================
# INTERACTIVE CLICK + SCORE
# ===============================

def click_and_score_image(image_path: Path, debug: bool = True):
    img = cv2.imread(str(image_path))
    if img is None:
        print(f"[!] Could not read {image_path}")
        return None

    h, w = img.shape[:2]

    # Step 4: scale + warnings
    px_per_cm, scale_meta, warnings = estimate_scale_meta(image_path, w)
    if debug:
        print(
            f"[DEBUG SCALE] img_width_px={w}, px_per_cm={px_per_cm:.3f}, "
            f"method={scale_meta.get('method')}, confidence={scale_meta.get('confidence')}, "
            f"dpi_used={scale_meta.get('dpi_used')}"
        )

    # heuristic hints
    upper_x_sug, lower_x_sug, bone_left_sug, bone_right_sug = suggest_lines_and_endpoints(img)
    if debug:
        print(
            f"[HINT] upper_x ≈ {upper_x_sug}, lower_x ≈ {lower_x_sug}, "
            f"bone_left_sug={bone_left_sug}, bone_right_sug={bone_right_sug}"
        )

    window_name = f"Click 4 points: {image_path.name}"
    cv2.namedWindow(window_name, cv2.WINDOW_NORMAL)

    base = img.copy()

    # static hints
    cv2.line(base, (upper_x_sug, 0), (upper_x_sug, h), (255, 0, 0), 1)
    cv2.putText(base, "1: Hint upper midline", (10, 20),
                cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 0, 0), 1)

    cv2.line(base, (lower_x_sug, 0), (lower_x_sug, h), (255, 0, 255), 1)
    cv2.putText(base, "2: Hint lower midline", (10, 40),
                cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 0, 255), 1)

    cv2.circle(base, bone_left_sug, 6, (0, 0, 255), 1)
    cv2.circle(base, bone_right_sug, 6, (0, 255, 0), 1)
    cv2.putText(base, "3 & 4: Hint bone ends (L/R)", (10, 60),
                cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 255), 1)

    step_texts = [
        "1) Click UPPER teeth midline",
        "2) Click LOWER teeth midline",
        "3) Click LEFT bone end (image LEFT, PATIENT RIGHT)",
        "4) Click RIGHT bone end (image RIGHT, PATIENT LEFT)",
    ]

    points: list[tuple[int, int]] = []

    def redraw_with_status():
        disp = base.copy()

        cv2.rectangle(disp, (0, h - 40), (w, h), (0, 0, 0), -1)
        step_idx = min(len(points), 3)
        msg = f"Next: {step_texts[step_idx]}   [r=reset, q=skip, ESC=quit]"
        cv2.putText(disp, msg, (10, h - 15),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)

        labels = ["UPPER", "LOWER", "BONE L", "BONE R"]
        colors = [(0, 255, 255), (255, 255, 0), (0, 0, 255), (0, 255, 0)]

        for i, (px, py) in enumerate(points):
            color = colors[i] if i < len(colors) else (0, 0, 255)
            label = labels[i] if i < len(labels) else str(i + 1)
            cv2.circle(disp, (px, py), 6, color, -1)
            cv2.putText(disp, label, (px + 8, py - 8),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.6, color, 2)

        cv2.imshow(window_name, disp)

    def mouse_callback(event, x, y, flags, param):
        nonlocal points
        if event == cv2.EVENT_LBUTTONDOWN:
            if len(points) >= 4:
                return
            points.append((int(x), int(y)))
            print(f"Point {len(points)} ({step_texts[len(points)-1]}): ({x}, {y})")
            redraw_with_status()

    cv2.setMouseCallback(window_name, mouse_callback)
    redraw_with_status()

    # 1) click phase
    while True:
        key = cv2.waitKey(20) & 0xFF

        if key == ord('r'):
            points = []
            print("[*] Points reset.")
            redraw_with_status()

        elif key == ord('q'):
            print("[*] Skipping this image.")
            cv2.destroyWindow(window_name)
            return None

        elif key == 27:  # ESC
            print("[*] ESC pressed — quitting application.")
            cv2.destroyAllWindows()
            raise SystemExit(0)

        elif len(points) >= 4:
            break

    if len(points) != 4:
        print("[!] Not enough points (need 4). Skipping.")
        cv2.destroyWindow(window_name)
        return None

    upper_mid, lower_mid, bone_left, bone_right = points

    # Step 5.5: annotation confidence (distance from heuristic hint midlines)
    dx_upper = abs(int(upper_mid[0]) - int(upper_x_sug))
    dx_lower = abs(int(lower_mid[0]) - int(lower_x_sug))

    annotation_confidence = "high"
    if dx_upper > 2 or dx_lower > 2:
        annotation_confidence = "medium"
    if dx_upper > 5 or dx_lower > 5:
        annotation_confidence = "low"
        warnings.append("Annotation deviates >5px from heuristic midline hints; scores may be unstable.")

    # 2) scoring phase (pure function)
    scores = compute_scores_from_points(
        upper_mid=upper_mid,
        lower_mid=lower_mid,
        bone_left=bone_left,
        bone_right=bone_right,
        img_width_px=w,
        px_per_cm=px_per_cm,
        debug=debug,
    )
    s2 = scores["col2_bone_balance"]
    s3 = scores["col3_upper_mid_center"]
    s4 = scores["col4_upper_lower_alignment"]

    overlay = img.copy()

    # draw points
    cv2.circle(overlay, upper_mid, 7, (0, 255, 255), -1)
    cv2.circle(overlay, lower_mid, 7, (255, 255, 0), -1)
    cv2.circle(overlay, bone_left, 7, (0, 0, 255), -1)
    cv2.circle(overlay, bone_right, 7, (0, 255, 0), -1)

    # draw lines
    cv2.line(overlay, (upper_mid[0], 0), (upper_mid[0], h), (0, 255, 255), 1)
    cv2.line(overlay, (lower_mid[0], 0), (lower_mid[0], h), (255, 255, 0), 1)

    cv2.line(overlay, upper_mid, bone_left, (0, 0, 255), 2)
    cv2.line(overlay, upper_mid, bone_right, (0, 255, 0), 2)

    text = f"C2:{s2}  C3:{s3}  C4:{s4}  conf:{annotation_confidence}"
    cv2.putText(overlay, text, (10, 30),
                cv2.FONT_HERSHEY_SIMPLEX, 1.0, (255, 255, 255), 2)

    # ---- write artifacts via ObjectStore (S3-like keys) ----
    run_id = uuid.uuid4().hex[:8]
    case_id = image_path.stem

    overlay_png_key = f"xray/overlays/case_id={case_id}/run_id={run_id}/overlay.png"
    overlay_json_key = f"xray/overlays/case_id={case_id}/run_id={run_id}/overlay.json"

    png_result = STORE.put_png(overlay_png_key, overlay)
    print("Saved overlay to:", png_result.path)

    record = build_overlay_record(
        case_id=case_id,
        run_id=run_id,
        landmarks=[
            {"name": "upper_mid", "x": int(upper_mid[0]), "y": int(upper_mid[1])},
            {"name": "lower_mid", "x": int(lower_mid[0]), "y": int(lower_mid[1])},
            {"name": "bone_left", "x": int(bone_left[0]), "y": int(bone_left[1])},
            {"name": "bone_right", "x": int(bone_right[0]), "y": int(bone_right[1])},
        ],
        measurements=[],  # keep px_per_cm only in scale_meta to avoid duplication
        scores={
            "col2_bone_balance": int(s2),
            "col3_upper_mid_center": int(s3),
            "col4_upper_lower_alignment": int(s4),
        },
        warnings=warnings,
        pipeline={
            "name": "dental-xray-scoring",
            "algorithm_version": "heuristic-v1",
            "annotation_confidence": annotation_confidence,
            "hint_dx_px": {"upper": int(dx_upper), "lower": int(dx_lower)},
        },
        input_meta={"path": image_path.name, "width_px": int(w), "height_px": int(h)},
        scale_meta=scale_meta,
        provenance={
            "git_commit": get_git_commit(),
            "python_version": sys.version.split()[0],
            "platform": platform.platform(),
        },
    )

    json_result = STORE.put_json(overlay_json_key, record)
    print("Saved overlay JSON to:", json_result.path)

    # show overlay
    cv2.imshow(window_name, overlay)

    while True:
        key = cv2.waitKey(0) & 0xFF

        if key in (ord('n'), 13):  # 'n' or Enter
            cv2.destroyWindow(window_name)
            return {
                "image_name": image_path.name,
                "col2": s2,
                "col3": s3,
                "col4": s4,
                "run_id": run_id,
                "annotation_confidence": annotation_confidence,
                "overlay_png_key": overlay_png_key,
                "overlay_json_key": overlay_json_key,
            }

        elif key == ord('q'):
            cv2.destroyWindow(window_name)
            return None

        elif key == 27:  # ESC
            cv2.destroyAllWindows()
            raise SystemExit(0)


def main():
    print("PROJECT_ROOT:", PROJECT_ROOT)
    print("DATA_DIR:", DATA_DIR)
    print("RESULTS_DIR:", RESULTS_DIR)
    print("OBJECT_STORE_ROOT:", STORE.root_dir)

    images = sorted(
        p for p in DATA_DIR.glob("*")
        if p.suffix.lower() in {".jpg", ".jpeg", ".png"}
    )

    if not images:
        print("[!] No images found in", DATA_DIR)
        return

    print(f"Found {len(images)} images.")
    for i, p in enumerate(images[:10]):
        print(i, "->", p.name)

    write_header = not SCORES_CSV.exists()
    writer = None

    with open(SCORES_CSV, "a", newline="") as f:
        for img_path in images:
            print(f"\n[MAIN] Now scoring: {img_path.name}")

            try:
                result = click_and_score_image(img_path, debug=True)
            except SystemExit:
                print("[MAIN] User requested exit. Stopping.")
                break

            if result is None:
                continue

            if writer is None:
                fieldnames = list(result.keys())
                writer = csv.DictWriter(f, fieldnames=fieldnames)
                if write_header:
                    writer.writeheader()

            writer.writerow(result)
            f.flush()
            print(f"[CSV] Wrote row for {result['image_name']}")

    print("Saved scores to:", SCORES_CSV)
    print("\nDone.")


if __name__ == "__main__":
    main()
