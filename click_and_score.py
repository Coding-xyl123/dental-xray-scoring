
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
import cv2  # type: ignore
import numpy as np
from pathlib import Path
import csv
from PIL import Image  # add this to your imports


# ===============================
# SCALE CONFIG
# ===============================

DEFAULT_IMAGE_WIDTH_CM = 26.0   # assumed pano width if no trusted DPI
MIN_TRUSTED_DPI = 150           # below this we treat DPI as "screen" / untrusted

def suggest_upper_midline_x(img: np.ndarray) -> int:
    """
    Heuristic suggestion for the UPPER teeth midline x-position.

    Strategy (simple + robust):
    1) Convert to grayscale.
    2) Use Sobel vertical edges to highlight tooth/bone structures.
    3) Sum edge strength per column.
    4) Only look in a central band (e.g. 30%–70% of width) to avoid edges.
    5) Take the column with the highest edge energy in that band.
    """
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    h, w = gray.shape[:2]

    # Vertical Sobel to detect vertical structures
    sobelx = cv2.Sobel(gray, cv2.CV_64F, 1, 0, ksize=3)
    abs_sobelx = np.abs(sobelx)

    # Column-wise energy
    col_energy = abs_sobelx.sum(axis=0)

    # Restrict to a central band to avoid extreme edges
    left = int(w * 0.30)
    right = int(w * 0.70)
    band = col_energy[left:right]

    # If band is weirdly empty, just use image center
    if band.size == 0:
        return w // 2

    best_offset = int(np.argmax(band))
    best_x = left + best_offset
    return best_x


def estimate_px_per_cm(image_path: Path, img_width_px: int) -> float:
    """
    Estimate how many pixels ≈ 1 cm for this panoramic image.

    Strategy:
    1) Try to read a *trusted* DPI value from the image metadata.
       - Many clinical images are exported at 200–300 DPI or higher.
       - Screen-like DPIs (72, 96) are ignored because they're not true acquisition DPI.
    2) If DPI is trusted, compute cm from: width_inch = pixels / DPI, then cm = inch * 2.54.
    3) If DPI is missing or looks untrusted, fall back to a typical pano width
       (DEFAULT_IMAGE_WIDTH_CM, e.g. 26 cm).

    NOTE:
    With JPEG/PNG exports only (no DICOM, no scale bar), we cannot recover
    exact real-world centimeters. This function provides a consistent
    *approximate* scale that is sufficient for relative scoring.
    """
    width_cm = None

    # Try EXIF DPI first
    try:
        with Image.open(image_path) as pil_img:
            dpi = pil_img.info.get("dpi", None)
            if dpi is not None and dpi[0] >= MIN_TRUSTED_DPI:
                dpi_x = dpi[0]
                width_inch = img_width_px / dpi_x
                width_cm = width_inch * 2.54
    except Exception as e:
        print(f"[INFO] Could not read DPI from {image_path}: {e}")

    # Fallback: assume a typical pano sensor width
    if width_cm is None:
        width_cm = DEFAULT_IMAGE_WIDTH_CM

    return img_width_px / width_cm


# ===============================
# PROJECT PATHS
# ===============================

try:
    PROJECT_ROOT = Path(__file__).resolve().parent
except NameError:
    PROJECT_ROOT = Path.cwd().resolve()

DATA_DIR = PROJECT_ROOT / "data" / "images"
RESULTS_DIR = PROJECT_ROOT / "results" / "overlays"
RESULTS_DIR.mkdir(parents=True, exist_ok=True)
SCORES_CSV = PROJECT_ROOT / "results" / "scores.csv"


# ===============================
# HELPER FUNCTIONS (SCORING)
# ===============================

