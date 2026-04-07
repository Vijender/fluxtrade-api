"""User data: watchlist, strategies, saved trades (ideas), alert history — Postgres tables."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Header, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import delete, select

from api.auth_util import open_authenticated_session
from db.models import Alert, Strategy, Trade, Watchlist

router = APIRouter(tags=["user-data"])


class SymbolsBody(BaseModel):
    symbols: list[str] = Field(..., description='Ticker symbols, e.g. ["AAPL", "MSFT"]')


class StrategyCreateBody(BaseModel):
    name: str = Field(..., min_length=1, max_length=256)
    strategy_type: str = Field(default="", max_length=128)
    option_type: str = Field(default="", max_length=16)
    params: dict | None = None


class StrategyPatchBody(BaseModel):
    name: str | None = Field(default=None, max_length=256)
    strategy_type: str | None = Field(default=None, max_length=128)
    option_type: str | None = Field(default=None, max_length=16)
    params: dict | None = None


class TradeCreateBody(BaseModel):
    ticker: str = Field(..., min_length=1, max_length=32)
    title: str = Field(default="", max_length=512)
    idea: dict = Field(..., description="Saved scanner row or custom JSON")


class TradePatchBody(BaseModel):
    ticker: str | None = Field(default=None, max_length=32)
    title: str | None = Field(default=None, max_length=512)
    idea: dict | None = None


def _upper_sym(s: str) -> str:
    return str(s).strip().upper()


def _strategy_out(r: Strategy) -> dict:
    return {
        "id": str(r.id),
        "name": r.name,
        "strategy_type": r.strategy_type,
        "option_type": r.option_type,
        "params": r.params,
        "created_at": r.created_at.isoformat() if r.created_at else None,
        "updated_at": r.updated_at.isoformat() if r.updated_at else None,
    }


def _trade_out(r: Trade) -> dict:
    return {
        "id": str(r.id),
        "ticker": r.ticker.upper(),
        "title": r.title or "",
        "idea": r.idea,
        "created_at": r.created_at.isoformat() if r.created_at else None,
        "updated_at": r.updated_at.isoformat() if r.updated_at else None,
    }


@router.get("/user/watchlist")
def get_watchlist(authorization: str | None = Header(default=None)) -> dict:
    user, session = open_authenticated_session(authorization)
    try:
        rows = session.scalars(
            select(Watchlist)
            .where(Watchlist.user_id == user.id)
            .order_by(Watchlist.sort_order, Watchlist.symbol)
        ).all()
        return {"email": user.email, "symbols": [r.symbol.upper() for r in rows]}
    finally:
        session.close()


@router.put("/user/watchlist")
def put_watchlist(
    body: SymbolsBody,
    authorization: str | None = Header(default=None),
) -> dict:
    user, session = open_authenticated_session(authorization)
    try:
        session.execute(delete(Watchlist).where(Watchlist.user_id == user.id))
        cleaned: list[str] = []
        for raw in body.symbols:
            s = _upper_sym(raw)
            if s and s not in cleaned:
                cleaned.append(s)
        for i, sym in enumerate(cleaned):
            session.add(Watchlist(user_id=user.id, symbol=sym, sort_order=i))
        session.commit()
        return {"ok": True, "email": user.email, "symbols": cleaned}
    finally:
        session.close()


@router.get("/user/strategies")
def list_strategies(authorization: str | None = Header(default=None)) -> dict:
    user, session = open_authenticated_session(authorization)
    try:
        rows = session.scalars(
            select(Strategy)
            .where(Strategy.user_id == user.id)
            .order_by(Strategy.updated_at.desc())
        ).all()
        return {"email": user.email, "strategies": [_strategy_out(r) for r in rows]}
    finally:
        session.close()


@router.post("/user/strategies")
def create_strategy(
    body: StrategyCreateBody,
    authorization: str | None = Header(default=None),
) -> dict:
    user, session = open_authenticated_session(authorization)
    try:
        row = Strategy(
            user_id=user.id,
            name=body.name.strip(),
            strategy_type=(body.strategy_type or "").strip(),
            option_type=(body.option_type or "").strip(),
            params=body.params,
        )
        session.add(row)
        session.commit()
        session.refresh(row)
        return {"ok": True, "email": user.email, "strategy": _strategy_out(row)}
    finally:
        session.close()


@router.patch("/user/strategies/{strategy_id}")
def patch_strategy(
    strategy_id: uuid.UUID,
    body: StrategyPatchBody,
    authorization: str | None = Header(default=None),
) -> dict:
    user, session = open_authenticated_session(authorization)
    try:
        row = session.get(Strategy, strategy_id)
        if not row or row.user_id != user.id:
            raise HTTPException(status_code=404, detail="Strategy not found")
        if body.name is not None:
            row.name = body.name.strip()
        if body.strategy_type is not None:
            row.strategy_type = body.strategy_type.strip()
        if body.option_type is not None:
            row.option_type = body.option_type.strip()
        if body.params is not None:
            row.params = body.params
        session.add(row)
        session.commit()
        session.refresh(row)
        return {"ok": True, "email": user.email, "strategy": _strategy_out(row)}
    finally:
        session.close()


@router.delete("/user/strategies/{strategy_id}")
def delete_strategy(
    strategy_id: uuid.UUID,
    authorization: str | None = Header(default=None),
) -> dict:
    user, session = open_authenticated_session(authorization)
    try:
        row = session.get(Strategy, strategy_id)
        if not row or row.user_id != user.id:
            raise HTTPException(status_code=404, detail="Strategy not found")
        session.delete(row)
        session.commit()
        return {"ok": True, "email": user.email}
    finally:
        session.close()


@router.get("/user/trades")
def list_trades(authorization: str | None = Header(default=None)) -> dict:
    user, session = open_authenticated_session(authorization)
    try:
        rows = session.scalars(
            select(Trade)
            .where(Trade.user_id == user.id)
            .order_by(Trade.updated_at.desc())
        ).all()
        return {"email": user.email, "trades": [_trade_out(r) for r in rows]}
    finally:
        session.close()


@router.post("/user/trades")
def create_trade(
    body: TradeCreateBody,
    authorization: str | None = Header(default=None),
) -> dict:
    user, session = open_authenticated_session(authorization)
    try:
        row = Trade(
            user_id=user.id,
            ticker=_upper_sym(body.ticker),
            title=(body.title or "").strip(),
            idea=body.idea,
        )
        session.add(row)
        session.commit()
        session.refresh(row)
        return {"ok": True, "email": user.email, "trade": _trade_out(row)}
    finally:
        session.close()


@router.patch("/user/trades/{trade_id}")
def patch_trade(
    trade_id: uuid.UUID,
    body: TradePatchBody,
    authorization: str | None = Header(default=None),
) -> dict:
    user, session = open_authenticated_session(authorization)
    try:
        row = session.get(Trade, trade_id)
        if not row or row.user_id != user.id:
            raise HTTPException(status_code=404, detail="Trade not found")
        if body.ticker is not None:
            row.ticker = _upper_sym(body.ticker)
        if body.title is not None:
            row.title = body.title.strip()
        if body.idea is not None:
            row.idea = body.idea
        session.add(row)
        session.commit()
        session.refresh(row)
        return {"ok": True, "email": user.email, "trade": _trade_out(row)}
    finally:
        session.close()


@router.delete("/user/trades/{trade_id}")
def delete_trade(
    trade_id: uuid.UUID,
    authorization: str | None = Header(default=None),
) -> dict:
    user, session = open_authenticated_session(authorization)
    try:
        row = session.get(Trade, trade_id)
        if not row or row.user_id != user.id:
            raise HTTPException(status_code=404, detail="Trade not found")
        session.delete(row)
        session.commit()
        return {"ok": True, "email": user.email}
    finally:
        session.close()


@router.get("/user/alerts")
def get_alert_history(
    authorization: str | None = Header(default=None),
    limit: int = Query(50, ge=1, le=200),
) -> dict:
    user, session = open_authenticated_session(authorization)
    try:
        rows = session.scalars(
            select(Alert)
            .where(Alert.user_id == user.id)
            .order_by(Alert.created_at.desc())
            .limit(limit)
        ).all()
        return {
            "email": user.email,
            "batches": [
                {
                    "id": str(b.id),
                    "created_at": b.created_at.isoformat() if b.created_at else None,
                    "run_at_iso": b.run_at_iso,
                    "timezone": b.timezone,
                    "run_key": b.run_key,
                    "tickers_scanned": b.tickers_scanned,
                    "trade_count": b.trade_count,
                    "new_trade_count": b.new_trade_count,
                    "trades": b.trades,
                    "new_trades": b.new_trades,
                }
                for b in rows
            ],
        }
    finally:
        session.close()
