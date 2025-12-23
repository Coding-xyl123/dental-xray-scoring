# src/scoring_core.py
from __future__ import annotations

from typing import Dict, Tuple


Point = Tuple[int, int]


def score_bone_balance(
    upper_mid: Point,
    bone_left: Point,
    bone_right: Point,
    px_per_cm: float,
    equal_tol_cm: float = 0.1,
    within_tol_cm: float = 1.0,
    debug: bool = False,
) -> int:
    """
    Column 2 – horizontal bone balance (PATIENT left/right).
    """
    patient_left_cm = abs(bone_right[0] - upper_mid[0]) / px_per_cm   # image RIGHT
    patient_right_cm = abs(bone_left[0] - upper_mid[0]) / px_per_cm   # image LEFT

    diff_cm = patient_left_cm - patient_right_cm
    diff_abs_cm = abs(diff_cm)

    if debug:
        print(f"[DEBUG C2] p_left_cm={patient_left_cm:.2f}, "
              f"p_right_cm={patient_right_cm:.2f}, "
              f"diff_cm={diff_cm:.2f}, |diff|={diff_abs_cm:.2f}")

    if diff_abs_cm <= equal_tol_cm:
        return 3

    if diff_cm > 0:
        return 2 if diff_abs_cm <= within_tol_cm else 1

    return 4 if diff_abs_cm <= within_tol_cm else 5


def score_upper_midline_position(
    upper_mid: Point,
    img_width_px: int,
    px_per_cm: float,
    center_tol_cm: float = 0.2,
    debug: bool = False,
) -> int:
    """
    Column 3 – is upper teeth midline in the middle of the image? (PATIENT perspective)
    """
    img_center_x = img_width_px / 2.0
    dx_px_image = upper_mid[0] - img_center_x
    patient_dx_cm = -dx_px_image / px_per_cm

    if debug:
        print(f"[DEBUG C3] patient_dx_cm={patient_dx_cm:.2f}")

    if abs(patient_dx_cm) <= center_tol_cm:
        return 2
    elif patient_dx_cm > 0:
        return 1
    else:
        return 3


def score_upper_lower_alignment(
    upper_mid: Point,
    lower_mid: Point,
    px_per_cm: float,
    equal_tol_cm: float = 0.1,
    debug: bool = False,
) -> int:
    """
    Column 4 – alignment between UPPER and LOWER teeth midlines (PATIENT perspective).
    """
    dx_px_image = lower_mid[0] - upper_mid[0]
    patient_dx_cm = -dx_px_image / px_per_cm
    dx_abs_cm = abs(patient_dx_cm)

    if debug:
        print(f"[DEBUG C4] patient_dx_cm={patient_dx_cm:.2f}, |dx|={dx_abs_cm:.2f}")

    if dx_abs_cm <= equal_tol_cm:
        return 3

    if patient_dx_cm > 0:
        return 4 if dx_abs_cm <= 1.0 else 5

    return 2 if dx_abs_cm <= 1.0 else 1


def compute_scores_from_points(
    *,
    upper_mid: Point,
    lower_mid: Point,
    bone_left: Point,
    bone_right: Point,
    img_width_px: int,
    px_per_cm: float,
    debug: bool = False,
) -> Dict[str, int]:
    """
    Deterministic scoring given four clicked points + scale.
    """
    s2 = score_bone_balance(upper_mid, bone_left, bone_right, px_per_cm, debug=debug)
    s3 = score_upper_midline_position(upper_mid, img_width_px, px_per_cm, debug=debug)
    s4 = score_upper_lower_alignment(upper_mid, lower_mid, px_per_cm, debug=debug)
    return {
        "col2_bone_balance": int(s2),
        "col3_upper_mid_center": int(s3),
        "col4_upper_lower_alignment": int(s4),
    }
