
from engine.spreads.models import CreditSpread, BaseOptionTrade, LongOption, DebitSpread
from datetime import datetime
from data.data_yahoo_option import get_earnings_date
from math import log, sqrt, exp
from scipy.stats import norm
from core.logger import get_logger

logger = get_logger(__name__)


def compute_delta(S, K, T, r, iv, option_type):
    d1 = (log(S / K) + (r + 0.5 * iv**2) * T) / (iv * sqrt(T))

    if option_type == "CALL":
        return norm.cdf(d1)
    else:  # PUT
        return norm.cdf(d1) - 1


# Compute the fields
def enrich_trade(trade: BaseOptionTrade, underlying_price, iv_rank, iv):
    # --- 1. SHARED DATA (Common to Longs and Spreads) ---
    trade.underlying_price = underlying_price
    trade.iv_rank = iv_rank
    trade.iv = iv

    # DTE Calculation
    exp_date = datetime.fromisoformat(trade.expiry).date()
    trade.dte = (exp_date - datetime.now().date()).days

    # Bid/Ask Width % (Liquidity check)
    if (trade.ask + trade.bid) > 0:
        trade.bid_ask_width_pct = ((trade.ask - trade.bid) / ((trade.ask + trade.bid) / 2)) * 100

    # --- 2. STRATEGY SPECIFIC LOGIC ---
    if isinstance(trade, LongOption):
        # OTM % for Single Leg
        if trade.option_type == "PUT":
            trade.otm_percent = ((underlying_price - trade.strike) / underlying_price) * 100
        else:
            trade.otm_percent = ((trade.strike - underlying_price) / underlying_price) * 100

        # Delta for Long (used for EV)
        trade.delta = compute_delta(
            S=underlying_price, K=trade.strike, T=trade.dte/365,
            r=0.05, iv=iv, option_type=trade.option_type
        )

        # Simple EV for Long: (Delta * 100 potential) - Cost
        # (This is a simplified projection for ranking purposes)
        trade.ev = (abs(trade.delta) * underlying_price * 0.1) - trade.cost
    elif isinstance(trade, CreditSpread):
        # OTM % for Short Strike
        if trade.option_type == "PUT":
            trade.otm_percent = ((underlying_price - trade.short_strike) / underlying_price) * 100
        else:
            trade.otm_percent = ((trade.short_strike - underlying_price) / underlying_price) * 100

        # Risk/Reward (max loss / credit — dollars at risk per $1 of premium)
        trade.max_gain = trade.credit
        trade.max_loss = trade.width - trade.credit

        if trade.credit > 0:
            trade.risk_reward = trade.max_loss / trade.max_gain

        # Expected Value for Spreads
        trade.short_delta = compute_delta(
            S=underlying_price, K=trade.short_strike, T=trade.dte/365,
            r=0.05, iv=iv, option_type=trade.option_type
        )

        p_win = 1 - abs(trade.short_delta)
        p_loss = 1 - p_win
        trade.ev = (p_win * trade.credit) - (p_loss * trade.max_loss)

    elif isinstance(trade, DebitSpread):
        # 1. OTM % for the 'Long' Strike (The one we need to reach)
        if trade.option_type == "PUT":
            trade.otm_percent = ((trade.long_strike - underlying_price) / underlying_price) * 100
        else:
            trade.otm_percent = ((underlying_price - trade.long_strike) / underlying_price) * 100

        # 2. Risk/Reward (Cost is the Max Loss)
        trade.max_loss = trade.cost
        trade.max_gain = trade.width - trade.cost

        if trade.max_loss > 0:
            trade.risk_reward = trade.max_gain / trade.max_loss

        # 3. Expected Value for Debit Spreads
        # We use the Delta of the Long strike as our proxy for p_win
        trade.long_delta = compute_delta(
            S=underlying_price, K=trade.long_strike, T=trade.dte/365,
            r=0.05, iv=iv, option_type=trade.option_type
        )

        # For a debit spread to be profitable, it needs to move ITM.
        # Approximation: p_win is roughly the Delta of the long strike.
        p_win = abs(trade.long_delta)
        p_loss = 1 - p_win

        trade.ev = (p_win * trade.max_gain) - (p_loss * trade.max_loss)

    return trade
