from backend.configs.config import TICKER_RULES
from backend.engine.spreads.models import CreditSpread, MarketSnapshot, VolatilityMode, LongOption, DebitSpread
from backend.data.data_yahoo_option import pick_expiry, get_option_chain, get_bid_ask, get_mid
from backend.engine.spreads.enrich import enrich_trade
from backend.engine.spreads.scoring import compute_liquidity_score, compute_otm_percent
from datetime import datetime
from backend.engine.spreads.spread_type_selector import auto_select_option_type, map_regime_to_direction, \
    calculate_market_regime_v2
import json
from backend.core.logger import get_logger

logger = get_logger(__name__)

def compute_credit(short_bid, short_ask, long_bid, long_ask):

    short_mid = get_mid(short_bid, short_ask)
    long_mid  = get_mid(long_bid, long_ask)

    if short_mid is None or long_mid is None:
        return None

    return short_mid - long_mid


def compute_dte(expiry):
    exp = datetime.fromisoformat(expiry)
    today = datetime.now()
    return (exp - today).days

def compute_bidask_width_pct(s):
    # fallback: assume 3% width for liquid tickers
    return s.get("bidAskWidthPct", 3)

def pick_put_strikes(options, current_price, min_otm_pct, width):
    """
    min_otm_pct: OTM as percent points (e.g. 7.0 for 7%), NOT a decimal (0.07).
    """
    # 1. Calculate the 'Danger Zone' boundary
    # If price is 100 and min_otm is 7%, max_strike is 93
    max_strike_allowed = current_price * (1 - (min_otm_pct / 100))

    # 2. Filter for strikes that are BELOW that boundary
    valid_shorts = [opt for opt in options if opt['strike'] <= max_strike_allowed]

    if not valid_shorts:
        return None, None

    # 3. Pick the one closest to our safety boundary (best premium for the risk)
    short_strike = max(valid_shorts, key=lambda x: x['strike'])['strike']
    long_strike = short_strike - width

    return short_strike, long_strike

def pick_call_strikes(options, current_price, min_otm_pct, width):
    """
    Finds the safest Call Credit strikes based on a minimum OTM percentage.
    min_otm_pct: percent points (e.g. 7.0 for 7%), NOT a decimal (0.07).
    """
    # 1. Calculate the 'Safety Boundary'
    # If price is $210 and min_otm is 5%, min_strike must be $220.50
    min_strike_allowed = current_price * (1 + (min_otm_pct / 100))

    # 2. Filter for strikes that are ABOVE that boundary (Out-of-the-Money)
    valid_shorts = [opt for opt in options if opt['strike'] >= min_strike_allowed]

    if not valid_shorts:
        # If no strikes are safe enough, return None to trigger a SKIP
        return None, None

    # 3. Pick the 'Short' strike closest to our boundary
    # (This usually provides the highest premium for the given safety)
    short_strike = min(valid_shorts, key=lambda x: x['strike'])['strike']
    # 4. Long strike is just the short strike + width
    long_strike = short_strike + width

    return short_strike, long_strike

def get_short_delta(options, short_strike) :

    short_row = options[options["strike"] == short_strike].iloc[0]
    short_delta = float(short_row["delta"])

    return short_delta

def snap_to_strike(available_strikes, target):
    # available_strikes is a list like [330, 335, 340, ...]
    return min(available_strikes, key=lambda x: abs(x - target))


def get_strategy_label(strategy_type, option_type):
    """
    strategy_type: CREDIT / DEBIT / LONG_SINGLE
    option_type: CALL / PUT / BOTH
    """

    if strategy_type == "DEBIT":
        if option_type == "CALL":
            return "DEBIT SPREAD - BULL CALL"
        elif option_type == "PUT":
            return "DEBIT SPREAD - BEAR PUT"

    elif strategy_type == "CREDIT":
        if option_type == "PUT":
            return "CREDIT SPREAD - BULL PUT"
        elif option_type == "CALL":
            return "CREDIT SPREAD - BEAR CALL"
        elif option_type == "BOTH":
            return "CREDIT SPREAD - IRON CONDOR"

    elif strategy_type == "LONG_SINGLE":
        if option_type == "CALL":
            return "LONG CALL"
        elif option_type == "PUT":
            return "LONG PUT"

    return "UNKNOWN"


