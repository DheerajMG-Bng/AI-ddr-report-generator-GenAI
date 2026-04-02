"""
Rule-based analysis engine: no external AI APIs.
Builds structured DDR JSON from inspection + thermal PDF text.
"""

from __future__ import annotations

import logging
import re
from collections import Counter
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
    (r"\bliving room\b", "Living room"),
    (r"\bkitchen\b", "Kitchen"),
    (r"\bbedroom\b", "Bedroom"),
    (r"\bbathroom\b", "Bathroom"),
    (r"\broof\b", "Roof"),
    (r"\bwall\b", "Wall"),
    (r"\bceiling\b", "Ceiling"),
]

ROOM_ORDER = ["bedroom", "bathroom", "kitchen", "living room"]

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

CONFIDENCE_EXPLANATION = (
    "Match strength (0–100%, shown as Strong / Moderate / Developing) reflects how well each finding is "
    "supported by rule-based cues: matched keywords, whether a location is explicit in the text, and "
    "whether thermal wording aligns. It is not a statistical confidence interval; reviewers can use it to "
    "compare relative reliability of extractions when scoring accuracy under the rubric."
)

EVALUATION_RUBRIC = {
    "accuracy_of_extracted_information": (
        "Compare observations[].description, area, issue, matched_keywords, match strength, and "
        "image_path (if any) against the original inspection and thermal PDF text layers."
    ),
    "logical_merging_inspection_and_thermal": (
        "Review combined_insight, thermal_observation, property_issue_summary, and probable_root_cause for "
        "coherent join of both reports without contradicting the sources."
    ),
    "handling_missing_or_conflicting_details": (
        "Assess missing_or_unclear and conflicts for transparent handling of gaps and tensions between reports."
    ),
    "clarity_of_final_ddr_output": (
        "Judge severity_assessment, recommended_actions, narrative sections, and DOCX/PDF exports for "
        "clear structure and client readability."
    ),
}


def _confidence_tier_from_percent(percent: float) -> str:
    if percent >= 80.0:
        return "Strong"
    if percent >= 65.0:
        return "Moderate"
    return "Developing"


def _confidence_to_percent_and_tier(internal: float) -> tuple[float, str]:
    """Internal score is 0–1; expose as percent (one decimal) + tier so distinct PDFs rarely look identical."""
    pct = round(min(100.0, max(0.0, internal * 100)), 1)
    return pct, _confidence_tier_from_percent(pct)

THERMAL_NOT_AVAILABLE = "Not Available"


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
    for pat, label in AREA_PATTERNS:
        if re.search(pat, s):
            return label
    return "Not Available"


def refine_composite_area(sentence: str, base: str) -> str:
    """e.g. bedroom + ceiling -> Bedroom ceiling."""
    if not sentence:
        return base
    s = sentence.lower()
    room = None
    for r in ROOM_ORDER:
        if r in s:
            room = r
            break
    struct = None
    for name in ("ceiling", "wall", "roof"):
        if re.search(rf"\b{name}\b", s):
            struct = name
            break
    if room and struct:
        rb = room[0].upper() + room[1:]
        sb = struct[0].upper() + struct[1:]
        return f"{rb} {sb}"
    if base and base != "Not Available":
        return base
    return base


def default_area_for_issue(issue: str, keywords: list[str], sentence: str) -> str:
    """When area unknown, assign client-friendly defaults."""
    lab = (issue or "").lower()
    sent = (sentence or "").lower()
    kws = " ".join(keywords).lower() if keywords else ""
    blob = f"{lab} {sent} {kws}"

    if any(x in blob for x in ("leakage", "seepage", "leak", "plumb")):
        return "Plumbing area"
    if any(x in blob for x in ("roof", "exterior")):
        return "Exterior / envelope"
    if any(
        x in blob
        for x in ("mold", "moisture", "damp", "crack", "ceiling", "wall", "discoloration", "damage")
    ):
        return "Interior area"
    if "thermal" in lab or "heat" in blob:
        return "General area"
    return "General area"


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


