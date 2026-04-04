####  Urbanroof Internship Assignment Work

---

#  AI DDR Report Generator

### (Detailed Diagnostic Report Generator)

🔗 **Live App:** https://ai-ddr-report-generator-genai-dheeraj-m-g.streamlit.app/

---

##  Overview

The **AI DDR Report Generator** is an end-to-end system that converts unstructured **Inspection Reports** and **Thermal Reports** into a **structured, client-ready Detailed Diagnostic Report (DDR)**.

This project focuses on **AI workflow design, reasoning, and system building**, rather than relying on paid APIs.

---

##  Problem Statement

In real-world scenarios:

* Inspection data is **unstructured**
* Thermal reports are **hard to interpret**
* Clients struggle to understand technical findings

 The goal is to **automate this process** and generate a clear, structured, and professional report.

---

##  Solution

This system:

1.  Accepts **Inspection + Thermal PDF reports**
2.  Extracts **text and images**
3.  Applies a **rule-based AI engine**
4.  Merges insights intelligently
5.  Generates a **structured DDR report**
6.  Outputs **DOCX, PDF, and JSON**

---

##  AI Approach 

Instead of using paid APIs, this project implements a **rule-based AI reasoning system** that simulates:

*  Information extraction
*  Multi-source data fusion
*  Conflict handling
*  Missing data handling
*  Severity classification
*  Logical inference


---

## Architecture (text diagram)

```
┌─────────────┐     ┌──────────────────┐     ┌─────────────────┐
│  Streamlit  │────▶│  pdf_processing  │───▶│ extracted_images│
│    app.py   │     │   (PyMuPDF)      │     │   + page text   │
└──────┬──────┘     └────────┬─────────┘     └────────┬────────┘
       │                     │                        │
       │                     ▼                        │
       │             ┌──────────────────┐             │
       │             │  analysis_engine │◀───────────┘
       │             │  (rules + merge) │
       │             └────────┬─────────┘
       │                      │
       │                      ▼
       │             ┌──────────────────┐     ┌─────────────┐
       └────────────▶│ report_generator │───▶│   outputs/  │
                     │ DOCX + PDF + JSON      │  (optional) │
                     └──────────────────┘     └─────────────┘
```

- **`utils.py`**: logging helpers, safe strings, directory creation.
- **`report_generator.py`**: document assembly and image placement under each observation when paths exist.
---

##  Project Structure

```
/project
│── app.py                  # Streamlit UI
│── pdf_processing.py       # PDF text + image extraction
│── analysis_engine.py      # Core AI logic (rule-based)
│── report_generator.py     # Report creation (DOCX + PDF)
│── utils.py                # Helper functions
│── requirements.txt        # Dependencies
│── README.md
│
├── extracted_images/       # Extracted images from PDFs
├── outputs/                # Generated reports
```

---

##  Features

 Upload 2 PDFs (Inspection + Thermal)
 Extract text and images automatically
 Detect issues (damp, crack, mold, leakage)
 Merge multi-source insights
 Assign severity levels
 Generate recommendations
 Handle missing/conflicting data
 Produce structured DDR report
 Download DOCX, PDF, JSON

---

##  Output Structure (DDR)

The system generates:

1. Property Issue Summary
2. Area-wise Observations
3. Probable Root Cause
4. Severity Assessment
5. Recommended Actions
6. Additional Notes
7. Missing / Unclear Information

---

##  Screenshots 
### -🔹 Upload Interface

<img width="1913" height="686" alt="image" src="https://github.com/user-attachments/assets/6d6f0fd6-22bd-4171-9c7b-2293662ea524" />


### -🔹 Processing Summary

<img width="1813" height="1024" alt="image" src="https://github.com/user-attachments/assets/5c177553-79c9-4728-a8b7-7433c1ffa41b" />


### -🔹 Final Report Output

<img width="1811" height="1011" alt="image" src="https://github.com/user-attachments/assets/b7d4fcb7-8917-4497-87c9-06dce387a46d" />


---

##  Example Use Cases

* Residential property inspection
* Construction quality analysis
* Maintenance diagnostics
* Real estate reporting

---

##  Limitations

* Rule-based logic (no deep NLP understanding level)
* Image-to-text mapping is basic
* Complex language variations may not be fully captured

---

##  Future Improvements

* Integrate LLMs (GPT / Gemini)
* Add NLP-based entity extraction
* Improve image-to-observation mapping
* Add RAG-based document understanding
* Enhance severity prediction with ML

---

##  What I Learned 

This project helped me understand:

### 🔹 AI / ML Concepts

* Information extraction
* Feature engineering (keywords → insights)
* Classification logic (severity detection)

### 🔹 Generative AI Concepts

* Prompt design (initial approach)
* Structured output thinking
* AI workflow design

### 🔹 Agentic AI Thinking

* Multi-step reasoning pipeline
* Decision-based processing
* Autonomous report generation

### 🔹 System Design

* End-to-end pipeline building
* Modular architecture
* Error handling and robustness

### 🔹 Real-world Engineering

* Handling incomplete data
* Conflict resolution
* Building production-ready systems

---

##  Tech Stack

* Python
* Streamlit
* PyMuPDF (fitz)
* python-docx
* ReportLab
* Pillow

---

##  Final Note

It demonstrates (my work):

✔ Problem solving
✔ System design
✔ AI reasoning
✔ Real-world applicability

---

### ⭐ If you found this useful, feel free to star the repo!
