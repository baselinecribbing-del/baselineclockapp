from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.customer_site import CustomerSite
from app.models.email_ingestion_event import EmailIngestionEvent
from app.models.event_outbox import EventOutbox
from app.models.job_purchase_order import JobPurchaseOrder
from app.services.bin_request_service import RequestType, create_service_request
from app.services.po_parser import extract_po_details
from app.services.waste_bin_notifications import render_request_acknowledgement

BIN_SERVICE_REQUEST_EMAIL_ACK_READY = "BIN_SERVICE_REQUEST_EMAIL_ACK_READY"
_INVALID_PO_TOKENS = {"AND", "THE", "THIS", "THAT", "WITH", "FROM", "PLEASE"}


@dataclass(frozen=True)
class ParsedBinEmailIntake:
    request_type: RequestType
    parsed_po_number: str | None
    customer_site_id: str | None
    customer_site_match_label: str | None
    confidence: Decimal
    notes: str


def _normalize(value: str | None) -> str:
    if not value:
        return ""
    return re.sub(r"\s+", " ", str(value).strip().lower())


def _detect_request_type(subject: str, parsed_text: str) -> tuple[RequestType, Decimal, str]:
    haystack = _normalize(f"{subject}\n{parsed_text}")

    if any(token in haystack for token in ["swap", "exchange", "replace bin"]):
        return "SWAP", Decimal("0.95"), "swap"
    if any(token in haystack for token in ["pickup", "pick up", "remove bin", "haul away"]):
        return "PICKUP", Decimal("0.90"), "pickup"
    if any(token in haystack for token in ["drop", "delivery", "deliver bin", "new bin"]):
        return "DROP", Decimal("0.90"), "drop"

    return "DROP", Decimal("0.35"), "default"


def _find_customer_site_match(*, db: Session, company_id: int, searchable_text: str) -> tuple[str | None, str | None]:
    text = _normalize(searchable_text)
    if not text:
        return None, None

    rows = (
        db.query(CustomerSite)
        .filter(CustomerSite.company_id == int(company_id))
        .order_by(CustomerSite.customer_site_id.asc())
        .all()
    )

    if not rows:
        return None, None

    ranked: list[tuple[int, str, str]] = []
    for site in rows:
        score = 0
        labels: list[str] = []

        address = _normalize(site.address_line_1)
        if address and address in text:
            score += 3
            labels.append(f"address:{site.address_line_1}")

        site_name = _normalize(site.site_name)
        if site_name and site_name in text:
            score += 2
            labels.append(f"site:{site.site_name}")

        customer_name = _normalize(site.customer_name)
        if customer_name and customer_name in text:
            score += 1
            labels.append(f"customer:{site.customer_name}")

        if score > 0:
            ranked.append((score, str(site.customer_site_id), "; ".join(labels)))

    if not ranked:
        return None, None

    ranked.sort(key=lambda item: (-item[0], item[1]))
    top = ranked[0]
    if len(ranked) > 1 and ranked[1][0] == top[0]:
        return None, None

    return top[1], top[2]


def _build_notes(
    *,
    request_type: RequestType,
    confidence: Decimal,
    parsed_po_number: str | None,
    matched_po_id: str | None,
    site_match_label: str | None,
    fallback_type: bool,
) -> str:
    parts = [
        f"email_intake request_type={request_type}",
        f"confidence={confidence}",
        f"parsed_po_number={parsed_po_number or 'none'}",
        f"job_purchase_order_match={matched_po_id or 'none'}",
        f"customer_site_match={site_match_label or 'none'}",
    ]
    if fallback_type:
        parts.append("request_type inferred by default (no explicit keyword found)")
    return " | ".join(parts)


def _clean_parsed_po_number(value: str | None) -> str | None:
    if value is None:
        return None

    candidate = str(value).strip().upper()
    if not candidate:
        return None
    if candidate in _INVALID_PO_TOKENS:
        return None

    has_signal = bool(re.search(r"\d", candidate)) or ("-" in candidate) or ("/" in candidate)
    if not has_signal:
        return None
    return candidate


