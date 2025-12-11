# # # streamlit_app.py
# # import streamlit as st
# # import pandas as pd
# # from pathlib import Path
# # from PIL import Image

# # # -----------------------------
# # # Paths (match your project)
# # # -----------------------------
# # PROJECT_ROOT = Path(__file__).resolve().parent
# # DATA_DIR = PROJECT_ROOT / "data" / "images"
# # OVERLAYS_DIR = PROJECT_ROOT / "results" / "overlays"
# # SCORES_CSV = PROJECT_ROOT / "results" / "scores.csv"


# # # -----------------------------
# # # Helpers
# # # -----------------------------
# # @st.cache_data
# # def load_scores():
# #     df = pd.read_csv(SCORES_CSV)

# #     if "image_name" not in df.columns:
# #         st.error("scores.csv does not contain an 'image_name' column.")
# #         st.stop()

# #     # ensure string and strip spaces
# #     df["image_name"] = df["image_name"].astype(str).str.strip()
# #     return df


# # def sorted_image_names(names):
# #     """Sort 1.jpg, 2.jpg, 10.jpg by numeric part."""
# #     def key_fn(name: str):
# #         stem = Path(name).stem
# #         try:
# #             return int(stem)
# #         except ValueError:
# #             return 10**9
# #     return sorted(names, key=key_fn)


# # # -----------------------------
# # # Streamlit UI
# # # -----------------------------
# # st.set_page_config(page_title="Dental X-ray Scoring Explorer", layout="wide")

# # st.title("Dental Panoramic X-ray Scoring Explorer")

# # scores = load_scores()

# # # Sidebar: dataset description
# # st.sidebar.header("Dataset folders")
# # st.sidebar.markdown(
# #     f"""
# # - `data/images/` – original panoramic images  
# # - `results/overlays/` – images with scoring overlays  
# # - `results/scores.csv` – per-image scores (C2, C3, C4)
# # """
# # )

# # # Sidebar: case selector – **this is the important fix**
# # image_names = sorted_image_names(scores["image_name"].unique().tolist())
# # default_index = 0

# # selected_image = st.sidebar.selectbox(
# #     "Select a case (image_name)",
# #     options=image_names,
# #     index=default_index,
# # )

# # st.sidebar.markdown(f"**Selected file:** `{selected_image}`")

# # # Get the row for this image
# # row = scores[scores["image_name"] == selected_image]
# # if row.empty:
# #     st.error(f"No row found in scores.csv for image `{selected_image}`.")
# #     st.stop()
# # row = row.iloc[0]

# # # Paths
# # img_path = DATA_DIR / selected_image
# # overlay_path = OVERLAYS_DIR / f"{Path(selected_image).stem}_scored.png"

# # # -----------------------------
# # # Main layout
# # # -----------------------------
# # col_img, col_scores = st.columns([2, 1])

# # with col_img:
# #     st.subheader("Image view")

# #     # Original image
# #     if img_path.exists():
# #         st.caption(f"Original image: `{img_path}`")
# #         st.image(Image.open(img_path), use_column_width=True)
# #     else:
# #         st.warning(f"Original image not found at `{img_path}`")

# #     # Overlay image
# #     if overlay_path.exists():
# #         st.caption(f"Overlay (with clicks & scores): `{overlay_path.name}`")
# #         st.image(Image.open(overlay_path), use_column_width=True)
# #     else:
# #         st.info("No overlay image found for this case yet.")

# # with col_scores:
# #     st.subheader("Per-image scores")

# #     st.markdown("**Rubric (1–5)**")
# #     st.markdown(
# #         """
# # - **C2**: left/right bone length asymmetry  
# # - **C3**: distance of upper midline from image center  
# # - **C4**: horizontal offset between upper and lower midlines
# # """
# #     )

# #     c2 = int(row["col2"])
# #     c3 = int(row["col3"])
# #     c4 = int(row["col4"])

# #     st.markdown("### Column 2 – Bone balance")
# #     st.metric("C2 score", c2)

# #     st.markdown("### Column 3 – Upper midline vs center")
# #     st.metric("C3 score", c3)

