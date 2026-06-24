from dataclasses import dataclass

from app.schemas.company import CompanyModuleCode, CompanyTier

SUPPORTED_MODULE_ORDER: tuple[CompanyModuleCode, ...] = (
    "foundations",
    "waste_bins",
    "jobs",
    "payroll",
    "costing",
    "invoices",
    "field",
    "dispatch",
    "credentials",
)

TIER_ENTITLED_MODULES: dict[CompanyTier, tuple[CompanyModuleCode, ...]] = {
    "tier_1_clock_in": ("field",),
    "tier_2_clock_in_payroll": ("field", "payroll"),
    "tier_3_full_system": SUPPORTED_MODULE_ORDER,
}

TIER_CAPABILITIES: dict[CompanyTier, tuple[str, ...]] = {
    "tier_1_clock_in": ("field", "clock_in"),
    "tier_2_clock_in_payroll": ("field", "clock_in", "payroll", "employees"),
    "tier_3_full_system": ("field", "clock_in", "payroll", "employees", "full_system", "frontier_ai"),
}


@dataclass(frozen=True)
class ResolvedCompanyEntitlements:
    selected_tier: CompanyTier
    entitled_modules: list[CompanyModuleCode]
    enabled_modules: list[CompanyModuleCode]
    entitled_capabilities: list[str]


def _ordered_modules(module_codes: list[str] | tuple[str, ...]) -> list[CompanyModuleCode]:
    allowed = set(module_codes)
    return [module_code for module_code in SUPPORTED_MODULE_ORDER if module_code in allowed]


def resolve_company_entitlements(
    *,
    selected_tier: CompanyTier,
    enabled_modules: list[CompanyModuleCode],
) -> ResolvedCompanyEntitlements:
    entitled_modules = _ordered_modules(list(TIER_ENTITLED_MODULES[selected_tier]))
    normalized_enabled_modules = _ordered_modules(enabled_modules)

    invalid_modules = sorted(set(normalized_enabled_modules) - set(entitled_modules))
    if invalid_modules:
        raise ValueError(
            f"Modules not available for {selected_tier}: {', '.join(invalid_modules)}"
        )

    return ResolvedCompanyEntitlements(
        selected_tier=selected_tier,
        entitled_modules=entitled_modules,
        enabled_modules=normalized_enabled_modules,
        entitled_capabilities=list(TIER_CAPABILITIES[selected_tier]),
    )
