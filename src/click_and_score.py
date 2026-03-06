# src/click_and_score.py
# Interactive annotator for dental panoramic X-rays.
# User clicks 4 points (upper midline, lower midline, left/right bone ends),
# we compute rubric scores and write overlay PNG + overlay JSON to a local
# “S3-like” object store.

from __future__ import annotations

import csv
import platform
import subprocess
import sys
import uuid
from pathlib import Path
from src.integrity import write_final_metadata, verify_run
from src.object_store import ObjectStore
from src.overlay_json import build_overlay_record
from src.scoring_core import compute_scores_from_points
import cv2  
import numpy as np
from datetime import datetime, timezone
from PIL import Image

# ===============================
# SCALE CONFIG
# ===============================

DEFAULT_IMAGE_WIDTH_CM = 30.0
MIN_TRUSTED_DPI = 150


# ===============================
# MODE CONSTANTS
# ===============================

MODE_RESUME = "resume"
MODE_RESTART = "restart"
MODE_QUIT = "quit"
# ===============================
# PROJECT PATHS
# ===============================

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = PROJECT_ROOT / "data" / "images"
RESULTS_DIR = PROJECT_ROOT / "results"
RESULTS_DIR.mkdir(parents=True, exist_ok=True)

SCORES_CSV = RESULTS_DIR / "scores.csv"
STORE = ObjectStore(RESULTS_DIR / "object_store")


# ===============================
# UI HELPERS
# ===============================

def draw_hint_text(
    img: np.ndarray,
    lines: list[tuple[str, tuple[int, int, int]]],
    x: int = 10,
    y0: int = 25,
    dy: int = 20,
    scale: float = 0.55,
    thickness: int = 1,
) -> None:
    """Draw stacked TRANSPARENT hint text (no background box) in upper-left."""
    font = cv2.FONT_HERSHEY_SIMPLEX
    y = y0
    for text, color in lines:
        cv2.putText(img, text, (x, y), font, scale, color, thickness, cv2.LINE_AA)
        y += dy


# ===============================
# PROVENANCE
# ===============================
#this function makes my outputs traceable, reproducible,  and defensive
def get_git_commit() -> str:
    try:
        return (
            # Runs an external shell command Captures its stdout and returns it as bytes
            subprocess.check_output(
                #This is a command designed for script use to translate human-readable Git references (like branch names, tags, or relative references) into their underlying object names (SHA-1 hashes).
                #HEAD: This is a special pointer that always refers to the commit at the tip of the current branch or the currently checked-out commit (in a detached HEAD state). 
                ["git", "rev-parse", "HEAD"],
                #discard error output
                stderr=subprocess.DEVNULL,

                cwd=str(PROJECT_ROOT),
                #run the command inside your project directory
          
            )
            # Convert bytes to string and remove extra whitespace
            .decode("utf-8")
            .strip()
        )
    except Exception:
        return "unknown"


# ===============================
# SCALE META
# ===============================

def estimate_scale_meta(image_path: Path, img_width_px: int) -> tuple[float, dict, list[str]]:
   #Collects warnings that will be attached to the output JSON,Empty list means “no issues detected
    warnings: list[str] = []
    method = "assumed_sensor_width_cm"
    confidence = "low"
    dpi_used = None
    width_cm = None

    try:
        with Image.open(image_path) as pil_img:
            dpi = pil_img.info.get("dpi")
            if dpi and dpi[0] >= MIN_TRUSTED_DPI:
                dpi_used = float(dpi[0])
                #Convert pixels → inches → centimeters
                width_cm = (float(img_width_px) / dpi_used) * 2.54
                method = "dpi"
                confidence = "medium"
    except Exception:
        pass

    if width_cm is None:
        width_cm = DEFAULT_IMAGE_WIDTH_CM
        warnings.append("Scale is approximate (no trusted DPI; assumed pano width).")
    else:
        warnings.append("Scale is approximate (DPI-based; JPEG/PNG without DICOM).")
    #actual number used by scoring logic.
    px_per_cm = float(img_width_px) / float(width_cm)

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
# HEURISTICS
# ===============================

