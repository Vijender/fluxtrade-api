import numpy as np
import yfinance as yf
from backend.engine.spreads.models import MarketSnapshot
import pandas as pd
from backend.core.logger import get_logger

logger = get_logger(__name__)

# When Yahoo returns no VIX series (rate limits, symbol quirks), use a neutral default
# so the scanner keeps working; regime logic in spread_type_selector still runs.
_VIX_FALLBACK = 20.0


def _fetch_vix_close() -> float:
    """Best-effort VIX level; never raises."""
    for symbol in ("^VIX", "VIX"):
        try:
            hist = yf.Ticker(symbol).history(period="5d", interval="1d")
            if hist is None or hist.empty or "Close" not in hist.columns:
                continue
            close = hist["Close"].dropna()
            if len(close) == 0:
                continue
            val = float(close.iloc[-1])
            if val > 0:
                return val
        except Exception as e:
            logger.warning("VIX fetch failed for %s: %s", symbol, e)
    logger.warning(
        "VIX unavailable from Yahoo; using fallback %.1f (scanner continues)",
        _VIX_FALLBACK,
    )
    return _VIX_FALLBACK


def extract_earnings_date(earnings):
    # Case 1: DataFrame
    if isinstance(earnings, pd.DataFrame):
        if "Earnings Date" in earnings.index:
            return earnings.loc["Earnings Date"][0]

    # Case 2: Dictionary
    if isinstance(earnings, dict):
        if "Earnings Date" in earnings:
            val = earnings["Earnings Date"]
            # Sometimes it's a list
            if isinstance(val, list) and len(val) > 0:
                return val[0]
            return val

    # Fallback
    return None


def compute_iv_rank(ticker):
    """
    Compute IV Rank using Yahoo Finance's implied volatility fields:
    - Current ATM IV
    - 52-week IV high
    - 52-week IV low
    """
    try:
        tk = yf.Ticker(ticker)
        expiry = tk.options[0]  # nearest expiry
        chain = tk.option_chain(expiry)

        calls = chain.calls
        puts = chain.puts

        # ATM strike
        price = tk.history(period="1d")["Close"].iloc[-1]
        calls["diff"] = abs(calls["strike"] - price)
        puts["diff"] = abs(puts["strike"] - price)

        atm_call_iv = calls.sort_values("diff").iloc[0]["impliedVolatility"]
        atm_put_iv = puts.sort_values("diff").iloc[0]["impliedVolatility"]

        hist = yf.download(ticker, period="1y", interval="1d")
        hist["returns"] = hist["Close"].pct_change()
        hv_series = hist["returns"].rolling(20).std() * np.sqrt(252)
        hv_series = hv_series.dropna()

        iv_today = float((atm_call_iv + atm_put_iv) / 2)

        hv_min = hv_series.min()
        hv_max = hv_series.max()

        if hv_max == hv_min:
            iv_rank = 0
        else:
            iv_rank = (iv_today - hv_min) / (hv_max - hv_min) * 100


        iv_rank = max(0, min(100, iv_rank))
        return iv_today, iv_rank

    except Exception as e:
        logger.warning("IV Rank error for %s: %s", ticker, e)
        return None


def get_snapshot_from_yahoo(ticker: str) -> MarketSnapshot:
    # 1. Fetch historical data (use 1y or 2y to ensure 200 days are available)
    data = yf.Ticker(ticker)
    df  = data.history(period="2y", interval="1d")
    vix_val = _fetch_vix_close()

    price = data.history_metadata["regularMarketPrice"]
    prev_price = data.history_metadata["chartPreviousClose"]
    today_move_pct = (price - prev_price) / prev_price * 100

    # 2. Calculate the 200-day Simple Moving Average
    # 'window=200' tells pandas to look back 200 rows
    df['SMA200'] = df['Close'].rolling(window=200).mean()
    df['SMA50'] = df['Close'].rolling(window=50).mean()

    # 3. Return the most recent value
    current_sma200 = df['SMA200'].iloc[-1]
    current_sma50 = df['SMA50'].iloc[-1]

    # Earnings date

    info = data.info
    skip_earnings = False
    if info.get("quoteType") == "ETF":
        skip_earnings = True

    days_to_earnings = 999
    if not skip_earnings:
        earnings = data.calendar
        earnings_date = extract_earnings_date(earnings)
        if earnings_date:
            days_to_earnings = (earnings_date - df.index[-1].date()).days

    # Get IV rank and IV val (optional chain data)
    iv_pair = compute_iv_rank(ticker)
    if iv_pair is None:
        iv_today, iv_rank = 0.25, 50.0
    else:
        iv_today, iv_rank = iv_pair

    return MarketSnapshot(
        ticker=ticker,
        price=round(price, 2),
        days_to_earnings=int(days_to_earnings),
        today_move_pct=float(today_move_pct),
        iv=round(iv_today, 2),
        iv_rank=round(iv_rank, 2),
        sma_200=round(current_sma200, 2),
        sma_50=round(current_sma50, 2),
        vix=float(vix_val),
    )