def score_bone_balance(upper_mid, bone_left, bone_right, px_per_cm,
                       equal_tol_cm=0.1, within_tol_cm=1.0, debug=True):
    """
    Column 2 – horizontal bone balance (PATIENT left/right).
    """
    # image -> patient mapping
    patient_left_cm = abs(bone_right[0] - upper_mid[0]) / px_per_cm   # image RIGHT
    patient_right_cm = abs(bone_left[0] - upper_mid[0]) / px_per_cm   # image LEFT

    diff_cm = patient_left_cm - patient_right_cm
    diff_abs_cm = abs(diff_cm)

    if debug:
        print(f"[DEBUG C2] p_left_cm={patient_left_cm:.2f}, "
              f"p_right_cm={patient_right_cm:.2f}, "
              f"diff_cm={diff_cm:.2f}, |diff|={diff_abs_cm:.2f}")

    # equal lengths
    if diff_abs_cm <= equal_tol_cm:
        return 3

    # PATIENT LEFT side longer
    if diff_cm > 0:
        return 2 if diff_abs_cm <= within_tol_cm else 1

    # PATIENT RIGHT side longer
    return 4 if diff_abs_cm <= within_tol_cm else 5



def score_upper_midline_position(upper_mid, img_width_px, px_per_cm,
                                 center_tol_cm=0.2, debug=True):
    """
    Column 3 – is upper teeth midline in the middle of the image? (PATIENT perspective)
    """
    img_center_x = img_width_px / 2.0
    dx_px_image = upper_mid[0] - img_center_x  # image coords (image right = +)

    # image right = patient LEFT, so patient_dx = -dx_image
    patient_dx_cm = -dx_px_image / px_per_cm

    if debug:
        print(f"[DEBUG C3] patient_dx_cm={patient_dx_cm:.2f}")

    if abs(patient_dx_cm) <= center_tol_cm:
        return 2
    elif patient_dx_cm > 0:
        # upper midline is PATIENT LEFT of center
        return 1
    else:
        # upper midline is PATIENT RIGHT of center
        return 3


def score_upper_lower_alignment(upper_mid, lower_mid, px_per_cm,
                                equal_tol_cm=0.1, debug=True):
    """
    Column 4 – alignment between UPPER and LOWER teeth midlines (PATIENT perspective).

    patient_dx_cm > 0  -> LOWER is PATIENT LEFT of UPPER
    patient_dx_cm < 0  -> LOWER is PATIENT RIGHT of UPPER

    Rubric (和 Excel 一致的版本)：
      - |dx| <= equal_tol_cm           -> 3  (perfect aligned)
      - LOWER 在 PATIENT LEFT，|dx|<=1 -> 4
      - LOWER 在 PATIENT LEFT，|dx|>1  -> 5
      - LOWER 在 PATIENT RIGHT，|dx|<=1-> 2
      - LOWER 在 PATIENT RIGHT，|dx|>1 -> 1
    """
    dx_px_image = lower_mid[0] - upper_mid[0]   # image coords
    patient_dx_cm = -dx_px_image / px_per_cm    # flip for patient space
    dx_abs_cm = abs(patient_dx_cm)

    if debug:
        print(f"[DEBUG C4] patient_dx_cm={patient_dx_cm:.2f}, |dx|={dx_abs_cm:.2f}")

    # 完全对齐
    if dx_abs_cm <= equal_tol_cm:
        return 3

    # LOWER 在病人左侧
    if patient_dx_cm > 0:
        return 4 if dx_abs_cm <= 1.0 else 5

    # LOWER 在病人右侧
    return 2 if dx_abs_cm <= 1.0 else 1
