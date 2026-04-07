from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    email: Mapped[str] = mapped_column(String(320), unique=True, nullable=False, index=True)
    email_verified: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    password_hash: Mapped[str | None] = mapped_column(String(255), nullable=True)

    smtp_host: Mapped[str] = mapped_column(String(512), default="")
    smtp_port: Mapped[int] = mapped_column(Integer, default=587)
    smtp_user: Mapped[str] = mapped_column(String(512), default="")
    smtp_password_enc: Mapped[str] = mapped_column(Text, default="")
    smtp_from: Mapped[str] = mapped_column(String(512), default="")

    alerts_email_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    alert_trade_sent_signatures: Mapped[list | None] = mapped_column(JSONB, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    watchlist_rows: Mapped[list["Watchlist"]] = relationship(
        "Watchlist", back_populates="user", cascade="all, delete-orphan"
    )
    strategies: Mapped[list["Strategy"]] = relationship(
        "Strategy", back_populates="user", cascade="all, delete-orphan"
    )
    saved_trades: Mapped[list["Trade"]] = relationship(
        "Trade", back_populates="user", cascade="all, delete-orphan"
    )
    alerts: Mapped[list["Alert"]] = relationship(
        "Alert", back_populates="user", cascade="all, delete-orphan"
    )


class Watchlist(Base):
    __tablename__ = "watchlist"
    __table_args__ = (UniqueConstraint("user_id", "symbol", name="uq_watchlist_user_symbol"),)

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    symbol: Mapped[str] = mapped_column(String(32), nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    user: Mapped["User"] = relationship("User", back_populates="watchlist_rows")


class Strategy(Base):
    """User-saved strategy template (type + optional params)."""

    __tablename__ = "strategies"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(256), nullable=False)
    strategy_type: Mapped[str] = mapped_column(String(128), default="")
    option_type: Mapped[str] = mapped_column(String(16), default="")
    params: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    user: Mapped["User"] = relationship("User", back_populates="strategies")


class Trade(Base):
    """Saved trade idea (scanner row snapshot or custom payload)."""

    __tablename__ = "trades"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    ticker: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(512), default="")
    idea: Mapped[dict] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    user: Mapped["User"] = relationship("User", back_populates="saved_trades")


class Alert(Base):
    """One scheduled alert batch run per user."""

    __tablename__ = "alerts"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    run_key: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    run_at_iso: Mapped[str] = mapped_column(String(64), nullable=False)
    timezone: Mapped[str] = mapped_column(String(64), nullable=False)
    tickers_scanned: Mapped[list] = mapped_column(JSONB, nullable=False)
    trades: Mapped[list] = mapped_column(JSONB, nullable=False)
    new_trades: Mapped[list] = mapped_column(JSONB, nullable=False)
    trade_count: Mapped[int] = mapped_column(Integer, default=0)
    new_trade_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )

    user: Mapped["User"] = relationship("User", back_populates="alerts")


class ScanResult(Base):
    """Optional cache for full-symbol scan payloads (shared, not per-user)."""

    __tablename__ = "scan_results"
    __table_args__ = (UniqueConstraint("ticker", "mode", name="uq_scan_results_ticker_mode"),)

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    ticker: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    mode: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