def suggest_midline_x_in_band(img: np.ndarray, top_frac: float, bot_frac: float) -> int:
    h, w = img.shape[:2]
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    blur = cv2.GaussianBlur(gray, (9, 9), 0)

    top = int(h * top_frac)
    bot = int(h * bot_frac)
    if bot <= top:
        top, bot = 0, h

    band = blur[top:bot, :]

    center = w // 2
    best_x, best_score = center, float("inf")

    for x in range(center - 80, center + 81):
        if x <= 0 or x >= w:
            continue

        left = band[:, :x]
        right = cv2.flip(band[:, x:], 1)
        m = min(left.shape[1], right.shape[1])
        if m < 40:
            continue

        diff = np.mean(np.abs(left[:, :m] - right[:, :m]))
        if diff < best_score:
            best_score = diff
            best_x = x

    return int(best_x)


def suggest_lines_and_endpoints(img: np.ndarray) -> tuple[int, int, tuple[int, int], tuple[int, int]]:
    h, w = img.shape[:2]
    upper = suggest_midline_x_in_band(img, 0.25, 0.55)
    lower = suggest_midline_x_in_band(img, 0.50, 0.85)
    y = int(h * 0.35)
    return upper, lower, (int(w * 0.12), y), (int(w * 0.88), y)


# ===============================
# RESUME / RESTART HELPERS
# ===============================

def scores_csv_has_header(path: Path) -> bool:
    if not path.exists():
        return False
    try:
        first = path.open("r", encoding="utf-8").readline().strip().lower()
    except Exception:
        return False
    return first.startswith("image_name,")


