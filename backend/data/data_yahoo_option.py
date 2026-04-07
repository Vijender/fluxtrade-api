import yfinance as yf
from datetime import datetime, date, timedelta
from typing import List, Literal, Optional, Tuple
import logging
import json
from backend.core.logger import get_logger
logger = get_logger(__name__)

def get_option_chain_yf(ticker, expiry):
     return get_option_chain(ticker, expiry)

def get_option_chain(ticker, expiry):
    t = yf.Ticker(ticker)
    chain = t.option_chain(expiry)
    return chain.calls, chain.puts

def get_mid(bid, ask):
    if bid is None or ask is None:
        return None
    return (bid + ask) / 2

def get_bid_ask(chain, strike):
    row = chain[chain['strike'] == strike]
    if row.empty :
        return None
    bid = row['bid'].iloc[0]
    ask = row['ask'].iloc[0]

    if bid == 0 and ask == 0:
        return None
    return bid, ask

def pick_expiry_yf(ticker, weeks_out) :
    return pick_expiry(ticker, weeks_out)

def pick_expiry(ticker, weeks_out) :
    try:
        t=yf.Ticker(ticker)
        expirations = t.options
        target_date = datetime.today() + timedelta(weeks=weeks_out)

        # Convert String to Date Time
        exp_dates = [datetime.strptime(e, "%Y-%m-%d") for e in expirations]

        # Pick the expiry closest to target_date
        best = min(exp_dates, key=lambda d: abs(d - target_date))
        logger.info(json.dumps({
            "module": "yahoo options",
            "ticker": ticker,
            "best": str(best.strftime("%Y-%m-%d"))
        }))
    except Exception as e:
        logger.error(json.dumps({
            "module": "yahoo options",
            "ticker": ticker,
            "error": str(e)
        }))
        return None

    return best.strftime("%Y-%m-%d")

def get_earnings_date(ticker: str) -> date | None:
    try:
        data = yf.Ticker(ticker)
        ed = data.get_earnings_dates()
        if ed is not None and not ed.empty:
            # first row, first column
            return ed.index[0].date()
        # 2. Fallback to old API
        cal = data.calendar
        if isinstance(cal, dict) and "Earnings Date" in cal:
            val = cal["Earnings Date"]
            if isinstance(val, list) and len(val) > 0:
                return val[0]
            if isinstance(val, datetime):
                return val.date()

        # 3. No earnings found
        return None
    except Exception:
        return None