def suggest_midline_x_in_band(img: np.ndarray,
                              top_frac: float,
                              bottom_frac: float) -> int:
    """
    Generic helper:
      - takes a vertical band [top_frac, bottom_frac] of the image
      - finds the x where left/right halves are most symmetric
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


def suggest_lines_and_endpoints(img):
    """
    Heuristic hints for:
      - upper midline x
      - lower midline x
      - left bone endpoint (x, y)
      - right bone endpoint (x, y)

    These are ONLY visual hints, not used in scoring.
    """
    h, w = img.shape[:2]

    # upper midline: band slightly above image center
    upper_x = suggest_midline_x_in_band(img, top_frac=0.25, bottom_frac=0.55)

    # lower midline: band slightly below image center
    lower_x = suggest_midline_x_in_band(img, top_frac=0.50, bottom_frac=0.85)

    # very coarse bone endpoints
    y_bone = int(h * 0.35)
    left_x = int(w * 0.12)
    right_x = int(w * 0.88)

    left_pt = (left_x, y_bone)
    right_pt = (right_x, y_bone)

    return upper_x, lower_x, left_pt, right_pt

# def suggest_midline_x_in_band(img: np.ndarray,
#                               top_frac: float,
#                               bottom_frac: float) -> int:
#     """
#     Generic helper:
#       - takes a vertical band [top_frac, bottom_frac] of the image
#       - finds the x where left/right halves are most symmetric
#     """
#     h, w = img.shape[:2]
#     gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
#     gray_blur = cv2.GaussianBlur(gray, (9, 9), 0)

#     top = int(h * top_frac)
#     bottom = int(h * bottom_frac)
#     if bottom <= top:
#         top = 0
#         bottom = h

#     band = gray_blur[top:bottom, :]

#     center = w // 2
#     window = 80
#     best_x = center
#     best_score = 1e9

#     for x in range(center - window, center + window + 1):
#         if x <= 0 or x >= w:
#             continue

#         left = band[:, :x]
#         right = band[:, x:]
#         right_flipped = cv2.flip(right, 1)

#         min_width = min(left.shape[1], right_flipped.shape[1])
#         if min_width < 40:
#             continue

#         left_crop = left[:, :min_width]
#         right_crop = right_flipped[:, :min_width]
#         diff = np.mean(np.abs(left_crop - right_crop))

#         if diff < best_score:
#             best_score = diff
#             best_x = x

#     return int(best_x)


# def suggest_lines_and_endpoints(img):
#     """
#     Heuristic hints for:
#       - upper midline x
#       - lower midline x
#       - left bone endpoint (x, y)
#       - right bone endpoint (x, y)

#     These are ONLY visual hints, not used in scoring.
#     """
#     h, w = img.shape[:2]

#     # upper midline: band slightly above image center
#     upper_x = suggest_midline_x_in_band(img, top_frac=0.25, bottom_frac=0.55)

#     # lower midline: band slightly below image center
#     lower_x = suggest_midline_x_in_band(img, top_frac=0.50, bottom_frac=0.85)

#     # very coarse bone endpoints
#     y_bone = int(h * 0.35)
#     left_x = int(w * 0.12)
#     right_x = int(w * 0.88)

#     left_pt = (left_x, y_bone)
#     right_pt = (right_x, y_bone)

#     return upper_x, lower_x, left_pt, right_pt

# ===============================
# INTERACTIVE CLICK + SCORE
# ===============================
# 