def load_done_images(scores_csv: Path) -> set[str]:
    done: set[str] = set()
    if not scores_csv.exists():
        return done

    if not scores_csv_has_header(scores_csv):
        print("[WARN] scores.csv exists but header is missing/invalid; resume will NOT skip.")
        return done

    with scores_csv.open("r", newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            name = (row.get("image_name") or "").strip()
            if name:
                done.add(name)
    return done


def backup_and_reset_scores_csv(scores_csv: Path) -> None:
    if not scores_csv.exists():
        print("[START OVER] No existing scores.csv found. Starting fresh.")
        return
    backup = scores_csv.with_name(f"{scores_csv.stem}.backup_{uuid.uuid4().hex[:8]}{scores_csv.suffix}")
    scores_csv.replace(backup)
    print(f"[START OVER] Backed up old CSV to: {backup}")


def prompt_resume_or_restart(done_count: int, total: int) -> str:
    """Returns: 'resume' | 'restart' | 'quit'. Always prompts."""
    print("\n===================================================", flush=True)
    print(f"Progress detected: {done_count}/{total} images already scored.", flush=True)
    print("Choose how to run:", flush=True)
    print("  [R] Resume (skip already-scored images)", flush=True)
    print("  [S] Start over (backup scores.csv if it exists, then score all images)", flush=True)
    print("  [Q] Quit", flush=True)
    print("===================================================", flush=True)

    sys.stdout.flush()

    while True:
        try:
            choice = input("Enter R / S / Q: ").strip().lower()
        except EOFError:
            # This happens when you're running without a real stdin (IDE runner, etc.)
            print("\n[ERROR] No stdin available for input(). Run from Terminal.", flush=True)
            return MODE_QUIT

        if choice in ("r", MODE_RESUME):
            return MODE_RESUME
        if choice in ("s", "start", MODE_RESTART):
            return MODE_RESTART
        if choice in ("q", MODE_QUIT):
            return MODE_QUIT
        print("Invalid input. Please enter R, S, or Q.", flush=True)

# ===============================
# CLICK + SCORE
# ===============================

def click_and_score_image(image_path: Path, debug: bool = True):
    img = cv2.imread(str(image_path))
    if img is None:
        print("[!] Could not read:", image_path)
        return None

    h, w = img.shape[:2]

    px_per_cm, scale_meta, warnings = estimate_scale_meta(image_path, w)
    if debug:
        print(
            f"[DEBUG SCALE] w={w} px_per_cm={px_per_cm:.3f} "
            f"method={scale_meta.get('method')} conf={scale_meta.get('confidence')} dpi={scale_meta.get('dpi_used')}"
        )

    upper_x_sug, lower_x_sug, bone_l_sug, bone_r_sug = suggest_lines_and_endpoints(img)
    if debug:
        print(f"[HINT] upper_x≈{upper_x_sug} lower_x≈{lower_x_sug} boneL={bone_l_sug} boneR={bone_r_sug}")

    win_name = f"Click 4 points: {image_path.name}"
    cv2.namedWindow(win_name, cv2.WINDOW_NORMAL)

    # Base display: show heuristic guidance (HINTS)
    base = img.copy()
    cv2.line(base, (upper_x_sug, 0), (upper_x_sug, h), (255, 0, 0), 1)       # blue
    cv2.line(base, (lower_x_sug, 0), (lower_x_sug, h), (255, 0, 255), 1)     # purple
    cv2.circle(base, bone_l_sug, 6, (0, 0, 255), 1)                          # red
    cv2.circle(base, bone_r_sug, 6, (0, 255, 0), 1)                          # green

    step_texts = [
        "1) Click UPPER teeth midline",
        "2) Click LOWER teeth midline",
        "3) Click LEFT bone end (image LEFT, patient RIGHT)",
        "4) Click RIGHT bone end (image RIGHT, patient LEFT)",
    ]

    points: list[tuple[int, int]] = []

    def redraw():
        # base = original image + static hint overlays
        disp = base.copy()

        # Top-left transparent legend
        hint_lines = [
            ("HINTS (guidance only):", (255, 255, 255)),
            ("Blue line   = upper midline suggestion (symmetry)", (255, 0, 0)),
            ("Purple line = lower midline suggestion (symmetry)", (255, 0, 255)),
            ("Red circle  = bone LEFT hint (image LEFT)", (0, 0, 255)),
            ("Green circle= bone RIGHT hint (image RIGHT)", (0, 255, 0)),
            ("Note: image LEFT = patient RIGHT", (200, 200, 200)),
        ]
        draw_hint_text(disp, hint_lines, x=10, y0=25, dy=20, scale=0.55, thickness=1)

        # Clicked points
        labels = ["UPPER", "LOWER", "BONE L", "BONE R"]
        colors = [(0, 255, 255), (255, 255, 0), (0, 0, 255), (0, 255, 0)]

        for i, (x, y) in enumerate(points):
            # points is an ordered list of clicks 
            # disp → current display image (x, y) → center of the marker 6 → radius in pixels
            cv2.circle(disp, (x, y), 6, colors[i], -1)
            cv2.putText(
                disp,
                labels[i],
                (x + 8, y - 8),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.6,
                colors[i],
                2,
                cv2.LINE_AA,
            )

        # Bottom instruction bar
        bar_h = 60
        cv2.rectangle(disp, (0, h - bar_h), (w, h), (0, 0, 0), -1)
        step_idx = min(len(points), 3)
        msg1 = f"Next click: {step_texts[step_idx]}"
        msg2 = "Keys: r=reset   q=skip image   ESC=quit   (click window to focus)"

        cv2.putText(disp, msg1, (10, h - 32), cv2.FONT_HERSHEY_SIMPLEX, 0.62, (255, 255, 255), 1, cv2.LINE_AA)
        cv2.putText(disp, msg2, (10, h - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (200, 200, 200), 1, cv2.LINE_AA)

        cv2.imshow(win_name, disp)

    def on_click(event, x, y, *_):
        if event == cv2.EVENT_LBUTTONDOWN and len(points) < 4:
            points.append((int(x), int(y)))
            redraw()

    cv2.setMouseCallback(win_name, on_click)
    redraw()

    # Click loop (macOS-safe)
    while len(points) < 4:
        key = cv2.waitKey(20) & 0xFF

        if key == ord("r"):
            points.clear()
            print("[*] reset points")
            redraw()
        elif key == ord("q"):
            cv2.destroyWindow(win_name)
            cv2.waitKey(1)
            return None
        elif key == 27:
            cv2.destroyAllWindows()
            raise SystemExit(0)

    upper_mid, lower_mid, bone_left, bone_right = points

    dx_upper = abs(upper_mid[0] - int(upper_x_sug))
    dx_lower = abs(lower_mid[0] - int(lower_x_sug))

    annotation_conf = "high"
    if dx_upper > 2 or dx_lower > 2:
        annotation_conf = "medium"
    if dx_upper > 5 or dx_lower > 5:
        annotation_conf = "low"
        warnings.append("Annotation deviates >5px from heuristic midline hints; scores may be unstable.")

    scores = compute_scores_from_points(
        upper_mid=upper_mid,
        lower_mid=lower_mid,
        bone_left=bone_left,
        bone_right=bone_right,
        img_width_px=w,
        px_per_cm=px_per_cm,
        debug=debug,
    )

    overlay = img.copy()
    cv2.circle(overlay, upper_mid, 7, (0, 255, 255), -1)
    cv2.circle(overlay, lower_mid, 7, (255, 255, 0), -1)
    cv2.circle(overlay, bone_left, 7, (0, 0, 255), -1)
    cv2.circle(overlay, bone_right, 7, (0, 255, 0), -1)

    cv2.line(overlay, (upper_mid[0], 0), (upper_mid[0], h), (0, 255, 255), 1)
    cv2.line(overlay, (lower_mid[0], 0), (lower_mid[0], h), (255, 255, 0), 1)
    cv2.line(overlay, upper_mid, bone_left, (0, 0, 255), 2)
    cv2.line(overlay, upper_mid, bone_right, (0, 255, 0), 2)

    text = (
        f"C2:{scores['col2_bone_balance']}  "
        f"C3:{scores['col3_upper_mid_center']}  "
        f"C4:{scores['col4_upper_lower_alignment']}  "
        f"conf:{annotation_conf}"
    )
    cv2.putText(overlay, text, (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (255, 255, 255), 2, cv2.LINE_AA)

    cv2.rectangle(overlay, (0, h - 40), (w, h), (0, 0, 0), -1)
    cv2.putText(
        overlay,
        "Scored.  ENTER/'n'=next  q=skip  ESC=quit  (click window to focus)",
        (10, h - 15),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.5,
        (255, 255, 255),
        1,
        cv2.LINE_AA,
    )
    run_id = uuid.uuid4().hex[:8]
    case_id = image_path.stem
    run_prefix = f"xray/overlays/case_id={case_id}/run_id={run_id}"

# 1) Copy input into run folder
    input_key = f"{run_prefix}/input/{image_path.name}"
    input_result = STORE.put_bytes(input_key, image_path.read_bytes())
    print("Saved input copy to:", input_result.path)

# 2) Write overlay artifacts
    png_key = f"{run_prefix}/overlay.png"
    json_key = f"{run_prefix}/overlay.json"

    png_result = STORE.put_png(png_key, overlay)
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
    measurements=[],
    scores={k: int(v) for k, v in scores.items()},
    warnings=warnings,
    pipeline={
        "name": "dental-xray-scoring",
        "algorithm_version": "heuristic-v1",
        "annotation_confidence": annotation_conf,
    },
    input_meta={"path": image_path.name, "width_px": int(w), "height_px": int(h)},
    scale_meta=scale_meta,
    provenance={
        "git_commit": get_git_commit(),
        "python_version": sys.version.split()[0],
        "platform": platform.platform(),
    },
   )

    json_result = STORE.put_json(json_key, record)
    print("Saved overlay JSON to:", json_result.path)

    summary_key = f"{run_prefix}/summary.json"

    summary = {
        "schema_version": "1.0",
        "case_id": str(case_id),
        "run_id": run_id,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "img_width_px": int(w),
        "img_height_px": int(h),
        "px_per_cm": float(px_per_cm),
        "scale_method": scale_meta.get("method"),
        "scale_confidence": scale_meta.get("confidence"),
        "annotation_confidence": annotation_conf,
        "warnings": warnings,
        "scores": {
            "col2_bone_balance": int(scores["col2_bone_balance"]),
            "col3_upper_mid_center": int(scores["col3_upper_mid_center"]),
            "col4_upper_lower_alignment": int(scores["col4_upper_lower_alignment"]),
        },
        "landmarks": {
            "upper_mid": {"x": int(upper_mid[0]), "y": int(upper_mid[1])},
            "lower_mid": {"x": int(lower_mid[0]), "y": int(lower_mid[1])},
            "bone_left": {"x": int(bone_left[0]), "y": int(bone_left[1])},
            "bone_right": {"x": int(bone_right[0]), "y": int(bone_right[1])},
        },
        "artifacts": {
            "input_image_key": input_key,
            "overlay_png_key": png_key,
            "overlay_json_key": json_key,
            "summary_json_key": summary_key,
        },
    }

    summary_result = STORE.put_json(summary_key, summary)
    print("Saved summary JSON to:", summary_result.path)

# 3) Derive run_dir (no placeholder needed)
    run_dir = str(png_result.path.parent)

# 4) Write metadata LAST
    config = {
        "algorithm_version": "heuristic-v1",
        "min_trusted_dpi": MIN_TRUSTED_DPI,
        "default_image_width_cm": DEFAULT_IMAGE_WIDTH_CM,
    }

    artifact_paths = {
        "overlay_png": str(png_result.path),
        "overlay_json": str(json_result.path),
        "summary_json": str(summary_result.path),
    }

    write_final_metadata(
        run_dir=run_dir,
        run_id=run_id,
        input_path_in_run=str(input_result.path),
        config=config,
        artifact_paths=artifact_paths,
        status="SUCCESS",
    )

# 5) Verify invariants
    verify_run(run_dir)
    print("✅ verify_run passed:", run_dir)



    cv2.imshow(win_name, overlay)

    print("[INFO] Press ENTER or 'n' to continue to next image.")
    while True:
        key = cv2.waitKey(0) & 0xFF
        if key in (10, 13, ord("n")):
            cv2.destroyWindow(win_name)
            cv2.waitKey(1)
            return {
                "image_name": image_path.name,
                "col2": int(scores["col2_bone_balance"]),
                "col3": int(scores["col3_upper_mid_center"]),
                "col4": int(scores["col4_upper_lower_alignment"]),
                "run_id": run_id,
                "annotation_confidence": annotation_conf,
                "overlay_png_key": png_key,
                "overlay_json_key": json_key,
                "summary_json_key": summary_key,
            }
        if key == ord("q"):
            cv2.destroyWindow(win_name)
            cv2.waitKey(1)
            return None
        if key == 27:
            cv2.destroyAllWindows()
            raise SystemExit(0)


# ===============================
# MAIN
# ===============================

def main():
 
    print(">>> RUNNING FILE:", __file__, flush=True)
    print(">>> PYTHON:", sys.executable, flush=True)

    images = sorted(p for p in DATA_DIR.iterdir() if p.suffix.lower() in {".jpg", ".png", ".jpeg"})
    if not images:
        print("[!] No images found in", DATA_DIR)
        return

    print("PROJECT_ROOT:", PROJECT_ROOT)
    print("DATA_DIR:", DATA_DIR)
    print("RESULTS_DIR:", RESULTS_DIR)
    print("OBJECT_STORE_ROOT:", STORE.root_dir)
    print(f"Found {len(images)} images.")

    done = load_done_images(SCORES_CSV)
    mode = prompt_resume_or_restart(done_count=len(done), total=len(images))

    if mode == MODE_QUIT:
        print("Quit.")
        return

    if mode == MODE_RESTART:
        backup_and_reset_scores_csv(SCORES_CSV)
        done = set()

    write_header = not scores_csv_has_header(SCORES_CSV)
    writer: csv.DictWriter | None = None

    with open(SCORES_CSV, "a", newline="") as f:
        for img_path in images:
            if mode == MODE_RESUME and img_path.name in done:
                continue

            print("\n[MAIN] Now scoring:", img_path.name)

            try:
                result = click_and_score_image(img_path, debug=True)
            except SystemExit:
                print("[MAIN] User requested exit. Stopping.")
                break

            if result is None:
                continue

            if writer is None:
                fieldnames = [
                    "image_name",
                    "col2",
                    "col3",
                    "col4",
                    "run_id",
                    "annotation_confidence",
                    "overlay_png_key",
                    "overlay_json_key",
                    "summary_json_key",
                ]
                writer = csv.DictWriter(f, fieldnames=fieldnames)
                if write_header:
                    writer.writeheader()

            writer.writerow(result)
            f.flush()
            done.add(img_path.name)

    print("\nDone. Saved scores to:", SCORES_CSV)


if __name__ == "__main__":
    main()
