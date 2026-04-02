"""
Rule-based analysis engine: no external AI APIs.
Builds structured DDR JSON from inspection + thermal PDF text.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

ISSUE_KEYWORDS = [
    "crack",
    "leakage",
    "seepage",
    "damp",
    "moisture",
    "mold",
    "corrosion",
    "damage",
    "defect",
    "discoloration",
]

THERMAL_KEYWORDS = [
    "high temperature",
    "heat loss",
    "hot spot",
    "thermal anomaly",
]

AREA_PATTERNS = [
    r"\bliving room\b",
    r"\bkitchen\b",
    r"\bbedroom\b",
    r"\bbathroom\b",
    r"\broof\b",
    r"\bwall\b",
    r"\bceiling\b",
]

NEGATION_NEAR = re.compile(
    r"\b(no|without|absence of|free of|not\s+(any\s+)?|nil|none|negative for)\b",
    re.IGNORECASE,
)

NO_ISSUE_PHRASES = re.compile(
    r"\b(no issue|no significant issue|no defects observed|nothing abnormal|within normal)\b",
    re.IGNORECASE,
)

HIGH_TEMP_THERMAL = re.compile(
    r"\b(high temperature|hot spot|thermal anomaly|heat loss|elevated temp)\b",
    re.IGNORECASE,
)


def preprocess_text(text: str) -> tuple[str, list[str]]:
    """Lowercase, normalize spaces, split into sentences."""
    if not text or not text.strip():
        return "", []
    lowered = text.lower()
    lowered = re.sub(r"\s+", " ", lowered).strip()
    raw = re.split(r"(?<=[.!?])\s+", lowered)
    sentences = [s.strip() for s in raw if s.strip()]
    if not sentences and lowered:
        sentences = [lowered]
    return lowered, sentences


def _find_keywords_in_sentence(sentence: str, keywords: list[str]) -> list[str]:
    found: list[str] = []
    for kw in keywords:
        if kw in sentence:
            found.append(kw)
    return found


def detect_area(sentence: str) -> str:
    s = sentence.lower()
    for pat in AREA_PATTERNS:
        m = re.search(pat, s)
        if m:
            return m.group(0).strip()
    return "Not Available"


def _sentence_has_negated_issue(sentence: str, issue_kw: str) -> bool:
    idx = sentence.find(issue_kw)
    if idx < 0:
        return False
    window = sentence[max(0, idx - 45) : idx]
    return bool(NEGATION_NEAR.search(window))


def _issue_label_from_keywords(keywords: list[str]) -> str:
    if not keywords:
        return "general observation"
    for preferred in (
        "crack",
        "leakage",
        "seepage",
        "moisture",
        "damp",
        "mold",
        "thermal anomaly",
        "heat loss",
        "hot spot",
    ):
        if preferred in keywords:
            return preferred
    return keywords[0]


def _severity_for_observation(issue_keywords: list[str], sentence: str) -> str:
    s = sentence.lower()
    has_crack = "crack" in issue_keywords or "crack" in s
    has_leak = (
        any(k in issue_keywords for k in ("leakage", "seepage"))
        or "leakage" in s
        or "leak" in s
    )
    if has_crack and has_leak:
        return "High"
    if any(k in issue_keywords for k in ("moisture", "damp", "mold")) or any(
        x in s for x in ("moisture", "damp", "mold")
    ):
        return "Medium"
    if "discoloration" in s and "minor" in s:
        return "Low"
    if issue_keywords or any(k in s for k in ISSUE_KEYWORDS):
        return "Not Available"
    return "Not Available"


def _recommendation_for(issue_label: str, thermal_related: bool) -> str:
    lab = issue_label.lower()
    if thermal_related or "heat" in lab or "thermal" in lab:
        return (
            "Check insulation and thermal envelope; verify with a follow-up thermal scan if needed."
        )
    if "leakage" in lab or "seepage" in lab or "leak" in lab:
        return "Inspect plumbing and repair leaks."
    if "crack" in lab:
        return "Structural inspection recommended."
    if "mold" in lab or "moisture" in lab or "damp" in lab:
        return "Improve ventilation and moisture control; assess for mold remediation if needed."
    if "corrosion" in lab:
        return "Identify exposure source; treat or replace affected metal components."
    if "damage" in lab or "defect" in lab:
        return "Document damage extent and plan targeted repairs."
    return "Review on site with qualified personnel."


def _confidence_score(matched: list[str], has_area: bool, thermal_match: bool) -> float:
    base = 0.35 + 0.08 * min(len(matched), 4)
    if has_area:
        base += 0.15
    if thermal_match:
        base += 0.12
    return round(min(base, 0.95), 2)


def _dedupe_key(area: str, issue: str) -> tuple[str, str]:
    return (area.strip().lower(), issue.strip().lower())


@dataclass
class RawObservation:
    area: str
    issue: str
    description: str
    thermal_observation: str
    source_sentence_inspection: str = ""
    source_sentence_thermal: str = ""
    severity: str = "Not Available"
    recommendation: str = "Not Available"
    confidence: float = 0.0
    matched_keywords: list[str] = field(default_factory=list)
    page_hint: int | None = None


def _scan_pages(
    page_map: list[dict[str, Any]],
    source_type: str,
) -> tuple[list[RawObservation], list[tuple[str, str]]]:
    observations: list[RawObservation] = []
    thermal_only: list[tuple[str, str]] = []

    for pg in page_map:
        pnum = pg.get("page_num")
        ptext = pg.get("text") or ""
        ptext_lower = re.sub(r"\s+", " ", ptext.lower()).strip()
        if not ptext_lower:
            continue
        subs = [s.strip() for s in re.split(r"(?<=[.!?])\s+", ptext_lower) if s.strip()]
        for sent in subs:
            issues = _find_keywords_in_sentence(sent, ISSUE_KEYWORDS)
            thermal = _find_keywords_in_sentence(sent, THERMAL_KEYWORDS)
            issues = [k for k in issues if not _sentence_has_negated_issue(sent, k)]
            if issues:
                area = detect_area(sent)
                label = _issue_label_from_keywords(issues + thermal)
                sev = _severity_for_observation(issues, sent)
                matched = list(dict.fromkeys(issues + thermal))
                conf = _confidence_score(matched, area != "Not Available", bool(thermal))
                rec = _recommendation_for(label, bool(thermal))
                observations.append(
                    RawObservation(
                        area=area,
                        issue=label,
                        description=sent[:500],
                        thermal_observation=", ".join(thermal) if thermal else "Not Available",
                        source_sentence_inspection=sent if source_type == "inspection" else "",
                        source_sentence_thermal=sent if source_type == "thermal" else "",
                        severity=sev,
                        recommendation=rec,
                        confidence=conf,
                        matched_keywords=matched,
                        page_hint=pnum,
                    )
                )
            elif thermal:
                thermal_only.append((sent, ", ".join(thermal)))

    return observations, thermal_only


def build_observations_from_document(
    sentences: list[str],
    source_type: str,
    page_map: list[dict[str, Any]] | None = None,
) -> tuple[list[RawObservation], list[tuple[str, str]]]:
    if page_map:
        return _scan_pages(page_map, source_type)

    thermal_only: list[tuple[str, str]] = []
    observations: list[RawObservation] = []
    for sent in sentences:
        issues = _find_keywords_in_sentence(sent, ISSUE_KEYWORDS)
        thermal = _find_keywords_in_sentence(sent, THERMAL_KEYWORDS)
        issues = [k for k in issues if not _sentence_has_negated_issue(sent, k)]
        if issues:
            area = detect_area(sent)
            label = _issue_label_from_keywords(issues + thermal)
            sev = _severity_for_observation(issues, sent)
            matched = list(dict.fromkeys(issues + thermal))
            conf = _confidence_score(matched, area != "Not Available", bool(thermal))
            rec = _recommendation_for(label, bool(thermal))
            observations.append(
                RawObservation(
                    area=area,
                    issue=label,
                    description=sent[:500],
                    thermal_observation=", ".join(thermal) if thermal else "Not Available",
                    source_sentence_inspection=sent if source_type == "inspection" else "",
                    source_sentence_thermal=sent if source_type == "thermal" else "",
                    severity=sev,
                    recommendation=rec,
                    confidence=conf,
                    matched_keywords=matched,
                )
            )
        elif thermal:
            thermal_only.append((sent, ", ".join(thermal)))
    return observations, thermal_only


def _rank_severity(overall: str) -> int:
    order = {"Low": 1, "Not Available": 2, "Medium": 3, "High": 4}
    return order.get(overall, 2)


def _merge_severity(a: str, b: str) -> str:
    if _rank_severity(b) > _rank_severity(a):
        return b
    return a


def merge_inspection_thermal(
    insp_obs: list[RawObservation],
    therm_obs: list[RawObservation],
    insp_thermal_orphans: list[tuple[str, str]],
    therm_thermal_orphans: list[tuple[str, str]],
) -> list[dict[str, Any]]:
    merged: dict[tuple[str, str], dict[str, Any]] = {}

    def ingest(r: RawObservation, from_inspection_doc: bool) -> None:
        key = _dedupe_key(r.area, r.issue)
        insp_part = r.source_sentence_inspection or (
            r.description if from_inspection_doc and not r.source_sentence_thermal else ""
        )
        therm_part = r.source_sentence_thermal or (
            r.description if not from_inspection_doc and not r.source_sentence_inspection else ""
        )
        parts = []
        if insp_part:
            parts.append(f"Inspection: {insp_part}")
        if therm_part:
            parts.append(f"Thermal: {therm_part}")
        elif r.thermal_observation != "Not Available":
            parts.append(f"Thermal cues: {r.thermal_observation}")
        combined = " | ".join(parts) if parts else r.description

        if key not in merged:
            merged[key] = {
                "area": r.area,
                "issue": r.issue,
                "description": r.description,
                "thermal_observation": r.thermal_observation
                if r.thermal_observation != "Not Available"
                else "Not Available",
                "combined_insight": combined,
                "severity": r.severity,
                "recommendation": r.recommendation,
                "confidence": r.confidence,
                "matched_keywords": list(r.matched_keywords),
                "page_hint": r.page_hint,
            }
        else:
            m = merged[key]
            if r.description and r.description not in m["description"]:
                m["description"] = f"{m['description']}; {r.description}"[:800]
            if r.thermal_observation != "Not Available":
                if m["thermal_observation"] == "Not Available":
                    m["thermal_observation"] = r.thermal_observation
                elif r.thermal_observation not in m["thermal_observation"]:
                    m["thermal_observation"] = f"{m['thermal_observation']}; {r.thermal_observation}"
            m["combined_insight"] = f"{m['combined_insight']} | {combined}"[:1200]
            m["severity"] = _merge_severity(m["severity"], r.severity)
            m["confidence"] = round(max(m["confidence"], r.confidence), 2)
            m["matched_keywords"] = list(
                dict.fromkeys(m.get("matched_keywords", []) + list(r.matched_keywords))
            )
            if m.get("page_hint") is None and r.page_hint is not None:
                m["page_hint"] = r.page_hint

    for r in insp_obs:
        ingest(r, from_inspection_doc=True)
    for r in therm_obs:
        ingest(r, from_inspection_doc=False)

    # Attach orphan thermal sentences to nearest area match (same sentence area) or new row
    for sent, tkw in therm_thermal_orphans + insp_thermal_orphans:
        area = detect_area(sent)
        key = _dedupe_key(area, "thermal finding")
        line = f"Thermal: {sent}"
        if key not in merged:
            merged[key] = {
                "area": area,
                "issue": "thermal finding",
                "description": "Not Available",
                "thermal_observation": tkw,
                "combined_insight": line,
                "severity": "Not Available",
                "recommendation": _recommendation_for("thermal", True),
                "confidence": _confidence_score(tkw.split(", "), area != "Not Available", True),
                "matched_keywords": [k.strip() for k in tkw.split(",") if k.strip()],
                "page_hint": None,
            }
        else:
            m = merged[key]
            if tkw not in str(m["thermal_observation"]):
                m["thermal_observation"] = (
                    f"{m['thermal_observation']}; {tkw}"
                    if m["thermal_observation"] != "Not Available"
                    else tkw
                )
            m["combined_insight"] = f"{m['combined_insight']} | {line}"[:1200]

    return list(merged.values())


def detect_conflicts(full_inspection_text: str, full_thermal_text: str) -> list[str]:
    conflicts: list[str] = []
    insp = (full_inspection_text or "").lower()
    therm = (full_thermal_text or "").lower()
    if not insp or not therm:
        return conflicts

    insp_no_issue = bool(NO_ISSUE_PHRASES.search(insp))
    therm_hot = bool(HIGH_TEMP_THERMAL.search(therm))
    if insp_no_issue and therm_hot:
        conflicts.append(
            "Inspection narrative suggests minimal or no issues while thermal text mentions "
            "elevated temperature, hot spots, or thermal anomalies. Correlation recommended."
        )

    if "no leak" in insp and ("moisture" in therm or "heat loss" in therm):
        conflicts.append(
            "Inspection states no leakage; thermal wording references moisture- or heat-related cues. "
            "Verify with targeted inspection."
        )
    return conflicts


def collect_missing(observations: list[dict[str, Any]], conflicts: list[str]) -> list[str]:
    missing: list[str] = []
    for o in observations:
        if o.get("area") == "Not Available":
            missing.append(f"Issue '{o.get('issue')}' lacks explicit area in text.")
        if o.get("thermal_observation") == "Not Available" and "thermal" not in str(o.get("issue", "")).lower():
            pass  # optional note — keep list short
    if not observations:
        missing.append("No rule-based issues detected; PDFs may lack keyword matches or text layer.")
    if not conflicts and not observations:
        missing.append("Conflict scan skipped or inconclusive (insufficient text).")
    return missing


def overall_severity(observations: list[dict[str, Any]]) -> tuple[str, str]:
    if not observations:
        return "Not Available", "No observations matched keyword rules."
    highs = sum(1 for o in observations if o.get("severity") == "High")
    meds = sum(1 for o in observations if o.get("severity") == "Medium")
    lows = sum(1 for o in observations if o.get("severity") == "Low")
    if highs:
        return (
            "High",
            f"{highs} observation(s) flagged as High (e.g. crack + leakage patterns). "
            f"Additionally {meds} medium and {lows} low priority items.",
        )
    if meds:
        return (
            "Medium",
            f"{meds} observation(s) involve moisture or damp-related wording; "
            f"{lows} low priority.",
        )
    if lows:
        return "Low", f"{lows} observation(s) suggest minor findings per rules."
    return (
        "Not Available / Mixed",
        "Severity not escalated by rules; review narrative and imagery manually.",
    )


def root_cause_summary(observations: list[dict[str, Any]]) -> str:
    if not observations:
        return "Not Available"
    themes: list[str] = []
    text_blob = " ".join(
        o.get("combined_insight", "") + " " + str(o.get("thermal_observation", ""))
        for o in observations
    ).lower()
    if any(x in text_blob for x in ("leak", "seep", "moist", "damp")):
        themes.append("Water ingress or sustained moisture")
    if "crack" in text_blob:
        themes.append("Possible structural or finish movement")
    if any(x in text_blob for x in ("thermal", "heat", "insulation")):
        themes.append("Thermal performance or envelope defects")
    if not themes:
        return "Multiple coded issues; root cause requires site verification."
    return "; ".join(themes)


def property_summary(observations: list[dict[str, Any]]) -> str:
    if not observations:
        return "Not Available"
    n = len(observations)
    areas = sorted({o.get("area", "Not Available") for o in observations})
    areas_str = ", ".join(a for a in areas if a != "Not Available") or "Not Available"
    return (
        f"Rule-based scan found {n} distinct issue group(s). "
        f"Areas mentioned include: {areas_str}. "
        "Confirm all findings on site."
    )


def recommended_actions_list(observations: list[dict[str, Any]]) -> list[str]:
    actions: list[str] = []
    seen: set[str] = set()
    for o in observations:
        r = o.get("recommendation") or "Not Available"
        if r != "Not Available" and r not in seen:
            seen.add(r)
            actions.append(r)
    if not actions:
        return ["Not Available"]
    return actions


def assign_images_to_observations(
    observations: list[dict[str, Any]],
    inspection_images: list[dict[str, Any]],
    thermal_images: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Map images by page_hint first, then round-robin."""
    out: list[dict[str, Any]] = []
    pool_insp = list(inspection_images)
    pool_therm = list(thermal_images)

    for i, obs in enumerate(observations):
        o = dict(obs)
        page = obs.get("page_hint")
        chosen: str | None = None
        if page is not None:
            for plist in (pool_insp, pool_therm):
                for idx, meta in enumerate(plist):
                    if meta.get("page") == page:
                        chosen = meta.get("path")
                        plist.pop(idx)
                        break
                if chosen:
                    break
        if not chosen:
            pool = pool_insp if pool_insp else pool_therm
            if pool:
                chosen = pool.pop(0).get("path")
        o["image_path"] = chosen if chosen else None
        out.append(o)
    return out


