"""
Scheduled alert batch: scan each user's alert symbols (or watchlist fallback)
across **Defensive, Balanced, and Aggressive** modes, keep **TRADE** rows only,
merge duplicates by stable signature, persist to Postgres ``alerts``,
email **only new** TRADE rows. Old batch rows are purged per retention (2–5 days).
"""

from __future__ import annotations

import math
import os
import time
import uuid
from datetime import datetime, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Any
import smtplib
from zoneinfo import ZoneInfo

from core.logger import get_logger
from core.settings import database_url
from engine.spreads.models import VolatilityMode
from engine.spreads.scanner import build_expiry_comparison_for_ticker

logger = get_logger(__name__)

PST = "America/Los_Angeles"


def _within_alert_window_la(now: datetime) -> bool:
    """
    Monday through Sunday, 5:00 AM through 11:59 PM local (America/Los_Angeles).
    Every day before 5:00 AM is out (hourly jobs use hours 5–23 inclusive).
    """
    return now.hour >= 5


# Cap stored email-dedupe signatures per user (oldest dropped first if over limit).
_ALERT_SENT_SIGNATURES_MAX = 6000

# All scanner risk modes for alert discovery (not Balanced-only).
_ALERT_VOLATILITY_MODES: tuple[VolatilityMode, ...] = (
    VolatilityMode.DEFENSIVE,
    VolatilityMode.BALANCED,
    VolatilityMode.AGGRESSIVE,
)

# Last return payload from run_all_users_alert_batch (for GET / diagnostics).
LAST_ALERT_BATCH_RESULT: dict[str, Any] = {}