def build_option_structure(option_type, chain, ticker, expiry, short_strike, strategy_type, width=None, long_strike=None):
    """
    Unified builder for Long Options and Credit Spreads.
    """
    strategy_label = get_strategy_label(strategy_type, option_type)

    # 1. Validation: Ensure we have the necessary strikes
    if short_strike is None:
        return None

    # 2. Strategy: LONG SINGLE
    if strategy_type == "LONG_SINGLE":
        quote = get_bid_ask(chain, short_strike)
        if not quote: return None

        bid, ask = quote
        liquidity = round(compute_liquidity_score(ask, bid), 2)

        # Using keyword arguments to ensure strict dataclass mapping
        return LongOption(
            ticker=ticker,
            expiry=expiry,
            strategy_type=strategy_type,
            option_type=option_type,
            strategy_label=strategy_label,
            bid=bid,
            ask=ask,
            liquidity_score=liquidity,
            strike=short_strike,
            cost=ask # You pay the ask for a long
        )

    # 3. Strategy: CREDIT SPREAD
    if strategy_type == "CREDIT":
        if long_strike is None or width is None:
            return None

        short_quote = get_bid_ask(chain, short_strike)
        long_quote = get_bid_ask(chain, long_strike)

        if not short_quote or not long_quote:
            return None

        s_bid, s_ask = short_quote
        l_bid, l_ask = long_quote

        # For Credit: We sell the 'Short' (Bid) and buy the 'Long' (Ask)
        credit = s_bid - l_ask
        if credit <= 0 or credit >= width:
            return None

        liquidity = round(compute_liquidity_score(s_ask, s_bid), 2)

        return CreditSpread(
            ticker=ticker,
            expiry=expiry,
            strategy_type=strategy_type,
            option_type=option_type,
            strategy_label=strategy_label,
            bid=s_bid,
            ask=s_ask,
            liquidity_score=liquidity,
            short_strike=short_strike,
            long_strike=long_strike,
            width=width,
            credit=credit
        )

    # 4. Strategy: DEBIT SPREAD
    if strategy_type == "DEBIT":
        if long_strike is None or short_strike is None or width is None:
            return None

        # In a Debit Spread, we BUY the 'Long' (expensive) and SELL the 'Short' (cheap)
        long_quote = get_bid_ask(chain, long_strike)
        short_quote = get_bid_ask(chain, short_strike)

        if not long_quote or not short_quote:
            return None

        l_bid, l_ask = long_quote
        s_bid, s_ask = short_quote

        # Math for Debit: We pay the 'Ask' for long and get the 'Bid' for short
        net_cost = l_ask - s_bid

        # Hard Filter: If cost > 50% of width, the risk/reward is usually poor
        if net_cost <= 0 or net_cost >= width:
            return None

        liquidity = round(compute_liquidity_score(l_ask, l_bid), 2)

        return DebitSpread(
            ticker=ticker,
            expiry=expiry,
            strategy_type=strategy_type,
            option_type=option_type,
            strategy_label=strategy_label,
            bid=l_bid,
            ask=l_ask,
            liquidity_score=liquidity,
            long_strike=long_strike,
            short_strike=short_strike,
            width=width,
            cost=net_cost  # Note: DebitSpread uses 'cost', not 'credit'
        )
    return None

def pick_single_otm_strike(options_list, current_price, otm_percent, option_type):
    """
    otm_percent: decimal fraction (e.g. 0.05 for 5% OTM), used as 1±otm on price.
    """
    # 1. Target price calculation
    direction = 1 + otm_percent if option_type == "CALL" else 1 - otm_percent
    target_price = current_price * direction

    valid_options = []

    for opt in options_list:
        # 2. Safety Check: If opt is a string, convert to a basic dict
        if isinstance(opt, str):
            try:
                strike_val = float(opt)
                # If it's just a string, we assume it's valid but have no bid/ask data
                valid_options.append({'strike': strike_val, 'bid': 1.0, 'ask': 1.0})
            except ValueError:
                continue
        # 3. If it's already a dict, ensure it has the 'strike' key
        elif isinstance(opt, dict) and 'strike' in opt:
            valid_options.append(opt)

    if not valid_options:
        return None

    # 4. Find the closest strike to our math target
    best_option = min(valid_options, key=lambda x: abs(x['strike'] - target_price))

    return best_option['strike']