# #     st.markdown("### Column 4 – Upper vs lower midline")
# #     st.metric("C4 score", c4)

# # st.markdown("---")
# # st.caption(
# #     "This app reads `results/scores.csv` and always uses the `image_name` "
# #     "column as the case identifier, so each case corresponds to one filename "
# #     "like `1.jpg`, `10.jpg`, etc."
# # )
# # streamlit_app.py
# import streamlit as st
# import pandas as pd
# import numpy as np
# from pathlib import Path
# from PIL import Image
# import matplotlib.pyplot as plt

# # -----------------------------
# # Paths (match your project)
# # -----------------------------
# PROJECT_ROOT = Path(__file__).resolve().parent
# DATA_DIR = PROJECT_ROOT / "data" / "images"
# OVERLAYS_DIR = PROJECT_ROOT / "results" / "overlays"
# SCORES_CSV = PROJECT_ROOT / "results" / "scores.csv"

# # Optional ground-truth Excel (if present, will be used for confusion matrices)
# TRUTH_XLSX = PROJECT_ROOT / "Copy of scoring 1-200.xlsx"


# # -----------------------------
# # Helpers
# # -----------------------------
# @st.cache_data
# def load_scores() -> pd.DataFrame:
#     df = pd.read_csv(SCORES_CSV)

#     if "image_name" not in df.columns:
#         st.error("scores.csv does not contain an 'image_name' column.")
#         st.stop()

#     df["image_name"] = df["image_name"].astype(str).str.strip()
#     return df


# @st.cache_data
# def load_truth() -> pd.DataFrame | None:
#     """
#     Load ground truth from Excel if it exists.

#     Assumptions (adjust if your sheet is different):
#       - First column: case index (1..N)
#       - Second column: truth for Column 2 (bone balance)
#       - Third column: truth for Column 3
#       - Fourth column: truth for Column 4
#     """
#     if not TRUTH_XLSX.exists():
#         return None

#     raw = pd.read_excel(TRUTH_XLSX)

#     if raw.shape[1] < 4:
#         # Not enough columns to parse truth
#         return None

#     img_col = raw.columns[0]
#     c2_col = raw.columns[1]
#     c3_col = raw.columns[2]
#     c4_col = raw.columns[3]

#     truth = pd.DataFrame()
#     # Convert 1.0 -> "1.jpg" etc.
#     truth["image_name"] = (
#         raw[img_col]
#         .astype("Int64")  # pandas nullable int
#         .astype(str)
#         .str.strip()
#         + ".jpg"
#     )

#     truth["true_col2"] = raw[c2_col].astype("Int64")
#     truth["true_col3"] = raw[c3_col].astype("Int64")
#     truth["true_col4"] = raw[c4_col].astype("Int64")

#     truth["image_name"] = truth["image_name"].astype(str).str.strip()
#     return truth


# def sorted_image_names(names):
#     """Sort 1.jpg, 2.jpg, 10.jpg by numeric part."""
#     def key_fn(name: str):
#         stem = Path(name).stem
#         try:
#             return int(stem)
#         except ValueError:
#             return 10**9
#     return sorted(names, key=key_fn)


# def plot_confusion_matrix(cm: pd.DataFrame, title: str):
#     """Render a confusion matrix heatmap with matplotlib."""
#     fig, ax = plt.subplots()
#     im = ax.imshow(cm.values, cmap="Blues")

#     ax.set_title(title)
#     ax.set_xlabel("Predicted")
#     ax.set_ylabel("Ground truth")

#     ax.set_xticks(range(len(cm.columns)))
#     ax.set_yticks(range(len(cm.index)))
#     ax.set_xticklabels(cm.columns)
#     ax.set_yticklabels(cm.index)

#     # Rotate x tick labels for readability
#     plt.setp(ax.get_xticklabels(), rotation=45, ha="right", rotation_mode="anchor")

#     # Add cell annotations
#     for i in range(len(cm.index)):
#         for j in range(len(cm.columns)):
#             val = cm.values[i, j]
#             ax.text(j, i, str(val),
#                     ha="center", va="center",
#                     color="black", fontsize=9)

#     fig.colorbar(im, ax=ax, fraction=0.046, pad=0.04)
#     st.pyplot(fig)