def _record_batch_result(payload: dict[str, Any]) -> dict[str, Any]:
    global LAST_ALERT_BATCH_RESULT
    LAST_ALERT_BATCH_RESULT = {
        **payload,
        "recordedAtUtc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    return payload


def trade_signature(row: dict[str, Any]) -> str:
    """Stable id for a TRADE row so we never email the same setup twice."""
    def _num(v: Any) -> str:
        if v is None:
            return ""
        try:
            return str(round(float(v), 6))
        except (TypeError, ValueError):
            return str(v)

    parts = [
        str(row.get("ticker", "")).upper(),
        str(row.get("strategy_label") or row.get("strategy_type") or ""),
        str(row.get("option_type", "")),
        str(row.get("expiry", "")),
        str(row.get("weeks_out", "")),
        _num(row.get("short_strike")),
        _num(row.get("long_strike")),
        str(row.get("strike_label") or ""),
    ]
    return "|".join(parts)


def _sanitize(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): _sanitize(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_sanitize(v) for v in value]
    if isinstance(value, (int, str, bool)) or value is None:
        return value
    if isinstance(value, float):
        if math.isnan(value) or math.isinf(value):
            return None
        return value
    if hasattr(value, "item"):
        try:
            return float(value.item())
        except Exception:
            return str(value)
    return value


def collect_trade_rows(
    ticker: str, mode: VolatilityMode = VolatilityMode.BALANCED
) -> list[dict[str, Any]]:
    sym = ticker.strip().upper()
    if not sym:
        return []
    try:
        raw = build_expiry_comparison_for_ticker(sym, mode)
    except Exception:
        logger.exception("Scanner failed for %s", sym)
        return []
    if not raw:
        return []
    rows = raw.get("comparison_table") or []
    out: list[dict[str, Any]] = []
    for r in rows:
        if str(r.get("decision", "")).upper() != "TRADE":
            continue
        row = dict(r)
        row["ticker"] = sym
        out.append(_sanitize(row))
    return out


def collect_trade_rows_all_modes(ticker: str) -> list[dict[str, Any]]:
    """
    TRADE-only rows from Defensive, Balanced, and Aggressive scans.

    Rows are deduplicated by ``trade_signature`` (ticker, strategy, strikes,
    expiry, …) so the same physical setup is not listed or emailed multiple
    times when it qualifies as TRADE in more than one mode. When scores differ,
    the row with the higher ``overall_score`` is kept; ``volatility_mode`` is
    set to the mode that produced that winning row.
    """
    by_sig: dict[str, dict[str, Any]] = {}
    per_mode_counts: dict[str, int] = {m.value: 0 for m in _ALERT_VOLATILITY_MODES}
    for mode in _ALERT_VOLATILITY_MODES:
        chunk = collect_trade_rows(ticker, mode)
        per_mode_counts[mode.value] = len(chunk)
        for row in chunk:
            sig = trade_signature(row)
            score_new = float(row.get("overall_score") or 0)
            prev = by_sig.get(sig)
            if prev is None:
                r = dict(row)
                r["volatility_mode"] = mode.value
                by_sig[sig] = r
                continue
            score_old = float(prev.get("overall_score") or 0)
            if score_new > score_old:
                r = dict(row)
                r["volatility_mode"] = mode.value
                by_sig[sig] = r
    sym = ticker.strip().upper()
    logger.info(
        "Alert TRADE scan %s per-mode %s → merged_unique=%s",
        sym,
        per_mode_counts,
        len(by_sig),
    )
    return list(by_sig.values())


def _send_smtp_raw(
    host: str,
    port: int,
    login_user: str,
    password: str,
    from_addr: str,
    to_addr: str,
    subject: str,
    text_body: str,
    html_body: str,
) -> None:
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = from_addr
    msg["To"] = to_addr
    msg.attach(MIMEText(text_body, "plain", "utf-8"))
    msg.attach(MIMEText(html_body, "html", "utf-8"))

    with smtplib.SMTP(host, port, timeout=120) as smtp:
        smtp.starttls()
        if login_user:
            smtp.login(login_user, password)
        smtp.sendmail(from_addr, [to_addr], msg.as_string())


def _send_email_global(to_addr: str, subject: str, text_body: str, html_body: str) -> bool:
    host = os.environ.get("FLUXTRADE_SMTP_HOST", "").strip()
    if not host:
        return False
    port = int(os.environ.get("FLUXTRADE_SMTP_PORT", "587"))
    user = os.environ.get("FLUXTRADE_SMTP_USER", "").strip()
    password = os.environ.get("FLUXTRADE_SMTP_PASSWORD", "")
    from_addr = os.environ.get("FLUXTRADE_SMTP_FROM", user).strip() or user
    _send_smtp_raw(host, port, user, password, from_addr, to_addr, subject, text_body, html_body)
    return True


def _send_new_trade_email_for_user(
    to_addr: str,
    subject: str,
    text_body: str,
    html_body: str,
    data: dict[str, Any],
) -> tuple[bool, str]:
    """
    Returns (sent, reason). reason is 'sent', 'disabled', 'no_transport', or error str.
    """
    if data.get("alertsEmailEnabled") is False:
        logger.info("Email skipped: alertsEmailEnabled=false for recipient pipeline")
        return (False, "alerts_disabled")

    from core.smtp_crypto import decrypt_smtp_password

    u_host = str(data.get("smtpHost") or "").strip()
    enc = str(data.get("smtpPasswordEnc") or "").strip()
    if u_host and enc:
        pwd = decrypt_smtp_password(enc)
        if not pwd:
            logger.warning("Could not decrypt user SMTP password (wrong FERNET key?)")
            return (False, "decrypt_failed")
        port = int(data.get("smtpPort") or 587)
        login = str(data.get("smtpUser") or "").strip()
        from_a = str(data.get("smtpFrom") or login).strip() or login
        try:
            _send_smtp_raw(u_host, port, login, pwd, from_a, to_addr, subject, text_body, html_body)
            return (True, "sent_user_smtp")
        except Exception as e:
            logger.exception("User SMTP send failed")
            return (False, str(e))

    try:
        if _send_email_global(to_addr, subject, text_body, html_body):
            return (True, "sent_global_smtp")
    except Exception as e:
        logger.exception("Global SMTP send failed")
        return (False, str(e))

    return (False, "no_smtp")


def _build_email_bodies(
    trades: list[dict], tickers_scanned: list[str], *, new_only: bool
) -> tuple[str, str]:
    kind = "New TRADE" if new_only else "TRADE"
    header = (
        f"FluxTrade {kind} alert — {len(trades)} row(s) from tickers: "
        f"{', '.join(tickers_scanned) or '(none)'}"
    )
    lines = [header, ""]
    for t in trades:
        mode = t.get("volatility_mode") or "—"
        lines.append(
            f"- {t.get('ticker')} | {t.get('strategy_label')} | {t.get('expiry')} | "
            f"{mode} | score {t.get('overall_score')}"
        )
    text = "\n".join(lines)

    rows_html = "".join(
        f"<tr><td>{t.get('ticker')}</td><td>{t.get('strategy_label')}</td><td>{t.get('expiry')}</td>"
        f"<td>{t.get('strike_label')}</td><td>{t.get('volatility_mode') or '—'}</td>"
        f"<td>{t.get('overall_score')}</td></tr>"
        for t in trades
    )
    html = f"""<html><body>
<p>{header}</p>
<table border="1" cellpadding="4"><thead><tr>
<th>Ticker</th><th>Strategy</th><th>Expiry</th><th>Strikes</th><th>Mode</th><th>Score</th>
</tr></thead><tbody>{rows_html or '<tr><td colspan="6">No TRADE rows this run.</td></tr>'}</tbody></table>
</body></html>"""
    return text, html


def _merge_sent_signatures(prev_list: list[str], rows: list[dict]) -> list[str]:
    prev = list(prev_list or [])
    seen = set(prev)
    for t in rows:
        s = trade_signature(t)
        if s not in seen:
            prev.append(s)
            seen.add(s)
    if len(prev) > _ALERT_SENT_SIGNATURES_MAX:
        prev = prev[-_ALERT_SENT_SIGNATURES_MAX:]
    return prev


def _user_smtp_payload(user: Any) -> dict[str, Any]:
    sigs = (
        user.alert_trade_sent_signatures
        if isinstance(user.alert_trade_sent_signatures, list)
        else []
    )
    return {
        "smtpHost": str(user.smtp_host or ""),
        "smtpPort": int(user.smtp_port or 587),
        "smtpUser": str(user.smtp_user or ""),
        "smtpPasswordEnc": str(user.smtp_password_enc or ""),
        "smtpFrom": str(user.smtp_from or ""),
        "alertsEmailEnabled": bool(user.alerts_email_enabled),
        "alertTradeSentSignatures": sigs,
    }


def _symbols_for_alert_batch(session: Any, user_id: uuid.UUID) -> list[str]:
    """Symbols from ``watchlist`` for this user."""
    from sqlalchemy import select

    from db.models import Watchlist

    wl = session.scalars(
        select(Watchlist.symbol)
        .where(Watchlist.user_id == user_id)
        .order_by(Watchlist.sort_order, Watchlist.symbol)
    ).all()
    return [str(s).strip().upper() for s in wl if str(s).strip()]


def _run_postgres_alert_batch() -> dict[str, Any]:
    from sqlalchemy import select

    from db.models import Alert, User
    from db.session import configure_session, SessionLocal

    configure_session()
    if SessionLocal is None:
        return {"ok": False, "error": "postgres_session_unavailable"}

    utc_now = datetime.now(timezone.utc)
    run_iso = utc_now.strftime("%Y-%m-%dT%H:%M:%SZ")
    run_key = f"run_{int(time.time())}"

    summary: dict[str, Any] = {
        "ok": True,
        "storage": "postgres",
        "users_seen": 0,
        "users_processed": 0,
        "emails_sent": 0,
        "batches_written": 0,
        "new_trade_emails": 0,
        "errors": [],
    }

    session = SessionLocal()
    try:
        users = list(session.scalars(select(User)).all())
        for u in users:
            summary["users_seen"] += 1
            if not u.email_verified:
                continue
            email = (u.email or "").strip()
            data = _user_smtp_payload(u)
            tickers = _symbols_for_alert_batch(session, u.id)
            if not tickers:
                continue

            summary["users_processed"] += 1
            all_trades: list[dict] = []
            for sym in tickers:
                all_trades.extend(collect_trade_rows_all_modes(sym))

            prev_sigs_raw = u.alert_trade_sent_signatures
            prev_list = (
                list(prev_sigs_raw)
                if isinstance(prev_sigs_raw, list)
                else []
            )
            prev_strings = [str(x) for x in prev_list if str(x)]
            already_sent = set(prev_strings)
            new_trade_rows = _new_trades_for_email(all_trades, already_sent)

            rows_to_ack: list[dict] = []
            try:
                batch = Alert(
                    user_id=u.id,
                    run_key=run_key,
                    run_at_iso=run_iso,
                    timezone=PST,
                    tickers_scanned=tickers,
                    trades=all_trades,
                    new_trades=new_trade_rows,
                    trade_count=len(all_trades),
                    new_trade_count=len(new_trade_rows),
                )
                session.add(batch)
                session.flush()
                summary["batches_written"] += 1

                if new_trade_rows:
                    has_global_smtp = bool(
                        os.environ.get("FLUXTRADE_SMTP_HOST", "").strip()
                    )
                    has_user_smtp = bool(
                        str(data.get("smtpHost") or "").strip()
                    ) and bool(str(data.get("smtpPasswordEnc") or "").strip())
                    can_try_email = bool(email) and (has_global_smtp or has_user_smtp)

                    if not can_try_email:
                        rows_to_ack = all_trades
                    else:
                        subj = (
                            f"FluxTrade: {len(new_trade_rows)} new TRADE row(s) — {run_iso}"
                        )
                        text, html = _build_email_bodies(
                            new_trade_rows, tickers, new_only=True
                        )
                        sent, reason = _send_new_trade_email_for_user(
                            email, subj, text, html, data
                        )
                        if sent:
                            summary["emails_sent"] += 1
                            summary["new_trade_emails"] += 1
                            rows_to_ack = new_trade_rows
                        elif reason == "alerts_disabled":
                            rows_to_ack = []
                        elif reason == "no_smtp":
                            rows_to_ack = all_trades
                        else:
                            logger.warning(
                                "Email not sent for %s: %s", email, reason
                            )
                            summary["errors"].append(
                                {"email": email, "error": reason}
                            )
                            rows_to_ack = []

                if rows_to_ack:
                    u.alert_trade_sent_signatures = _merge_sent_signatures(
                        prev_strings, rows_to_ack
                    )
                    session.add(u)

                session.commit()
            except Exception as e:
                session.rollback()
                logger.exception("Postgres alert batch failed for user=%s", u.id)
                summary["errors"].append({"user_id": str(u.id), "error": str(e)})
    except Exception as e:
        logger.exception("Postgres alert batch fatal error")
        summary["ok"] = False
        summary["errors"].append({"fatal": str(e)})
    finally:
        session.close()

    return summary


def _new_trades_for_email(
    all_trades: list[dict], already_sent: set[str]
) -> list[dict]:
    out: list[dict] = []
    seen_sig: set[str] = set()
    for t in all_trades:
        sig = trade_signature(t)
        if sig in already_sent or sig in seen_sig:
            continue
        seen_sig.add(sig)
        out.append(t)
    return out


def run_all_users_alert_batch(*, bypass_schedule: bool = False) -> dict[str, Any]:
    """
    Full batch run. Scheduled **every hour at :00** **Monday–Sunday**, **5:00 AM–11:59 PM**
    local (America/Los_Angeles). Outside that window the job no-ops (unless
    ``bypass_schedule=True``).

    ``bypass_schedule=True`` (manual ``?force=1``) skips the window check.
    """
    now = datetime.now(ZoneInfo(PST))
    wd = now.weekday()  # Mon=0 … Sun=6
    if not bypass_schedule:
        if not _within_alert_window_la(now):
            logger.info(
                "Alert batch skipped (outside Mon–Sun 5:00 AM–11:59 PM local, now=%s %s).",
                now.strftime("%Y-%m-%d %H:%M"),
                PST,
            )
            return _record_batch_result(
                {
                    "ok": True,
                    "skipped": True,
                    "reason": "outside_trading_window",
                    "hour_local": now.hour,
                    "minute_local": now.minute,
                    "timezone": PST,
                }
            )
    else:
        logger.warning(
            "Alert batch bypass_schedule=True (window check skipped) at %s local.",
            now.strftime("%Y-%m-%d %H:%M"),
        )

    logger.info(
        "Alert batch running (%s local, weekday=%s hour=%s).",
        now.strftime("%Y-%m-%d %H:%M"),
        wd,
        now.hour,
    )

    if not database_url():
        summary = {
            "ok": False,
            "error": "database_not_configured",
            "hint": "Set DATABASE_URL or FLUXTRADE_DATABASE_URL.",
        }
    else:
        from db.alert_cleanup import purge_expired_storage

        purge_expired_storage()
        summary = _run_postgres_alert_batch()

    logger.info("Alert batch finished: %s", summary)
    return _record_batch_result(summary)