def click_and_score_image(image_path: Path, debug=True):
    img = cv2.imread(str(image_path))
    if img is None:
        print(f"[!] Could not read {image_path}")
        return None

    h, w = img.shape[:2]

    # Estimate pixel-to-centimeter scale.
    px_per_cm = estimate_px_per_cm(image_path, w)

    if debug:
        print(f"[DEBUG SCALE] img_width_px={w}, px_per_cm={px_per_cm:.3f}")

    # === heuristic hints (upper/lower midlines + bone endpoints) ===
    upper_x_sug, lower_x_sug, bone_left_sug, bone_right_sug = \
        suggest_lines_and_endpoints(img)

    if debug:
        print(f"[HINT] upper_x ≈ {upper_x_sug}, lower_x ≈ {lower_x_sug}, "
              f"bone_left_sug={bone_left_sug}, bone_right_sug={bone_right_sug}")

    window_name = f"Click 4 points: {image_path.name}"
    cv2.namedWindow(window_name, cv2.WINDOW_NORMAL)

    base = img.copy()

    # --- draw static hints on base image ---
    # 1) upper midline hint (blue)
    cv2.line(base, (upper_x_sug, 0), (upper_x_sug, h), (255, 0, 0), 1)
    cv2.putText(base, "1: Hint upper midline",
                (10, 20),
                cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 0, 0), 1)

    # 2) lower midline hint (magenta)
    cv2.line(base, (lower_x_sug, 0), (lower_x_sug, h), (255, 0, 255), 1)
    cv2.putText(base, "2: Hint lower midline",
                (10, 40),
                cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 0, 255), 1)

    # 3) bone endpoints hints
    cv2.circle(base, bone_left_sug, 6, (0, 0, 255), 1)   # red
    cv2.circle(base, bone_right_sug, 6, (0, 255, 0), 1)  # green
    cv2.putText(base, "3 & 4: Hint bone ends (L/R)",
                (10, 60),
                cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 255), 1)

    step_texts = [
        "1) Click UPPER teeth midline",
        "2) Click LOWER teeth midline",
        "3) Click LEFT bone end (image LEFT, PATIENT RIGHT)",
        "4) Click RIGHT bone end (image RIGHT, PATIENT LEFT)",
    ]

    points: list[tuple[int, int]] = []

    def redraw_with_status():
        """
        Redraw image with:
          - static hints
          - current step instructions at bottom
          - already clicked points labeled by type
        """
        disp = base.copy()

        # bottom black bar for instructions
        cv2.rectangle(disp, (0, h - 40), (w, h), (0, 0, 0), -1)
        step_idx = min(len(points), 3)  # 0..3
        msg = f"Next: {step_texts[step_idx]}   [r=reset, q=skip, ESC=quit]"
        cv2.putText(disp, msg,
                    (10, h - 15),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)

        # draw clicked points with meaningful labels
        labels = ["UPPER", "LOWER", "BONE L", "BONE R"]
        colors = [(0, 255, 255),  # yellow
                  (255, 255, 0),  # cyan
                  (0, 0, 255),    # red
                  (0, 255, 0)]    # green

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
                return  # ignore extra clicks
            points.append((int(x), int(y)))
            print(f"Point {len(points)} ({step_texts[len(points)-1]}): ({x}, {y})")
            redraw_with_status()

    cv2.setMouseCallback(window_name, mouse_callback)

    # initial draw
    redraw_with_status()

    print("\n===========================")
    print(f"Image: {image_path.name}")
    print("Click order (also shown at bottom of the window):")
    for txt in step_texts:
        print("  ", txt)
    print("Keys during clicking:  r = reset  •  q = skip this image  •  ESC = quit application")
    print("After all 4 points:    n / Enter = accept & go to next image")
    print("===========================")

    # ---- 1) CLICK PHASE: collect exactly 4 points or skip/quit ----
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
            # we have all 4 points; move to scoring phase
            break

    if len(points) != 4:
        print("[!] Not enough points (need 4). Skipping.")
        cv2.destroyWindow(window_name)
        return None

    upper_mid, lower_mid, bone_left, bone_right = points

    # ---- 2) SCORING PHASE: compute scores & overlay ----
    s2 = score_bone_balance(upper_mid, bone_left, bone_right, px_per_cm,
                            debug=debug)
    s3 = score_upper_midline_position(upper_mid, w, px_per_cm, debug=debug)
    s4 = score_upper_lower_alignment(upper_mid, lower_mid, px_per_cm,
                                     debug=debug)

    print("Scores for", image_path.name)
    print("  Column 2 (bone balance, patient L/R):   ", s2)
    print("  Column 3 (upper mid in center, patient):", s3)
    print("  Column 4 (upper vs lower, patient):     ", s4)

    overlay = img.copy()

    # points
    cv2.circle(overlay, upper_mid, 7, (0, 255, 255), -1)   # yellow
    cv2.circle(overlay, lower_mid, 7, (255, 255, 0), -1)   # cyan
    cv2.circle(overlay, bone_left, 7, (0, 0, 255), -1)     # red
    cv2.circle(overlay, bone_right, 7, (0, 255, 0), -1)    # green

    # midlines
    cv2.line(overlay, (upper_mid[0], 0), (upper_mid[0], h), (0, 255, 255), 1)
    cv2.line(overlay, (lower_mid[0], 0), (lower_mid[0], h), (255, 255, 0), 1)

    # bone arms
    cv2.line(overlay, upper_mid, bone_left, (0, 0, 255), 2)
    cv2.line(overlay, upper_mid, bone_right, (0, 255, 0), 2)

    text = f"C2:{s2}  C3:{s3}  C4:{s4}"
    cv2.putText(overlay, text, (10, 30),
                cv2.FONT_HERSHEY_SIMPLEX, 1.0, (255, 255, 255), 2)

    # bottom bar for post-scoring instructions
    cv2.rectangle(overlay, (0, h - 40), (w, h), (0, 0, 0), -1)
    cv2.putText(overlay, "Scored.  n / Enter = next  •  q = skip  •  ESC = quit",
                (10, h - 15),
                cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)

    out_path = RESULTS_DIR / f"{image_path.stem}_scored.png"
    cv2.imwrite(str(out_path), overlay)
    print("Saved overlay to:", out_path)

    # show overlay and WAIT for user confirmation
    cv2.imshow(window_name, overlay)

    print("[INFO] Scoring complete. Press:")
    print("       n or Enter  -> accept & go to next image")
    print("       q           -> skip this image (no CSV row)")
    print("       ESC         -> quit the application")

    while True:
        key = cv2.waitKey(0) & 0xFF

        if key in (ord('n'), 13):  # 'n' or Enter
            cv2.destroyWindow(window_name)
            return {
                "image_name": image_path.name,
                "col2": s2,
                "col3": s3,
                "col4": s4,
            }

        elif key == ord('q'):
            print("[*] User chose to skip this image after preview.")
            cv2.destroyWindow(window_name)
            return None

        elif key == 27:  # ESC
            print("[*] ESC pressed — quitting application.")
            cv2.destroyAllWindows()
            raise SystemExit(0)
        # any other key: ignore and continue waiting



