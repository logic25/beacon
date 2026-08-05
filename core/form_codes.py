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
