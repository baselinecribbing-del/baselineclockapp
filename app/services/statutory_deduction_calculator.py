from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal, ROUND_HALF_UP
from typing import TypedDict


class StatutoryDeductionRow(TypedDict):
    deduction_type_code: str
    amount_cents: int
    calculation_source: str


@dataclass(frozen=True)
class StatutoryRule:
    code: str
    rate: Decimal
    max_amount_cents: int | None = None


class StatutoryDeductionCalculator:
    """Deterministic placeholder for statutory deductions until CRA tables are wired in."""

    def __init__(self, *, rules: list[StatutoryRule] | None = None) -> None:
        self._rules = rules or [
            StatutoryRule(code="CPP", rate=Decimal("0.06")),
            StatutoryRule(code="EI", rate=Decimal("0.02")),
        ]

    @staticmethod
    def _calc_amount_cents(gross_pay_cents: int, rate: Decimal) -> int:
        gross = Decimal(int(gross_pay_cents))
        amount = (gross * rate).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
        return max(0, int(amount))

    def calculate(self, *, gross_pay_cents: int, as_of_date: date) -> list[StatutoryDeductionRow]:
        # as_of_date is intentionally part of the signature so real CRA effective-dated tables can slot in.
        _ = as_of_date
        rows: list[StatutoryDeductionRow] = []
        for rule in self._rules:
            amount_cents = self._calc_amount_cents(int(gross_pay_cents), rule.rate)
            if rule.max_amount_cents is not None:
                amount_cents = min(amount_cents, int(rule.max_amount_cents))
            rows.append(
                {
                    "deduction_type_code": str(rule.code),
                    "amount_cents": int(amount_cents),
                    "calculation_source": "STATUTORY",
                }
            )
        return rows


def get_default_statutory_calculator() -> StatutoryDeductionCalculator:
    return StatutoryDeductionCalculator()
