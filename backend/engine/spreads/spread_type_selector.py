from backend.engine.spreads.models import MarketSnapshot, VolatilityMode
import json
from backend.core.logger import get_logger

logger = get_logger(__name__)

def get_iv_threshold(mode):
    # Dynamic thresholds for Credit Spreads (selling)
    thresholds = {
        "AGGRESSIVE": 35,  # Sell more often, even if premium isn't at peak
        "BALANCED": 45,    # The standard "middle ground"
        "DEFENSIVE": 55    # Only sell when fear is at extreme levels (Best for War)
    }
    return thresholds.get(mode, 45)

def calculate_market_regime(snapshot: MarketSnapshot):
    vix_val = snapshot.vix
    current_price = snapshot.price
    sma_200 = snapshot.sma_200
    # 3. Logic-Based Assignment
    if vix_val > 30:
        return "CRISIS"   # High War Volatility - Maximum Caution
    elif current_price < sma_200:
        return "BEARISH"  # Long-term Downtrend
    elif current_price > sma_200 and vix_val < 20:
        return "BULLISH"  # Healthy Growth
    else:
        return "NEUTRAL"  # Sideways / Uncertain

def calculate_market_regime_v2(snapshot):
    vix = snapshot.vix
    price = snapshot.price
    sma_200 = snapshot.sma_200
    sma_50 = snapshot.sma_50

    # --- Trend ---
    trend = "BULLISH" if price > sma_200 else "BEARISH"

    # --- Momentum ---
    momentum = "UP" if sma_50 > sma_200 else "DOWN"

    # --- Volatility ---
    if vix > 30:
        vol = "EXTREME"
    elif vix > 22:
        vol = "HIGH"
    elif vix < 14:
        vol = "LOW"
    else:
        vol = "NORMAL"

    # --- Final Regime ---
    if vol == "EXTREME":
        return "CRISIS"

    if trend == "BULLISH" and momentum == "UP":
        if vol == "LOW":
            return "STRONG_BULL"
        else:
            return "BULL_VOLATILE"

    if trend == "BEARISH" and momentum == "DOWN":
        if vol in ["HIGH", "EXTREME"]:
            return "STRONG_BEAR"
        else:
            return "BEAR"

    return "CHOPPY"

def map_regime_to_direction(regime):
    if regime in ["STRONG_BULL"]:
        return "BULLISH"
    elif regime in ["STRONG_BEAR"]:
        return "BEARISH"
    elif regime in ["BULL_VOLATILE"]:
        return "BULLISH"
    elif regime in ["BEAR"]:
        return "BEARISH"
    else:
        return "NEUTRAL"

def auto_select_option_type(snapshot: MarketSnapshot, mode: VolatilityMode):
    """
    Returns (Strategy_Type, Option_Type)
    Strategy_Type: 'CREDIT' (Sell) or 'DEBIT' (Buy)
    Option_Type: 'CALL' or 'PUT'
    """
    iv_rank = snapshot.iv_rank
    regime = calculate_market_regime_v2(snapshot)
    market_direction = map_regime_to_direction(regime)

    threshold = get_iv_threshold(mode)

    logger.info(json.dumps({
        "module": "auto_select_option_type",
        "mode": mode,
        "iv_rank": snapshot.iv_rank,
        "threshold": threshold
    }))

    if iv_rank is None or iv_rank <= 5:
        logger.warning("IV Rank too low / invalid")

        if market_direction == "BEARISH":
            return "DEBIT", "PUT"
        elif market_direction == "BULLISH":
            return "DEBIT", "CALL"
        else:
            return "CREDIT", "BOTH"

    # HIGH VOLATILITY: Sell Premium (Credit Spreads)
    if iv_rank > threshold:
        # If you are bearish, sell Calls (Bear Call Spread)
        if market_direction == "BEARISH":
            return "CREDIT", "CALL"
        # If you are bullish, sell Puts (Bull Put Spread)
        else:
            return "CREDIT", "PUT"
    # ULTRA-LOW VOLATILITY: Buy Naked Options (High Vega Exposure)
    # 🟢 TRUE LOW IV (valid)
    elif iv_rank < 15:
        if market_direction == "BEARISH":
            # Buy a single Put (No spread) to capture maximum downside + IV spike
            return "LONG_SINGLE", "PUT"
        else:
            # Buy a single Call for a potential breakout
            return "LONG_SINGLE", "CALL"
    # LOW VOLATILITY: Buy Premium (Debit Spreads / Long Options)
    # 🟡 MODERATE LOW IV
    elif iv_rank < 25:
        # build a BEAR PUT SPREAD (Debit)
        if market_direction == "BEARISH":
            return "DEBIT", "PUT"
        #  build a BULL CALL SPREAD (Debit)
        else:
            return "DEBIT", "CALL"

    # NEUTRAL / MID-IV: Allow both for Iron Condors or Diagonals
    # ⚪ MID IV
    else:
        # MIX zone → allow debit spreads
        if market_direction == "BEARISH":
            return "DEBIT", "PUT"
        elif market_direction == "BULLISH":
            return "DEBIT", "CALL"
        else:
            return "CREDIT", "BOTH"
