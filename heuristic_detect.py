import cv2
import numpy as np

def heuristic_detect_points(img):
    """
    Lightweight heuristic detector for:
      - upper midline
      - lower midline
      - left bone end
      - right bone end

    Returns dict with keys:
      "upper_mid", "lower_mid", "left_bone", "right_bone"
    """

    h, w = img.shape[:2]

    # --- 1) Convert to grayscale ---
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

    # --- 2) Smooth / denoise ---
    blur = cv2.GaussianBlur(gray, (25, 25), 0)

    # --- 3) Compute vertical intensity profile ---
    vertical_profile = blur.mean(axis=0)  # average each column

    # --- 4) Upper midline heuristic ---
    # We expect the dental arch to have a dark notch at the midline.
    # Find global minimum around image center ± 10%.
    center_zone = vertical_profile[int(w * 0.35): int(w * 0.65)]
    min_idx = np.argmin(center_zone)
    upper_mid_x = int(w * 0.35) + min_idx
    upper_mid_y = int(h * 0.40)   # heuristic vertical location

    # --- 5) Lower midline heuristic ---
    # Typically below upper midline; reuse x but deeper y.
    lower_mid_x = upper_mid_x
    lower_mid_y = int(h * 0.60)

    # --- 6) Bone ends heuristic ---
    # Teeth region is bright; bone edges appear where intensity drops.
    # Use gradient magnitude across the width.
    grad = np.abs(np.gradient(vertical_profile))

    # Take the highest gradients near edges (bone transition)
    left_zone = grad[: int(w * 0.25)]
    right_zone = grad[int(w * 0.75):]

    left_x = int(np.argmax(left_zone))
    right_x = int(w * 0.75) + int(np.argmax(right_zone))

    # Assume both bone endpoints at similar vertical level
    bone_y = int(h * 0.35)

    return {
        "upper_mid": (upper_mid_x, upper_mid_y),
        "lower_mid": (lower_mid_x, lower_mid_y),
        "left_bone": (left_x, bone_y),
        "right_bone": (right_x, bone_y),
    }