def main():
    print("PROJECT_ROOT:", PROJECT_ROOT)
    print("DATA_DIR:", DATA_DIR)
    print("RESULTS_DIR:", RESULTS_DIR)

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

    # --- prepare CSV dir ---
    SCORES_CSV.parent.mkdir(parents=True, exist_ok=True)
    write_header = not SCORES_CSV.exists()

    writer = None  # we will create it after first valid result

    with open(SCORES_CSV, "a", newline="") as f:
        for img_path in images:
            print(f"\n[MAIN] Now scoring: {img_path.name}")

            try:
                result = click_and_score_image(img_path, debug=True)
            except SystemExit:
                # ESC pressed inside click_and_score_image
                print("[MAIN] User requested exit. Stopping.")
                break

            # User skipped this image (q either during click or after overlay)
            if result is None:
                continue

            # First valid result: build CSV writer with correct columns
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

# NOTE ON SCALE AND THE "1 CM" RULE
# ---------------------------------
# These images are JPEG/PNG exports without DICOM calibration metadata.
# That means we cannot recover the true physical centimeters of the anatomy.
#
# In this project, we estimate scale in two steps:
#   1. If the image has a trustworthy DPI in its metadata (e.g. >= 150 DPI),
#      we use it to convert pixels -> inches -> centimeters.
#   2. Otherwise, we assume a typical panoramic sensor width of 26 cm.
#
# The scoring rubric (1–5 for each column) depends on RELATIVE asymmetry
# and deviations, not on exact millimeter precision. The "1 cm" rule is
# implemented as ~1.2 cm in code to better match visual / Excel labels.
# This approximate scale is sufficient for the intended use of this tool.