# # -----------------------------
# # Streamlit UI
# # -----------------------------
# st.set_page_config(page_title="Dental X-ray Scoring Explorer", layout="wide")

# st.title("Dental Panoramic X-ray Scoring Explorer")

# scores = load_scores()
# truth = load_truth()  # may be None

# # Sidebar: dataset description
# st.sidebar.header("Dataset folders")
# st.sidebar.markdown(
#     f"""
# - `data/images/` – original panoramic images  
# - `results/overlays/` – images with scoring overlays  
# - `results/scores.csv` – per-image scores (C2, C3, C4)
# """
# )

# # Sidebar: case selector – **uses image_name**
# image_names = sorted_image_names(scores["image_name"].unique().tolist())
# default_index = 0

# selected_image = st.sidebar.selectbox(
#     "Select a case (image_name)",
#     options=image_names,
#     index=default_index,
# )

# st.sidebar.markdown(f"**Selected file:** `{selected_image}`")

# # Get the row for this image
# row = scores[scores["image_name"] == selected_image]
# if row.empty:
#     st.error(f"No row found in scores.csv for image `{selected_image}`.")
#     st.stop()
# row = row.iloc[0]

# # Paths
# img_path = DATA_DIR / selected_image
# overlay_path = OVERLAYS_DIR / f"{Path(selected_image).stem}_scored.png"

# # -----------------------------
# # Main layout – per-image view
# # -----------------------------
# col_img, col_scores = st.columns([2, 1])

# with col_img:
#     st.subheader("Image view")

#     # Original image
#     if img_path.exists():
#         st.caption(f"Original image: `{img_path}`")
#         st.image(Image.open(img_path), use_column_width=True)
#     else:
#         st.warning(f"Original image not found at `{img_path}`")

#     # Overlay image
#     if overlay_path.exists():
#         st.caption(f"Overlay (with clicks & scores): `{overlay_path.name}`")
#         st.image(Image.open(overlay_path), use_column_width=True)
#     else:
#         st.info("No overlay image found for this case yet.")

# with col_scores:
#     st.subheader("Per-image scores")

#     st.markdown("**Rubric (1–5)**")
#     st.markdown(
#         """
# - **C2**: left/right bone length asymmetry  
# - **C3**: distance of upper midline from image center  
# - **C4**: horizontal offset between upper and lower midlines
# """
#     )

#     c2 = int(row["col2"])
#     c3 = int(row["col3"])
#     c4 = int(row["col4"])

#     st.markdown("### Column 2 – Bone balance")
#     st.metric("C2 score", c2)

#     st.markdown("### Column 3 – Upper midline vs center")
#     st.metric("C3 score", c3)

#     st.markdown("### Column 4 – Upper vs lower midline")
#     st.metric("C4 score", c4)

# st.markdown("---")

# # -----------------------------
# # Analytics section
# # -----------------------------
# st.header("Analytics")

# # 1) Simple score distributions
# st.subheader("Score distributions (C2 / C3 / C4)")

# col_a, col_b, col_c = st.columns(3)
# for col, name in zip([col_a, col_b, col_c], ["col2", "col3", "col4"]):
#     with col:
#         st.markdown(f"**{name.upper()}**")
#         vc = scores[name].value_counts().sort_index()
#         # Turn into a dataframe for bar_chart
#         plot_df = vc.rename_axis("score").reset_index(name="count")
#         plot_df = plot_df.set_index("score")
#         st.bar_chart(plot_df)

# # 2) Confusion matrices if ground truth is available
# if truth is not None:
#     st.subheader("Model vs. ground-truth (confusion matrices)")

#     merged = scores.merge(truth, on="image_name", how="inner")

#     st.caption(f"Merged {len(merged)} images that have both model scores and ground truth.")

#     # Each (pred, truth) pair
#     configs = [
#         ("col2", "true_col2", "Column 2 – Bone balance"),
#         ("col3", "true_col3", "Column 3 – Upper midline vs center"),
#         ("col4", "true_col4", "Column 4 – Upper vs lower midline"),
#     ]