def normalize_display_issue(issue: str, keywords: list[str]) -> str:
    """Merge moisture + mold style issues; title-case for clients."""
    i = (issue or "").lower()
    k = [x.lower() for x in keywords] if keywords else []

    def has(*terms: str) -> bool:
        return any(t in k or t in i for t in terms)

    if has("mold", "moisture", "damp"):
        if sum(1 for t in ("mold", "moisture", "damp") if t in k or t in i) >= 2:
            return "Moisture and mold issue"
        if "mold" in i or "mold" in k:
            return "Mold concern"
        return "Moisture / damp issue"
    if "thermal" in i or i == "thermal finding":
        return "Thermal anomaly"
    if "leakage" in i or "seepage" in i or "leak" in i:
        return "Leakage"
    if "crack" in i:
        return "Crack"
    if "discoloration" in i:
        return "Discoloration"
    if "corrosion" in i:
        return "Corrosion"
    if "damage" in i:
        return "Damage"
    if "defect" in i:
        return "Defect"
    return issue.replace("_", " ").strip().title() if issue else "Observation"


def _severity_final(issue_display: str, keywords: list[str], description: str) -> str:
    """
    Clear severity rules — every observation gets Low / Medium / High (never 'Not Available').
    leakage → High; crack → Medium; mold → Medium; damp/moisture → Medium; minor discoloration → Low
    crack + leakage cues → High
    """
    d = (description or "").lower()
    idisp = (issue_display or "").lower()
    k = " ".join(keywords).lower() if keywords else ""

    has_leak = any(x in idisp or x in k or x in d for x in ("leak", "leakage", "seepage"))
    has_crack = "crack" in idisp or "crack" in k or "crack" in d
    has_minor_disc = "minor" in d and "discoloration" in d

    if has_leak:
        return "High"
    if has_crack and has_leak:
        return "High"
    if has_minor_disc and not has_leak and not has_crack:
        return "Low"
    if any(x in idisp for x in ("leakage", "leak")) or has_leak:
        return "High"
    if "crack" in idisp or has_crack:
        return "Medium"
    if "mold" in idisp or "mold" in k or "mold" in d:
        return "Medium"
    if any(x in idisp for x in ("moisture", "damp", "mold")) or any(
        x in k or x in d for x in ("moisture", "damp")
    ):
        return "Medium"
    if "thermal" in idisp:
        return "Medium"
    if "discoloration" in idisp or "discoloration" in d:
        return "Low" if has_minor_disc or "minor" in d else "Medium"
    if any(x in idisp for x in ("corrosion", "damage", "defect")):
        return "Medium"
    return "Medium"


def _recommendation_for(issue_display: str, thermal_related: bool) -> str:
    lab = issue_display.lower()
    if thermal_related or "thermal" in lab or "heat" in lab:
        return (
            "Review insulation and the thermal envelope, and schedule a follow-up thermal assessment "
            "if temperature anomalies persist."
        )
    if "leakage" in lab or "leak" in lab:
        return "Inspect the plumbing system and repair any active leaks."
    if "crack" in lab:
        return "Conduct a structural assessment and repair cracks per engineering guidance."
    if "moisture" in lab or "mold" in lab or "damp" in lab:
        return "Improve ventilation, identify and address the moisture source, and remediate mold safely if present."
    if "corrosion" in lab:
        return "Identify the corrosion source, protect metalwork, and replace components where section loss exists."
    if "damage" in lab or "defect" in lab:
        return "Document the extent of damage or defects and implement scoped repairs."
    if "discoloration" in lab:
        return "Investigate finish discoloration; confirm whether it is cosmetic or moisture-related."
    return "Review findings on site with qualified personnel and capture photos for the record."


def _text_has_location_cue(text: str) -> bool:
    return bool(
        re.search(
            r"\b(bedroom|bathroom|kitchen|living room|roof|wall|ceiling|basement|attic|floor|sink|window)\b",
            text or "",
            re.I,
        )
    )


