1. Project Motivation

Dentists and orthodontists often evaluate panoramic X-rays using rubrics such as:

C2 – Bone balance (left/right symmetry)

C3 – Upper midline centering

C4 – Upper–lower midline alignment

However, in practice:

Clinical scoring is subjective

Manual measurements are inconsistent

Most datasets lack physical calibration

ML training requires clean, explainable labels

This project builds a human-in-the-loop scoring pipeline that is:

Reproducible

Explainable

Versioned

Ready for analysis and ML

2. Project Goals
   Research

Standardize annotations across datasets

Quantify human annotation variability

ML Development

Export clean landmark + score labels

Prepare for future auto-detection models

Clinical QA

Provide consistent C2 / C3 / C4 scoring

Preserve visual evidence of every score

3. Official Artifact (Core Design Choice)
   Official Artifact: Overlay PNG

Type: image/png

Purpose: Explainable visualization of all measurement points and lines used to compute scores

Rule: Must be written only via ObjectStore.put\_\*()
(no direct file writes)

Immutability: Every run produces a new version

Storage key format:

xray/overlays/case_id=<CASE_ID>/run_id=<RUN_ID>/overlay.png

Associated metadata is written as:

xray/overlays/case_id=<CASE_ID>/run_id=<RUN_ID>/overlay.json

There is no “overwrite”.
The latest overlay is determined by querying, not mutation.

This mirrors real object storage systems (e.g. S3).

4. End-to-End Pipeline Overview
   Raw panoramic image (.jpg)
   ↓
   Human annotation (4 clicks)

- heuristic visual hints
  ↓
  scoring_core.py (pure function)
  ↓
  Scores + confidence
  ↓
  ObjectStore (immutable artifacts)

* overlay.png
* overlay.json
  ↓
  results/scores.csv (index table)
  ↓
  Analysis scripts
* noise sensitivity
* annotation audit
  ↓
  Streamlit dashboard

5. Manual Scoring with Intelligent Hints
   Click order (enforced):

Upper teeth midline

Lower teeth midline

Bone LEFT end (image left → patient right)

Bone RIGHT end (image right → patient left)

Visual hints (guidance only):

Blue vertical line – suggested upper midline (symmetry)

Purple vertical line – suggested lower midline

Red circle – suggested left bone endpoint

Green circle – suggested right bone endpoint

Hints are not used directly for scoring — only your clicks are.

Each run produces:

overlay.png (official artifact)

overlay.json (structured record)

One row in results/scores.csv

6. Scoring Logic (C2 / C3 / C4)
   C2 – Bone Balance

Compares patient-space distances:

Patient left = distance(upper_mid, bone_right)

Patient right = distance(upper_mid, bone_left)

Symmetry → score 3

Left longer → 1–2

Right longer → 4–5

C3 – Upper Midline Centering

Measures deviation from image center (cm)

Pixel-to-cm scale via:

Trusted EXIF DPI (if available)

Otherwise assumed pano width (26 cm)

C4 – Upper vs Lower Midline Alignment

Horizontal offset between upper and lower midlines

Aligned → 3

Offset left / right → 1–2 or 4–5

7. Annotation Confidence

Each annotation run is assigned a confidence level:

High – close to heuristic hints

Medium – small deviation

Low – large deviation (>5px)

This is critical because human variability often dominates algorithmic noise.

8. Annotation Quality Audit

We analyze all human annotations by measuring deviation from heuristic symmetry hints.

Key findings:

Annotation error is multi-modal, not Gaussian

Deviations up to ~100px observed

Lower midline annotations are less stable than upper midline

Human variability dominates algorithmic noise below ≈5px

This directly motivated:

Confidence scoring

Noise sensitivity evaluation

Conservative interpretation of C3 / C4

9. Noise Sensitivity Analysis

We evaluate how small perturbations (±1px, ±2px, ±5px) in landmarks affect scores.

This answers:

“How stable are the scores relative to annotation noise?”

Results show:

Scores are stable under very small noise

Instability grows rapidly beyond a few pixels

Reinforces the importance of annotation confidence

10. Streamlit Dashboard

The Streamlit app provides:

Case viewer (original image + overlay)

C2 / C3 / C4 distributions

Confusion matrices (vs ground truth)

Dataset-level summaries

11. Resume / Restart Support

When starting the tool:

The program detects existing progress in scores.csv

You can choose:

Resume (skip already-scored images)

Start over (CSV is backed up, then re-run)

Quit

This enables long annotation sessions without data loss.

12. Repository Structure
    dental-xray-scoring/
    │
    ├── src/
    │ ├── click_and_score.py
    │ ├── scoring_core.py
    │ ├── analyze_annotations.py
    │ ├── noise_sensitivity.py
    │ └── streamlit_app.py
    │
    ├── data/
    │ └── images/\*.jpg
    │
    ├── results/
    │ ├── scores.csv
    │ └── object_store/
    │ └── xray/overlays/...
    │
    ├── README.md
    └── requirements.txt

13. Installation
    pip install -r requirements.txt

14. Usage
    Manual scoring
    python src/click_and_score.py

Annotation audit
python src/analyze_annotations.py

Noise sensitivity
python src/noise_sensitivity.py

Streamlit dashboard
streamlit run src/streamlit_app.py

15. Future Work

Auto-detection of landmarks (ML)

Inter-annotator agreement analysis

Cloud deployment (S3 + Athena / BigQuery)

Active learning loop for annotation efficiency

16. Key Takeaway

This project is not just a tool, but a measurement system:

Human-centered

Explainable

Versioned

Analysis-driven

It bridges clinical reasoning, software engineering, and ML readiness.

Summary (1-minute)

This project demonstrates:

- Human-in-the-loop system design
- Immutable artifact storage (S3-style)
- Noise sensitivity analysis
- Annotation quality auditing
- Explainable outputs for clinical QA

## Cloud Mapping (AWS / GCP)

This system is designed to be cloud-ready:

- ObjectStore → S3 / GCS (versioned objects)
- click_and_score.py → Lambda / Cloud Function (stateless)
- scores.csv → Athena / BigQuery external table
- overlay PNGs → S3 object browser for QA
- annotation audit → scheduled batch job
- Streamlit → Cloud Run / EC2 / App Runner

No core logic changes are required to move to the cloud.

python -m src.click_and_score