def analyze_reports(
    inspection_pdf_result: dict[str, Any],
    thermal_pdf_result: dict[str, Any],
) -> dict[str, Any]:
    """
    Main entry: accept outputs from process_pdf for both documents.
    """
    insp_text = inspection_pdf_result.get("full_text") or ""
    therm_text = thermal_pdf_result.get("full_text") or ""
    _, insp_sents = preprocess_text(insp_text)
    _, therm_sents = preprocess_text(therm_text)

    insp_pages = inspection_pdf_result.get("pages") or []
    therm_pages = thermal_pdf_result.get("pages") or []

    insp_obs, insp_thermal_orphan = build_observations_from_document(
        insp_sents, "inspection", insp_pages if insp_pages else None
    )
    therm_obs, therm_thermal_orphan = build_observations_from_document(
        therm_sents, "thermal", therm_pages if therm_pages else None
    )

    merged = merge_inspection_thermal(
        insp_obs,
        therm_obs,
        insp_thermal_orphan,
        therm_thermal_orphan,
    )
    conflicts = detect_conflicts(insp_text, therm_text)

    merged_with_images = assign_images_to_observations(
        merged,
        [m for m in inspection_pdf_result.get("image_paths", []) if m.get("path")],
        [m for m in thermal_pdf_result.get("image_paths", []) if m.get("path")],
    )

    observations_out: list[dict[str, Any]] = []
    for o in merged_with_images:
        observations_out.append(
            {
                "area": o.get("area", "Not Available"),
                "issue": o.get("issue", "Not Available"),
                "description": o.get("description", "Not Available"),
                "thermal_observation": o.get("thermal_observation", "Not Available"),
                "combined_insight": o.get("combined_insight", "Not Available"),
                "severity": o.get("severity", "Not Available"),
                "recommendation": o.get("recommendation", "Not Available"),
                "confidence": o.get("confidence", 0.0),
                "matched_keywords": o.get("matched_keywords", []),
                "image_path": o.get("image_path"),
            }
        )

    overall, reasoning = overall_severity(observations_out)
    missing = collect_missing(observations_out, conflicts)

    result: dict[str, Any] = {
        "property_issue_summary": property_summary(observations_out),
        "observations": observations_out,
        "probable_root_cause": root_cause_summary(observations_out),
        "severity_assessment": {
            "overall": overall,
            "reasoning": reasoning,
        },
        "recommended_actions": recommended_actions_list(observations_out),
        "additional_notes": (
            "Generated by rule-based keyword and pattern logic; not a substitute for a licensed inspection."
        ),
        "missing_or_unclear": missing,
        "conflicts": conflicts,
    }

    logger.info("Analysis complete: %s observations, %s conflicts", len(observations_out), len(conflicts))
    return result


def highlight_keywords(text: str, keywords: list[str]) -> str:
    """Wrap matched keywords in markdown bold for Streamlit (bonus)."""
    if not text or text == "Not Available":
        return text
    out = text
    for kw in sorted(set(keywords), key=len, reverse=True):
        if not kw:
            continue
        pattern = re.compile(re.escape(kw), re.IGNORECASE)
        out = pattern.sub(lambda m: f"**{m.group(0)}**", out)
    return out
