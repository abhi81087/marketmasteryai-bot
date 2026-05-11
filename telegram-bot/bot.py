"""
bot.py — MarketMasteryAI Bot (production)

Key design decisions:
- _fetch_many(): parallel yfinance fetching with asyncio.to_thread + Semaphore
  Makes screeners 5-10× faster (20 stocks: ~10s instead of ~100s).
- is_valid_ticker(): rejects garbage input before any network call.
- Name cache in analysis.py avoids slow stock.info on repeat queries.
- 6-factor signal model in analysis.py reduces false signals.
"""

import asyncio
import logging
import os
import re
from datetime import time as dtime

from telegram import Update
from telegram.ext import (
    ApplicationBuilder, CommandHandler, ContextTypes,
    MessageHandler, filters,
)

from analysis import analyze
from alerts import get_alert, get_all_alerts, remove_alert, set_alert
from backtest import run_backtest
from formatter import format_report
from journal import (
    add_trade, delete_trade, get_pnl_stats,
    get_streak_and_equity, get_trades,
)
from price_alerts import (
    add_price_alert, get_all_price_alerts, get_user_alerts,
    remove_price_alert, remove_triggered_alert,
)
from sentiment import fetch_sentiment
from utils import (
    chg_emoji, chg_str, fmt, fmt_macd, fmt_pnl,
    is_indian, market_status_ist, rsi_zone, sig_icon,
)
from watchlist import add_tickers, clear_watchlist, get_watchlist, remove_tickers

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

DISCLAIMER = "⚠️ _Educational only. Not financial advice. Consult a SEBI-registered advisor._"

# ─────────────────────────────────────────────────────────────────────────────
# Ticker validation
# ─────────────────────────────────────────────────────────────────────────────

# Allows: AAPL, TCS.NS, RELIANCE.BO, ^NSEI, ^NSEBANK, BRK-B
_TICKER_RE = re.compile(r'^[\^A-Z0-9][A-Z0-9\.\-]{0,19}$')


def is_valid_ticker(t: str) -> bool:
    return bool(_TICKER_RE.match(t.upper().strip()))


def clean_ticker(t: str) -> str:
    return t.upper().strip()


# ─────────────────────────────────────────────────────────────────────────────
# Parallel fetcher — the key speed improvement
# ─────────────────────────────────────────────────────────────────────────────

async def _fetch_many(
    tickers: list[str],
    max_concurrent: int = 5,
    period: str = "1y",
) -> dict[str, dict | None]:
    """
    Fetch multiple tickers concurrently.
    Uses asyncio.to_thread to run the blocking analyze() in a thread pool.
    Semaphore limits concurrent yfinance requests to avoid rate-limiting.
    Returns {ticker: data_dict} — value is None on failure.
    """
    sem     = asyncio.Semaphore(max_concurrent)
    results: dict[str, dict | None] = {}

    async def _one(ticker: str):
        async with sem:
            try:
                results[ticker] = await asyncio.to_thread(analyze, ticker, period)
            except Exception as e:
                logger.warning(f"Fetch error [{ticker}]: {e}")
                results[ticker] = None

    await asyncio.gather(*[_one(t) for t in tickers])
    return results


# ─────────────────────────────────────────────────────────────────────────────
# Stock universe
# ─────────────────────────────────────────────────────────────────────────────

TOP_INDIA = [
    "RELIANCE.NS", "TCS.NS",      "INFY.NS",      "HDFCBANK.NS",  "ICICIBANK.NS",
    "SBIN.NS",     "WIPRO.NS",    "BAJFINANCE.NS", "AXISBANK.NS",  "KOTAKBANK.NS",
    "LT.NS",       "MARUTI.NS",   "TATAMOTORS.NS", "SUNPHARMA.NS", "ADANIENT.NS",
    "HINDALCO.NS", "NTPC.NS",     "TATASTEEL.NS",  "BHARTIARTL.NS","POWERGRID.NS",
]

TOP_US = [
    "AAPL", "MSFT", "NVDA", "GOOGL", "AMZN",
    "META", "TSLA", "AMD",  "NFLX",  "JPM",
    "V",    "MA",   "BAC",  "DIS",   "INTC",
]

SIGNAL_RANK = {
    "STRONG BUY": 0, "BUY": 1,
    "HOLD / NEUTRAL": 2,
    "SELL": 3, "STRONG SELL": 4,
}

SECTOR_MAP = {
    "RELIANCE.NS":    "⚡ Energy & Retail",
    "TCS.NS":         "💻 IT / Tech",
    "INFY.NS":        "💻 IT / Tech",
    "WIPRO.NS":       "💻 IT / Tech",
    "BHARTIARTL.NS":  "📡 Telecom",
    "HDFCBANK.NS":    "🏦 Banking",
    "ICICIBANK.NS":   "🏦 Banking",
    "SBIN.NS":        "🏦 Banking",
    "AXISBANK.NS":    "🏦 Banking",
    "KOTAKBANK.NS":   "🏦 Banking",
    "BAJFINANCE.NS":  "💰 NBFC",
    "LT.NS":          "🏗 Infra",
    "MARUTI.NS":      "🚗 Auto",
    "TATAMOTORS.NS":  "🚗 Auto",
    "HINDALCO.NS":    "🔩 Metals",
    "TATASTEEL.NS":   "🔩 Metals",
    "NTPC.NS":        "⚡ Power",
    "POWERGRID.NS":   "⚡ Power",
    "SUNPHARMA.NS":   "💊 Pharma",
    "ADANIENT.NS":    "🏗 Infra",
    "AAPL":  "💻 Tech (US)",    "MSFT":  "💻 Tech (US)",
    "NVDA":  "💻 Tech (US)",    "GOOGL": "💻 Tech (US)",
    "AMZN":  "💻 Tech (US)",    "META":  "💻 Tech (US)",
    "AMD":   "💻 Tech (US)",    "INTC":  "💻 Tech (US)",
    "NFLX":  "🎬 Media (US)",   "DIS":   "🎬 Media (US)",
    "TSLA":  "🚗 Auto (US)",
    "JPM":   "🏦 Finance (US)", "V":     "🏦 Finance (US)",
    "MA":    "🏦 Finance (US)", "BAC":   "🏦 Finance (US)",
}

SECTOR_ORDER = [
    "💻 IT / Tech", "🏦 Banking", "💰 NBFC",
    "⚡ Energy & Retail", "⚡ Power", "📡 Telecom",
    "🚗 Auto", "🔩 Metals", "🏗 Infra", "💊 Pharma",
    "💻 Tech (US)", "🏦 Finance (US)", "🚗 Auto (US)", "🎬 Media (US)",
]


def _ticker_arg(args: list) -> tuple[list[str], str]:
    """Parse optional `india`/`in`/`us` from args. Default: Indian stocks."""
    key = " ".join(args).lower().strip() if args else ""
    if key == "us":
        return TOP_US, "🇺🇸 US Stocks"
    if key in ("india", "in"):
        return TOP_INDIA, "🇮🇳 Indian Stocks"
    return TOP_INDIA, "🇮🇳 Indian Stocks"


# ─────────────────────────────────────────────────────────────────────────────
# Help text
# ─────────────────────────────────────────────────────────────────────────────

HELP_TEXT = """\
🤖 *MarketMasteryAI Bot — Commands*

━━━━━━━━━━━━━━━━━━━━
📌 *Quick start*
Just type a ticker:  `TCS.NS`  `^NSEI`

━━━━━━━━━━━━━━━━━━━━
📊 *Single stock*
/signal `TCS.NS` — Quick AI signal card
/swing `TCS.NS`  — Swing trade setup
/intraday `TCS.NS` — Intraday bias
/summary `TCS.NS` — Brief + sentiment
/report `TCS.NS`  — Full printable report

━━━━━━━━━━━━━━━━━━━━
🇮🇳 *Indian market*
/nifty      — NSE live dashboard
/breakout   — Active breakout stocks
/top        — Top signals now
/movers     — Today's gainers & losers
/heatmap    — NSE heatmap (20 stocks)
/sector     — Sector strength overview
_(append `us` for US stocks)_

━━━━━━━━━━━━━━━━━━━━
🔍 *Screeners*
/gainers52w — Near 52-week highs
/oversold   — Oversold dip setups
/compare `TCS.NS INFY.NS` — Side-by-side

━━━━━━━━━━━━━━━━━━━━
📋 *Watchlist*
/watchlist — View saved tickers
/add `TCS.NS INFY.NS` — Add
/remove `TCS.NS` — Remove
/scan  — Analyse watchlist
/clear — Clear all

━━━━━━━━━━━━━━━━━━━━
🔔 *Alerts*
/alert `RELIANCE.NS above 3000`
/alerts — View active alerts
/delalert `1` — Cancel by ID
/setalert `03:45` — Daily scan (UTC)
/myalert  — Check scheduled time
/cancelalert — Cancel daily scan

━━━━━━━━━━━━━━━━━━━━
📒 *Trade journal*
/journal `TCS.NS long 3800 4100 10`
/trades   — History
/pnl      — Stats & profit factor
/streak   — Streak & equity curve
/deltrade `3` — Delete by ID

━━━━━━━━━━━━━━━━━━━━
📐 *Risk & backtest*
/risk `RELIANCE.NS 100000`
/risk `TCS.NS 50000 1` _(1% risk)_
/backtest `TCS.NS` _(1y default)_
/backtest `TCS.NS 2y`

━━━━━━━━━━━━━━━━━━━━
🇮🇳 *Ticker guide*
  NSE:   `TCS.NS`  `RELIANCE.NS`
  Index: `^NSEI`  `^NSEBANK`
  BSE:   `TCS.BO`

⚠️ _Educational only. Not financial advice._\
"""

# ─────────────────────────────────────────────────────────────────────────────
# Daily alert infrastructure
# ─────────────────────────────────────────────────────────────────────────────

def _build_scan_message(tickers: list[str], results: dict) -> str:
    rows   = []
    errors = []
    for t in tickers:
        d = results.get(t)
        if not d:
            errors.append(t)
            continue
        sig     = d["signal"]["action"]
        brk     = d["breakout"]
        brk_tag = " 🚨↑" if brk["breakout_up"] else (" 💥↓" if brk["breakout_down"] else "")
        rows.append(
            f"{sig_icon(sig)} *{t}* `{fmt(d['last_close'], t)}`"
            f" `{chg_str(d['change_pct'])}` RSI`{d['rsi']}`{brk_tag}"
        )
    L = [f"📊 *Watchlist Scan — {len(tickers)} ticker(s)*", "━━━━━━━━━━━━━━━━━━━━", ""]
    L.extend(rows)
    if errors:
        L.append("")
        L.append(f"_⚠️ {len(errors)} ticker(s) unavailable_")
    L += ["", "_Type any ticker for a full analysis._", DISCLAIMER]
    return "\n".join(L)


async def daily_alert_job(context):
    uid     = context.job.data["user_id"]
    chat_id = context.job.data["chat_id"]
    tickers = get_watchlist(uid)
    if not tickers:
        await context.bot.send_message(
            chat_id=chat_id,
            text="⏰ *Daily Alert*\n\nYour watchlist is empty.\nUse `/add TCS.NS RELIANCE.NS` to add stocks.",
            parse_mode="Markdown",
        )
        return
    results = await _fetch_many(tickers)
    await context.bot.send_message(
        chat_id=chat_id,
        text="⏰ *Daily Watchlist Alert*\n\n" + _build_scan_message(tickers, results),
        parse_mode="Markdown",
    )


def _schedule_alert(app, user_id: int, chat_id: int, hour: int, minute: int):
    name = f"alert_{user_id}"
    for job in app.job_queue.get_jobs_by_name(name):
        job.schedule_removal()
    app.job_queue.run_daily(
        daily_alert_job,
        time=dtime(hour=hour, minute=minute),
        name=name,
        data={"user_id": user_id, "chat_id": chat_id},
    )

