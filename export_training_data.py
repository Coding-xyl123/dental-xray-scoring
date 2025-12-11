# export_training_data.py
import pandas as pd  # type: ignore
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent
SCORES_CSV = PROJECT_ROOT / "results" / "scores.csv"
TRUTH_XLSX = PROJECT_ROOT / "scoring 1-200.xlsx"
OUT_CSV = PROJECT_ROOT / "results" / "training_dataset.csv"


def load_scores() -> pd.DataFrame:
    df = pd.read_csv(SCORES_CSV)
    df["image_name"] = df["image_name"].astype(str).str.strip()
    return df


def load_truth() -> pd.DataFrame:
    """
    Your Excel has weird column names; we normalize them.
    We expect:
      - a column with image index 1..200
      - three columns with GT scores for col2, col3, col4
    """
    raw = pd.read_excel(TRUTH_XLSX)

    # Identify the image index column (first numeric-ish column)
    possible_idx_cols = []
    for col in raw.columns:
        if pd.api.types.is_numeric_dtype(raw[col]):
            possible_idx_cols.append(col)

    if not possible_idx_cols:
        raise ValueError("Could not find numeric index column in truth Excel.")

    img_idx_col = possible_idx_cols[0]

    # First three non-empty columns after index will be col2/3/4 GT
    non_idx_cols = [c for c in raw.columns if c != img_idx_col]
    gt_cols = non_idx_cols[:3]

    truth = raw[[img_idx_col] + gt_cols].copy()
    truth.columns = ["img_id", "gt_col2", "gt_col3", "gt_col4"]

    truth["img_id"] = truth["img_id"].astype("Int64")
    truth = truth.dropna(subset=["img_id"])
    truth["img_id"] = truth["img_id"].astype(int)

    # Create "image_name" like "1.jpg"
    truth["image_name"] = truth["img_id"].astype(str) + ".jpg"
    truth["image_name"] = truth["image_name"].str.strip()

    return truth


def main():
    scores = load_scores()
    truth = load_truth()

    merged = scores.merge(truth, on="image_name", how="inner")
    print("Merged shape:", merged.shape)

    # Rename model columns
    merged = merged.rename(
        columns={
            "col2": "model_col2",
            "col3": "model_col3",
            "col4": "model_col4",
        }
    )

    cols = [
        "image_name",
        "model_col2", "model_col3", "model_col4",
        "gt_col2", "gt_col3", "gt_col4",
    ]
    merged[cols].to_csv(OUT_CSV, index=False)
    print("Saved training dataset to:", OUT_CSV)


if __name__ == "__main__":
    main()