def build_credit_spread(ticker, snapshot, weeks_out,  mode: VolatilityMode, width=None):
    try:

        # 1. Get Ticker-Specific Rules
        rules = TICKER_RULES.get(ticker, TICKER_RULES["DEFAULT"])
        otm_threshold_spread = rules.get("min_otm_spread", 7.0)
        otm_threshold_long = rules.get("max_otm_long", 5.0)
        # Long single-leg picker uses decimal OTM (e.g. 0.05 for 5%).
        target_long_dec = otm_threshold_long / 100
        # Credit spread pickers take whole % (e.g. 7.0) and divide by 100 internally.


        logger.info(json.dumps({
            "module": "build_spread",
            "ticker": ticker,
            "closes": snapshot.price,
            "mode" : mode
        }))

        #Get Expiry Week
        expiry = pick_expiry(ticker, weeks_out)
        #Calls and puts
        calls, puts = get_option_chain(ticker, expiry)

        #Select Option type
        strategy_type, option_type \
            = auto_select_option_type(snapshot, mode)

        logger.info(json.dumps({
            "module": "build_spread",
            "strategy_type": strategy_type,
            "ticker": ticker,
            "closes": snapshot.price,
            "mode" : mode
        }))

        results = []

        # Define which strike-picking logic to use based on strategy
        is_long = strategy_type == "LONG_SINGLE"

        # Convert the DataFrame to a list of dictionaries before passing it
        puts_dicts = puts.to_dict('records')
        calls_dicts = calls.to_dict('records')

        #The Flow of Data
        # Rules Engine: Tells you "I want a trade roughly 3% OTM."
        # Picker: Finds the actual strike (e.g., $170) that is closest to that 3%.
        # Constructor: Builds the LongOption(strike=170).
        # Enricher: Calculates the Actual OTM (e.g., 2.94%) based on that $170 strike.

        # --- PUT LOGIC ---
        if option_type in ("PUT", "BOTH"):
            if is_long:
                # Pick a single OTM Put strike (e.g., 2-5% OTM)
                target_strike = pick_single_otm_strike(puts_dicts, snapshot.price, target_long_dec, "PUT")
                option = build_option_structure("PUT", puts, ticker, expiry, target_strike, strategy_type)
            else:
                #  Spread logic
                put_short, put_long = pick_put_strikes(
                    puts_dicts, snapshot.price, otm_threshold_spread, width
                )
                option = build_option_structure("PUT", puts, ticker, expiry, put_short, strategy_type, width, put_long)

            if option:
                # Enriches either a CreditSpread or LongOption object
                enriched = enrich_trade(option, snapshot.price, snapshot.iv_rank, snapshot.iv)
                results.append(enriched)

        # --- CALL LOGIC ---
        if option_type in ("CALL", "BOTH"):
            if is_long:
                target_strike = pick_single_otm_strike(calls_dicts, snapshot.price, target_long_dec, "CALL")
                option = build_option_structure("CALL", calls, ticker, expiry, target_strike, strategy_type)
            else:
                call_short, call_long = pick_call_strikes(
                    calls_dicts, snapshot.price, otm_threshold_spread, width
                )
                option = build_option_structure("CALL", calls, ticker, expiry, call_short, strategy_type, width, call_long)

            if option:
                enriched = enrich_trade(option, snapshot.price, snapshot.iv_rank, snapshot.iv)
                results.append(enriched)

    except Exception as e:
        logger.error(json.dumps({
            "module": "build_credit_spread_ERR",
            "ticker": ticker,
            "error": str(e)
        }))
        return None, None, None

    return results