# ─────────────────────────────────────────────────────────────────────────────
# /start  /help
# ─────────────────────────────────────────────────────────────────────────────

async def start_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🤖 *Welcome to MarketMasteryAI Bot!*\n"
        "_AI-powered Indian Stock Market Assistant_\n\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "Just type any ticker to get a full analysis:\n\n"
        "  `RELIANCE.NS` — Reliance Industries\n"
        "  `TCS.NS`      — Tata Consultancy\n"
        "  `HDFCBANK.NS` — HDFC Bank\n"
        "  `^NSEI`       — Nifty 50 Index\n"
        "  `^NSEBANK`    — Bank Nifty\n\n"
        "🎯 *Top commands:*\n"
        "  /nifty    — Live NSE market dashboard\n"
        "  /signal `TCS.NS` — Quick AI signal\n"
        "  /top      — Best signals right now\n"
        "  /heatmap  — Visual market heatmap\n"
        "  /breakout — Active breakout stocks\n\n"
        "📋 /help — Full command reference\n\n"
        "🇮🇳 _Focused on NSE/BSE. Prices in ₹ INR._\n\n"
        + DISCLAIMER,
        parse_mode="Markdown",
    )


async def help_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(HELP_TEXT, parse_mode="Markdown")

# ─────────────────────────────────────────────────────────────────────────────
# Main ticker message handler
# ─────────────────────────────────────────────────────────────────────────────

async def analyze_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text   = update.message.text.strip()
    if text.startswith("/"):
        return
    parts  = text.split()
    ticker = clean_ticker(parts[0])

    if not is_valid_ticker(ticker):
        await update.message.reply_text(
            f"❓ `{ticker}` doesn't look like a valid ticker.\n\n"
            "Examples:\n"
            "  `TCS.NS`     — NSE stock\n"
            "  `RELIANCE.NS`— NSE stock\n"
            "  `^NSEI`      — Nifty 50\n"
            "  `AAPL`       — US stock\n\n"
            "_Add .NS for NSE or .BO for BSE stocks._",
            parse_mode="Markdown",
        )
        return

    msg = await update.message.reply_text(f"🔍 Analysing `{ticker}`…", parse_mode="Markdown")
    try:
        data   = await asyncio.to_thread(analyze, ticker)
        report = format_report(data)
        await msg.edit_text(report, parse_mode="Markdown")
    except ValueError as e:
        await msg.edit_text(
            f"❌ *Not found:* `{ticker}`\n\n_{e}_\n\n"
            "Check the ticker format:\n"
            "  `TCS.NS`   — NSE (most common)\n"
            "  `TCS.BO`   — BSE\n"
            "  `^NSEI`    — Nifty 50 Index",
            parse_mode="Markdown",
        )
    except Exception as e:
        logger.exception(f"analyze_handler [{ticker}]: {e}")
        await msg.edit_text(
            f"⚠️ Data unavailable for `{ticker}` right now.\n\n"
            "_Yahoo Finance may be rate-limiting. Try again in 30 seconds._",
            parse_mode="Markdown",
        )

# ─────────────────────────────────────────────────────────────────────────────
# Shared: validate + fetch single ticker
# ─────────────────────────────────────────────────────────────────────────────

async def _require_ticker(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    command: str,
    example: str,
) -> tuple[str | None, dict | None, object]:
    """
    Validate ticker argument and fetch analysis.
    Returns (ticker, data, msg_object) — all None on failure.
    """
    args = context.args
    if not args:
        await update.message.reply_text(
            f"Usage: `/{command} TICKER`\n\nExample: `/{command} {example}`",
            parse_mode="Markdown",
        )
        return None, None, None

    ticker = clean_ticker(args[0])
    if not is_valid_ticker(ticker):
        await update.message.reply_text(
            f"❌ `{ticker}` is not a valid ticker symbol.\n\n"
            "Use `.NS` for NSE stocks, e.g. `TCS.NS`",
            parse_mode="Markdown",
        )
        return None, None, None

    msg = await update.message.reply_text(f"⏳ Fetching data for `{ticker}`…", parse_mode="Markdown")
    try:
        data = await asyncio.to_thread(analyze, ticker)
        return ticker, data, msg
    except ValueError as e:
        await msg.edit_text(
            f"❌ *Not found:* `{ticker}`\n\n_{e}_",
            parse_mode="Markdown",
        )
        return None, None, None
    except Exception as e:
        logger.exception(f"/{command} [{ticker}]: {e}")
        await msg.edit_text(
            f"⚠️ Could not fetch `{ticker}` right now.\n"
            "_Try again in 30 seconds. Yahoo Finance may be rate-limiting._",
            parse_mode="Markdown",
        )
        return None, None, None

# ─────────────────────────────────────────────────────────────────────────────
# /signal — Quick AI signal card
# ─────────────────────────────────────────────────────────────────────────────

async def signal_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    ticker, data, msg = await _require_ticker(update, context, "signal", "TCS.NS")
    if not data:
        return

    sig      = data["signal"]
    price    = data["last_close"]
    chg      = data["change_pct"]
    rsi      = data["rsi"]
    swing    = data["swing"]
    brk      = data["breakout"]
    vol      = data["volume"]
    bull_n   = sig.get("bull_count", 3)
    total_n  = sig.get("total_factors", 6)
    ema_dir  = "↑ Bull" if data["ema9"] > data["ema21"] else "↓ Bear"
    struct   = "Bull" if data["ema50"] > data["ema200"] else "Bear"
    vr       = vol["volume_ratio"]
    vol_tag  = " 🔥" if vr >= 2.0 else (" ⬆️" if vr >= 1.5 else "")
    d_arrow  = "⬆️" if swing["direction"] == "LONG" else "⬇️"

    L = [
        f"⚡ *Signal — `{ticker}`*",
        f"_{data['name']}_",
        "━━━━━━━━━━━━━━━━━━━━",
        "",
        f"💰 `{fmt(price, ticker)}`  {chg_emoji(chg)} `{chg_str(chg)}`",
        f"🎯 *{sig_icon(sig['action'])} {sig['action']}*",
        f"   _{bull_n}/{total_n} indicators aligned_",
        "",
        f"📉 RSI:  `{rsi}` — {rsi_zone(rsi)}",
        f"📐 EMA:  `{ema_dir}` | Struct: `{struct}`",
        f"📦 Vol:  `{vr}x avg`{vol_tag}",
        "",
    ]

    if brk["breakout_up"]:
        L.append("🚀 *BREAKOUT UP!* — Resistance cleared")
    elif brk["breakout_down"]:
        L.append("💥 *BREAKDOWN!* — Support broken")

    rps = abs(price - swing["stop_loss"])
    rr1 = round(abs(swing["target1"] - price) / rps, 1) if rps else 0
    L += [
        "",
        f"🏹 Swing: {d_arrow} {swing['direction']} `{swing['confidence']}%`",
        f"   🛡 Stop: `{fmt(swing['stop_loss'], ticker)}`",
        f"   🎯 T1:   `{fmt(swing['target1'],   ticker)}`  R:R `{rr1}x`",
        f"   🎯 T2:   `{fmt(swing['target2'],   ticker)}`",
        "",
        "━━━━━━━━━━━━━━━━━━━━",
        DISCLAIMER,
    ]
    await msg.edit_text("\n".join(L), parse_mode="Markdown")

# ─────────────────────────────────────────────────────────────────────────────
# /swing — Detailed swing trade setup
# ─────────────────────────────────────────────────────────────────────────────