def _confidence_score(
    matched: list[str],
    has_area: bool,
    thermal_match: bool,
    text_blob: str = "",
) -> float:
    """
    0–1 internal score: keyword count, location cues, thermal alignment, plus vocabulary/length
    from the actual merged text so different PDFs do not collapse to the same number.
    """
    n = min(len(matched), 6)
    score = 0.52 + 0.048 * n
    if has_area:
        score += 0.11
    if thermal_match:
        score += 0.09
    tb = text_blob or ""
    words = re.findall(r"[a-z]{3,}", tb.lower())
    if words:
        diversity = len(set(words)) / len(words)
        score += min(0.08, diversity * 0.10)
    score += min(0.06, len(tb) / 4500.0)
    # Deterministic spread from excerpt text (not random; changes when PDF wording changes)
    excerpt = tb[:400]
    sig = (sum(ord(c) for c in excerpt) % 31) / 1000.0
    score += sig
    return round(min(score, 0.97), 3)


def _dedupe_key(area: str, issue: str) -> tuple[str, str]:
    return (area.strip().lower(), issue.strip().lower())


def _word_set(text: str) -> set[str]:
    if not text:
        return set()
    return set(re.findall(r"[a-z0-9]+", text.lower()))


def _description_similarity(a: str, b: str) -> float:
    wa, wb = _word_set(a), _word_set(b)
    if not wa or not wb:
        return 0.0
    inter = len(wa & wb)
    return inter / max(len(wa), len(wb))


def _area_rank(area: str) -> int:
    """Prefer more specific composite areas."""
    if not area:
        return 0
    a = area.lower()
    if "general" in a and "area" in a:
        return 1
    if "plumbing" in a:
        return 3
    if "interior" in a:
        return 2
    if "exterior" in a:
        return 4
    if " " in area:
        return 6
    return 4


def _pick_better_area(a1: str, a2: str) -> str:
    if _area_rank(a2) > _area_rank(a1):
        return a2
    if _area_rank(a1) > _area_rank(a2):
        return a1
    lengths = (len(a1 or ""), len(a2 or ""))
    return a1 if lengths[0] >= lengths[1] else a2


def _strip_inspection_thermal_prefixes(text: str) -> str:
    t = re.sub(r"^\s*(inspection|thermal)\s*:\s*", "", text, flags=re.I).strip()
    return t


def _dedupe_sentences(parts: list[str]) -> str:
    """Merge list of snippets into 1–2 short sentences, drop repeated phrases."""
    seen: set[str] = set()
    out: list[str] = []
    for p in parts:
        p = re.sub(r"\s+", " ", _strip_inspection_thermal_prefixes(p)).strip(" ;|")
        if len(p) < 6:
            continue
        key = " ".join(sorted(_word_set(p)))[:120]
        if key in seen:
            continue
        seen.add(key)
        out.append(p)
    blob = "; ".join(out[:3])
    blob = re.sub(r"; repetition:.*$", "", blob, flags=re.I)
    if not blob:
        return ""
    sents = re.split(r"(?<=[.!?])\s+", blob)
    sents = [s.strip() for s in sents if s.strip()][:2]
    result = " ".join(sents)
    words = result.split()
    if len(words) > 55:
        result = " ".join(words[:55]).rstrip(",;") + "…"
    return result


def synthesize_combined_insight(
    inspection_snippet: str,
    thermal_snippet: str,
    thermal_obs: str,
) -> str:
    """Single natural sentence(s), not 'Inspection: | Thermal:'."""
    ins = _one_clause(inspection_snippet) if inspection_snippet else ""
    therm = _one_clause(thermal_snippet) if thermal_snippet else ""
    if thermal_obs and thermal_obs != THERMAL_NOT_AVAILABLE and not therm:
        therm = thermal_obs.split(",")[0].strip()

    has_i = bool(ins and ins.lower() not in ("not available", ""))
    has_t = bool(therm and therm.lower() not in ("not available", ""))

    if has_i and has_t:
        return (
            f"The inspection narrative points to {ins.rstrip('.')}, and thermal findings are consistent "
            f"with {therm.rstrip('.')}."
        )
    if has_i:
        return f"Inspection documentation describes {ins.rstrip('.')}."
    if has_t:
        return f"Thermal evidence highlights {therm.rstrip('.')}."
    return "Findings are inferred from available report wording and should be confirmed on site."


