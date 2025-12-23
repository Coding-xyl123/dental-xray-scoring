Official Artifact: Overlay PNG

Artifact type: image/png

Purpose: Explainable visualization of measurement points/lines used to compute scores

Storage rule: Must be written only via ObjectStore.put() (no direct file writes)

Key format (proposed): xray/overlays/case_id=<CASE_ID>/overlay.png

Versioning: Every run produces a new immutable version

1. Project Goal

Dentists and orthodontists evaluate panoramic X-rays using rubrics such as:

Bone balance (left/right symmetry)

Upper midline centering

Upper–lower midline alignment

But:

Clinical scoring is subjective

Measurements lack consistency

Most datasets have no physical calibration

ML training requires many labeled cases

This project builds a semi-automatic, reproducible scoring system that supports:

🎯 Research

Standardizes annotations for datasets.

🎯 ML Development

Exports clean labels for training a future auto-detection model.

🎯 Clinical QA

Provides consistent C2–C3–C4 scoring with visual overlays.
+---------------------------+
| data/images/_.jpg |
| (raw panoramic images) |
+-------------+-------------+
|
v
Manual click scoring (OpenCV) + heuristic midline guidance
|
Outputs: col2, col3, col4 + overlay.png
|
v
+-----------------------------------------------+
| results/scores.csv |
| results/overlays/_.png |
+----------------+------------------------------+
|
v
+------------------------------------------------+
| Streamlit Dashboard |
| - Case viewer |
| - Score distributions |
| - Confusion matrices (vs ground truth) |
| - Accuracy summary |
+------------------------------------------------+
|
v
(Optional) ML model training 3. Features
🔹 Manual Scoring with Intelligent Hints

Click in order:

Upper midline

Lower midline

Bone left (image left → patient right)

Bone right

Real-time suggested midlines & bone endpoints

Automatically generates:

overlay.png

scores.csv row

Training record (JSON or future TFRecord)
Streamlit Case Viewer

Displays:

Original panoramic image

Scored overlay image

C2/C3/C4 metrics

Useful for oral radiology research and datasets.

🔹 Analytics Dashboard

Includes:

Score histograms

Confusion matrices from Excel ground truth

Per-column accuracy

Dataset summary

🔹 Ground-Truth Excel Integration

Place:

scoring 1-200.xlsx

In the project root.
Streamlit will auto-parse:

Image ID

True C2

True C3

True C4

…and merge with scores.csv.

🔹 Ready for ML Training

Click outputs (x, y) + scores are structured for:

Landmark prediction models

Regression/Classification

Ensemble scoring models

🧮 4. Scoring Logic
C2 – Bone Balance

Compares patient-space distances:

Patient left = distance(upper_mid, bone_right)
Patient right = distance(upper_mid, bone_left)

Perfect symmetry → Score 3
Left longer → 1–2
Right longer → 4–5

C3 – Upper Midline vs Image Center

Evaluates deviation from image center (in cm).

Uses pixel-to-cm estimation via:

EXIF DPI (if trustworthy)

Otherwise: assumed pano sensor width (26 cm)

C4 – Upper vs Lower Midline Alignment

Measures horizontal offset:

Aligned → 3
Left offset → 4–5
Right offset → 1–2

📊 5. Analytics (Streamlit)

Features include:

Histograms of C2/C3/C4

Confusion matrices (prediction vs truth)

Accuracy summary

Auto-sorted case selector (1.jpg … 200.jpg)
☁️ 6. Cloud Architecture Sketch (AWS)
+----------------------+
| Browser |
| Streamlit Frontend |
+-----------+----------+
|
v
+-----------------------------+
| EC2 / Lightsail / Fargate |
| Host Streamlit Web App |
+-----------------------------+
|
v
+-------------------+
| AWS Lambda |
| - scoring backend |
| - auto-detection |
+-------------------+
|
v
+-------------------+
| S3 Bucket |
| - images |
| - overlays |
| - scores |
+-------------------+
|
v
+-----------------------------+
| Athena SQL + QuickSight BI |
+-----------------------------+
GCP Equivalent:

Cloud Run (Streamlit)

Cloud Functions

GCS

BigQuery → Looker Studio

🗂️ 7. Repository Structure
dental-xray-scoring/
│
├── click*and_score.py
├── streamlit_app.py
├── export_training_data.py
│
├── data/
│ └── images/*.jpg
│
├── results/
│ ├── overlays/\_.png
│ └── scores.csv
│
├── README.md
└── requirements.txt

⚙️ 8. Installation
pip install -r requirements.txt

Run the scoring tool:

python click_and_score.py

Run Streamlit:

streamlit run streamlit_app.py
