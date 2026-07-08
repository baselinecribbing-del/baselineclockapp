from __future__ import annotations

from typing import Any

from app.models.employee import Employee


def resolve_tax_preset_metadata(*, country: str | None, province_state: str | None) -> dict[str, Any]:
    normalized_country = (country or "").strip().upper() or None
    normalized_region = (province_state or "").strip().upper() or None

    if normalized_country == "CA":
        preset_code = f"CA-{normalized_region or 'DEFAULT'}-PAYROLL-BASE"
        return {
            "country": "CA",
            "province_state": normalized_region,
            "preset_code": preset_code,
            "tax_authority": "CRA",
            "calculation_engine_status": "NOT_IMPLEMENTED",
            "metadata": {
                "supports_source_deductions_tracking": True,
                "supports_employee_claim_fields": True,
                "supported_employee_fields": [
                    "sin",
                    "province_of_employment",
                    "federal_claim_amount",
                    "provincial_claim_amount",
                    "additional_tax_withholding",
                    "tax_exemptions",
                ],
            },
        }

    preset_code = f"{normalized_country or 'UNSPECIFIED'}-{normalized_region or 'DEFAULT'}-PAYROLL-BASE"
    return {
        "country": normalized_country,
        "province_state": normalized_region,
        "preset_code": preset_code,
        "tax_authority": None,
        "calculation_engine_status": "NOT_IMPLEMENTED",
        "metadata": {
            "supports_source_deductions_tracking": False,
            "supports_employee_claim_fields": False,
            "supported_employee_fields": [],
        },
    }


def resolve_employee_tax_preset(*, employee: Employee) -> dict[str, Any]:
    province_state = employee.province_of_employment or employee.province
    payload = resolve_tax_preset_metadata(
        country=employee.country,
        province_state=province_state,
    )
    payload["employee_id"] = int(employee.id)
    return payload
