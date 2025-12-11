import pandas as pd  # type: ignore
import re
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent
SCORES_CSV = PROJECT_ROOT / "results" / "scores.csv"
TRUTH_XLSX = PROJECT_ROOT / "scoring 1-200.xlsx"

# 1. Load your model scores (from click_and_score.py)
scores = pd.read_csv(SCORES_CSV)
print("Scores columns:", scores.columns.tolist())

# 2. Load the ground truth from Excel
truth = pd.read_excel(TRUTH_XLSX)
print("Truth columns:", truth.columns.tolist())

# ---------------------------------------------------------
# STEP A: Build a numeric ID (img_id) on BOTH sides
# ---------------------------------------------------------

def extract_id_from_scores(name):
    """
    From '1.jpg' or 'image_001.png' -> 1
    """
    s = str(name)
    m = re.search(r"(\d+)", s)
    if m:
        return int(m.group(1))
    return None

scores["img_id"] = scores["image_name"].apply(extract_id_from_scores)

# 👉 In your current Excel, the FIRST column is the image index (1..200),
# even though its name is something weird like '\xa0\xa0'.
img_col = truth.columns[0]
print("Using truth image column:", repr(img_col))

def extract_id_from_truth(v):
    """
    Excel may store:
      - 1, 2, 3
      - 1.0, 2.0
      - '1', '2'
      - '1.jpg'
    We normalize all of them to integer IDs (1, 2, 3, ...).
    """
    s = str(v).strip()
    if s == "" or s.lower() == "nan":
        return None

    # Try numeric first
    try:
        return int(float(s))
    except ValueError:
        pass

    # Otherwise, fall back to regex (e.g., "1.jpg")
    m = re.search(r"(\d+)", s)
    if m:
        return int(m.group(1))

    return None

truth["img_id"] = truth[img_col].apply(extract_id_from_truth)

print("\nSample img_id values from scores:", scores["img_id"].head().tolist())
print("Sample img_id values from truth:", truth["img_id"].head().tolist())

# ---------------------------------------------------------
# STEP B: Identify which columns in Excel are C2 / C3 / C4
# ---------------------------------------------------------
# With your current Excel header:
#   col 0: image index (we just used it)
#   col 1: Column 2 labels
#   col 2: Column 3 labels
#   col 3: Column 4 labels
#
# So we rename them directly:

rubric_cols = truth.columns[1:4]  # Unnamed: 1, Unnamed: 2, Unnamed: 3
truth = truth.rename(
    columns={
        rubric_cols[0]: "true_col2",
        rubric_cols[1]: "true_col3",
        rubric_cols[2]: "true_col4",
    }
)

# Ensure labels are numeric (1–5)
for c in ["true_col2", "true_col3", "true_col4"]:
    truth[c] = pd.to_numeric(truth[c], errors="coerce")

# Keep only the useful columns
truth_small = truth[["img_id", "true_col2", "true_col3", "true_col4"]].copy()

# ---------------------------------------------------------
# STEP C: Merge scores with truth on img_id
# ---------------------------------------------------------
merged = scores.merge(truth_small, on="img_id", how="inner")
print("\nMerged shape:", merged.shape)
print(merged[["image_name", "img_id", "col2", "true_col2"]].head())

if merged.empty:
    raise SystemExit("Merged dataframe is empty (no matching img_id). Check IDs in scores.csv and Excel.")

# ---------------------------------------------------------
# STEP D: Evaluate accuracy for each column
# ---------------------------------------------------------
def evaluate_column(pred_col, true_col, name):
    mask = merged[true_col].notna()
    if mask.sum() == 0:
        print(f"\n[{name}] No valid ground-truth labels found.")
        return

    acc = (merged.loc[mask, pred_col] == merged.loc[mask, true_col]).mean()
    print(f"\n[{name}] accuracy: {acc * 100:.2f}% (on {mask.sum()} images)")

    print(f"[{name}] confusion table (truth rows, predictions columns):")
    print(pd.crosstab(merged.loc[mask, true_col],
                      merged.loc[mask, pred_col],
                      rownames=["truth"],
                      colnames=["pred"]))


evaluate_column("col2", "true_col2", "Column 2 – bone balance")
evaluate_column("col3", "true_col3", "Column 3 – upper midline center")
evaluate_column("col4", "true_col4", "Column 4 – upper vs lower alignment")

print("\nDone.")