def parse_bin_service_request_email(
    *,
    db: Session,
    company_id: int,
    event: EmailIngestionEvent,
    parsed_text_override: str | None,
) -> ParsedBinEmailIntake:
    subject = str(event.subject or "")
    parsed_text = str(parsed_text_override or "")
    request_type, confidence, marker = _detect_request_type(subject, parsed_text)

    extracted = extract_po_details(subject=subject, text=parsed_text)
    parsed_po_number = _clean_parsed_po_number(event.parsed_po_number or extracted.po_number or None)

    po_id: str | None = None
    if parsed_po_number is not None:
        po = (
            db.query(JobPurchaseOrder)
            .filter(JobPurchaseOrder.company_id == int(company_id))
            .filter(func.upper(JobPurchaseOrder.po_number) == str(parsed_po_number).upper())
            .one_or_none()
        )
        if po is not None:
            po_id = str(po.job_purchase_order_id)

    searchable_text = "\n".join([subject, parsed_text, str(parsed_po_number or "")])
    customer_site_id, site_match_label = _find_customer_site_match(
        db=db,
        company_id=company_id,
        searchable_text=searchable_text,
    )

    notes = _build_notes(
        request_type=request_type,
        confidence=confidence,
        parsed_po_number=parsed_po_number,
        matched_po_id=po_id,
        site_match_label=site_match_label,
        fallback_type=(marker == "default"),
    )

    return ParsedBinEmailIntake(
        request_type=request_type,
        parsed_po_number=parsed_po_number,
        customer_site_id=customer_site_id,
        customer_site_match_label=site_match_label,
        confidence=confidence,
        notes=notes,
    )


def create_bin_service_request_from_email(
    *,
    db: Session,
    company_id: int,
    email_ingestion_event_id: str,
    parsed_text_override: str | None,
):
    event = (
        db.query(EmailIngestionEvent)
        .filter(EmailIngestionEvent.company_id == int(company_id))
        .filter(EmailIngestionEvent.email_ingestion_event_id == str(email_ingestion_event_id))
        .one_or_none()
    )
    if event is None:
        raise ValueError("Email ingestion event not found")

    parsed = parse_bin_service_request_email(
        db=db,
        company_id=company_id,
        event=event,
        parsed_text_override=parsed_text_override,
    )

    po_id: str | None = None
    if parsed.parsed_po_number is not None:
        po = (
            db.query(JobPurchaseOrder)
            .filter(JobPurchaseOrder.company_id == int(company_id))
            .filter(func.upper(JobPurchaseOrder.po_number) == str(parsed.parsed_po_number).upper())
            .one_or_none()
        )
        if po is not None:
            po_id = str(po.job_purchase_order_id)

    row = create_service_request(
        db=db,
        company_id=int(company_id),
        customer_site_id=parsed.customer_site_id,
        job_purchase_order_id=po_id,
        request_type=parsed.request_type,
        request_notes=parsed.notes,
        request_source="EMAIL_INGESTION",
        source_email_ingestion_event_id=str(event.email_ingestion_event_id),
    )
    row.parsed_confidence = parsed.confidence.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    rendered = render_request_acknowledgement(
        db=db,
        company_id=int(company_id),
        request_row=row,
    )

    event_type = BIN_SERVICE_REQUEST_EMAIL_ACK_READY
    idempotency_key = f"{event_type}:{company_id}:{event.email_ingestion_event_id}"
    existing = (
        db.query(EventOutbox)
        .filter(EventOutbox.company_id == int(company_id))
        .filter(EventOutbox.idempotency_key == idempotency_key)
        .one_or_none()
    )
    if existing is None:
        db.add(
            EventOutbox(
                company_id=int(company_id),
                event_type=event_type,
                idempotency_key=idempotency_key,
                payload={
                    "company_id": int(company_id),
                    "bin_service_request_id": str(row.bin_service_request_id),
                    "request_type": str(row.request_type),
                    "customer_site_id": row.customer_site_id,
                    "job_purchase_order_id": row.job_purchase_order_id,
                    "source_email_ingestion_event_id": str(event.email_ingestion_event_id),
                    "rendered_subject": rendered.subject,
                    "rendered_body": rendered.body,
                },
            )
        )

    return row
