"""DOB form/report code detection — shared by ingest (tagging) and retrieval (topic shelf).

Short alphanumeric codes ("TR2", "PW1", "PAA") don't embed distinctively, so semantic search
misses the right doc. We tag docs with the codes they contain and pull them by tag at query
time. Word boundaries keep PA (Place of Assembly) and PAA (Post Approval Amendment) — where
PA ⊂ PAA — strictly separate.
"""
import re

FORM_CODES = ["PAA", "TR1", "TR2", "TR3", "TR8", "PW1", "PW2", "PW3", "ALT1", "ALT2", "ALT3",
              "TPP", "TPA", "BPP", "AHV", "LNO", "TCO", "PACO", "EUP", "LAA", "FISP",
              "PA", "NB", "DM", "COC", "OT"]


def code_pattern(code: str) -> str:
    """Regex body for a code allowing a separator between letters and digits (TR2 / TR-2 / TR 2)."""
    m = re.match(r"^([A-Za-z]+)(\d+)$", code)
    if m:
        return re.escape(m.group(1)) + r"[-\s]?" + re.escape(m.group(2))
    return re.escape(code)


# Longest codes first so 'PAA' is preferred over 'PA' in alternation.
_FORM_CODE_RE = re.compile(
    r"\b(" + "|".join(code_pattern(c) for c in sorted(FORM_CODES, key=len, reverse=True)) + r")s?\b",
    re.I,
)


def extract_form_codes(text: str) -> set:
    """Normalized DOB form codes present in the text (TR-2/tr2s -> 'TR2')."""
    return {re.sub(r"[-\s]", "", m.group(1).upper()) for m in _FORM_CODE_RE.finditer(text or "")}


# Section numbers + OP-form codes that ALSO don't embed distinctively, so a broad omnibus
# doc (e.g. "Int 1321-A" Energy Code Enactment) out-ranks the doc whose TITLE names the exact
# section. Kept RAW (not separator-stripped) so the retriever's rerank can find the literal
# string in a doc's title/text. High-precision patterns only, to avoid boosting on stray numbers.
_SECTION_RE = re.compile(
    r"(?:§\s?)?\b(28-\d{3}(?:\.\d+)*)\b"            # NYC Admin Code, e.g. 28-112.2, 28-105.4.2, 28-104
    r"|§\s?(\d+[A-Za-z0-9]*(?:[.\-]\d+)+)"          # any §-prefixed section, e.g. §3202.2.1, §32-153
    r"|\b(OP-?\d+)\b",                               # OP forms, e.g. OP-49
    re.I,
)


def extract_section_codes(text: str) -> set:
    """Section numbers / OP codes in the text, RAW (e.g. '28-112.2', 'OP-49') — for the
    retriever's keyword boost so section-number queries surface the titling doc."""
    out = set()
    for m in _SECTION_RE.finditer(text or ""):
        tok = next((g for g in m.groups() if g), None)
        if tok:
            out.add(re.sub(r"\s", "", tok.upper()))
    return out
