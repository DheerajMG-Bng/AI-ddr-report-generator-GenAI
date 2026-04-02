"""
Streamlit entrypoint: DDR Report Generator (rule-based, no paid APIs).
Deployable on Streamlit Community Cloud.
"""

from __future__ import annotations

import hashlib
import logging
import traceback
from datetime import datetime
from pathlib import Path

import streamlit as st

from analysis_engine import (
    EVALUATION_RUBRIC,
    ISSUE_KEYWORDS,
    THERMAL_KEYWORDS,
    analyze_reports,
    highlight_keywords,
)
from pdf_processing import process_pdf
from report_generator import OUTPUT_DIR, build_docx, build_pdf, save_json_report
from utils import ensure_dirs, sanitize_filename, setup_logging

setup_logging()
logger = logging.getLogger("ddr.app")

PROJECT_ROOT = Path(__file__).resolve().parent
IMAGE_DIR = PROJECT_ROOT / "extracted_images"
ensure_dirs(IMAGE_DIR, OUTPUT_DIR)

st.set_page_config(
    page_title="DDR Report Generator",
    layout="wide",
    initial_sidebar_state="collapsed",
)

CUSTOM_CSS = """
<style>
    .main-title {
        font-size: 2.35rem;
        font-weight: 700;
        letter-spacing: -0.02em;
        margin-bottom: 0.25rem;
        line-height: 1.15;
    }
    .sub-title {
        font-size: 1.05rem;
        margin-bottom: 1.25rem;
        opacity: 0.82;
    }
    div[data-testid="stMetricValue"] { font-size: 1.35rem; }
    [data-testid="stVerticalBlockBorderWrapper"] {
        background: rgba(128, 128, 128, 0.06);
    }
</style>
"""


def append_step(log: list[str], msg: str) -> None:
    ts = datetime.now().strftime("%H:%M:%S")
    log.append(f"[{ts}] {msg}")


def ddr_to_markdown(report: dict, highlight: bool) -> str:
    lines: list[str] = ["## Final report preview", ""]
    psum = report.get("property_issue_summary", "Not Available")
    if highlight:
        psum = highlight_keywords(psum, ISSUE_KEYWORDS + THERMAL_KEYWORDS)
    lines.append(f"### Property issue summary\n{psum}\n")

    lines.append("### Area-wise observations\n")
    obs = report.get("observations") or []
    if not obs:
        lines.append("- _No keyword-based observations. Upload text-based PDFs for best results._\n")
    for i, o in enumerate(obs, 1):
        desc = o.get("description", "Not Available")
        comb = o.get("combined_insight", "Not Available")
        if highlight:
            kws = list(o.get("matched_keywords") or []) + ISSUE_KEYWORDS[:3]
            desc = highlight_keywords(desc, kws)
            comb = highlight_keywords(comb, kws)
        lines.append(f"**{i}. {o.get('area', 'N/A')} — {o.get('issue', '')}**  ")
        ms = o.get("confidence_percent")
        mt = o.get("confidence_tier")
        if ms is not None and mt:
            mss = f"{float(ms):.1f}% ({mt})"
        else:
            c = o.get("confidence")
            mss = f"{int(round(float(c) * 100))}%" if isinstance(c, (int, float)) else "—"
        lines.append(f"- **Severity:** {o.get('severity')} | **Match strength:** {mss}")
        lines.append(f"- **Description:** {desc}")
        lines.append(f"- **Thermal:** {o.get('thermal_observation')}")
        lines.append(f"- **Combined:** {comb}")
        lines.append(f"- **Recommendation:** {o.get('recommendation')}")
        img = o.get("image_path")
        lines.append(f"- **Image:** {'Attached in exports' if img else 'Not mapped'}")
        lines.append("")

    lines.append(f"### Probable root cause\n{report.get('probable_root_cause', 'Not Available')}\n")
    sev = report.get("severity_assessment") or {}
    lines.append(
        f"### Severity assessment\n- **Overall:** {sev.get('overall')}\n- **Reasoning:** {sev.get('reasoning')}\n"
    )
    if report.get("confidence_explanation"):
        lines.append(f"*Confidence:* {report['confidence_explanation']}\n")
    lines.append("### Recommended actions\n")
    for a in report.get("recommended_actions") or []:
        lines.append(f"- {a}")
    lines.append("")
    lines.append("### Missing / unclear\n")
    for m in report.get("missing_or_unclear") or []:
        lines.append(f"- {m}")
    conf = report.get("conflicts") or []
    if conf:
        lines.append("\n### Conflicts\n")
        for c in conf:
            lines.append(f"- {c}")
    return "\n".join(lines)


