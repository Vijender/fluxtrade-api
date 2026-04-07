from data.data_yahoo import get_snapshot_from_yahoo
from configs.config import TICKER_RULES, PRESELECTED_TICKERS
from engine.spreads.builder import build_credit_spread
from engine.spreads.models import VolatilityMode, CreditSpread, DebitSpread, LongOption
from engine.spreads.scoring import compute_ai_score, compute_overall_score, compute_color, grade_from_score
from engine.spreads.rules import evaluate_trade, final_decision
from core.logger import get_logger

logger = get_logger(__name__)

def get_credit_spread_category(option_type):
    if option_type == "PUT":
        return "Bull Put Credit"
    elif option_type == "CALL":
        return "Bear Call Credit"
    else:
        return "Unknown"


def get_weeks_out(ticker: str):
    rules = TICKER_RULES.get(ticker, {})
    return rules.get("weeks_out", TICKER_RULES["DEFAULT"]["weeks_out"])


def build_expiry_comparison_for_ticker(ticker: str, mode: VolatilityMode):
    from db.scan_cache import get_cached_scan, set_cached_scan

    cached = get_cached_scan(ticker, mode)
    if cached is not None:
        return cached

    # Snapshot
    snapshot = get_snapshot_from_yahoo(ticker)
    # 2. Load rules ONCE
    weeks_out_list = get_weeks_out(ticker)

    rows = []
    for w in weeks_out_list:
        # compute expiry, strikes, credit, etc.
        options = build_credit_spread(
            ticker=ticker,
            snapshot=snapshot,
            weeks_out=w,
            mode=mode,
            width=5
        )
        if options is None:
            print("Could not build option (missing strikes or credit).")
            continue

        for option in options:
            # 1. Determine Strategy Type for UI display
            if option is None:
                continue

            is_credit = isinstance(option, CreditSpread)
            is_debit = isinstance(option, DebitSpread)
            is_long = isinstance(option, LongOption)

            #2. Strategy-Specific Extraction
            #use 0 for N.A missing Spread values in Long Positions
            short_strike = getattr(option, 'short_strike', getattr(option, 'strike', 0))
            long_strike = getattr(option, 'long_strike', None)

            # Safe way to handle both types:
            if is_credit or is_debit:
                if is_credit:
                    price_label = "Credit"
                    price_value = getattr(option, 'credit', 0)
                else:
                    # DEBIT uses 'cost', not 'credit'
                    price_label = "Debit"
                    price_value = getattr(option, 'cost', 0)
            else:
                price_label = "Cost"
                price_value = getattr(option, 'cost', 0)

            #3 Shared Metrics
            overall_score = compute_overall_score(option)
            ai_score = compute_ai_score(option)
            decision, reasons = evaluate_trade(snapshot, option, overall_score, ai_score)
            trade_decision  = final_decision(overall_score, ai_score, mode)

            rows.append({
                "strategy_type": option.strategy_type,
                "option_type": option.option_type,
                "strategy_label": option.strategy_label,
                "expiry": option.expiry,
                "weeks_out": w,
                "strike_label":  str(short_strike) if is_long else f"{short_strike}/{long_strike}" ,
                "short_strike": short_strike,
                "long_strike": long_strike,
                "otm_percent": round(option.otm_percent, 2),
                "price_label": price_label,
                "price_value": price_value,
                "max_loss": option.max_loss,
                "risk_reward": getattr(option, 'risk_reward', None),
                "liquidity_score": option.liquidity_score,
                "overall_score": overall_score,
                "decision": trade_decision,
                "color": compute_color(decision),
                "grade": grade_from_score(overall_score),
                "reasons": ", ".join(reasons) if reasons else "All rules passed"
            })

    if not rows:
        return None

    # 1. Filter for Tradable picks
    tradable = [r for r in rows if r.get("decision") == "TRADE"]

    # 2. Pick the champion based on overall_score
    if tradable:
        best = max(tradable, key=lambda r: r["overall_score"])
    else:
        # Fallback to the highest score even if it's a "SKIP" or "WATCH"
        best = max(rows, key=lambda r: r["overall_score"])

    # 3. Construct the response for the UI
    result = {
        "ticker": ticker,
        "price": snapshot.price,
        "weeks_out": weeks_out_list,
        "comparison_table": rows,  # The full list we appended earlier
        "best_expiry": {
            "strategy_type": best.get("strategy_type"),
            "option_type": best["option_type"],
            "strategy_label": best["strategy_label"],
            "expiry": best["expiry"],
            "weeks_out": best["weeks_out"],
            "strike_label": best.get("strike_label"), # e.g., "180/185" or "170"
            "decision": best["decision"],
            "overall_score": best["overall_score"],
            "otm_percent": best["otm_percent"],
            "risk_reward": best.get("risk_reward"), # Will be None for Longs
            "price_label": best.get("price_label"), # "Credit" or "Cost"
            "price_value": best.get("price_value"),
            "grade": best["grade"],
            "reasons": best["reasons"],
            "color": best.get("color")
        },
        "preselected_tickers": PRESELECTED_TICKERS,
    }
    set_cached_scan(ticker, mode, result)
    return result

def pick_best(rows):
    # Priority 1: TRADE
    trade = [r for r in rows if r["decision"] == "TRADE"]
    if trade:
        return max(trade, key=lambda r: r["overall_score"])

    # Priority 2: WATCH
    watch = [r for r in rows if r["decision"] == "WATCH"]
    if watch:
        return max(watch, key=lambda r: r["overall_score"])

    # Priority 3: SKIP (fallback)
    return max(rows, key=lambda r: r["overall_score"])
