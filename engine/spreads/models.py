from dataclasses import dataclass
from enum import Enum
from fastapi import  Query
from typing import Optional

class VolatilityMode(str, Enum):
    DEFENSIVE = "DEFENSIVE"
    BALANCED = "BALANCED"
    AGGRESSIVE = "AGGRESSIVE"


async def common_params(
        mode: VolatilityMode = Query(VolatilityMode.BALANCED, description="The volatility filtering threshold")
):
    print(f"Captured Mode: {mode}")
    return {"mode": mode}

@dataclass
class MarketSnapshot:
    ticker: str
    price: float
    iv: float
    iv_rank: float
    days_to_earnings: int
    today_move_pct: float
    sma_200: float
    sma_50: float
    vix: float

from dataclasses import dataclass
from typing import Optional

@dataclass
class BaseOptionTrade:
    ticker: str
    expiry: str
    liquidity_score: float
    bid: float
    ask: float
    strategy_type: str
    option_type: str
    strategy_label: str

    # Computed fields - Always provide defaults for Optional fields in Dataclasses
    otm_percent: Optional[float] = 0.0
    dte: Optional[int] = None
    iv: Optional[float] = None
    iv_rank: Optional[float] = None
    underlying_price: Optional[float] = None
    has_earnings: bool = False
    ev: Optional[float] = None
    bid_ask_width_pct: Optional[float] = 0.0

@dataclass
class LongOption(BaseOptionTrade):
    strike: float = 0.0
    cost: float = 0.0  # This is the Ask price paid
    delta: Optional[float] = None

    @property
    def max_loss(self):
        return self.cost

@dataclass
class CreditSpread(BaseOptionTrade):
    short_strike: float = 0.0
    long_strike: float = 0.0
    width: float = 0.0
    credit: float = 0.0
    short_delta: Optional[float] = None

    def __post_init__(self):
        # Automatically calculate width if strikes are provided
        if self.short_strike and self.long_strike:
            self.width = abs(self.short_strike - self.long_strike)

    @property
    def max_loss(self):
        return self.width - self.credit

    @property
    def risk_reward(self):
        # Max loss per $1 max profit (conventional risk/reward for credit spreads).
        return self.max_loss / self.credit if self.credit > 0 else 0.0

    @max_loss.setter
    def max_loss(self, value):
        self._max_loss = value

    @risk_reward.setter
    def risk_reward(self, value):
        self._risk_reward = value

@dataclass
class DebitSpread(BaseOptionTrade):
    # The 'Long' strike is the one you buy (closer to the money)
    long_strike: float = 0.0
    # The 'Short' strike is the one you sell (further out of the money)
    short_strike: float = 0.0

    # The distance between the two strikes
    width: float = 0.0

    # In a Debit Spread, we use 'cost' (the amount paid) instead of 'credit'
    cost: float = 0.0

    # Delta of the primary long leg for conviction scoring
    long_delta: Optional[float] = None

    @property
    def max_profit(self) -> float:
        """Maximum profit is the width minus the cost paid."""
        return self.width - self.cost

    @property
    def break_even(self) -> float:
        """Calculates break-even based on option type."""
        if self.option_type == "CALL":
            return self.long_strike + self.cost
        return self.long_strike - self.cost

    @property
    def risk_reward(self) -> float:
        """Ratio of potential profit to the amount risked (cost)."""
        if self.cost == 0: return 0.0
        return self.max_profit / self.cost