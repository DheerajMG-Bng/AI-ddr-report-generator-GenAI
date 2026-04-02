# DDR Report Generator

**Detailed Diagnostic Report (DDR)** from two PDFs—**Inspection** and **Thermal**—using a **100% free, rule-based** pipeline (no OpenAI, Gemini, or paid APIs). The app is built for **Streamlit Cloud** and a clean recruiter-facing demo.

## Project overview

The system:

1. Extracts **text and embedded images** from both PDFs with **PyMuPDF (fitz)**.
2. Runs a **keyword- and pattern-based “AI” engine** (`analysis_engine.py`) to find issues, areas, severity, recommendations, and conflicts.
3. Produces structured **JSON** plus **DOCX** (python-docx) and **PDF** (ReportLab) reports.
4. Presents results in a **wide-layout Streamlit** UI with metrics, expanders, downloads, and optional keyword highlighting.

## Architecture (text diagram)

```
┌─────────────┐     ┌──────────────────┐     ┌─────────────────┐
│  Streamlit  │────▶│  pdf_processing  │────▶│ extracted_images│
│    app.py   │     │   (PyMuPDF)      │     │   + page text   │
└──────┬──────┘     └────────┬─────────┘     └────────┬────────┘
       │                     │                         │
       │                     ▼                         │
       │             ┌──────────────────┐             │
       │             │  analysis_engine │◀────────────┘
       │             │  (rules + merge) │
       │             └────────┬─────────┘
       │                      │
       │                      ▼
       │             ┌──────────────────┐     ┌─────────────┐
       └────────────▶│ report_generator │────▶│  outputs/   │
                     │ DOCX + PDF + JSON      │  (optional) │
                     └──────────────────┘     └─────────────┘
```

- **`utils.py`**: logging helpers, safe strings, directory creation.
- **`report_generator.py`**: document assembly and image placement under each observation when paths exist.

## How it works (step-by-step)

1. **Upload** inspection and thermal PDFs in the Streamlit UI.
2. **Extract** per-page text and images; images are written under `extracted_images/`.
3. **Preprocess** text (lowercase, normalize whitespace, sentence split).
4. **Detect** issue keywords (e.g. crack, leakage, moisture) and thermal phrases (e.g. hot spot, thermal anomaly).
5. **Detect** areas (living room, kitchen, bedroom, bathroom, roof, wall, ceiling) or mark **Not Available**.
6. **Build observations** with area, issue label, description, thermal text, and **combined_insight**.
7. **Deduplicate** rows with the same area + issue.
8. **Assign severity** using rules (e.g. crack + leakage → High; moisture/damp → Medium; minor discoloration → Low).
9. **Recommendations** are mapped from issue types (e.g. leakage → plumbing; crack → structural check; thermal → insulation).
10. **Conflicts**: e.g. inspection suggests “no issue” while thermal mentions high temperature / hot spots.
11. **Images** are mapped to observations by **page match** when possible, then leftover images are distributed.
12. **Export** DOCX, PDF, and JSON; preview markdown in the app.

## Setup

**Requirements:** Python 3.10+ recommended.

```bash
cd urbanroof-project
python -m venv .venv
# Windows
.venv\Scripts\activate
pip install -r requirements.txt
streamlit run app.py
```

Open the local URL Streamlit prints (usually `http://localhost:8501`).

## Deploy on Streamlit Community Cloud

1. Push this folder to a GitHub repository.
2. In [Streamlit Cloud](https://streamlit.io/cloud), **New app** → select the repo.
3. Set **Main file path** to `app.py`.
4. Deploy. The app uses only `requirements.txt` dependencies—no API keys.

**Note:** Ephemeral filesystem on Cloud may discard `extracted_images/` between sessions; downloads still work in-session.

## Demo flow

1. Prepare two PDFs with a **text layer** (scanned-only PDFs without OCR will yield little text).
2. Include sample phrases such as *“hairline crack in the bathroom ceiling”* and *“thermal anomaly near the roof”* for rule hits.
3. Upload both files → **Generate DDR** → review metrics, JSON expander, markdown preview.
4. Download **DOCX**, **PDF**, and **JSON**.

## Evaluation rubric (coursework / portfolio)

Many assessments use criteria like the following. This project is structured so you can point reviewers to **specific JSON fields** and UI sections:

| Criterion | What to verify | Where it appears |
| -------- | -------------- | ---------------- |
| **Accuracy of extracted information** | Wording and locations match the PDFs; cues are not invented. | `observations[]` → `description`, `area`, `issue`, `matched_keywords`, `confidence_percent` / `confidence_tier`, `image_path`; compare to source PDFs. |
| **Logical merging of inspection + thermal** | One narrative ties both reports together without contradicting either. | `combined_insight`, `thermal_observation`, `property_issue_summary`, `probable_root_cause`. |
| **Handling of missing/conflicting details** | Gaps and disagreements are explicit, not hidden. | `missing_or_unclear`, `conflicts`. |
| **Clarity of final DDR output** | A non-technical reader can follow priorities and next steps. | Streamlit preview, `severity_assessment`, `recommended_actions`, DOCX/PDF exports. |

The same mapping is available in the app (**Evaluation criteria** expander) and in the JSON object **`evaluation_rubric`**.

**Match strength (per observation):** Shown as **0–100%** plus **Strong / Moderate / Developing**. It reflects rule-based cue coverage (keywords, explicit location, thermal alignment), not a statistical confidence interval—use it to compare how well-supported each automated row is when discussing **accuracy**.

## Limitations

- **Not true semantic AI**: conclusions follow **keyword/pattern rules**, not deep language understanding.
- **Scanned PDFs** need OCR upstream; otherwise extraction is sparse.
- **Image-to-issue mapping** is heuristic (page alignment + fallback order), not vision AI.
- **Negation handling** is approximate (short window before a keyword).
- **Severity and root cause** are template-style inferences, not engineering sign-off.

## Future improvements

- Lightweight **on-device** OCR (e.g. Tesseract) for scanned reports.
- **Configurable** keyword lists and YAML rules for different property types.
- Richer **negation and entity** parsing without paid APIs.
- **PDF output** styling (headers, footers, table of contents).

## License

Use and modify for portfolio and learning. Verify suitability before any real-world inspections or legal use.
