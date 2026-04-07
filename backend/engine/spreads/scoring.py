from backend.configs.config import MODE_CONFIG
from backend.engine.spreads.models import CreditSpread, BaseOptionTrade, LongOption
from backend.core.logger import get_logger

logger = get_logger(__name__)

def grade_from_score(score):
    if score >= 8: return "A"
    if score >= 6: return "B"
    if score >= 4: return "C"
    if score >= 2: return "D"
    return "F"

def normalize_credit(c):
    return max(0, min(10, c))

def normalize_otm(o):
    return max(0, min(10, o))

def normalize_rr(rr):
    return max(0, min(10, 10 - rr))

# Liquidity Score
# - Tight spreads (0.05 → 9.5)
# - Moderate spreads (0.40 → 6.0)
# - Wide spreads (0.80 → 2.0)
# - Extremely wide spreads (>1.0 → 0)
def compute_liquidity_score(ask, bid):
    spread_width = max(ask - bid, 0)
    return round(max(0, min(10, 10 - (spread_width * 10))), 2)

def compute_otm_percent(option_type, strike, price):
    if option_type == "PUT":
        return ((price - strike) / price) * 100
    else:  # CALL credit spread
        return ((strike - price) / price) * 100

def compute_color(decision):
    if decision == "TRADE":
        return "green"
    if decision == "WATCH":
        return "blue"
    return "red"

def normalize_otm_spread(otm_pct):
    """Sellers love distance."""
    return min(otm_pct, 15.0) / 1.5  # Cap at 15% OTM = 10 points

def normalize_otm_long(otm_pct):
    """Buyers love proximity."""
    if otm_pct > 10: return 0
    return 10 * (1 - (otm_pct / 10)) # 0% OTM = 10 points, 10% OTM = 0 points

def normalize_long_cost(cost, underlying_price, max_cost_pct=0.10):
    """
    Normalizes the premium paid.
    Lower cost = Higher score.
    """
    # Calculate what a 'very expensive' option looks like (e.g. 10% of stock price)
    limit = underlying_price * max_cost_pct

    if cost <= 0: return 0
    if cost >= limit: return 0

    # Linear scale: 10 is cheap, 0 is at the limit
    score = 10 * (1 - (cost / limit))
    return round(score, 2)


def normalize_delta(delta):
    """
    Normalizes the Delta.
    Higher absolute Delta = Higher score (more directional certainty).
    """
    if delta is None: return 0

    # We use absolute value so it works for both Puts (-0.50) and Calls (0.50)
    abs_d = abs(delta)

    # Use a non-linear boost: 0.3 to 0.5 Delta is the "Sweet Spot"
    if abs_d >= 0.30:
        score = 7.0 + (abs_d * 3.0) # Boosts 0.3 Delta to 7.9/10
    else:
        score = abs_d * 20 # 0.1 Delta becomes 2.0/10

    return min(round(score, 2), 10.0)


def compute_overall_score(trade: BaseOptionTrade):
    is_spread = isinstance(trade, CreditSpread)
    # 1. Base Liquidity (Shared)
    liq_val = getattr(trade, 'liquidity_score', 0.0)
    otm_pct = getattr(trade, 'otm_percent', 0.0)

    liq_component = 0.4 * liq_val

    # 2. Strategy-Specific OTM Normalization
    if is_spread:
        # For Spreads: Further OTM is better (Safety)
        otm_val = normalize_otm_spread(otm_pct)
    else:
        # For Longs: Closer OTM is better (Probability)
        otm_val = normalize_otm_long(otm_pct)

    # 3. Strategy-Specific Performance (40% Weight)
    if is_spread:
        # Credit Spreads: reward/risk (credit / max loss); higher is better
        rr = trade.max_gain / trade.max_loss if trade.max_loss > 0 else 0.0
        rr_val = min(rr * 30, 10.0)
        strategy_component = 0.4 * rr_val
    else:
        # Long Options: Focus on Leverage (Delta) and Cost Efficiency
        # We want high Delta (0.40+) but reasonable cost relative to stock price
        delta = getattr(trade, 'delta', 0.0)
        delta_score = normalize_delta(delta)

        cost = getattr(trade, 'cost', 0.0)
        u_price = getattr(trade, 'underlying_price', 1.0) # Avoid division by zero
        cost_score = normalize_long_cost(cost, u_price)

        # Weight Delta more heavily than cost for conviction
        strategy_component = 0.4 * ((delta_score * 0.7) + (cost_score * 0.3))

    # 4. Final Calculation
    final_score = liq_component + (0.2 * otm_val) + strategy_component

    return round(final_score, 2)


