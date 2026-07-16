"""Rule protocol and the shared context passed to every rule.

Each rule is a pure function: ``(RuleContext) -> list[Finding]``. Rules never do
I/O and never mutate their input — this is what makes them trivially testable
against fixtures (see tests/ and the notebooks).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Protocol

from m365_review.core.models import Finding, SubscribedSku, TenantData
from m365_review.core.pricing import PricingCatalog


@dataclass
class RuleContext:
    """Everything a rule needs: the tenant data, pricing, and a stable 'now'.

    ``now`` is injected (not read from the clock inside rules) so tests and
    notebooks are deterministic.
    """

    data: TenantData
    pricing: PricingCatalog
    now: datetime
    experimental_enabled: bool = False

    def __post_init__(self) -> None:
        # Normalize to timezone-aware UTC so date math against Graph timestamps is safe.
        if self.now.tzinfo is None:
            self.now = self.now.replace(tzinfo=timezone.utc)

    # --- convenience lookups shared by several rules ---
    def sku_by_id(self) -> dict[str, SubscribedSku]:
        return {s.sku_id: s for s in self.data.skus}

    def price_for_sku_id(self, sku_id: str) -> float | None:
        sku = self.sku_by_id().get(sku_id)
        if sku is None:
            return None
        return self.pricing.price(sku.sku_part_number)

    def user_license_monthly_cost(self, sku_ids: list[str]) -> tuple[float, bool]:
        """Sum monthly cost of a user's licenses. Returns (total, all_prices_known)."""
        total = 0.0
        all_known = True
        skus = self.sku_by_id()
        for sid in sku_ids:
            sku = skus.get(sid)
            price = self.pricing.price(sku.sku_part_number) if sku else None
            if price is None:
                all_known = False
            else:
                total += price
        return round(total, 2), all_known

    def license_names_for(self, sku_ids: list[str]) -> list[str]:
        skus = self.sku_by_id()
        names = []
        for sid in sku_ids:
            sku = skus.get(sid)
            names.append(self.pricing.display_name(sku.sku_part_number) if sku else sid)
        return names


class Rule(Protocol):
    """Structural type every rule module satisfies."""

    rule_id: str
    title: str
    experimental: bool

    def evaluate(self, ctx: RuleContext) -> list[Finding]:
        ...