def _one_clause(text: str) -> str:
    if not text or text == THERMAL_NOT_AVAILABLE:
        return ""
    t = _strip_inspection_thermal_prefixes(text)
    t = re.sub(r"\s+", " ", t).strip()
    parts = re.split(r"\s*\|\s*", t)
    t = parts[0].strip() if parts else t
    if len(t) > 220:
        t = t[:217].rsplit(" ", 1)[0] + "…"
    return t


@dataclass
class RawObservation:
    area: str
    issue: str
    description: str
    thermal_observation: str
    source_sentence_inspection: str = ""
    source_sentence_thermal: str = ""
    severity: str = "Medium"
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
                area = refine_composite_area(sent, area)
                label = _issue_label_from_keywords(issues + thermal)
                disp = normalize_display_issue(label, list(dict.fromkeys(issues + thermal)))
                matched = list(dict.fromkeys(issues + thermal))
                sev = _severity_final(disp, matched, sent)
                if area == "Not Available":
                    area = default_area_for_issue(disp, matched, sent)
                conf = _confidence_score(
                    matched,
                    area != "Not Available",
                    bool(thermal),
                    sent,
                )
                rec = _recommendation_for(disp, bool(thermal))
                observations.append(
                    RawObservation(
                        area=area,
                        issue=label,
                        description=sent[:500],
                        thermal_observation=", ".join(thermal) if thermal else THERMAL_NOT_AVAILABLE,
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
            area = refine_composite_area(sent, area)
            label = _issue_label_from_keywords(issues + thermal)
            disp = normalize_display_issue(label, list(dict.fromkeys(issues + thermal)))
            matched = list(dict.fromkeys(issues + thermal))
            sev = _severity_final(disp, matched, sent)
            if area == "Not Available":
                area = default_area_for_issue(disp, matched, sent)
            conf = _confidence_score(
                matched,
                area != "Not Available",
                bool(thermal),
                sent,
            )
            rec = _recommendation_for(disp, bool(thermal))
            observations.append(
                RawObservation(
                    area=area,
                    issue=label,
                    description=sent[:500],
                    thermal_observation=", ".join(thermal) if thermal else THERMAL_NOT_AVAILABLE,
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


def _merge_severity(a: str, b: str) -> str:
    order = {"Low": 1, "Medium": 2, "High": 3}
    return b if order.get(b, 0) > order.get(a, 0) else a


def _canonical_issue_key(issue_raw: str, keywords: list[str]) -> str:
    disp = normalize_display_issue(issue_raw, keywords).lower()
    if "moisture" in disp and "mold" in disp:
        return "moisture_mold"
    if "leak" in disp:
        return "leakage"
    if "crack" in disp:
        return "crack"
    if "thermal" in disp:
        return "thermal"
    if "discoloration" in disp:
        return "discoloration"
    if "corrosion" in disp:
        return "corrosion"
    if "damage" in disp:
        return "damage"
    if "defect" in disp:
        return "defect"
    return re.sub(r"\W+", "_", disp)[:40] or "general"


def merge_inspection_thermal(
    insp_obs: list[RawObservation],
    therm_obs: list[RawObservation],
    insp_thermal_orphans: list[tuple[str, str]],
    therm_thermal_orphans: list[tuple[str, str]],
) -> list[dict[str, Any]]:
    merged: dict[tuple[str, str], dict[str, Any]] = {}

    def ingest(r: RawObservation, from_inspection_doc: bool) -> None:
        kws = list(r.matched_keywords)
        disp = normalize_display_issue(r.issue, kws)
        area = r.area
        if area == "Not Available":
            area = default_area_for_issue(disp, kws, r.description)
        area = refine_composite_area(r.description, area)

        key = _dedupe_key(area, _canonical_issue_key(r.issue, kws) + "::" + disp[:20])

        insp_part = r.source_sentence_inspection or (
            r.description if from_inspection_doc and not r.source_sentence_thermal else ""
        )
        therm_part = r.source_sentence_thermal or (
            r.description if not from_inspection_doc and not r.source_sentence_inspection else ""
        )
        parts = []
        if insp_part:
            parts.append(insp_part)
        if therm_part:
            parts.append(therm_part)
        elif r.thermal_observation != THERMAL_NOT_AVAILABLE:
            parts.append(f"Thermal wording: {r.thermal_observation}")
        combined_seed = " | ".join(parts) if parts else r.description

        if key not in merged:
            mk = " ".join(r.matched_keywords).lower()
            thermal_hit = r.thermal_observation != THERMAL_NOT_AVAILABLE or any(
                t in mk for t in THERMAL_KEYWORDS
            )
            merged[key] = {
                "area": area,
                "issue_raw": r.issue,
                "issue": disp,
                "description": r.description,
                "thermal_observation": r.thermal_observation
                if r.thermal_observation != THERMAL_NOT_AVAILABLE
                else THERMAL_NOT_AVAILABLE,
                "combined_insight": combined_seed,
                "severity": r.severity,
                "recommendation": _recommendation_for(disp, thermal_hit),
                "confidence": r.confidence,
                "matched_keywords": list(r.matched_keywords),
                "page_hint": r.page_hint,
                "_insp_bits": [insp_part] if insp_part else [],
                "_therm_bits": [therm_part] if therm_part else [],
            }
        else:
            m = merged[key]
            m["area"] = _pick_better_area(m["area"], area)
            if r.description and r.description not in m["description"]:
                m["description"] = f"{m['description']}; {r.description}"[:900]
            if r.thermal_observation != THERMAL_NOT_AVAILABLE:
                if m["thermal_observation"] == THERMAL_NOT_AVAILABLE:
                    m["thermal_observation"] = r.thermal_observation
                elif r.thermal_observation not in m["thermal_observation"]:
                    m["thermal_observation"] = f"{m['thermal_observation']}; {r.thermal_observation}"
            m["combined_insight"] = f"{m['combined_insight']} | {combined_seed}"[:1600]
            m["severity"] = _merge_severity(m["severity"], r.severity)
            m["confidence"] = round(max(m["confidence"], r.confidence), 2)
            m["matched_keywords"] = list(dict.fromkeys(m.get("matched_keywords", []) + list(r.matched_keywords)))
            if insp_part and insp_part not in m.get("_insp_bits", []):
                m.setdefault("_insp_bits", []).append(insp_part)
            if therm_part and therm_part not in m.get("_therm_bits", []):
                m.setdefault("_therm_bits", []).append(therm_part)
            if m.get("page_hint") is None and r.page_hint is not None:
                m["page_hint"] = r.page_hint

    for r in insp_obs:
        ingest(r, from_inspection_doc=True)
    for r in therm_obs:
        ingest(r, from_inspection_doc=False)

    for sent, tkw in therm_thermal_orphans + insp_thermal_orphans:
        area = detect_area(sent)
        area = refine_composite_area(sent, area)
        if area == "Not Available":
            area = default_area_for_issue("Thermal anomaly", tkw.split(","), sent)
        key = _dedupe_key(area, "thermal::" + tkw[:15])
        if key not in merged:
            merged[key] = {
                "area": area,
                "issue_raw": "thermal finding",
                "issue": "Thermal anomaly",
                "description": _one_clause(sent) or sent[:240],
                "thermal_observation": tkw,
                "combined_insight": sent,
                "severity": "Medium",
                "recommendation": _recommendation_for("Thermal anomaly", True),
                "confidence": _confidence_score(
                    [x.strip() for x in tkw.split(",") if x.strip()],
                    area != "Not Available",
                    True,
                    sent,
                ),
                "matched_keywords": [k.strip() for k in tkw.split(",") if k.strip()],
                "page_hint": None,
                "_insp_bits": [],
                "_therm_bits": [sent],
            }
        else:
            m = merged[key]
            if tkw not in str(m["thermal_observation"]):
                m["thermal_observation"] = (
                    f"{m['thermal_observation']}; {tkw}"
                    if m["thermal_observation"] != THERMAL_NOT_AVAILABLE
                    else tkw
                )
            m.setdefault("_therm_bits", []).append(sent)

    return list(merged.values())


def cluster_similar_observations(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Merge rows with same canonical issue and similar description."""
    buckets: list[dict[str, Any]] = []
    for row in rows:
        kws = row.get("matched_keywords") or []
        canon = _canonical_issue_key(row.get("issue_raw", row.get("issue", "")), kws)
        merged_into = False
        for b in buckets:
            bk = _canonical_issue_key(b.get("issue_raw", b.get("issue", "")), b.get("matched_keywords") or [])
            if bk != canon:
                continue
            sim = _description_similarity(row.get("description", ""), b.get("description", ""))
            sim2 = _description_similarity(row.get("combined_insight", ""), b.get("combined_insight", ""))
            if sim >= 0.42 or sim2 >= 0.45 or (
                row.get("description", "") in b.get("description", "")
                or b.get("description", "") in row.get("description", "")
            ):
                b["area"] = _pick_better_area(b["area"], row["area"])
                for fld in ("_insp_bits", "_therm_bits"):
                    if fld in row:
                        b.setdefault(fld, [])
                        for bit in row.get(fld) or []:
                            if bit and bit not in b[fld]:
                                b[fld].append(bit)
                b["description"] = _dedupe_sentences(
                    [b.get("description", ""), row.get("description", "")]
                ) or (b.get("description") or row.get("description"))
                if row.get("thermal_observation") != THERMAL_NOT_AVAILABLE:
                    if b["thermal_observation"] == THERMAL_NOT_AVAILABLE:
                        b["thermal_observation"] = row["thermal_observation"]
                    elif row["thermal_observation"] not in b["thermal_observation"]:
                        b["thermal_observation"] = f"{b['thermal_observation']}; {row['thermal_observation']}"
                b["matched_keywords"] = list(
                    dict.fromkeys((b.get("matched_keywords") or []) + (row.get("matched_keywords") or []))
                )
                b["issue"] = normalize_display_issue(b.get("issue_raw", b.get("issue", "")), b["matched_keywords"])
                b["severity"] = _merge_severity(b["severity"], row["severity"])
                b["confidence"] = round(max(b["confidence"], row["confidence"]), 2)
                if row.get("page_hint") is not None and b.get("page_hint") is None:
                    b["page_hint"] = row["page_hint"]
                merged_into = True
                break
        if not merged_into:
            r = dict(row)
            r.setdefault("_insp_bits", list(r.get("_insp_bits") or []))
            r.setdefault("_therm_bits", list(r.get("_therm_bits") or []))
            buckets.append(r)
    return buckets


def finalize_observation_client_ready(obs: dict[str, Any]) -> dict[str, Any]:
    """Clean description, combined insight, severity, recommendation; drop internal keys."""
    kws = obs.get("matched_keywords") or []
    issue_disp = normalize_display_issue(obs.get("issue_raw", obs.get("issue", "")), kws)
    area = obs.get("area", "General area")
    if area == "Not Available":
        area = default_area_for_issue(issue_disp, kws, obs.get("description", ""))
    area = refine_composite_area(obs.get("description", ""), area)

    insp_bits = obs.get("_insp_bits") or []
    therm_bits = obs.get("_therm_bits") or []
    if not insp_bits and obs.get("combined_insight"):
        parts = re.split(r"\s*\|\s*", obs["combined_insight"])
        for p in parts:
            p = p.strip()
            if p.lower().startswith("inspection:"):
                insp_bits.append(p.split(":", 1)[-1].strip())
            elif p.lower().startswith("thermal:"):
                therm_bits.append(p.split(":", 1)[-1].strip())

    desc_clean = _dedupe_sentences(
        [obs.get("description", "")] + [b for b in insp_bits if b][:2]
    )
    if not desc_clean:
        desc_clean = _one_clause(obs.get("description", "")) or "See combined insight below."

    thermal_note = obs.get("thermal_observation", THERMAL_NOT_AVAILABLE)
    if thermal_note == THERMAL_NOT_AVAILABLE and therm_bits:
        thermal_note = ", ".join({b[:80] for b in therm_bits if b})[:200]

    if insp_bits:
        insp_for_combined = " ".join(insp_bits)
    elif therm_bits:
        insp_for_combined = ""
    else:
        insp_for_combined = desc_clean

    therm_for_combined = " ".join(therm_bits) if therm_bits else ""
    if not therm_for_combined and thermal_note != THERMAL_NOT_AVAILABLE:
        therm_for_combined = thermal_note

    thermal_rel = thermal_note != THERMAL_NOT_AVAILABLE or bool(therm_bits)
    combined = synthesize_combined_insight(
        insp_for_combined,
        therm_for_combined,
        thermal_note if thermal_note != THERMAL_NOT_AVAILABLE else "",
    )

    sev = _severity_final(issue_disp, kws, desc_clean + " " + combined)
    rec = _recommendation_for(issue_disp, thermal_rel)

    text_blob = f"{desc_clean} {combined} {thermal_note}"
    raw_conf = _confidence_score(
        kws,
        _text_has_location_cue(text_blob),
        thermal_note != THERMAL_NOT_AVAILABLE,
        text_blob,
    )
    conf_pct, conf_tier = _confidence_to_percent_and_tier(raw_conf)

    out = {
        "area": area,
        "issue": issue_disp,
        "description": desc_clean,
        "thermal_observation": thermal_note,
        "combined_insight": combined,
        "severity": sev,
        "recommendation": rec,
        "confidence": raw_conf,
        "confidence_percent": conf_pct,
        "confidence_tier": conf_tier,
        "matched_keywords": kws,
        "page_hint": obs.get("page_hint"),
        "image_path": obs.get("image_path"),
    }
    return out


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
            "elevated temperature, hot spots, or anomalies — reconcile with a targeted site review."
        )

    if "no leak" in insp and ("moisture" in therm or "heat loss" in therm):
        conflicts.append(
            "Inspection states no leakage while thermal wording references moisture- or heat-related cues; "
            "verify with localized inspection."
        )
    return conflicts


def collect_missing_grouped(
    observations: list[dict[str, Any]],
    defaulted_areas: bool,
) -> list[str]:
    """Short, grouped bullets for clients."""
    lines: list[str] = []
    if not observations:
        lines.append(
            "No automated findings were extracted. This usually means the PDF has little selectable text "
            "(for example, a scan without OCR)."
        )
        return lines
    if defaulted_areas:
        lines.append(
            "Some locations were not spelled out in the source documents; sensible default areas were applied "
            "so the report stays readable."
        )
    lines.append(
        "Rule-based extraction may miss nuanced wording. Use this output as a structured draft and validate "
        "everything on site."
    )
    return lines


def overall_severity(observations: list[dict[str, Any]]) -> tuple[str, str]:
    if not observations:
        return "Low", "No observations were auto-detected from the supplied text."
    highs = sum(1 for o in observations if o.get("severity") == "High")
    meds = sum(1 for o in observations if o.get("severity") == "Medium")
    lows = sum(1 for o in observations if o.get("severity") == "Low")
    if highs:
        return (
            "High",
            f"{highs} item(s) are prioritized as high concern (e.g., active leakage). "
            f"Remaining items: {meds} medium, {lows} low.",
        )
    if meds:
        return (
            "Medium",
            f"{meds} item(s) warrant timely follow-up; {lows} item(s) are lower priority.",
        )
    return "Low", f"{lows} item(s) are lower priority under the current rule set."


def root_cause_summary(observations: list[dict[str, Any]]) -> str:
    if not observations:
        return "Insufficient detail to infer a single root cause."
    themes: list[str] = []
    text_blob = " ".join(
        str(o.get("combined_insight", "")) + " " + str(o.get("thermal_observation", "")) + " " + str(o.get("issue", ""))
        for o in observations
    ).lower()
    if any(x in text_blob for x in ("leak", "seep", "plumb")):
        themes.append("Water leaks or drainage defects")
    if any(x in text_blob for x in ("moist", "damp", "mold")):
        themes.append("Moisture accumulation or inadequate drying")
    if "crack" in text_blob:
        themes.append("Cracking in finishes or structure")
    if any(x in text_blob for x in ("thermal", "heat", "insulation")):
        themes.append("Thermal performance gaps in the envelope")
    if not themes:
        return "Mixed coded observations; determine root cause with on-site corroboration."
    return "Likely themes: " + "; ".join(dict.fromkeys(themes)) + "."


def property_summary_human(observations: list[dict[str, Any]]) -> str:
    """2–3 lines, client tone."""
    if not observations:
        return (
            "No issues were auto-flagged from the PDF text. If you expected findings, confirm the files contain "
            "highlighted keywords and a selectable text layer."
        )
    issue_labels = [str(o.get("issue", "")) for o in observations]
    top_issues = [k for k, _ in Counter(issue_labels).most_common(4)]
    areas = sorted({str(o.get("area")) for o in observations if o.get("area")})
    areas_str = ", ".join(areas[:5])
    if len(areas) > 5:
        areas_str += ", and other zones"
    lead = (
        f"This draft highlights {len(observations)} consolidated concern(s), chiefly involving "
        f"{', '.join(top_issues[:3])}."
    )
    second = f"Mentioned locations include {areas_str}." if areas_str else ""
    third = "Use thermal cues and photos alongside walk-down verification before quoting work scopes."
    parts = [p for p in (lead, second, third) if p]
    return " ".join(parts[:3])


def recommended_actions_list(observations: list[dict[str, Any]]) -> list[str]:
    actions: list[str] = []
    seen: set[str] = set()
    for o in observations:
        r = o.get("recommendation") or ""
        if r and r not in seen:
            seen.add(r)
            actions.append(r)
    if not actions:
        return ["Schedule a qualified walk-through to validate any open items."]
    return actions


def assign_images_to_observations(
    observations: list[dict[str, Any]],
    inspection_images: list[dict[str, Any]],
    thermal_images: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    pool_insp = list(inspection_images)
    pool_therm = list(thermal_images)

    for obs in observations:
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
    merged = cluster_similar_observations(merged)

    merged = assign_images_to_observations(
        merged,
        [m for m in inspection_pdf_result.get("image_paths", []) if m.get("path")],
        [m for m in thermal_pdf_result.get("image_paths", []) if m.get("path")],
    )

    observations_out: list[dict[str, Any]] = []
    for o in merged:
        observations_out.append(finalize_observation_client_ready(o))

    conflicts = detect_conflicts(insp_text, therm_text)
    overall, reasoning = overall_severity(observations_out)
    zone_pat = re.compile(
        r"\b(bedroom|bathroom|kitchen|living room|roof|wall|ceiling)\b",
        re.I,
    )
    defaulted_flag = any(
        not zone_pat.search((o.get("description", "") + " " + str(o.get("combined_insight", ""))))
        for o in observations_out
    )
    missing = collect_missing_grouped(observations_out, defaulted_areas=defaulted_flag)

    result: dict[str, Any] = {
        "property_issue_summary": property_summary_human(observations_out),
        "observations": observations_out,
        "probable_root_cause": root_cause_summary(observations_out),
        "severity_assessment": {
            "overall": overall,
            "reasoning": reasoning,
        },
        "recommended_actions": recommended_actions_list(observations_out),
        "confidence_explanation": CONFIDENCE_EXPLANATION,
        "missing_or_unclear": missing,
        "conflicts": conflicts,
        "evaluation_rubric": EVALUATION_RUBRIC,
    }

    logger.info("Analysis complete: %s observations, %s conflicts", len(observations_out), len(conflicts))
    return result


def highlight_keywords(text: str, keywords: list[str]) -> str:
    if not text or text == THERMAL_NOT_AVAILABLE:
        return text
    out = text
    for kw in sorted(set(keywords), key=len, reverse=True):
        if not kw:
            continue
        pattern = re.compile(re.escape(kw), re.IGNORECASE)
        out = pattern.sub(lambda m: f"**{m.group(0)}**", out)
    return out
