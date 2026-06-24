import re
from dataclasses import dataclass

_PO_PATTERNS = (
    re.compile(r"\b(PO[-/][A-Z0-9][A-Z0-9\-/]{1,})\b", re.IGNORECASE),
    re.compile(r"\bP\s*\.?\s*O\s*\.?\s*(?:#|NO\.?|NUMBER)?\s*[:\-]?\s*([A-Z0-9][A-Z0-9\-/]{1,})\b", re.IGNORECASE),
    re.compile(r"\bPURCHASE\s+ORDER\s*(?:#|NO\.?|NUMBER)?\s*[:\-]?\s*([A-Z0-9][A-Z0-9\-/]{1,})\b", re.IGNORECASE),
)

_JOB_PATTERNS = (
    re.compile(r"\bJOB\s*(?:#|NO\.?|NUMBER|REF(?:ERENCE)?)?\s*[:\-]?\s*([A-Z0-9][A-Z0-9\-/]{1,})\b", re.IGNORECASE),
    re.compile(r"\bPROJECT\s*(?:#|NO\.?|NUMBER|REF(?:ERENCE)?)?\s*[:\-]?\s*([A-Z0-9][A-Z0-9\-/]{1,})\b", re.IGNORECASE),
)


@dataclass(frozen=True)
class POParseResult:
    po_number: str | None
    job_reference: str | None


def _extract_first(patterns: tuple[re.Pattern[str], ...], text: str) -> str | None:
    for pattern in patterns:
        match = pattern.search(text)
        if match:
            return str(match.group(1)).upper()
    return None


def extract_po_details(*, subject: str | None, text: str | None) -> POParseResult:
    combined = "\n".join(part for part in [(subject or "").strip(), (text or "").strip()] if part)
    if not combined:
        return POParseResult(po_number=None, job_reference=None)

    po_number = _extract_first(_PO_PATTERNS, combined)
    job_reference = _extract_first(_JOB_PATTERNS, combined)
    return POParseResult(po_number=po_number, job_reference=job_reference)