def compute_ai_score(trade: BaseOptionTrade, market_regime="BEARISH"):
    """
    Unified AI Score for Spreads and Longs.
    Weights: OTM (30%), Liquidity (25%), Strategy-Specific (20%), DTE (15%), IVR (10%)
    """
    # --- SAFETY GATE ---
    if trade is None:
        return 0.0

    is_spread = isinstance(trade, CreditSpread)

    # Use getattr to prevent attribute-level crashes
    otm = getattr(trade, 'otm_percent', 0.0)
    ivr = getattr(trade, 'iv_rank', 0.0)
    width = getattr(trade, 'bid_ask_width_pct', 0.0)

    # 1. OTM Score (30%) - Shared Logic
    if otm >= 15:   otm_val = 10
    elif otm >= 10: otm_val = 9
    elif otm >= 7:  otm_val = 7
    elif otm >= 5:  otm_val = 5
    else:           otm_val = 0

    # 2. Liquidity Score (25%) - Shared Logic
    # Using bid_ask_width_pct ensures we are checking current slippage
    if width <= 1.5:  liq_val = 10
    elif width <= 3:  liq_val = 8
    elif width <= 5:  liq_val = 5
    else:             liq_val = 0

    # 3. Strategy-Specific Performance (20%)
    if is_spread:
        # Credit spreads: trade.risk_reward is max_loss/credit; map bands via reward/risk
        rr = trade.max_gain / trade.max_loss if trade.max_loss > 0 else 0.0
        if 0.20 <= rr <= 0.35: rr_val = 10
        elif rr > 0.35:        rr_val = 7
        elif rr >= 0.15:       rr_val = 5
        else:                  rr_val = 2
    else:
        # Delta/Cost Efficiency for Long Options
        # We want high Delta (0.40+) but reasonable cost
        delta_val = normalize_delta(trade.delta)
        cost_val = normalize_long_cost(trade.cost, trade.underlying_price)
        rr_val = (delta_val * 0.7) + (cost_val * 0.3)

    # 4. DTE Score (15%)
    dte = trade.dte
    if is_spread:
        if 14 <= dte <= 45: dte_val = 10
        elif 7 <= dte < 14: dte_val = 6
        else:               dte_val = 0
    else:
        # Longs need MORE time to breathe (avoiding theta decay)
        if 30 <= dte <= 60: dte_val = 10
        elif dte > 60:      dte_val = 8
        elif 14 <= dte < 30: dte_val = 4
        else:               dte_val = 0

    # 5. IV Rank Score (10%)
    if is_spread:
        # Sell high IV
        if 40 <= ivr <= 80: iv_val = 10
        elif 20 <= ivr < 40: iv_val = 7
        else:                iv_val = 3
    else:
        # Buy low IV
        if ivr < 15:         iv_val = 10
        elif 15 <= ivr < 30: iv_val = 7
        else:                iv_val = 2

    # --- DIRECTIONAL ALIGNMENT ---
    # Credit: Bull Put is "PUT", Bear Call is "CALL"
    # Long: Long Put is "PUT", Long Call is "CALL"
    direction_mod = 1.0
    if market_regime == "BEARISH" and trade.option_type == "CALL":
        # Penalize Bullish trades in a Bearish market
        direction_mod = 0.6
    elif market_regime == "BULLISH" and trade.option_type == "PUT":
        # Penalize Bearish trades in a Bullish market
        direction_mod = 0.6

    final_score = (
                          (otm_val * 0.30) +
                          (liq_val * 0.25) +
                          (rr_val * 0.20) +
                          (dte_val * 0.15) +
                          (iv_val * 0.10)
                  ) * direction_mod

    return round(final_score, 2)

def decide_trade(score, mode):
    config = MODE_CONFIG[mode]
    t = config["min_score_trade"]

    if score >= t:
        return "TRADE"
    elif score >= t - 1:
        return "WATCH"
    else:
        return "SKIP"