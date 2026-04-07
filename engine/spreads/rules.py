from backend.engine.spreads.models import MarketSnapshot, CreditSpread, BaseOptionTrade
from backend.configs.config import TICKER_RULES, MODE_CONFIG
from backend.core.logger import get_logger

logger = get_logger(__name__)

def passes_earnings_filter(snapshot: MarketSnapshot) -> bool:
    return snapshot.days_to_earnings >= TICKER_RULES["DEFAULT"]["min_days_to_earnings"]

def passes_iv_filter(snapshot: MarketSnapshot) -> bool:
    return snapshot.iv_rank >= TICKER_RULES["DEFAULT"]["min_iv_rank"]

def passes_move_filter(snapshot: MarketSnapshot) -> bool:
    # avoid days like MU -50%
    return abs(snapshot.today_move_pct) <= 8.0

def passes_otm_filter(snapshot: MarketSnapshot, spread: CreditSpread) -> bool:
    rules = TICKER_RULES.get(snapshot.ticker, {"min_otm": 5.0})
    min_otm = rules["min_otm"]
    otm = spread.otm_percent(snapshot.price)
    return otm >= min_otm

def passes_risk_reward(spread: CreditSpread) -> bool:
    return spread.risk_reward <= TICKER_RULES["DEFAULT"]["max_risk_reward"]

def evaluate_trade(snapshot: MarketSnapshot, trade: BaseOptionTrade, overall_score: float, ai_score: float):
    """
    Final decision engine.
    Handles Hard Filters first, then maps Scores to Status.
    """
    # 1. Ultimate Safety Gate (The 'None' Guard)
    if trade is None:
        return "SKIP", ["Null trade object passed to evaluator"]

    reasons = []
    is_spread = isinstance(trade, CreditSpread)

    # 2. Configuration Loading (Base + Ticker Overrides)
    base_rules = TICKER_RULES.get("DEFAULT", {})
    ticker_rules = TICKER_RULES.get(snapshot.ticker, {})
    rules = {**base_rules, **ticker_rules}

    # 3. Market-Wide Hard Filters
    if snapshot.days_to_earnings < rules.get("min_days_to_earnings", 7):
        reasons.append(f"Earnings: {snapshot.days_to_earnings}d to report (High Vol Risk)")

    if abs(snapshot.today_move_pct) > rules.get("max_daily_move", 8.0):
        reasons.append(f"Volatility: Underlying moved {snapshot.today_move_pct:.2f}% (Wait for settling)")

    # 4. Strategy-Specific OTM & IV Logic
    otm_pct = getattr(trade, 'otm_percent', 0.0)
    iv_rank = getattr(snapshot, 'iv_rank', 0.0)

    if is_spread:
        # Spreads: We need a Safety Buffer
        min_otm = rules.get("min_otm_spread", 7.0)
        if otm_pct < min_otm:
            reasons.append(f"Safety: OTM {otm_pct:.1f}% < {min_otm}% floor")

        if iv_rank < rules.get("min_iv_rank_spread", 20):
            reasons.append(f"IV Rank: {iv_rank} too low to justify selling premium")
    else:
        # Longs: We need Proximity (The 'Hurdle')
        max_otm = rules.get("max_otm_long", 5.0)
        if otm_pct > max_otm:
            reasons.append(f"Probability: Long is {otm_pct:.1f}% OTM (Max hurdle is {max_otm}%)")

        if iv_rank > rules.get("max_iv_rank_long", 25):
            reasons.append(f"IV Crush: {iv_rank} is too high to buy premium safely")

    # 5. Liquidity & Execution Risk
    liq_score = getattr(trade, 'liquidity_score', 0.0)
    ba_width = getattr(trade, 'bid_ask_width_pct', 0.0)

    if liq_score < rules.get("min_liquidity_score", 4.0):
        reasons.append(f"Liquidity: Score {liq_score} indicates high slippage risk")

    if ba_width > rules.get("max_bid_ask_pct", 6.0):
        reasons.append(f"Slippage: Bid-Ask spread {ba_width:.1f}% is too wide")

    # 6. ITM Check (Safety Net)
    # For Spreads, check short_strike. For Longs, check strike.
    target_strike = getattr(trade, 'short_strike', getattr(trade, 'strike', 0))
    is_itm = False
    if trade.option_type == "PUT" and target_strike > snapshot.price:
        is_itm = True
    elif trade.option_type == "CALL" and target_strike < snapshot.price:
        is_itm = True

    if is_itm:
        reasons.append(f"Execution Error: Strike {target_strike} is already ITM")

    final_status = decision_maker(trade, overall_score, ai_score, rules, reasons)

    return final_status, reasons


def decision_maker(spread, overall_score, ai_score, rules, reasons):
    """
        Determines the final status (TRADE, WATCH, SKIP) based on scores and EV.
        """
    # 1. If we already have rejection reasons, it's an automatic SKIP
    if reasons or spread.ev <= 0:
        return "SKIP"

    # 2. Score Gates
    if ai_score < rules.get("ai_score_gate", 6.0):
        reasons.append(f"AI Score too low ({ai_score})")
        return "SKIP"

    if overall_score < rules.get("overall_score_gate", 6.0):
        reasons.append(f"Overall Score too low ({overall_score})")
        return "SKIP"

    # Weighted Combined Score
    final_score = (0.7 * overall_score) + (0.3 * ai_score)

    if final_score < rules.get("combined_score_gate", 6.5):
        reasons.append(f"Combined Score too low ({final_score:.2f})")
        return "SKIP"

    # 3. Decision Matrix (EV + Score)
    trade_thresh = rules["decision_thresholds"]["trade"]
    watch_thresh = rules["decision_thresholds"]["watch"]
    ev_min = rules.get("ev_trade_min", 1.0)

    if spread.ev >= ev_min and final_score >= trade_thresh:
        return "TRADE"

    if final_score >= watch_thresh:
        return "WATCH"

    return "SKIP"

def final_decision(overall_score, ai_score, mode):

    config = MODE_CONFIG[mode]
    t = config["min_score_trade"]

    final_score = (0.7 * overall_score) + (0.3 * ai_score)

    if final_score >= t:
        return "TRADE"
    elif final_score >= t - 1:
        return "WATCH"
    else:
        return "SKIP"