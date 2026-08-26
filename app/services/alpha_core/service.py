"""Small orchestration facade that keeps shadow evaluation write-free."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

from .config import resolve_mode
from .contracts import PaperOrderIntent
from .paper_ledger import PaperLedger
from .risk_kernel import MarketSnapshot, PortfolioSnapshot, RiskKernel, RiskPolicy


class AlphaCoreService:
    def __init__(
        self,
        policy: RiskPolicy,
        *,
        db_path: str | Path | None = None,
        mode: str | None = None,
    ) -> None:
        self.mode = resolve_mode(mode)
        self.ledger = PaperLedger(db_path, mode=self.mode)
        self.risk = RiskKernel(policy)

    def initialize_storage(self) -> dict[str, Any]:
        """Create schema only; safe in default shadow mode and no capital event."""

        self.ledger.initialize()
        return self.ledger.status()

    def shadow_evaluate(
        self,
        intent: PaperOrderIntent,
        portfolio: PortfolioSnapshot,
        market: MarketSnapshot,
        *,
        evaluated_at: str | datetime,
        nonce: str,
    ) -> dict[str, Any]:
        """Evaluate with zero DB writes even if the service was configured paper."""

        decision = self.risk.evaluate(
            intent,
            portfolio,
            market,
            evaluated_at=evaluated_at,
            nonce=nonce,
            mode="shadow",
        )
        return {
            "mode": "shadow",
            "persisted": False,
            "decision": decision.to_dict(),
        }