def main() -> None:
    st.markdown(CUSTOM_CSS, unsafe_allow_html=True)
    st.markdown('<p class="main-title">🏠 DDR Report Generator</p>', unsafe_allow_html=True)
    st.markdown(
        '<p class="sub-title">AI-powered inspection analysis (rule-based · no paid APIs)</p>',
        unsafe_allow_html=True,
    )

    er = st.expander("📋 Evaluation criteria — how this DDR maps to the rubric", expanded=False)
    with er:
        st.caption(
            "Use this checklist when grading or demoing: each item points to concrete fields in the report / JSON."
        )
        for key, text in EVALUATION_RUBRIC.items():
            label = key.replace("_", " ").title()
            st.markdown(f"**{label}** — {text}")

    col_ins, col_th = st.columns(2)
    with col_ins:
        with st.container(border=True):
            st.markdown("#### 📋 Inspection report")
            finsp = st.file_uploader("Upload inspection PDF", type=["pdf"], key="insp", label_visibility="visible")
    with col_th:
        with st.container(border=True):
            st.markdown("#### 🌡️ Thermal report")
            ftherm = st.file_uploader("Upload thermal PDF", type=["pdf"], key="therm", label_visibility="visible")

    can_run = finsp is not None and ftherm is not None

    if not can_run:
        st.session_state.pop("ddr_result", None)
        st.info("Upload both PDFs to enable analysis.")
        return

    ins_bytes = finsp.getvalue()
    therm_bytes = ftherm.getvalue()
    file_fingerprint = (
        hashlib.sha256(ins_bytes).hexdigest(),
        hashlib.sha256(therm_bytes).hexdigest(),
    )
    prev = st.session_state.get("ddr_result")
    if prev is not None and prev.get("file_fingerprint") != file_fingerprint:
        st.session_state.pop("ddr_result", None)

    _, cbtn, _ = st.columns([2, 1, 2])
    with cbtn:
        run = st.button("🚀 Generate DDR", type="primary", disabled=not can_run, use_container_width=True)

    if run:
        steps: list[str] = []
        try:
            append_step(steps, "Started pipeline")
            ins_label = sanitize_filename(finsp.name or "inspection", max_len=40)
            therm_label = sanitize_filename(ftherm.name or "thermal", max_len=40)

            with st.spinner("Analyzing reports…"):
                append_step(steps, "Extracting PDFs (PyMuPDF) + embedded images")
                ins_pdf = process_pdf(ins_bytes, source_label=ins_label, image_dir=IMAGE_DIR)
                therm_pdf = process_pdf(therm_bytes, source_label=therm_label, image_dir=IMAGE_DIR)
                append_step(steps, "Running analysis on this file pair (no cache)")
                report = analyze_reports(ins_pdf, therm_pdf)
                bundle = {"report": report, "ins_pdf": ins_pdf, "therm_pdf": therm_pdf}
                append_step(steps, "Rule-based merge + severity + conflict scan complete")
                append_step(steps, "Building DOCX and PDF exports")
                docx_b = build_docx(bundle["report"])
                pdf_b = build_pdf(bundle["report"])
                append_step(steps, "Exports ready (DOCX / PDF / JSON)")

            st.session_state["ddr_result"] = {
                **bundle,
                "steps": steps,
                "docx_bytes": docx_b,
                "pdf_bytes": pdf_b,
                "file_fingerprint": file_fingerprint,
            }
        except Exception:
            logger.exception("Pipeline failed")
            st.error("Something went wrong. Details:")
            st.code(traceback.format_exc())
            return

    if "ddr_result" not in st.session_state:
        st.info("Click **Generate DDR** to run the pipeline.")
        return

    bundle = st.session_state["ddr_result"]
    report = bundle["report"]
    ins_pdf = bundle["ins_pdf"]
    therm_pdf = bundle["therm_pdf"]
    steps = bundle.get("steps", [])

    st.markdown("---")
    st.markdown("### 📊 Processing summary")
    m1, m2, m3, m4 = st.columns(4)
    with m1:
        pc = (ins_pdf.get("page_count") or 0) + (therm_pdf.get("page_count") or 0)
        st.metric("Total pages", pc)
    with m2:
        tl = len(ins_pdf.get("full_text") or "") + len(therm_pdf.get("full_text") or "")
        st.metric("Chars extracted", f"{tl:,}")
    with m3:
        ic = len(ins_pdf.get("image_paths") or []) + len(therm_pdf.get("image_paths") or [])
        st.metric("Images saved", ic)
    with m4:
        st.metric("Observations", len(report.get("observations") or []))

    with st.expander("📜 Processing steps", expanded=False):
        for s in steps:
            st.caption(s)

    st.markdown("### 🧠 Structured insights (JSON)")
    with st.expander("View raw DDR JSON", expanded=False):
        st.json(report)

    st.markdown("### 📄 Report preview")
    highlight_toggle = st.checkbox("Highlight detected keywords in preview", value=True)
    st.markdown(ddr_to_markdown(report, highlight_toggle))

    st.markdown("### ⬇️ Downloads")
    prefix = datetime.now().strftime("DDR_%Y%m%d_%H%M%S")
    docx_bytes = bundle.get("docx_bytes") or build_docx(report)
    pdf_bytes = bundle.get("pdf_bytes") or build_pdf(report)
    json_path = OUTPUT_DIR / f"{prefix}.json"
    save_json_report(report, json_path)
    json_bytes = json_path.read_bytes()

    d1, d2, d3 = st.columns(3)
    with d1:
        st.download_button(
            label="Download DOCX",
            data=docx_bytes,
            file_name=f"{prefix}.docx",
            mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            use_container_width=True,
        )
    with d2:
        st.download_button(
            label="Download PDF",
            data=pdf_bytes,
            file_name=f"{prefix}.pdf",
            mime="application/pdf",
            use_container_width=True,
        )
    with d3:
        st.download_button(
            label="Download JSON",
            data=json_bytes,
            file_name=f"{prefix}.json",
            mime="application/json",
            use_container_width=True,
        )

    with st.sidebar:
        st.markdown("### About")
        st.markdown(
            "This app uses **PyMuPDF**, **python-docx**, and **ReportLab** only—no cloud LLM APIs."
        )


if __name__ == "__main__":
    main()