#     for pred_col, truth_col, title in configs:
#         # Drop NaNs for this pair
#         sub = merged[[pred_col, truth_col]].dropna()
#         if sub.empty:
#             st.info(f"No overlapping data for {title}.")
#             continue

#         cm = pd.crosstab(sub[truth_col].astype(int),
#                          sub[pred_col].astype(int),
#                          dropna=False)

#         total = cm.values.sum()
#         correct = np.diag(cm.reindex(index=cm.index, columns=cm.index, fill_value=0)).sum()
#         acc = correct / total if total > 0 else 0.0

#         st.markdown(f"### {title}")
#         st.write(f"Accuracy: **{acc:.2%}**")

#         plot_confusion_matrix(cm, title=f"{title} – Confusion matrix")

# else:
#     st.info(
#         "Ground-truth Excel file not found or not in the expected format.\n\n"
#         "Place `Copy of scoring 1-200.xlsx` in the project root to enable "
#         "confusion-matrix analytics."
#     )

# st.markdown("---")
# st.caption(
#     "This app reads `results/scores.csv` and uses the `image_name` column as "
#     "the case identifier (e.g. `1.jpg`, `10.jpg`). If a ground-truth Excel file "
#     "is available, confusion matrices are computed against columns 2–4."
# )
# streamlit_app.py

# streamlit_app.py
import streamlit as st
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import seaborn as sns
from pathlib import Path
from PIL import Image

# -----------------------------
# Paths (match your project)
# -----------------------------
PROJECT_ROOT = Path(__file__).resolve().parent
DATA_DIR = PROJECT_ROOT / "data" / "images"
OVERLAYS_DIR = PROJECT_ROOT / "results" / "overlays"
SCORES_CSV = PROJECT_ROOT / "results" / "scores.csv"

# Excel ground-truth file (for confusion matrices)
# Put your Excel here with the rubric labels.
TRUTH_XLSX = PROJECT_ROOT / "scoring 1-200.xlsx"

sns.set(style="whitegrid")


# -----------------------------
# Helpers – scores
# -----------------------------
@st.cache_data
def load_scores() -> pd.DataFrame:
    """Load model / tool scores from results/scores.csv."""
    df = pd.read_csv(SCORES_CSV)

    if "image_name" not in df.columns:
        st.error("scores.csv does not contain an 'image_name' column.")
        st.stop()

    # ensure string and strip spaces
    df["image_name"] = df["image_name"].astype(str).str.strip()
    return df


def sorted_image_names(names):
    """Sort 1.jpg, 2.jpg, 10.jpg by numeric part, then everything else."""
    def key_fn(name: str):
        stem = Path(name).stem
        try:
            return int(stem)
        except ValueError:
            return 10**9
    return sorted(names, key=key_fn)


# -----------------------------
# Helpers – truth + confusion
# -----------------------------
@st.cache_data
def load_truth_and_merge(scores_df: pd.DataFrame) -> pd.DataFrame | None:
    """
    Try to load the Excel truth file and merge with scores on image_name.

    Excel expected layout (flexible / robust):
      - column 0: case id, either 1, 2, ... or '1.jpg', '2.jpg', ...
      - column 1: truth label for C2 (can be int or text containing a number)
      - column 2: truth label for C3
      - column 3: truth label for C4

    Returns:
        merged DataFrame with columns:
            image_name, col2, col3, col4,
            true_c2, true_c3, true_c4
        or None if not available / parse error.
    """
    if not TRUTH_XLSX.exists():
        return None

    try:
        raw = pd.read_excel(TRUTH_XLSX)
    except Exception as e:
        st.warning(f"Could not read truth Excel file: {e}")
        return None

    if raw.shape[1] < 4:
        st.warning("Truth Excel has fewer than 4 columns; cannot parse ground truth.")
        return None

    id_col = raw.columns[0]
    c2_col = raw.columns[1]
    c3_col = raw.columns[2]
    c4_col = raw.columns[3]

    # --- image_name column: support both 1..N and '1.jpg' / '2.jpg' ---
    id_raw = raw[id_col].astype(str).str.strip()

    # If the id already looks like a filename, keep it; otherwise append ".jpg".
    is_filename = id_raw.str.lower().str.endswith((".jpg", ".jpeg", ".png"))
    image_name = np.where(is_filename, id_raw, id_raw + ".jpg")
    image_name = pd.Series(image_name).astype(str).str.strip()

    # --- label columns: pull first integer from each cell, robust to text ---
    def extract_int_series(col: pd.Series) -> pd.Series:
        # Convert to string, extract first group of digits, then to Int64.
        s = col.astype(str).str.extract(r"(\d+)", expand=False)
        return pd.to_numeric(s, errors="coerce").astype("Int64")

    try:
        truth = pd.DataFrame(
            {
                "image_name": image_name,
                "true_c2": extract_int_series(raw[c2_col]),
                "true_c3": extract_int_series(raw[c3_col]),
                "true_c4": extract_int_series(raw[c4_col]),
            }
        )
    except Exception as e:
        st.warning(f"Could not parse numeric labels from truth Excel: {e}")
        return None

    truth["image_name"] = truth["image_name"].astype(str).str.strip()

    merged = scores_df.merge(truth, on="image_name", how="inner")
    if merged.empty:
        st.warning("Merged scores + truth is empty (no overlapping image_name).")
        return None

    return merged


