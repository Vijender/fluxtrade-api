import json
from typing import Optional

from fastapi import APIRouter, Depends, Query

from configs.config import PRESELECTED_TICKERS
from engine.spreads.models import VolatilityMode, common_params

# Same volatility modes as the alert batch (Defensive / Balanced / Aggressive).
_SPREAD_SCAN_MODES: tuple[VolatilityMode, ...] = (
    VolatilityMode.DEFENSIVE,
    VolatilityMode.BALANCED,
    VolatilityMode.AGGRESSIVE,
)
from engine.spreads.scanner import build_expiry_comparison_for_ticker
from core.logger import get_logger

logger = get_logger(__name__)

router = APIRouter()


@router.get("/spreads/{ticker}")
def get_spread(ticker: str, params: dict = Depends(common_params)):
    result = build_expiry_comparison_for_ticker(ticker.upper(), params["mode"])
    logger.info(
        json.dumps({"module": "routes/spreads", "path": "by_ticker", "mode": str(params["mode"])})
    )
    return result


@router.get("/spreads")
def get_all_spreads(
    tickers: Optional[str] = Query(
        default=None,
        description="Comma-separated symbols; omit to use configured default universe",
    ),
    params: dict = Depends(common_params),
):
    mode = params["mode"]
    logger.info(json.dumps({"module": "routes/spreads", "path": "list", "mode": str(mode)}))

    if tickers and tickers.strip():
        ticker_list = [t.strip().upper() for t in tickers.split(",") if t.strip()]
    else:
        ticker_list = sorted(PRESELECTED_TICKERS)

    out = []
    for t in ticker_list:
        result = build_expiry_comparison_for_ticker(t, mode)
        if result is not None:
            out.append(result)
    return {"tickers": out}


@router.get("/spreads/all/modes")
async def scan_all_modes():
    """
    Scan the preselected universe under Defensive, Balanced, and Aggressive modes.
    Response shape matches ``build_expiry_comparison_for_ticker`` (ticker, best_expiry, …).
    """
    results = []
    for mode in _SPREAD_SCAN_MODES:
        logger.info(json.dumps({"module": "routes/spreads_all", "mode": str(mode)}))
        for t in sorted(PRESELECTED_TICKERS):
            res = build_expiry_comparison_for_ticker(t, mode)
            if res:
                be = res.get("best_expiry") or {}
                results.append(
                    {
                        "mode": mode.value,
                        "ticker": res.get("ticker"),
                        "price": res.get("price"),
                        "best_expiry": be,
                        "comparison_table": res.get("comparison_table"),
                    }
                )
    return {"results": results}
