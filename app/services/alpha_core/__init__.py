"""AlphaClaw v1.1 observation/paper backend core.

No import from this package performs filesystem or network I/O.
"""

from .config import (
    ALLOWED_MODES,
    AlphaCoreConfigurationError,
    default_db_path,
    resolve_mode,
)
from .contracts import (
    ContractValidationError,
    PaperFill,
    PaperOrderIntent,
    ReconciliationResult,
    RiskDecision,
    canonical_hash,
    canonical_json,
    parse_timestamp,
)
from .paper_fill_simulator import (
    CostSchedule,
    FillModel,
    MarketBar,
    SimulationResult,
    simulate_fill,
)
from .paper_ledger import (
    IdempotencyConflict,
    InvalidTransition,
    LedgerError,
    LedgerIntegrityError,
    LedgerNotInitialized,
    PaperLedger,
    ReadOnlyLedgerError,
    StaleApprovalError,
)
from .reconciliation import reconcile_projection
from .risk_kernel import MarketSnapshot, PortfolioSnapshot, RiskKernel, RiskPolicy
from .service import AlphaCoreService


__all__ = [
    "ALLOWED_MODES",
    "AlphaCoreConfigurationError",
    "AlphaCoreService",
    "ContractValidationError",
    "CostSchedule",
    "FillModel",
    "IdempotencyConflict",
    "InvalidTransition",
    "LedgerError",
    "LedgerIntegrityError",
    "LedgerNotInitialized",
    "MarketBar",
    "MarketSnapshot",
    "PaperFill",
    "PaperLedger",
    "PaperOrderIntent",
    "PortfolioSnapshot",
    "ReadOnlyLedgerError",
    "ReconciliationResult",
    "RiskDecision",
    "RiskKernel",
    "RiskPolicy",
    "SimulationResult",
    "StaleApprovalError",
    "canonical_hash",
    "canonical_json",
    "default_db_path",
    "reconcile_projection",
    "resolve_mode",
    "simulate_fill",
    "parse_timestamp",
]