def plot_confusion_heatmap(df: pd.DataFrame, truth_col: str, pred_col: str, title: str):
    """Draw a confusion-matrix heatmap using counts 1..5."""
    labels = [1, 2, 3, 4, 5]
    cm = (
        pd.crosstab(
            df[truth_col],
            df[pred_col],
            rownames=["True"],
            colnames=["Pred"],
            dropna=False,
        )
        .reindex(index=labels, columns=labels, fill_value=0)
    )

    fig, ax = plt.subplots()
    sns.heatmap(cm, annot=True, fmt="d", cmap="Blues", ax=ax)
    ax.set_title(title)
    st.pyplot(fig)


# -----------------------------
# Streamlit UI
# -----------------------------
st.set_page_config(page_title="Dental X-ray Scoring Explorer", layout="wide")
st.title("Dental Panoramic X-ray Scoring Explorer")

scores = load_scores()

# Sidebar: dataset description
st.sidebar.header("Dataset folders")
st.sidebar.markdown(
    """
- `data/images/` – original panoramic images  
- `results/overlays/` – images with scoring overlays  
- `results/scores.csv` – per-image scores (C2, C3, C4)
"""
)

# Tabs: Case Viewer + Analytics
tab_case, tab_analytics = st.tabs(["🔍 Case Viewer", "📊 Analytics"])


# -----------------------------
# TAB 1 – Case viewer
# -----------------------------
with tab_case:
    st.subheader("Case Viewer")

    # Sidebar case selector
    image_names = sorted_image_names(scores["image_name"].unique().tolist())
    default_index = 0

    selected_image = st.sidebar.selectbox(
        "Select a case (image_name)",
        options=image_names,
        index=default_index,
    )

    st.sidebar.markdown(f"**Selected file:** `{selected_image}`")

    # Get the row for this image
    row = scores[scores["image_name"] == selected_image]
    if row.empty:
        st.error(f"No row found in scores.csv for image `{selected_image}`.")
        st.stop()
    row = row.iloc[0]

    # Paths
    img_path = DATA_DIR / selected_image
    overlay_path = OVERLAYS_DIR / f"{Path(selected_image).stem}_scored.png"

    col_img, col_scores = st.columns([2, 1])

    with col_img:
        st.markdown("### Image view")

        # Original image
        if img_path.exists():
            st.caption(f"Original image: `{img_path}`")
            st.image(Image.open(img_path), use_column_width=True)
        else:
            st.warning(f"Original image not found at `{img_path}`")

        # Overlay image
        if overlay_path.exists():
            st.caption(f"Overlay (with clicks & scores): `{overlay_path.name}`")
            st.image(Image.open(overlay_path), use_column_width=True)
        else:
            st.info("No overlay image found for this case yet.")

    with col_scores:
        st.markdown("### Per-image scores")

        st.markdown("**Rubric (1–5)**")
        st.markdown(
            """
- **C2** – left/right bone length asymmetry  
- **C3** – distance of upper midline from image center  
- **C4** – horizontal offset between upper and lower midlines
"""
        )

        c2 = int(row["col2"])
        c3 = int(row["col3"])
        c4 = int(row["col4"])

        st.markdown("#### Column 2 – Bone balance")
        st.metric("C2 score", c2)

        st.markdown("#### Column 3 – Upper midline vs center")
        st.metric("C3 score", c3)

        st.markdown("#### Column 4 – Upper vs lower midline")
        st.metric("C4 score", c4)

    st.markdown("---")
    st.caption(
        "This app reads `results/scores.csv` and always uses the `image_name` "
        "column as the case identifier, so each case corresponds to a filename "
        "like `1.jpg`, `10.jpg`, etc."
    )