async def swing_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    ticker, data, msg = await _require_ticker(update, context, "swing", "RELIANCE.NS")
    if not data:
        return

    price = data["last_close"]
    swing = data["swing"]
    brk   = data["breakout"]
    sig   = data["signal"]["action"]
    rsi   = data["rsi"]
    bull_n = data["signal"].get("bull_count", 3)

    d_arrow  = "⬆️ LONG" if swing["direction"] == "LONG" else "⬇️ SHORT"
    conf     = swing["confidence"]
    bar      = "●" * (conf // 20) + "○" * (5 - conf // 20)
    rps      = abs(price - swing["stop_loss"])
    rr1      = round(abs(swing["target1"] - price) / rps, 1) if rps else 0
    rr2      = round(abs(swing["target2"] - price) / rps, 1) if rps else 0
    rr1_q    = "✅" if rr1 >= 2 else ("⚠️" if rr1 >= 1 else "❌")
    rr2_q    = "✅" if rr2 >= 2 else ("⚠️" if rr2 >= 1 else "❌")
    struct   = "Bull" if data["ema50"] > data["ema200"] else "Bear"

    L = [
        f"🏹 *Swing Setup — `{ticker}`*",
        f"_{data['name']}_",
        "━━━━━━━━━━━━━━━━━━━━",
        "",
        f"💰 `{fmt(price, ticker)}` {chg_emoji(data['change_pct'])} `{chg_str(data['change_pct'])}`",
        f"🎯 {sig_icon(sig)} {sig}  _{bull_n}/6 aligned_",
        f"📉 RSI `{rsi}` | 📐 EMA `{'↑' if data['ema9'] > data['ema21'] else '↓'}` | Struct `{struct}`",
        "",
        "─────────────────────",
        f"*Direction: {d_arrow}*",
        f"Confidence: `{conf}%`  [{bar}]",
        f"ATR (14):   `{fmt(swing['atr'], ticker)}`",
    ]

    if brk["breakout_up"]:
        L.append("🚀 *Active Breakout UP!* — adds LONG conviction")
    elif brk["breakout_down"]:
        L.append("💥 *Active Breakdown!* — adds SHORT conviction")

    L += [
        "",
        "─────────────────────",
        f"📍 Entry:    `{fmt(price,             ticker)}`",
        f"🛡 Stop:     `{fmt(swing['stop_loss'],ticker)}`  (1.5× ATR)",
        f"   Risk/sh:  `{fmt(round(rps, 2),     ticker)}`",
        f"🎯 Target 1: `{fmt(swing['target1'],  ticker)}`  R:R `{rr1}x` {rr1_q}",
        f"🎯 Target 2: `{fmt(swing['target2'],  ticker)}`  R:R `{rr2}x` {rr2_q}",
        "",
        "─────────────────────",
        f"Key levels:",
        f"  R: `{fmt(brk['resistance'], ticker)}`",
        f"  S: `{fmt(brk['support'],    ticker)}`",
        "",
        "_💡 Only trade setups with R:R ≥ 2x._",
        "_Use /risk for position sizing._",
        "",
        "━━━━━━━━━━━━━━━━━━━━",
        DISCLAIMER,
    ]
    await msg.edit_text("\n".join(L), parse_mode="Markdown")

# ─────────────────────────────────────────────────────────────────────────────
# /intraday — Intraday bias
# ─────────────────────────────────────────────────────────────────────────────

async def intraday_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    ticker, data, msg = await _require_ticker(update, context, "intraday", "RELIANCE.NS")
    if not data:
        return

    price    = data["last_close"]
    rsi      = data["rsi"]
    ema9     = data["ema9"];   ema21 = data["ema21"]
    ema50    = data["ema50"];  ema200 = data["ema200"]
    macd     = data["macd"];   macd_s = data["macd_signal"]
    vol      = data["volume"]; brk    = data["breakout"]
    swing    = data["swing"];  sig    = data["signal"]["action"]
    atr      = swing["atr"]

    checks = []
    score  = 0

    def check(cond: bool, bull_msg: str, bear_msg: str):
        nonlocal score
        if cond:
            score += 1; checks.append(f"✅ {bull_msg}")
        else:
            score -= 1; checks.append(f"❌ {bear_msg}")

    check(price > ema9,    "Price above EMA9 (immediate bullish)",    "Price below EMA9 (immediate bearish)")
    check(ema9 > ema21,    "EMA9 > EMA21 — short-term trend up",      "EMA9 < EMA21 — short-term trend down")
    check(macd > macd_s,   "MACD above signal — bullish momentum",    "MACD below signal — bearish momentum")
    check(rsi < 65,        f"RSI {rsi:.0f} — not yet overbought",     f"RSI {rsi:.0f} — overbought risk")
    check(vol["volume_ratio"] >= 1.0, f"Vol {vol['volume_ratio']}x — active session",
                                      f"Vol {vol['volume_ratio']}x — quiet session")

    if score >= 3:    bias_lbl = "🟢🟢 Strong Bullish"
    elif score >= 1:  bias_lbl = "🟢 Bullish"
    elif score <= -3: bias_lbl = "🔴🔴 Strong Bearish"
    elif score <= -1: bias_lbl = "🔴 Bearish"
    else:             bias_lbl = "🟡 Neutral"

    sl  = round(price - 0.5 * atr, 2)
    t1  = round(price + 0.8 * atr, 2)
    t2  = round(price + 1.5 * atr, 2)
    sl_s = round(price + 0.5 * atr, 2)
    t1_s = round(price - 0.8 * atr, 2)
    t2_s = round(price - 1.5 * atr, 2)

    status_str, time_str = market_status_ist()
    struct = "Bull" if ema50 > ema200 else "Bear"

    L = [
        f"📈 *Intraday Bias — `{ticker}`*",
        f"_{data['name']}_",
        "━━━━━━━━━━━━━━━━━━━━",
        "",
        f"💰 `{fmt(price, ticker)}` {chg_emoji(data['change_pct'])} `{chg_str(data['change_pct'])}`",
        f"Struct: `{struct}` | Daily: {sig_icon(sig)} {sig}",
        "",
        f"🧭 *Intraday Bias: {bias_lbl}*",
        "",
    ]
    for c in checks:
        L.append(f"  {c}")

    L += [
        "",
        "─────────────────────",
        "*Key Levels:*",
        f"  R: `{fmt(brk['resistance'], ticker)}`",
        f"  S: `{fmt(brk['support'],    ticker)}`",
        "",
        "_If bullish bias:_",
        f"  🛡 Stop: `{fmt(sl, ticker)}`",
        f"  🎯 T1:   `{fmt(t1, ticker)}`",
        f"  🎯 T2:   `{fmt(t2, ticker)}`",
        "",
        "_If bearish bias:_",
        f"  🛡 Stop: `{fmt(sl_s, ticker)}`",
        f"  🎯 T1:   `{fmt(t1_s, ticker)}`",
        f"  🎯 T2:   `{fmt(t2_s, ticker)}`",
        "",
    ]

    if brk["breakout_up"]:
        L.append("🚀 *Breakout UP active* — momentum favours buyers")
    elif brk["breakout_down"]:
        L.append("💥 *Breakdown active* — momentum favours sellers")

    L += [
        "",
        "─────────────────────",
        f"🕐 *{time_str}* — {status_str}",
        "_NSE: 9:15 AM – 3:30 PM IST_",
        "",
        "━━━━━━━━━━━━━━━━━━━━",
        "_Intraday levels use daily ATR as a proxy._",
        DISCLAIMER,
    ]
    await msg.edit_text("\n".join(L), parse_mode="Markdown")

# ─────────────────────────────────────────────────────────────────────────────
# /nifty — NSE Market Dashboard (parallel fetch)
# ─────────────────────────────────────────────────────────────────────────────

async def nifty_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = await update.message.reply_text(
        "📊 Loading NSE dashboard…\n_Scanning indices + 20 stocks in parallel_",
        parse_mode="Markdown",
    )

    all_tickers = ["^NSEI", "^NSEBANK"] + TOP_INDIA
    all_data    = await _fetch_many(all_tickers)

    index_data  = {t: all_data.get(t) for t in ["^NSEI", "^NSEBANK"]}
    stock_data  = {t: all_data.get(t) for t in TOP_INDIA}

    # Breadth
    breadth = {"STRONG BUY": 0, "BUY": 0, "HOLD / NEUTRAL": 0, "SELL": 0, "STRONG SELL": 0}
    movers  = []
    for t, d in stock_data.items():
        if not d:
            continue
        sig = d["signal"]["action"]
        breadth[sig] = breadth.get(sig, 0) + 1
        movers.append({"ticker": t, "chg": d["change_pct"], "rsi": d["rsi"], "signal": sig})

    movers.sort(key=lambda x: x["chg"], reverse=True)
    gainers = movers[:3]
    losers  = list(reversed(movers[-3:])) if len(movers) >= 3 else []

    tb = breadth.get("STRONG BUY", 0) + breadth.get("BUY", 0)
    ts = breadth.get("STRONG SELL", 0) + breadth.get("SELL", 0)
    tn = breadth.get("HOLD / NEUTRAL", 0)
    b_icon  = "🟢" if tb > ts else ("🔴" if ts > tb else "🟡")
    b_label = "Bullish" if tb > ts else ("Bearish" if ts > tb else "Neutral")

    status_str, time_str = market_status_ist()

    L = ["📊 *NSE Market Dashboard*", "━━━━━━━━━━━━━━━━━━━━", ""]

    for ticker, (em, label) in [("^NSEI", ("🔵", "Nifty 50")), ("^NSEBANK", ("🏦", "Bank Nifty"))]:
        d = index_data.get(ticker)
        if d:
            ema_dir  = "↑ Bull" if d["ema9"] > d["ema21"] else "↓ Bear"
            struct   = "Bull" if d["ema50"] > d["ema200"] else "Bear"
            bull_n   = d["signal"].get("bull_count", 3)
            L.append(
                f"{em} *{label}*  `{fmt(d['last_close'], ticker)}`"
                f"  {chg_emoji(d['change_pct'])} `{chg_str(d['change_pct'])}`"
            )
            L.append(
                f"   RSI `{d['rsi']}` | EMA `{ema_dir}` | Struct `{struct}`"
            )
            L.append(
                f"   {sig_icon(d['signal']['action'])} {d['signal']['action']}"
                f"  _{bull_n}/6 aligned_"
            )
        else:
            L.append(f"{em} *{label}* — data unavailable")
        L.append("")

    # Breadth
    L.append("━━━━━━━━━━━━━━━━━━━━")
    L.append(f"📊 *NSE Breadth ({len(movers)} stocks):* {b_icon} *{b_label}*")
    L.append(
        f"  🟢🟢`{breadth.get('STRONG BUY',0)}`"
        f" 🟢`{breadth.get('BUY',0)}`"
        f" 🟡`{tn}`"
        f" 🔴`{breadth.get('SELL',0)}`"
        f" 🔴🔴`{breadth.get('STRONG SELL',0)}`"
    )
    L.append(f"  Bull:`{tb}` Bear:`{ts}` Neutral:`{tn}`")
    L.append("")

    if gainers:
        L.append("🚀 *Top Gainers:*")
        for m in gainers:
            s = m["ticker"].replace(".NS", "").replace(".BO", "")
            L.append(f"  📈 *{s}* `{chg_str(m['chg'])}` RSI`{m['rsi']}` {sig_icon(m['signal'])}")
        L.append("")

    if losers:
        L.append("💥 *Top Losers:*")
        for m in losers:
            s = m["ticker"].replace(".NS", "").replace(".BO", "")
            L.append(f"  📉 *{s}* `{chg_str(m['chg'])}` RSI`{m['rsi']}` {sig_icon(m['signal'])}")
        L.append("")

    L.append("━━━━━━━━━━━━━━━━━━━━")
    L.append(f"🕐 *{time_str}*  {status_str}")
    L.append("_NSE: 9:15 AM–3:30 PM IST | F&O: Thursday_")
    L.append("")
    L.append("_/breakout  /top  /heatmap  /sector_")
    L.append(DISCLAIMER)

    await msg.edit_text("\n".join(L), parse_mode="Markdown")

# ─────────────────────────────────────────────────────────────────────────────
# /breakout — Active breakout scanner (parallel)
# ─────────────────────────────────────────────────────────────────────────────

async def breakout_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    tickers, label = _ticker_arg(context.args)
    msg = await update.message.reply_text(
        f"🔍 Scanning {len(tickers)} stocks for breakouts…", parse_mode="Markdown"
    )

    all_data = await _fetch_many(tickers)
    ups, downs = [], []

    for t, d in all_data.items():
        if not d:
            continue
        brk = d["breakout"]
        if not (brk["breakout_up"] or brk["breakout_down"]):
            continue
        row = {
            "ticker": t, "price": d["last_close"], "chg": d["change_pct"],
            "rsi": d["rsi"], "signal": d["signal"]["action"],
            "score": d["signal"]["score"], "vr": d["volume"]["volume_ratio"],
            "surge": brk["volume_surge"], "up": brk["breakout_up"],
            "level": brk["resistance"] if brk["breakout_up"] else brk["support"],
            "bull_n": d["signal"].get("bull_count", 3),
        }
        (ups if brk["breakout_up"] else downs).append(row)

    def row_line(r: dict) -> str:
        v    = " 🔥" if r["surge"] else (" ⬆️" if r["vr"] >= 1.5 else "")
        icon = "🚀" if r["up"] else "💥"
        return (
            f"{icon} *{r['ticker']}* `{fmt(r['price'], r['ticker'])}` `{chg_str(r['chg'])}`\n"
            f"  {sig_icon(r['signal'])} {r['signal']}  _{r['bull_n']}/6_"
            f"  RSI`{r['rsi']}` Vol`{r['vr']}x`{v}\n"
            f"  Level cleared: `{fmt(r['level'], r['ticker'])}`"
        )

    errors = sum(1 for v in all_data.values() if v is None)
    L      = [f"🚨 *Breakout Scanner — {label}*", "━━━━━━━━━━━━━━━━━━━━", ""]

    if ups:
        L.append(f"🚀 *Bullish Breakouts ({len(ups)}):*")
        L.append("")
        for r in sorted(ups, key=lambda x: -x["score"]):
            L.append(row_line(r)); L.append("")
    else:
        L.append("🟡 No bullish breakouts right now.")
        L.append("")

    if downs:
        L.append(f"💥 *Breakdowns ({len(downs)}):*")
        L.append("")
        for r in sorted(downs, key=lambda x: x["score"]):
            L.append(row_line(r)); L.append("")

    if not ups and not downs:
        L.append("_Market is in a consolidation phase._")

    if errors:
        L.append(f"_⚠️ {errors} ticker(s) unavailable._")

    L += ["_Type any ticker for full analysis._", DISCLAIMER]
    await msg.edit_text("\n".join(L), parse_mode="Markdown")

# ─────────────────────────────────────────────────────────────────────────────
# /top — Top signals (parallel)
# ─────────────────────────────────────────────────────────────────────────────

async def top_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    tickers, label = _ticker_arg(context.args)
    msg = await update.message.reply_text(
        f"🔍 Scanning {len(tickers)} stocks for strong signals…", parse_mode="Markdown"
    )

    all_data = await _fetch_many(tickers)
    hits  = []
    errors = sum(1 for v in all_data.values() if v is None)

    for t, d in all_data.items():
        if not d:
            continue
        sig    = d["signal"]
        action = sig["action"]
        brk    = d["breakout"]
        bull_n = sig.get("bull_count", 3)
        # Include STRONG signals, or BUY/SELL with active breakout
        if not ("STRONG" in action or (action in ("BUY", "SELL") and (brk["breakout_up"] or brk["breakout_down"]))):
            continue
        brk_tag = " 🚨↑" if brk["breakout_up"] else (" 💥↓" if brk["breakout_down"] else "")
        hits.append({
            "rank":  SIGNAL_RANK.get(action, 9),
            "score": abs(sig["score"]),
            "line": (
                f"{sig_icon(action)} *{t}* `{fmt(d['last_close'], t)}` `{chg_str(d['change_pct'])}`\n"
                f"  {action}  _{bull_n}/6_  RSI`{d['rsi']}`"
                f"  {d['swing']['direction']}{brk_tag}"
            ),
        })

    hits.sort(key=lambda x: (x["rank"], -x["score"]))
    L = [f"🏆 *Top Signals — {label}*", "━━━━━━━━━━━━━━━━━━━━", ""]

    if hits:
        L.append("_Strong signals & confirmed breakouts only:_")
        L.append("")
        for h in hits:
            L.append(h["line"])
            L.append("")
    else:
        L.append("🟡 No strong signals right now.")
        L.append("Market is broadly neutral. Check again later.")
        L.append("")

    if errors:
        L.append(f"_⚠️ {errors} ticker(s) unavailable._")
    L += ["_Type a ticker for full analysis._", DISCLAIMER]
    await msg.edit_text("\n".join(L), parse_mode="Markdown")

# ─────────────────────────────────────────────────────────────────────────────
# /movers — Gainers & losers (parallel)
# ─────────────────────────────────────────────────────────────────────────────

async def movers_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    tickers, label = _ticker_arg(context.args)
    msg = await update.message.reply_text(
        f"🔍 Fetching movers from {len(tickers)} stocks…", parse_mode="Markdown"
    )

    all_data = await _fetch_many(tickers)
    results  = []
    errors   = sum(1 for v in all_data.values() if v is None)

    for t, d in all_data.items():
        if not d:
            continue
        results.append({
            "ticker": t, "price": d["last_close"],
            "chg":    d["change_pct"], "rsi": d["rsi"],
            "signal": d["signal"]["action"],
            "vr":     d["volume"]["volume_ratio"],
        })

    if not results:
        await msg.edit_text("❌ Could not fetch any stock data. Try again shortly.", parse_mode="Markdown")
        return

    results.sort(key=lambda x: x["chg"], reverse=True)
    gainers = results[:5]
    losers  = list(reversed(results[-5:]))

    def vol_tag(vr): return " 🔥" if vr >= 2.0 else (" ⬆️" if vr >= 1.5 else "")

    L = [f"📈📉 *Top Movers — {label}*", "━━━━━━━━━━━━━━━━━━━━", ""]
    L.append("🚀 *Top Gainers:*")
    for r in gainers:
        L.append(
            f"  {sig_icon(r['signal'])} *{r['ticker']}* `{fmt(r['price'], r['ticker'])}`"
            f" `{chg_str(r['chg'])}` RSI`{r['rsi']}`{vol_tag(r['vr'])}"
        )
    L.append("")
    L.append("💥 *Top Losers:*")
    for r in losers:
        L.append(
            f"  {sig_icon(r['signal'])} *{r['ticker']}* `{fmt(r['price'], r['ticker'])}`"
            f" `{chg_str(r['chg'])}` RSI`{r['rsi']}`{vol_tag(r['vr'])}"
        )

    if errors:
        L.append(f"\n_⚠️ {errors} ticker(s) unavailable._")
    L += ["", "_Type any ticker for full analysis._", DISCLAIMER]
    await msg.edit_text("\n".join(L), parse_mode="Markdown")

# ─────────────────────────────────────────────────────────────────────────────
# /heatmap — Signal heatmap (parallel)
# ─────────────────────────────────────────────────────────────────────────────

async def heatmap_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = await update.message.reply_text(
        f"🗺️ Building NSE heatmap for {len(TOP_INDIA)} stocks…", parse_mode="Markdown"
    )

    all_data = await _fetch_many(TOP_INDIA)

    def cell(t: str) -> str:
        d = all_data.get(t)
        s = t.replace(".NS", "").replace(".BO", "")
        if not d:
            return f"⬜`{s}`"
        return f"{sig_icon(d['signal']['action'])}`{s}`"

    sb  = sum(1 for d in all_data.values() if d and "STRONG BUY"  in d["signal"]["action"])
    b   = sum(1 for d in all_data.values() if d and d["signal"]["action"] == "BUY")
    h   = sum(1 for d in all_data.values() if d and d["signal"]["action"] == "HOLD / NEUTRAL")
    s   = sum(1 for d in all_data.values() if d and d["signal"]["action"] == "SELL")
    ss  = sum(1 for d in all_data.values() if d and "STRONG SELL" in d["signal"]["action"])
    tb  = sb + b;  ts = ss + s
    bd  = "Bullish" if tb > ts else ("Bearish" if ts > tb else "Neutral")
    bdi = "🟢" if bd == "Bullish" else ("🔴" if bd == "Bearish" else "🟡")

    rsies   = [d["rsi"] for d in all_data.values() if d]
    avg_rsi = round(sum(rsies) / len(rsies), 1) if rsies else 0

    sec_tickers: dict[str, list] = {}
    for t in TOP_INDIA:
        sec_tickers.setdefault(SECTOR_MAP.get(t, "🔹 Other"), []).append(t)

    L = ["🗺️ *NSE Market Heatmap*", "━━━━━━━━━━━━━━━━━━━━", ""]
    for sec in SECTOR_ORDER:
        grp = sec_tickers.get(sec)
        if not grp:
            continue
        grp_sorted = sorted(grp, key=lambda t: -(all_data.get(t) or {}).get("signal", {}).get("score", 0))
        L.append(f"*{sec}*")
        L.append("  " + "  ".join(cell(t) for t in grp_sorted))
        L.append("")

    L += [
        "━━━━━━━━━━━━━━━━━━━━",
        f"📊 *Breadth:* {bdi} *{bd}*",
        f"  🟢🟢`{sb}` 🟢`{b}` 🟡`{h}` 🔴`{s}` 🔴🔴`{ss}`",
        f"  Bull:`{tb}` Bear:`{ts}` Avg RSI:`{avg_rsi}`",
        "",
        "_Type any ticker for full analysis._",
        DISCLAIMER,
    ]
    await msg.edit_text("\n".join(L), parse_mode="Markdown")

# ─────────────────────────────────────────────────────────────────────────────
# /sector — Sector strength (parallel)
# ─────────────────────────────────────────────────────────────────────────────

async def sector_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    tickers = TOP_INDIA + TOP_US
    msg     = await update.message.reply_text(
        f"🔍 Scanning {len(tickers)} stocks across sectors…", parse_mode="Markdown"
    )

    all_data = await _fetch_many(tickers)
    sectors: dict[str, list] = {}

    for t, d in all_data.items():
        if not d:
            continue
        sec = SECTOR_MAP.get(t, "🔹 Other")
        sectors.setdefault(sec, []).append({
            "ticker":  t,
            "rsi":     d["rsi"],
            "signal":  d["signal"]["action"],
            "score":   d["signal"]["score"],
            "chg":     d["change_pct"],
            "bull_n":  d["signal"].get("bull_count", 3),
        })

    def dominant(stocks):
        c = {}
        for s in stocks:
            c[s["signal"]] = c.get(s["signal"], 0) + 1
        return max(c, key=lambda x: c[x])

    summaries = []
    for sec, stocks in sectors.items():
        dom  = dominant(stocks)
        summaries.append({
            "sector":    sec,
            "count":     len(stocks),
            "avg_rsi":   round(sum(s["rsi"]   for s in stocks) / len(stocks), 1),
            "avg_chg":   round(sum(s["chg"]   for s in stocks) / len(stocks), 2),
            "avg_score": round(sum(s["score"] for s in stocks) / len(stocks), 1),
            "dom":       dom,
            "stocks":    stocks,
        })
    summaries.sort(key=lambda x: -x["avg_score"])

    errors = sum(1 for v in all_data.values() if v is None)
    L = ["🏭 *Sector Strength*", "━━━━━━━━━━━━━━━━━━━━", ""]

    for sec in summaries:
        tkr_list = " ".join(
            f"`{s['ticker'].replace('.NS','').replace('.BO','')}`"
            for s in sorted(sec["stocks"], key=lambda x: -x["score"])
        )
        L.append(f"{sig_icon(sec['dom'])} *{sec['sector']}* ({sec['count']})")
        L.append(
            f"  {sec['dom']} | RSI`{sec['avg_rsi']}` | `{chg_str(sec['avg_chg'])}`"
        )
        L.append(f"  {tkr_list}")
        L.append("")

    if errors:
        L.append(f"_⚠️ {errors} ticker(s) unavailable._")
    L += ["_Type any ticker for full analysis._", DISCLAIMER]
    await msg.edit_text("\n".join(L), parse_mode="Markdown")

# ─────────────────────────────────────────────────────────────────────────────
# /oversold — Oversold dip-buy setups (parallel)
# ─────────────────────────────────────────────────────────────────────────────

async def oversold_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    tickers, label = _ticker_arg(context.args)
    msg = await update.message.reply_text(
        f"🔍 Scanning {len(tickers)} stocks for oversold setups…", parse_mode="Markdown"
    )

    all_data = await _fetch_many(tickers)
    hits  = []
    errors = sum(1 for v in all_data.values() if v is None)

    for t, d in all_data.items():
        if not d:
            continue
        rsi   = d["rsi"]
        price = d["last_close"]
        if rsi >= 35:
            continue
        ema50  = d["ema50"];  ema200 = d["ema200"]
        ema9   = d["ema9"];   ema21  = d["ema21"]
        macd   = d["macd"];   macd_s = d["macd_signal"]
        # Require at least some bullish structural context
        bullish_struct = (ema50 > ema200) or (price > ema50) or (ema9 > ema21)
        if not bullish_struct:
            continue
        q     = 0
        parts = []
        if ema50 > ema200: q += 2; parts.append("EMA50>200")
        if price > ema50:  q += 1; parts.append("P>EMA50")
        if ema9 > ema21:   q += 1; parts.append("EMA9>21")
        if macd > macd_s:  q += 1; parts.append("MACD↑")
        if d["volume"]["obv_trend"] == "Rising": q += 1; parts.append("OBV↑")
        swing = d["swing"]
        hits.append({
            "rsi": rsi, "q": q,
            "line": (
                f"🔵 *{t}* `{fmt(price, t)}` `{chg_str(d['change_pct'])}` RSI`{rsi}`\n"
                f"  `{'|'.join(parts)}`\n"
                f"  Swing `{swing['direction']}` SL`{fmt(swing['stop_loss'],t)}` T1`{fmt(swing['target1'],t)}`"
            ),
        })

    hits.sort(key=lambda x: (-x["q"], x["rsi"]))
    L = [f"🔵 *Oversold Dip Setups — {label}*", "━━━━━━━━━━━━━━━━━━━━", ""]
    L.append("_RSI < 35 + at least one bullish EMA structure:_")
    L.append("")

    if hits:
        for h in hits:
            L.append(h["line"]); L.append("")
    else:
        L.append("No oversold setups now.")
        L.append("Market is likely in a strong uptrend.")

    if errors:
        L.append(f"_⚠️ {errors} ticker(s) unavailable._")
    L += ["", "_Type any ticker for full analysis._", DISCLAIMER]
    await msg.edit_text("\n".join(L), parse_mode="Markdown")

# ─────────────────────────────────────────────────────────────────────────────
# /gainers52w — Near 52-week highs + bullish signal (parallel)
# ─────────────────────────────────────────────────────────────────────────────

async def gainers52w_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    import yfinance as yf
    tickers, label = _ticker_arg(context.args)
    msg = await update.message.reply_text(
        f"🔍 Scanning {len(tickers)} stocks for 52-week high setups…", parse_mode="Markdown"
    )

    all_data = await _fetch_many(tickers)
    hits  = []
    errors = sum(1 for v in all_data.values() if v is None)

    for t, d in all_data.items():
        if not d:
            continue
        sig = d["signal"]["action"]
        if sig not in ("BUY", "STRONG BUY"):
            continue
        try:
            fi      = yf.Ticker(t).fast_info
            high52  = getattr(fi, "year_high", None)
            price   = d["last_close"]
            if not high52:
                info   = yf.Ticker(t).info
                high52 = info.get("fiftyTwoWeekHigh")
            if not high52 or high52 <= 0:
                continue
            high52    = round(float(high52), 2)
            pct_below = round(((high52 - price) / high52) * 100, 1)
            if pct_below > 10:
                continue
            vr      = d["volume"]["volume_ratio"]
            brk_tag = " 🚨" if d["breakout"]["breakout_up"] else ""
            vol_tag = " 🔥" if vr >= 2.0 else (" ⬆️" if vr >= 1.5 else "")
            bull_n  = d["signal"].get("bull_count", 3)
            hits.append({
                "pct": pct_below,
                "line": (
                    f"{'🟢🟢' if 'STRONG' in sig else '🟢'} *{t}* `{fmt(price, t)}` `{chg_str(d['change_pct'])}`"
                    f"  _{bull_n}/6_\n"
                    f"  `{pct_below}%` below 52w high `{fmt(high52, t)}`{brk_tag}{vol_tag}"
                    f"\n  RSI`{d['rsi']}` | Vol`{vr}x`"
                ),
            })
        except Exception as e:
            logger.warning(f"52w scan [{t}]: {e}")
            errors += 1

    hits.sort(key=lambda x: x["pct"])
    L = [f"📈 *Near 52-Week Highs — {label}*", "━━━━━━━━━━━━━━━━━━━━", ""]
    L.append("_Bullish stocks within 10% of their 52-week high:_")
    L.append("")

    if hits:
        for h in hits:
            L.append(h["line"]); L.append("")
    else:
        L.append("No stocks match the criteria right now.")

    if errors:
        L.append(f"_⚠️ {errors} ticker(s) unavailable._")
    L += ["_Type any ticker for full analysis._", DISCLAIMER]
    await msg.edit_text("\n".join(L), parse_mode="Markdown")

# ─────────────────────────────────────────────────────────────────────────────
# /compare — Side-by-side (parallel)
# ─────────────────────────────────────────────────────────────────────────────

async def compare_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = context.args
    if not args or len(args) < 2:
        await update.message.reply_text(
            "Usage: `/compare TICKER1 TICKER2 [TICKER3…]` _(2–6 tickers)_\n\n"
            "Example: `/compare TCS.NS INFY.NS WIPRO.NS`",
            parse_mode="Markdown",
        )
        return

    raw     = [clean_ticker(a) for a in args[:6]]
    tickers = [t for t in raw if is_valid_ticker(t)]
    invalid = [t for t in raw if not is_valid_ticker(t)]

    if len(tickers) < 2:
        await update.message.reply_text(
            "❌ Need at least 2 valid ticker symbols.",
            parse_mode="Markdown",
        )
        return

    msg      = await update.message.reply_text(
        f"🔍 Comparing {', '.join(f'`{t}`' for t in tickers)}…", parse_mode="Markdown"
    )
    all_data = await _fetch_many(tickers)
    rows     = []
    errors   = []

    for t in tickers:
        d = all_data.get(t)
        if not d:
            errors.append(t); continue
        sig      = d["signal"]["action"]
        bull_n   = d["signal"].get("bull_count", 3)
        ema_dir  = "↑" if d["ema9"] > d["ema21"] else "↓"
        struct   = "↑" if d["ema50"] > d["ema200"] else "↓"
        macd_dir = "↑" if d["macd"] > d["macd_signal"] else "↓"
        brk      = d["breakout"]
        brk_tag  = "↑BRK" if brk["breakout_up"] else ("↓BRK" if brk["breakout_down"] else "—")
        rows.append({
            "t": t, "price": d["last_close"], "chg": d["change_pct"],
            "sig": f"{sig_icon(sig)} {sig}", "rsi": d["rsi"],
            "bull_n": bull_n, "ema": ema_dir, "str": struct,
            "macd": macd_dir, "swing": d["swing"]["direction"],
            "conf": d["swing"]["confidence"], "brk": brk_tag,
        })

    if not rows:
        await msg.edit_text("❌ Could not fetch data for any ticker.", parse_mode="Markdown")
        return

    L = ["📊 *Stock Comparison*", "━━━━━━━━━━━━━━━━━━━━", ""]
    for r in rows:
        L.append(f"*{r['t']}* `{fmt(r['price'], r['t'])}` `{chg_str(r['chg'])}`")
        L.append(f"  {r['sig']}  _{r['bull_n']}/6_")
        L.append(f"  RSI`{r['rsi']}` EMA`{r['ema']}` MACD`{r['macd']}` Str`{r['str']}`")
        L.append(f"  Swing `{r['swing']}` `{r['conf']}%` | Brk: `{r['brk']}`")
        L.append("")

    if errors:
        L.append(f"_⚠️ Could not fetch: {', '.join(errors)}_")
    if invalid:
        L.append(f"_⚠️ Invalid tickers skipped: {', '.join(invalid)}_")
    L += ["_Type any ticker for full analysis._", DISCLAIMER]
    await msg.edit_text("\n".join(L), parse_mode="Markdown")

# ─────────────────────────────────────────────────────────────────────────────
# /summary — Combined technicals + sentiment
# ─────────────────────────────────────────────────────────────────────────────

async def summary_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    ticker, data, msg = await _require_ticker(update, context, "summary", "TCS.NS")
    if not data:
        return

    try:
        sent = await asyncio.to_thread(fetch_sentiment, ticker)
    except Exception:
        sent = {"overall": "NEUTRAL", "bullish": 0, "bearish": 0, "neutral": 0, "total": 0}

    sig       = data["signal"]
    price     = data["last_close"]
    chg       = data["change_pct"]
    swing     = data["swing"]
    brk       = data["breakout"]
    bull_n    = sig.get("bull_count", 3)
    ema_dir   = "Bullish" if data["ema9"]  > data["ema21"]      else "Bearish"
    struct    = "Bull"    if data["ema50"] > data["ema200"]     else "Bear"
    macd_dir  = "Bullish" if data["macd"]  > data["macd_signal"] else "Bearish"
    news_mood = sent["overall"]
    n_icon    = "🟢" if news_mood == "BULLISH" else ("🔴" if news_mood == "BEARISH" else "🟡")

    t_bull = "BUY" in sig["action"]
    t_bear = "SELL" in sig["action"]
    n_bull = news_mood == "BULLISH"
    n_bear = news_mood == "BEARISH"

    if t_bull and n_bull:
        note = "📗 *Technicals + news both bullish* — high confidence."
    elif t_bear and n_bear:
        note = "📕 *Technicals + news both bearish* — avoid or short."
    elif t_bull and n_bear:
        note = "⚠️ *Bullish chart, negative news* — wait for clarity."
    elif t_bear and n_bull:
        note = "⚠️ *Bearish chart despite positive news* — may be priced in."
    elif t_bull:
        note = "📘 *Bullish technicals, neutral news* — follow the chart."
    elif t_bear:
        note = "📘 *Bearish technicals* — manage risk carefully."
    else:
        note = "📘 *Mixed signals* — wait for confirmation."

    if brk["breakout_up"]:
        brk_line = "🚀 BREAKOUT UP — resistance cleared"
    elif brk["breakout_down"]:
        brk_line = "💥 BREAKDOWN — support broken"
    else:
        brk_line = f"S:`{fmt(brk['support'],ticker)}`  R:`{fmt(brk['resistance'],ticker)}`"

    L = [
        f"⚡ *Trade Brief — `{ticker}`*",
        f"_{data['name']}_",
        "━━━━━━━━━━━━━━━━━━━━",
        "",
        f"💰 `{fmt(price, ticker)}` {chg_emoji(chg)} `{chg_str(chg)}`",
        f"🎯 {sig_icon(sig['action'])} *{sig['action']}*  _{bull_n}/6 aligned_",
        f"📰 News: {n_icon} {news_mood} ({sent['bullish']}↑ {sent['bearish']}↓ / {sent['total']})",
        "",
        "*Technicals:*",
        f"  RSI `{data['rsi']}` | EMA `{ema_dir}` | MACD `{macd_dir}` | Struct `{struct}`",
        "",
        "*Levels:*",
        f"  {brk_line}",
        "",
        f"🏹 Swing: `{swing['direction']}` `{swing['confidence']}%`",
        f"  SL `{fmt(swing['stop_loss'],ticker)}`"
        f"  T1 `{fmt(swing['target1'],ticker)}`"
        f"  T2 `{fmt(swing['target2'],ticker)}`",
        "",
        "━━━━━━━━━━━━━━━━━━━━",
        f"💡 {note}",
        "",
        DISCLAIMER,
    ]
    await msg.edit_text("\n".join(L), parse_mode="Markdown")

# ─────────────────────────────────────────────────────────────────────────────
# /report — Full printable report
# ─────────────────────────────────────────────────────────────────────────────

async def report_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    ticker, data, msg = await _require_ticker(update, context, "report", "RELIANCE.NS")
    if not data:
        return

    try:
        sent = await asyncio.to_thread(fetch_sentiment, ticker)
    except Exception:
        sent = {"overall": "NEUTRAL", "bullish": 0, "bearish": 0, "neutral": 0, "total": 0, "headlines": []}

    from datetime import datetime, timezone
    now   = datetime.now(timezone.utc).strftime("%d %b %Y  %H:%M UTC")
    price = data["last_close"]
    swing = data["swing"]
    brk   = data["breakout"]
    vol   = data["volume"]
    sig   = data["signal"]
    bull_n = sig.get("bull_count", 3)

    if price > data["bb_upper"]:   bb_pos = "Above upper ⚠️"
    elif price < data["bb_lower"]: bb_pos = "Below lower 🔵"
    else:                           bb_pos = "Inside bands ✅"

    brk_str  = (
        "🚀 BREAKOUT UP" if brk["breakout_up"] else
        "💥 BREAKDOWN"   if brk["breakout_down"] else
        f"No breakout | S:{fmt(brk['support'],ticker)}  R:{fmt(brk['resistance'],ticker)}"
    )
    n_icon   = {"BULLISH": "🟢", "BEARISH": "🔴"}.get(sent["overall"], "🟡")
    ema_dir  = "Bullish ↑" if data["ema9"]  > data["ema21"]      else "Bearish ↓"
    struct   = "Bull"      if data["ema50"] > data["ema200"]     else "Bear"
    macd_dir = "Bullish"   if data["macd"]  > data["macd_signal"] else "Bearish"
    reasons  = "\n".join(f"  • {r}" for r in sig["reasons"])
    accel    = data.get("macd_accel", False)

    hl_lines = ""
    if sent.get("headlines"):
        hl = []
        for h in sent["headlines"][:4]:
            icon  = "🟢" if h["score"] > 0 else ("🔴" if h["score"] < 0 else "🟡")
            title = h["title"][:80] + ("…" if len(h["title"]) > 80 else "")
            hl.append(f"  {icon} {title}")
        hl_lines = "\n".join(hl)
    else:
        hl_lines = "  No recent headlines."

    L = [
        "📊 *ANALYSIS REPORT*",
        f"*{data['name']}* (`{ticker}`)",
        f"_{now}_",
        "━━━━━━━━━━━━━━━━━━━━",
        "",
        f"💰 *Price:* `{fmt(price, ticker)}` ({chg_str(data['change_pct'])})",
        f"🎯 *Signal:* {sig_icon(sig['action'])} *{sig['action']}*  _{bull_n}/6 aligned_",
        f"{reasons}",
        "",
        "─────────────────────",
        f"📉 *RSI (14):* `{data['rsi']}`",
        "",
        "─────────────────────",
        f"📐 *EMA:* `{ema_dir}` | Struct: `{struct}`",
        f"  9:`{fmt(data['ema9'],ticker)}`  21:`{fmt(data['ema21'],ticker)}`",
        f"  50:`{fmt(data['ema50'],ticker)}`  200:`{fmt(data['ema200'],ticker)}`",
        "",
        "─────────────────────",
        f"📊 *MACD:* `{macd_dir}` | Hist {'↑' if accel else '↓'} {'accel' if accel else 'decel'}",
        f"  `{fmt_macd(data['macd'])}` / `{fmt_macd(data['macd_signal'])}` / `{fmt_macd(data['macd_hist'])}`",
        "",
        "─────────────────────",
        f"📏 *Bollinger:* {bb_pos}",
        f"  U:`{fmt(data['bb_upper'],ticker)}`  M:`{fmt(data['bb_mid'],ticker)}`  L:`{fmt(data['bb_lower'],ticker)}`",
        f"  Pos: `{data.get('bb_pct', 50):.0f}%` in band",
        "",
        "─────────────────────",
        f"📦 *Volume:* `{vol['volume_ratio']}x` avg | OBV: `{vol['obv_trend']}`",
        f"  Today:`{vol['last_volume']:,}`  Avg20:`{vol['avg_volume_20d']:,}`",
        "",
        "─────────────────────",
        f"🚨 *Breakout:* {brk_str}",
        "",
        "─────────────────────",
        f"🏹 *Swing:* {swing['direction']} `{swing['confidence']}%`",
        f"  ATR:`{fmt(swing['atr'],ticker)}`",
        f"  SL: `{fmt(swing['stop_loss'],ticker)}`",
        f"  T1: `{fmt(swing['target1'],ticker)}`",
        f"  T2: `{fmt(swing['target2'],ticker)}`",
        "",
        "─────────────────────",
        f"📰 *News:* {n_icon} {sent['overall']} ({sent['bullish']}↑ {sent['bearish']}↓ / {sent['total']})",
        hl_lines,
        "",
        "━━━━━━━━━━━━━━━━━━━━",
        DISCLAIMER,
        "_Generated by MarketMasteryAI Bot_",
    ]
    await msg.edit_text("\n".join(L), parse_mode="Markdown")

# ─────────────────────────────────────────────────────────────────────────────
# /sentiment
# ─────────────────────────────────────────────────────────────────────────────

async def sentiment_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = context.args
    if not args:
        await update.message.reply_text(
            "Usage: `/sentiment RELIANCE.NS`\n\nFetches recent news and gives a sentiment summary.",
            parse_mode="Markdown",
        )
        return

    ticker = clean_ticker(args[0])
    if not is_valid_ticker(ticker):
        await update.message.reply_text(
            f"❌ `{ticker}` is not a valid ticker.", parse_mode="Markdown"
        )
        return

    msg = await update.message.reply_text(f"📰 Fetching news for `{ticker}`…", parse_mode="Markdown")
    try:
        s = await asyncio.to_thread(fetch_sentiment, ticker)
    except Exception as e:
        logger.exception(f"/sentiment [{ticker}]: {e}")
        await msg.edit_text(
            f"⚠️ Could not fetch news for `{ticker}`.\n"
            "_Yahoo Finance news may be unavailable for this ticker._",
            parse_mode="Markdown",
        )
        return

    overall = s["overall"]
    o_icon  = "🟢 BULLISH" if overall == "BULLISH" else ("🔴 BEARISH" if overall == "BEARISH" else "🟡 NEUTRAL")

    L = [
        f"📰 *News Sentiment — `{ticker}`*",
        "━━━━━━━━━━━━━━━━━━━━",
        "",
        f"Verdict: *{o_icon}*",
        f"Scanned: `{s['total']}` articles",
        f"🟢`{s['bullish']}` 🔴`{s['bearish']}` 🟡`{s['neutral']}`",
        "",
    ]
    if s.get("headlines"):
        L.append("*Recent headlines:*")
        L.append("")
        for h in s["headlines"]:
            icon  = "🟢" if h["score"] > 0 else ("🔴" if h["score"] < 0 else "🟡")
            title = h["title"][:90] + ("…" if len(h["title"]) > 90 else "")
            L.append(f"{icon} {title}")
    else:
        L.append("_No recent headlines found._")

    L += ["", "⚠️ _Keyword-based sentiment. Verify news independently._"]
    await msg.edit_text("\n".join(L), parse_mode="Markdown")

# ─────────────────────────────────────────────────────────────────────────────
# /risk — Position sizing
# ─────────────────────────────────────────────────────────────────────────────

async def risk_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = context.args
    if len(args) < 2:
        await update.message.reply_text(
            "Usage: `/risk TICKER CAPITAL [RISK%]`\n\n"
            "Examples:\n"
            "  `/risk RELIANCE.NS 100000`    _(2% risk default)_\n"
            "  `/risk TCS.NS 50000 1`         _(1% risk)_\n"
            "  `/risk HDFCBANK.NS 200000 3`   _(3% risk)_",
            parse_mode="Markdown",
        )
        return

    ticker = clean_ticker(args[0])
    if not is_valid_ticker(ticker):
        await update.message.reply_text(
            f"❌ `{ticker}` is not a valid ticker.", parse_mode="Markdown"
        )
        return

    try:
        capital = float(args[1].replace(",", "").replace("₹", "").replace("$", ""))
        if capital <= 0:
            raise ValueError()
    except ValueError:
        await update.message.reply_text(
            "❌ Invalid capital amount.\nExample: `/risk RELIANCE.NS 100000`",
            parse_mode="Markdown",
        )
        return

    risk_pct = 2.0
    if len(args) >= 3:
        try:
            risk_pct = max(0.1, min(float(args[2].replace("%", "")), 20.0))
        except ValueError:
            pass

    msg = await update.message.reply_text(f"📐 Calculating for `{ticker}`…", parse_mode="Markdown")
    try:
        data = await asyncio.to_thread(analyze, ticker)
    except ValueError as e:
        await msg.edit_text(f"❌ *Not found:* `{ticker}`\n\n_{e}_", parse_mode="Markdown")
        return
    except Exception as e:
        logger.exception(f"/risk [{ticker}]: {e}")
        await msg.edit_text(f"⚠️ Could not fetch `{ticker}`. Try again shortly.", parse_mode="Markdown")
        return

    price     = data["last_close"]
    swing     = data["swing"]
    stop_loss = swing["stop_loss"]
    target1   = swing["target1"]
    target2   = swing["target2"]
    atr       = swing["atr"]
    direction = swing["direction"]
    sig       = data["signal"]["action"]
    bull_n    = data["signal"].get("bull_count", 3)

    rps = abs(price - stop_loss)
    if rps == 0:
        await msg.edit_text("⚠️ Stop loss equals price — cannot size position.", parse_mode="Markdown")
        return

    max_risk = round(capital * (risk_pct / 100), 2)
    shares   = max(1, int(max_risk / rps))
    pos_val  = round(shares * price, 2)
    act_risk = round(shares * rps, 2)
    act_pct  = round(act_risk / capital * 100, 2)
    rw1      = round(shares * abs(target1 - price), 2)
    rw2      = round(shares * abs(target2 - price), 2)
    rr1      = round(rw1 / act_risk, 1) if act_risk else 0
    rr2      = round(rw2 / act_risk, 1) if act_risk else 0
    leftover = round(capital - pos_val, 2)
    curr     = "₹" if is_indian(ticker) else "$"
    d_arrow  = "⬆️" if direction == "LONG" else "⬇️"
    fits     = pos_val <= capital

    L = [
        f"📐 *Position Sizing — `{ticker}`*",
        "━━━━━━━━━━━━━━━━━━━━",
        "",
        f"💰 Price: `{fmt(price, ticker)}` | {sig_icon(sig)} {sig}  _{bull_n}/6_",
        f"📊 ATR(14): `{fmt(atr, ticker)}`  {d_arrow} {direction}",
        "",
        "─────────────────────",
        f"💼 Capital:      `{curr}{capital:,.0f}`",
        f"⚠️ Risk/trade:   `{risk_pct}%` = `{curr}{max_risk:,.0f}`",
        "",
        "─────────────────────",
        "*Position:*",
        f"  Qty:   `{shares:,}` shares",
        f"  Value: `{curr}{pos_val:,.0f}`" + (" ✅" if fits else " ⚠️ exceeds capital"),
        f"  Cash remaining: `{curr}{max(leftover, 0):,.0f}`",
        "",
        "─────────────────────",
        "*Risk:*",
        f"  Entry:    `{fmt(price,     ticker)}`",
        f"  Stop:     `{fmt(stop_loss, ticker)}`  (−`{fmt(round(rps,2), ticker)}`/share)",
        f"  Max loss: `{curr}{act_risk:,.0f}` ({act_pct}%)",
        "",
        "─────────────────────",
        "*Targets:*",
        f"  T1: `{fmt(target1,ticker)}` → `{curr}{rw1:,.0f}` R:R `{rr1}x`" + (" ✅" if rr1 >= 2 else " ⚠️"),
        f"  T2: `{fmt(target2,ticker)}` → `{curr}{rw2:,.0f}` R:R `{rr2}x`" + (" ✅" if rr2 >= 2 else " ⚠️"),
        "",
        "━━━━━━━━━━━━━━━━━━━━",
        f"_Change risk: `/risk {ticker} {int(capital)} 1`_",
        DISCLAIMER,
    ]
    await msg.edit_text("\n".join(L), parse_mode="Markdown")

# ─────────────────────────────────────────────────────────────────────────────
# Trade journal handlers
# ─────────────────────────────────────────────────────────────────────────────

async def journal_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = context.args
    if len(args) < 4:
        await update.message.reply_text(
            "Usage: `/journal TICKER DIRECTION ENTRY EXIT [SHARES]`\n\n"
            "Examples:\n"
            "  `/journal TCS.NS long 3800 4100 10`\n"
            "  `/journal RELIANCE.NS short 2900 2750 5`\n\n"
            "_Direction: `long` or `short` | Shares default: 1_",
            parse_mode="Markdown",
        )
        return

    ticker = clean_ticker(args[0])
    if not is_valid_ticker(ticker):
        await update.message.reply_text(f"❌ Invalid ticker: `{ticker}`", parse_mode="Markdown")
        return

    direction = args[1].lower().strip()
    if direction not in ("long", "short"):
        await update.message.reply_text("❌ Direction must be `long` or `short`.", parse_mode="Markdown")
        return

    def _parse_num(s: str) -> float:
        return float(s.replace("₹", "").replace("$", "").replace(",", ""))

    try:
        entry  = _parse_num(args[2])
        exit_p = _parse_num(args[3])
        shares = _parse_num(args[4]) if len(args) >= 5 else 1.0
        if entry <= 0 or exit_p <= 0 or shares <= 0:
            raise ValueError()
    except ValueError:
        await update.message.reply_text(
            "❌ Invalid numbers.\nExample: `/journal TCS.NS long 3800 4100 10`",
            parse_mode="Markdown",
        )
        return

    uid   = update.effective_user.id
    trade = add_trade(uid, ticker, direction, entry, exit_p, shares)
    w_icon = "✅ Win" if trade["won"] else "❌ Loss"
    d_icon = "⬆️" if trade["direction"] == "LONG" else "⬇️"

    await update.message.reply_text(
        f"📒 *Trade logged!* #{trade['id']}\n\n"
        f"{d_icon} *{ticker}* {trade['direction']} × {trade['shares']} shares\n"
        f"  Entry: `{fmt(trade['entry'], ticker)}` → Exit: `{fmt(trade['exit'], ticker)}`\n"
        f"  P&L:   `{fmt_pnl(trade['pnl'], ticker)}` ({trade['pnl_pct']}%)  — {w_icon}\n\n"
        "_/trades for history | /pnl for stats_",
        parse_mode="Markdown",
    )


async def trades_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid    = update.effective_user.id
    trades = get_trades(uid)
    if not trades:
        await update.message.reply_text(
            "📒 No trades yet.\n\nUse `/journal TCS.NS long 3800 4100 10` to log one.",
            parse_mode="Markdown",
        )
        return

    recent = list(reversed(trades[-15:]))
    L = [f"📒 *Trade Journal* ({len(trades)} total, showing last {min(15, len(trades))})", "━━━━━━━━━━━━━━━━━━━━", ""]
    for t in recent:
        w  = "✅" if t["won"] else "❌"
        d  = "⬆️" if t["direction"] == "LONG" else "⬇️"
        L.append(
            f"{w} #{t['id']} {d} *{t['ticker']}* `{t['date']}`\n"
            f"  `{fmt(t['entry'], t['ticker'])}` → `{fmt(t['exit'], t['ticker'])}` ×{t['shares']}\n"
            f"  `{fmt_pnl(t['pnl'], t['ticker'])}` ({t['pnl_pct']}%)"
        )
        L.append("")
    L.append("_/pnl for stats | `/deltrade ID` to remove_")
    await update.message.reply_text("\n".join(L), parse_mode="Markdown")


async def pnl_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid   = update.effective_user.id
    stats = get_pnl_stats(uid)
    if not stats:
        await update.message.reply_text(
            "📊 No trades yet.\n\nUse `/journal TCS.NS long 3800 4100 10`",
            parse_mode="Markdown",
        )
        return

    best  = stats["best"]
    worst = stats["worst"]
    pf    = str(stats["profit_factor"]) if stats["profit_factor"] != float("inf") else "∞"
    p_icon = "🟢" if stats["total_pnl"] >= 0 else "🔴"
    bt    = best.get("ticker", "")
    wt    = worst.get("ticker", "")

    L = [
        "📊 *P&L Statistics*",
        "━━━━━━━━━━━━━━━━━━━━",
        "",
        f"{p_icon} *Total P&L:* `{fmt_pnl(stats['total_pnl'], bt)}`",
        f"📈 Win Rate: `{stats['win_rate']}%` ({stats['wins']}W / {stats['losses']}L / {stats['total']} trades)",
        f"⚖️ Profit Factor: `{pf}`",
        "",
        "─────────────────────",
        f"✅ Avg Win:  `{fmt_pnl(stats['avg_win'],         bt)}`",
        f"❌ Avg Loss: `{fmt_pnl(abs(stats['avg_loss']),   wt)}`",
        "",
        "─────────────────────",
        f"🏆 Best:  #{best['id']}  {best['ticker']}  `{fmt_pnl(best['pnl'],   bt)}` ({best['pnl_pct']}%)",
        f"💥 Worst: #{worst['id']} {worst['ticker']} `{fmt_pnl(worst['pnl'],  wt)}` ({worst['pnl_pct']}%)",
        "",
        "━━━━━━━━━━━━━━━━━━━━",
    ]

    if stats["win_rate"] >= 60 and stats["total_pnl"] > 0:
        L.append("💡 _Solid performance — stay disciplined._")
    elif stats["profit_factor"] and stats["profit_factor"] != float("inf") and stats["profit_factor"] < 1:
        L.append("💡 _Profit factor < 1 — losses outweigh gains. Review entries._")
    elif stats["win_rate"] < 40:
        L.append("💡 _Low win rate — tighten your entry criteria._")
    elif stats["total_pnl"] < 0:
        L.append("💡 _Net loss despite wins — average loss > average win._")
    else:
        L.append("💡 _Keep journaling consistently to track your edge._")

    await update.message.reply_text("\n".join(L), parse_mode="Markdown")


async def deltrade_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = context.args
    if not args:
        await update.message.reply_text("Usage: `/deltrade 3`\n\nUse /trades to find trade IDs.", parse_mode="Markdown")
        return
    try:
        tid = int(args[0])
    except ValueError:
        await update.message.reply_text("❌ Provide a valid trade ID number.", parse_mode="Markdown")
        return

    removed = delete_trade(update.effective_user.id, tid)
    if removed:
        await update.message.reply_text(f"🗑️ Trade #{tid} deleted.", parse_mode="Markdown")
    else:
        await update.message.reply_text(
            f"⚠️ No trade found with ID #{tid}.\nUse /trades to see your trade IDs.",
            parse_mode="Markdown",
        )


async def streak_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid  = update.effective_user.id
    data = get_streak_and_equity(uid)
    if not data:
        await update.message.reply_text(
            "📒 No trades logged yet.\n\nUse `/journal TCS.NS long 3800 4100 10`",
            parse_mode="Markdown",
        )
        return

    s_icon  = "🔥" if data["streak_type"] == "win" else "🧊"
    s_label = "Win streak" if data["streak_type"] == "win" else "Loss streak"
    s_msg   = (
        f"On a *{data['streak_count']}-trade {s_label}!* 💪"
        if data["streak_type"] == "win"
        else f"On a *{data['streak_count']}-trade {s_label}.* Stay patient."
    )

    pnl    = data["final_pnl"]
    p_icon = "🟢" if pnl >= 0 else "🔴"
    cum    = data["cumulative"]
    n      = data["trade_count"]

    L = [
        "📈 *Streak & Equity Curve*",
        "━━━━━━━━━━━━━━━━━━━━",
        "",
        f"{s_icon} *Current:* {data['streak_count']}× {s_label.lower()}",
        s_msg,
        "",
        "─────────────────────",
        f"🏆 Longest win streak:  `{data['longest_win']}` trades",
        f"💥 Longest loss streak: `{data['longest_loss']}` trades",
        "",
        "─────────────────────",
        f"📉 *Equity Curve* ({n} trades)",
        f"  `{data['sparkline']}`",
        f"  Peak: `{max(cum):,.2f}`  Low: `{min(cum):,.2f}`",
        "",
        "─────────────────────",
        f"{p_icon} *Cumulative P&L:* `{pnl:,.2f}`",
        f"📉 *Max Drawdown:*    `{data['max_drawdown']:,.2f}`",
        "",
        "━━━━━━━━━━━━━━━━━━━━",
        "_/pnl for full stats | /trades to review entries_",
    ]
    await update.message.reply_text("\n".join(L), parse_mode="Markdown")

# ─────────────────────────────────────────────────────────────────────────────
# /backtest
# ─────────────────────────────────────────────────────────────────────────────

async def backtest_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = context.args
    if not args:
        await update.message.reply_text(
            "Usage: `/backtest TICKER [PERIOD]`\n\n"
            "_EMA 9/21 crossover strategy on historical data._\n\n"
            "Periods: `6mo`  `1y`  `2y`  `5y`\n\n"
            "Examples:\n"
            "  `/backtest TCS.NS`\n"
            "  `/backtest RELIANCE.NS 2y`\n"
            "  `/backtest ^NSEI 5y`",
            parse_mode="Markdown",
        )
        return

    ticker = clean_ticker(args[0])
    if not is_valid_ticker(ticker):
        await update.message.reply_text(f"❌ Invalid ticker: `{ticker}`", parse_mode="Markdown")
        return

    period = args[1].lower().strip() if len(args) >= 2 else "1y"
    if period not in {"6mo", "1y", "2y", "5y"}:
        await update.message.reply_text(
            f"❌ Invalid period `{period}`.\nUse: `6mo`  `1y`  `2y`  `5y`",
            parse_mode="Markdown",
        )
        return

    msg = await update.message.reply_text(
        f"⚙️ Running EMA 9/21 backtest on `{ticker}` ({period})…", parse_mode="Markdown"
    )
    try:
        result = await asyncio.to_thread(run_backtest, ticker, period)
    except Exception as e:
        logger.exception(f"/backtest [{ticker}]: {e}")
        await msg.edit_text(f"❌ Could not fetch data for `{ticker}`.", parse_mode="Markdown")
        return

    if result is None:
        await msg.edit_text(
            f"⚠️ Not enough data for `{ticker}` over `{period}`.\n"
            "Try a longer period or a more liquid ticker.",
            parse_mode="Markdown",
        )
        return

    if result["total"] == 0:
        await msg.edit_text(
            f"📊 *Backtest — `{ticker}` ({period})*\n\n"
            "No EMA 9/21 crossovers found in this period.\n"
            f"Buy & Hold return: `{'+' if result['buy_hold'] >= 0 else ''}{result['buy_hold']}%`",
            parse_mode="Markdown",
        )
        return

    r      = result
    vs_bh  = round(r["total_return"] - r["buy_hold"], 2)
    pf_str = str(r["profit_factor"]) if r["profit_factor"] != float("inf") else "∞"

    def pct(v): return f"+{v}%" if v >= 0 else f"{v}%"

    recent = r["trades"][-5:]
    trade_lines = [
        f"  {'✅' if t['won'] else '❌'} `{t['entry_date']}→{t['exit_date']}`  `{pct(t['pnl_pct'])}`"
        + (" 🔓open" if t.get("open") else "")
        for t in recent
    ]

    L = [
        f"📊 *Backtest — `{ticker}` ({period})*",
        "_Strategy: EMA 9/21 crossover (long only)_",
        "━━━━━━━━━━━━━━━━━━━━",
        "",
        f"*Results:*",
        f"  Trades:     `{r['total']}` ({r['wins']}W / {r['losses']}L)",
        f"  Win rate:   `{r['win_rate']}%`",
        f"  Profit fac: `{pf_str}`",
        "",
        "─────────────────────",
        f"*Returns:*",
        f"  {'🟢' if r['total_return'] >= 0 else '🔴'} Strategy:    `{pct(r['total_return'])}`",
        f"  {'🟢' if r['buy_hold']     >= 0 else '🔴'} Buy & Hold:  `{pct(r['buy_hold'])}`",
        f"  {'✅' if vs_bh >= 0 else '❌'} Outperforms: `{pct(vs_bh)}`",
        "",
        "─────────────────────",
        f"*Per-trade stats:*",
        f"  Avg win:    `+{r['avg_win']}%`",
        f"  Avg loss:   `{r['avg_loss']}%`",
        f"  Max DD:     `-{r['max_drawdown']}%`",
        "",
        "─────────────────────",
        f"*Equity curve:*",
        f"  `{r['sparkline']}`",
        "",
        f"*Last {len(recent)} trades:*",
    ] + trade_lines + [
        "",
        "━━━━━━━━━━━━━━━━━━━━",
        "_🔓 = trade still open at period end_",
        "_Past performance ≠ future results._",
        DISCLAIMER,
    ]
    await msg.edit_text("\n".join(L), parse_mode="Markdown")

# ─────────────────────────────────────────────────────────────────────────────
# Watchlist handlers
# ─────────────────────────────────────────────────────────────────────────────

async def watchlist_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid     = update.effective_user.id
    tickers = get_watchlist(uid)
    if not tickers:
        await update.message.reply_text(
            "📋 Your watchlist is empty.\n\nUse `/add TCS.NS RELIANCE.NS` to add stocks.",
            parse_mode="Markdown",
        )
        return
    L = ["📋 *Your Watchlist:*", ""]
    for i, t in enumerate(tickers, 1):
        flag = "🇮🇳" if is_indian(t) else "🇺🇸"
        L.append(f"  {i}. `{t}` {flag}")
    L += ["", "Use /scan to analyse all  |  /setalert 03:45 for daily alerts"]
    await update.message.reply_text("\n".join(L), parse_mode="Markdown")


async def add_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid  = update.effective_user.id
    args = context.args
    if not args:
        await update.message.reply_text(
            "Usage: `/add TCS.NS RELIANCE.NS HDFCBANK.NS`", parse_mode="Markdown"
        )
        return

    valid   = [clean_ticker(a) for a in args if is_valid_ticker(clean_ticker(a))]
    invalid = [a for a in args if not is_valid_ticker(clean_ticker(a))]

    if not valid:
        await update.message.reply_text("❌ No valid tickers provided.", parse_mode="Markdown")
        return

    added, already = add_tickers(uid, valid)
    L = []
    if added:
        L.append("✅ Added: " + " ".join(f"`{t}`" for t in added))
    if already:
        L.append("ℹ️ Already in watchlist: " + " ".join(f"`{t}`" for t in already))
    if invalid:
        L.append("⚠️ Invalid, skipped: " + " ".join(f"`{t}`" for t in invalid))
    total = get_watchlist(uid)
    L.append(f"\n📋 Watchlist: *{len(total)}* ticker(s).")
    await update.message.reply_text("\n".join(L), parse_mode="Markdown")


async def remove_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid  = update.effective_user.id
    args = context.args
    if not args:
        await update.message.reply_text("Usage: `/remove TCS.NS RELIANCE.NS`", parse_mode="Markdown")
        return
    tickers             = [clean_ticker(a) for a in args]
    removed, not_found  = remove_tickers(uid, tickers)
    L = []
    if removed:
        L.append("🗑️ Removed: " + " ".join(f"`{t}`" for t in removed))
    if not_found:
        L.append("⚠️ Not in watchlist: " + " ".join(f"`{t}`" for t in not_found))
    total = get_watchlist(uid)
    L.append(f"\n📋 Watchlist: *{len(total)}* ticker(s).")
    await update.message.reply_text("\n".join(L), parse_mode="Markdown")


async def clear_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    clear_watchlist(update.effective_user.id)
    await update.message.reply_text("🗑️ Watchlist cleared.", parse_mode="Markdown")


async def scan_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid     = update.effective_user.id
    tickers = get_watchlist(uid)
    if not tickers:
        await update.message.reply_text(
            "📋 Watchlist is empty.\n\nUse `/add TCS.NS RELIANCE.NS` to add stocks.",
            parse_mode="Markdown",
        )
        return
    msg      = await update.message.reply_text(
        f"🔍 Scanning *{len(tickers)}* ticker(s) in parallel…", parse_mode="Markdown"
    )
    results  = await _fetch_many(tickers)
    await msg.edit_text(_build_scan_message(tickers, results), parse_mode="Markdown")

# ─────────────────────────────────────────────────────────────────────────────
# Alert schedule handlers
# ─────────────────────────────────────────────────────────────────────────────

async def setalert_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid     = update.effective_user.id
    chat_id = update.effective_chat.id
    args    = context.args
    if not args:
        await update.message.reply_text(
            "Usage: `/setalert HH:MM` _(24-hour UTC)_\n\n"
            "Example: `/setalert 03:45`\n"
            "_3:45 AM UTC = 9:15 AM IST — NSE market open_",
            parse_mode="Markdown",
        )
        return
    try:
        h, m = args[0].split(":")
        hour, minute = int(h), int(m)
        if not (0 <= hour <= 23 and 0 <= minute <= 59):
            raise ValueError()
    except (ValueError, AttributeError):
        await update.message.reply_text(
            "❌ Invalid time. Use HH:MM (24-hour UTC).\nExample: `/setalert 03:45`",
            parse_mode="Markdown",
        )
        return

    set_alert(uid, chat_id, hour, minute)
    _schedule_alert(context.application, uid, chat_id, hour, minute)
    tickers = get_watchlist(uid)
    wl_note = (
        f"Your watchlist has *{len(tickers)}* ticker(s)."
        if tickers
        else "Watchlist is empty — use `/add TCS.NS RELIANCE.NS` to add stocks first."
    )
    await update.message.reply_text(
        f"⏰ Daily alert set for *{hour:02d}:{minute:02d} UTC* every day.\n\n{wl_note}",
        parse_mode="Markdown",
    )


async def myalert_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid   = update.effective_user.id
    alert = get_alert(uid)
    if not alert:
        await update.message.reply_text(
            "No daily alert set.\nUse `/setalert 03:45` to set one.", parse_mode="Markdown"
        )
        return
    h, m = alert["hour"], alert["minute"]
    await update.message.reply_text(
        f"⏰ Daily alert: *{h:02d}:{m:02d} UTC* every day.\n\nUse /cancelalert to remove.",
        parse_mode="Markdown",
    )


async def cancelalert_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid     = update.effective_user.id
    removed = remove_alert(uid)
    for job in context.application.job_queue.get_jobs_by_name(f"alert_{uid}"):
        job.schedule_removal()
    msg = "✅ Daily alert cancelled." if removed else "No active daily alert found."
    await update.message.reply_text(msg, parse_mode="Markdown")

# ─────────────────────────────────────────────────────────────────────────────
# Price alerts
# ─────────────────────────────────────────────────────────────────────────────

async def check_price_alerts(context):
    import yfinance as yf
    all_alerts = get_all_price_alerts()
    for uid_str, alerts in all_alerts.items():
        uid = int(uid_str)
        for alert in list(alerts):
            ticker    = alert["ticker"]
            condition = alert["condition"]
            target    = alert["target"]
            chat_id   = alert["chat_id"]
            alert_id  = alert["id"]
            try:
                fi    = yf.Ticker(ticker).fast_info
                price = getattr(fi, "last_price", None)
                if price is None:
                    price = yf.Ticker(ticker).history(period="1d")["Close"].iloc[-1]
                price     = round(float(price), 2)
                triggered = (
                    (condition == "above" and price >= target) or
                    (condition == "below" and price <= target)
                )
                if triggered:
                    arrow = "⬆️" if condition == "above" else "⬇️"
                    await context.bot.send_message(
                        chat_id=chat_id,
                        text=(
                            f"🔔 *Price Alert Triggered!*\n\n"
                            f"{arrow} *{ticker}* is now `{fmt(price, ticker)}`\n"
                            f"Your target: {condition} `{fmt(target, ticker)}`\n\n"
                            f"_Type `{ticker}` for a full analysis._\n\n"
                            + DISCLAIMER
                        ),
                        parse_mode="Markdown",
                    )
                    remove_triggered_alert(uid, alert_id)
                    logger.info(f"Alert fired: {ticker} {condition} {target} user {uid}")
            except Exception as e:
                logger.warning(f"Alert check error [{ticker}] user {uid}: {e}")


async def alert_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = context.args
    if len(args) < 3:
        await update.message.reply_text(
            "Usage: `/alert TICKER above PRICE`\n\n"
            "Examples:\n"
            "  `/alert RELIANCE.NS above 3000`\n"
            "  `/alert TCS.NS below 3500`\n\n"
            "_Fires once when price crosses your target._\n"
            "_Checked every 15 minutes._",
            parse_mode="Markdown",
        )
        return

    ticker = clean_ticker(args[0])
    if not is_valid_ticker(ticker):
        await update.message.reply_text(f"❌ Invalid ticker: `{ticker}`", parse_mode="Markdown")
        return

    condition = args[1].lower().strip()
    if condition not in ("above", "below"):
        await update.message.reply_text("❌ Condition must be `above` or `below`.", parse_mode="Markdown")
        return

    try:
        target = float(args[2].replace("₹", "").replace("$", "").replace(",", ""))
        if target <= 0:
            raise ValueError()
    except ValueError:
        await update.message.reply_text("❌ Invalid price value.", parse_mode="Markdown")
        return

    uid      = update.effective_user.id
    chat_id  = update.effective_chat.id
    alert_id = add_price_alert(uid, chat_id, ticker, condition, target)
    arrow    = "⬆️" if condition == "above" else "⬇️"

    await update.message.reply_text(
        f"🔔 *Alert set!* #{alert_id}\n\n"
        f"{arrow} Notify when *{ticker}* goes *{condition}* `{fmt(target, ticker)}`\n\n"
        "_Checked every 15 min. Use /alerts to manage._",
        parse_mode="Markdown",
    )


async def list_alerts_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid    = update.effective_user.id
    alerts = get_user_alerts(uid)
    if not alerts:
        await update.message.reply_text(
            "🔕 No active price alerts.\n\nUse `/alert RELIANCE.NS above 3000` to set one.",
            parse_mode="Markdown",
        )
        return
    L = ["🔔 *Your Price Alerts:*", ""]
    for a in alerts:
        arrow = "⬆️" if a["condition"] == "above" else "⬇️"
        L.append(f"  #{a['id']} {arrow} *{a['ticker']}* {a['condition']} `{fmt(a['target'], a['ticker'])}`")
    L += ["", "_Use `/delalert ID` to cancel._"]
    await update.message.reply_text("\n".join(L), parse_mode="Markdown")


async def delalert_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = context.args
    if not args:
        await update.message.reply_text("Usage: `/delalert 1`\n\nUse /alerts to see IDs.", parse_mode="Markdown")
        return
    try:
        alert_id = int(args[0])
    except ValueError:
        await update.message.reply_text("❌ Provide a valid alert ID number.", parse_mode="Markdown")
        return

    uid     = update.effective_user.id
    removed = remove_price_alert(uid, alert_id)
    if removed:
        await update.message.reply_text(f"✅ Alert #{alert_id} cancelled.", parse_mode="Markdown")
    else:
        await update.message.reply_text(
            f"⚠️ No alert #{alert_id} found.\nUse /alerts to see your active alerts.",
            parse_mode="Markdown",
        )

# ─────────────────────────────────────────────────────────────────────────────
# Restore saved daily alerts on startup
# ─────────────────────────────────────────────────────────────────────────────

async def restore_alerts(app):
    all_saved = get_all_alerts()
    count = 0
    for uid_str, cfg in all_saved.items():
        try:
            _schedule_alert(app, int(uid_str), cfg["chat_id"], cfg["hour"], cfg["minute"])
            count += 1
        except Exception as e:
            logger.warning(f"Failed to restore alert for user {uid_str}: {e}")
    if count:
        logger.info(f"Restored {count} daily alert(s) on startup.")

# ─────────────────────────────────────────────────────────────────────────────
# main()
# ─────────────────────────────────────────────────────────────────────────────

def main():
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    if not token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN environment variable not set.")

    app = ApplicationBuilder().token(token).post_init(restore_alerts).build()

    # Price alert check every 15 minutes
    app.job_queue.run_repeating(check_price_alerts, interval=900, first=60)

    # Analysis
    app.add_handler(CommandHandler("start",       start_handler))
    app.add_handler(CommandHandler("help",        help_handler))
    app.add_handler(CommandHandler("nifty",       nifty_handler))
    app.add_handler(CommandHandler("signal",      signal_handler))
    app.add_handler(CommandHandler("swing",       swing_handler))
    app.add_handler(CommandHandler("intraday",    intraday_handler))
    app.add_handler(CommandHandler("summary",     summary_handler))
    app.add_handler(CommandHandler("report",      report_handler))
    app.add_handler(CommandHandler("sentiment",   sentiment_handler))

    # Screeners
    app.add_handler(CommandHandler("top",         top_handler))
    app.add_handler(CommandHandler("movers",      movers_handler))
    app.add_handler(CommandHandler("compare",     compare_handler))
    app.add_handler(CommandHandler("breakout",    breakout_handler))
    app.add_handler(CommandHandler("gainers52w",  gainers52w_handler))
    app.add_handler(CommandHandler("oversold",    oversold_handler))
    app.add_handler(CommandHandler("sector",      sector_handler))
    app.add_handler(CommandHandler("heatmap",     heatmap_handler))

    # Watchlist
    app.add_handler(CommandHandler("watchlist",   watchlist_handler))
    app.add_handler(CommandHandler("add",         add_handler))
    app.add_handler(CommandHandler("remove",      remove_handler))
    app.add_handler(CommandHandler("clear",       clear_handler))
    app.add_handler(CommandHandler("scan",        scan_handler))

    # Alert schedule
    app.add_handler(CommandHandler("setalert",    setalert_handler))
    app.add_handler(CommandHandler("myalert",     myalert_handler))
    app.add_handler(CommandHandler("cancelalert", cancelalert_handler))

    # Price alerts
    app.add_handler(CommandHandler("alert",       alert_handler))
    app.add_handler(CommandHandler("alerts",      list_alerts_handler))
    app.add_handler(CommandHandler("delalert",    delalert_handler))

    # Risk & backtest
    app.add_handler(CommandHandler("risk",        risk_handler))
    app.add_handler(CommandHandler("backtest",    backtest_handler))

    # Journal
    app.add_handler(CommandHandler("journal",     journal_handler))
    app.add_handler(CommandHandler("trades",      trades_handler))
    app.add_handler(CommandHandler("pnl",         pnl_handler))
    app.add_handler(CommandHandler("deltrade",    deltrade_handler))
    app.add_handler(CommandHandler("streak",      streak_handler))

    # Ticker catch-all (must be last)
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, analyze_handler))

    logger.info("MarketMasteryAI Bot starting — all handlers registered.")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