# -----------------------------
# TAB 2 – Analytics
# -----------------------------
with tab_analytics:
    st.subheader("Dataset Analytics")

    # --- Basic stats ---
    st.markdown("### Basic statistics")

    col_a, col_b, col_c = st.columns(3)
    with col_a:
        st.metric("Number of scored images", len(scores))
    with col_b:
        st.metric("Unique image files", scores["image_name"].nunique())
    with col_c:
        st.metric("Scored columns", 3)

    # --- Distributions ---
    st.markdown("### Score distributions")

    col1, col2_, col3_ = st.columns(3)
    for col_name, label, col_container in [
        ("col2", "C2 – bone balance", col1),
        ("col3", "C3 – upper midline vs center", col2_),
        ("col4", "C4 – upper vs lower midline", col3_),
    ]:
        with col_container:
            fig, ax = plt.subplots()
            counts = scores[col_name].value_counts().sort_index()
            ax.bar(counts.index.astype(str), counts.values)
            ax.set_title(label)
            ax.set_xlabel("Score")
            ax.set_ylabel("Count")
            st.pyplot(fig)

    st.markdown("---")
    st.markdown("### Confusion-matrix heatmaps (model vs ground truth)")

    merged = load_truth_and_merge(scores)
    if merged is None:
        st.info(
            "No usable ground-truth Excel found yet, or it could not be parsed.\n\n"
            "To enable confusion-matrix analytics, place your Excel file "
            "`Copy of scoring 1-200.xlsx` in the project root with columns:\n"
            "- col0: image id (1..N) **or** '1.jpg', '2.jpg', ...\n"
            "- col1: truth label for C2 (1–5)\n"
            "- col2: truth label for C3 (1–3)\n"
            "- col3: truth label for C4 (1–5)\n"
        )
    else:
        st.success(
            f"Loaded ground truth and merged with scores "
            f"({len(merged)} images with both predictions and labels)."
        )

        st.markdown("#### Column 2 – Bone balance (C2)")
        plot_confusion_heatmap(
            merged,
            truth_col="true_c2",
            pred_col="col2",
            title="C2 confusion matrix (True vs Predicted)",
        )

        st.markdown("#### Column 3 – Upper midline vs center (C3)")
        plot_confusion_heatmap(
            merged,
            truth_col="true_c3",
            pred_col="col3",
            title="C3 confusion matrix (True vs Predicted)",
        )

        st.markdown("#### Column 4 – Upper vs lower midline (C4)")
        plot_confusion_heatmap(
            merged,
            truth_col="true_c4",
            pred_col="col4",
            title="C4 confusion matrix (True vs Predicted)",
        )

        st.markdown("#### Accuracy summary")

        def accuracy(truth_col, pred_col):
            return (merged[truth_col] == merged[pred_col]).mean()

        st.write(
            f"- **C2 accuracy**: {accuracy('true_c2', 'col2') * 100:.1f}%\n"
            f"- **C3 accuracy**: {accuracy('true_c3', 'col3') * 100:.1f}%\n"
            f"- **C4 accuracy**: {accuracy('true_c4', 'col4') * 100:.1f}%"
        )

    st.markdown("---")
    st.caption(
        "Analytics tab: designed so you can later plug in a small ML model or "
        "threshold-tuning pipeline and immediately see updated confusion "
        "matrices, similar to an internal AWS/Google quality dashboard."
    )
