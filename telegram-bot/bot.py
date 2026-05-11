import os
import logging
from datetime import time as dtime
from telegram import Update
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler,
    filters, ContextTypes,
)
from analysis import analyze
from formatter import format_report
from watchlist import get_watchlist, add_tickers, remove_tickers, clear_watchlist
from alerts import set_alert, remove_alert, get_alert, get_all_alerts
from sentiment import fetch_sentiment
from journal import add_trade, get_trades, delete_trade, get_pnl_stats, get_streak_and_equity
from backtest import run_backtest
from utils import (
    fmt, fmt_pnl, fmt_macd, sig_icon,
    chg_str, chg_emoji, rsi_zone, is_indian,
    market_status_ist,
)
from price_alerts import (
    add_price_alert, get_user_alerts, remove_price_alert,
    remove_triggered_alert, get_all_price_alerts,
)

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

DISCLAIMER = "⚠️ _Educational only. Not financial advice. Consult a SEBI-registered advisor._"

# ─────────────────────────────────────────────────────────────────────────────
# Help & About text
# ─────────────────────────────────────────────────────────────────────────────

HELP_TEXT = """
🤖 *MarketMasteryAI Bot — Command Reference*

━━━━━━━━━━━━━━━━━━━━
📌 *Quick Analysis*
Just type any ticker for a full analysis:
  `RELIANCE.NS`  `TCS.NS`  `^NSEI`

━━━━━━━━━━━━━━━━━━━━
📊 *Analysis Commands*
/signal `TICKER` — Quick AI signal card
/swing `TICKER`  — Swing trade setup
/intraday `TICKER` — Intraday bias & levels
/summary `TICKER` — Technicals + news brief
/report `TICKER` — Full printable report
/sentiment `TICKER` — News sentiment

━━━━━━━━━━━━━━━━━━━━
🇮🇳 *Indian Market*
/nifty — NSE dashboard (Nifty + breadth)
/breakout — Active breakouts (Indian stocks)
/top — Top signals (Indian stocks)
/top us — Top signals (US stocks)
/movers — Today's gainers & losers
/movers us — US movers
/heatmap — Signal heatmap (NSE stocks)
/sector — Sector strength overview

━━━━━━━━━━━━━━━━━━━━
🔍 *Screeners*
/gainers52w — Near 52-week highs + bullish
/gainers52w india — Indian only
/gainers52w us — US only
/oversold — Oversold dip-buy setups
/oversold india — Indian only
/compare `A B C` — Side-by-side (2–6 tickers)

━━━━━━━━━━━━━━━━━━━━
📋 *Watchlist*
/watchlist — View saved tickers
/add `TCS.NS INFY.NS` — Add tickers
/remove `TCS.NS` — Remove ticker
/scan — Analyse full watchlist
/clear — Clear watchlist

━━━━━━━━━━━━━━━━━━━━
🔔 *Alerts*
/alert `RELIANCE.NS above 3000` — Price alert
/alerts — View active alerts
/delalert `1` — Cancel alert by ID
/setalert `03:45` — Daily scan (UTC time)
/myalert — Check daily alert time
/cancelalert — Cancel daily alert

━━━━━━━━━━━━━━━━━━━━
📒 *Trade Journal*
/journal `TCS.NS long 3800 4100 10`
/trades — View trade history
/pnl — P&L stats & profit factor
/streak — Win streak & equity curve
/deltrade `3` — Delete trade by ID

━━━━━━━━━━━━━━━━━━━━
📐 *Risk & Backtesting*
/risk `RELIANCE.NS 100000` — Position sizing
/risk `RELIANCE.NS 100000 1` — 1% risk
/backtest `TCS.NS` — EMA 9/21 backtest (1y)
/backtest `TCS.NS 2y` — 6mo 1y 2y 5y

━━━━━━━━━━━━━━━━━━━━
🇮🇳 *Indian Ticker Tips*
  NSE: `TCS.NS`  `RELIANCE.NS`
  BSE: `TCS.BO`  `RELIANCE.BO`
  Nifty 50:    `^NSEI`
  Bank Nifty:  `^NSEBANK`
  NSE hours:   9:15 AM – 3:30 PM IST
  Daily alert: Use UTC (IST = UTC+5:30)

⚠️ _Educational only. Not financial advice._
"""

ABOUT_TEXT = """
🤖 *MarketMasteryAI Bot*
_Premium AI-powered Indian stock market assistant_

━━━━━━━━━━━━━━━━━━━━
*Indicators computed:*
  RSI (14) — momentum oscillator
  EMA 9, 21, 50, 200 — trend direction
  MACD (12/26/9) — momentum crossover
  Bollinger Bands (20, 2σ) — volatility
  ATR (14) — average true range
  OBV — on-balance volume trend
  Support & Resistance (20-day high/low)

*Features:*
  🇮🇳 NSE/BSE stocks with ₹ INR pricing
  📊 AI Buy/Sell/Hold signals
  🏹 Swing setups with ATR-based SL & targets
  🚨 Breakout detection with volume confirmation
  📋 Personal watchlists & daily scan alerts
  🔔 Price alerts (checked every 15 min)
  📒 Trade journal & P&L tracking
  📈 Equity curve & streak tracker
  🧪 EMA crossover backtesting
  📐 Position sizing & risk calculator
  📰 News sentiment analysis

*Data:* Yahoo Finance via yfinance
*Indices:* ^NSEI, ^NSEBANK supported

⚠️ _Educational only. Not financial advice._
_Past performance ≠ future results._
"""

# ─────────────────────────────────────────────────────────────────────────────
# Stock lists
# ─────────────────────────────────────────────────────────────────────────────

TOP_INDIA = [
    "RELIANCE.NS", "TCS.NS",     "INFY.NS",      "HDFCBANK.NS",  "ICICIBANK.NS",
    "SBIN.NS",     "WIPRO.NS",   "BAJFINANCE.NS", "AXISBANK.NS",  "KOTAKBANK.NS",
    "LT.NS",       "MARUTI.NS",  "TATAMOTORS.NS", "SUNPHARMA.NS", "ADANIENT.NS",
    "HINDALCO.NS", "NTPC.NS",    "TATASTEEL.NS",  "BHARTIARTL.NS","POWERGRID.NS",
]

TOP_US = [
    "AAPL", "MSFT", "NVDA", "GOOGL", "AMZN",
    "META", "TSLA", "AMD",  "NFLX",  "JPM",
    "V",    "MA",   "BAC",  "DIS",   "INTC",
]

SIGNAL_RANK = {
    "STRONG BUY": 0, "STRONG SELL": 1,
    "BUY": 2,        "SELL": 3,
    "HOLD / NEUTRAL": 4,
}

SECTOR_MAP = {
    "RELIANCE.NS":   "⚡ Energy & Retail",
    "TCS.NS":        "💻 IT / Tech",
    "INFY.NS":       "💻 IT / Tech",
    "WIPRO.NS":      "💻 IT / Tech",
    "BHARTIARTL.NS": "📡 Telecom",
    "HDFCBANK.NS":   "🏦 Banking",
    "ICICIBANK.NS":  "🏦 Banking",
    "SBIN.NS":       "🏦 Banking",
    "AXISBANK.NS":   "🏦 Banking",
    "KOTAKBANK.NS":  "🏦 Banking",
    "BAJFINANCE.NS": "💰 NBFC",
    "LT.NS":         "🏗 Infra",
    "MARUTI.NS":     "🚗 Auto",
    "TATAMOTORS.NS": "🚗 Auto",
    "HINDALCO.NS":   "🔩 Metals",
    "TATASTEEL.NS":  "🔩 Metals",
    "NTPC.NS":       "⚡ Power",
    "POWERGRID.NS":  "⚡ Power",
    "SUNPHARMA.NS":  "💊 Pharma",
    "ADANIENT.NS":   "🏗 Infra",
    "AAPL":   "💻 Tech (US)",   "MSFT":  "💻 Tech (US)",
    "NVDA":   "💻 Tech (US)",   "GOOGL": "💻 Tech (US)",
    "AMZN":   "💻 Tech (US)",   "META":  "💻 Tech (US)",
    "AMD":    "💻 Tech (US)",   "INTC":  "💻 Tech (US)",
    "NFLX":   "🎬 Media (US)",  "DIS":   "🎬 Media (US)",
    "TSLA":   "🚗 Auto (US)",
    "JPM":    "🏦 Finance (US)", "V":    "🏦 Finance (US)",
    "MA":     "🏦 Finance (US)", "BAC":  "🏦 Finance (US)",
}

SECTOR_ORDER = [
    "💻 IT / Tech", "🏦 Banking", "💰 NBFC",
    "⚡ Energy & Retail", "⚡ Power", "📡 Telecom",
    "🚗 Auto", "🔩 Metals", "🏗 Infra", "💊 Pharma",
    "💻 Tech (US)", "🏦 Finance (US)", "🚗 Auto (US)", "🎬 Media (US)",
]

# ─────────────────────────────────────────────────────────────────────────────
# Shared helpers
# ─────────────────────────────────────────────────────────────────────────────

def _ticker_arg(args: list, default_indian: bool = True) -> tuple[list[str], str]:
    """Parse optional india/us/in argument from command args."""
    arg = " ".join(args).lower().strip() if args else ""
    if arg == "us":
        return TOP_US, "🇺🇸 US Stocks"
    if arg in ("india", "in"):
        return TOP_INDIA, "🇮🇳 Indian Stocks"
    if default_indian:
        return TOP_INDIA, "🇮🇳 Indian Stocks"
    return TOP_INDIA + TOP_US, "🌍 India + US"


def build_scan_message(tickers: list[str]) -> str:
    rows   = []
    errors = []
    for ticker in tickers:
        try:
            data    = analyze(ticker)
            sig     = data["signal"]["action"]
            brk     = data["breakout"]
            brk_tag = " 🚨↑" if brk["breakout_up"] else (" 💥↓" if brk["breakout_down"] else "")
            rows.append(
                f"{sig_icon(sig)} *{ticker}* `{fmt(data['last_close'], ticker)}` "
                f"({chg_str(data['change_pct'])}) RSI`{data['rsi']}`{brk_tag}"
            )
        except Exception as e:
            logger.warning(f"Scan error {ticker}: {e}")
            errors.append(f"⚠️ `{ticker}` — data unavailable")

    lines = [f"📊 *Watchlist Scan — {len(tickers)} ticker(s)*", "━━━━━━━━━━━━━━━━━━━━", ""]
    lines.extend(rows)
    if errors:
        lines.append("")
        lines.extend(errors)
    lines += ["", "_Tap any ticker for full analysis._", DISCLAIMER]
    return "\n".join(lines)

# ─────────────────────────────────────────────────────────────────────────────
# Daily alert job
# ─────────────────────────────────────────────────────────────────────────────

async def daily_alert_job(context):
    user_id = context.job.data["user_id"]
    chat_id = context.job.data["chat_id"]
    tickers = get_watchlist(user_id)
    if not tickers:
        await context.bot.send_message(
            chat_id=chat_id,
            text="⏰ *Daily Alert*\n\nYour watchlist is empty.\nUse `/add TCS.NS RELIANCE.NS` to add tickers.",
            parse_mode="Markdown",
        )
        return
    await context.bot.send_message(
        chat_id=chat_id,
        text="⏰ *Daily Watchlist Alert*\n\n" + build_scan_message(tickers),
        parse_mode="Markdown",
    )


def schedule_alert(app, user_id: int, chat_id: int, hour: int, minute: int):
    job_name = f"alert_{user_id}"
    for job in app.job_queue.get_jobs_by_name(job_name):
        job.schedule_removal()
    app.job_queue.run_daily(
        daily_alert_job,
        time=dtime(hour=hour, minute=minute),
        name=job_name,
        data={"user_id": user_id, "chat_id": chat_id},
    )

# ─────────────────────────────────────────────────────────────────────────────
# /start  /help  /about
# ─────────────────────────────────────────────────────────────────────────────

async def start_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🤖 *Welcome to MarketMasteryAI Bot!*\n"
        "_Your AI-powered Indian Stock Market Assistant_\n\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        "📌 *How to use:*\n"
        "Just type any ticker to get a full analysis:\n"
        "  `RELIANCE.NS` — Reliance Industries\n"
        "  `TCS.NS`      — Tata Consultancy Services\n"
        "  `HDFCBANK.NS` — HDFC Bank\n"
        "  `^NSEI`       — Nifty 50 Index\n"
        "  `^NSEBANK`    — Bank Nifty Index\n\n"
        "🎯 *Popular commands:*\n"
        "  /nifty         — NSE market dashboard\n"
        "  /signal TCS.NS — Quick AI signal card\n"
        "  /swing TCS.NS  — Swing trade setup\n"
        "  /breakout      — Active breakout stocks\n"
        "  /top           — Top signals right now\n"
        "  /heatmap       — Visual market heatmap\n\n"
        "📋 /help for the full command list\n\n"
        "🇮🇳 _Focused on NSE/BSE. Prices in ₹ INR._\n\n"
        + DISCLAIMER,
        parse_mode="Markdown",
    )


async def help_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(HELP_TEXT, parse_mode="Markdown")


async def about_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(ABOUT_TEXT, parse_mode="Markdown")

# ─────────────────────────────────────────────────────────────────────────────
# Watchlist handlers
# ─────────────────────────────────────────────────────────────────────────────

async def watchlist_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid     = update.effective_user.id
    tickers = get_watchlist(uid)
    if not tickers:
        await update.message.reply_text(
            "📋 Your watchlist is empty.\n\nUse `/add TCS.NS RELIANCE.NS` to add tickers.",
            parse_mode="Markdown",
        )
        return
    lines = ["📋 *Your Watchlist:*", ""]
    for i, t in enumerate(tickers, 1):
        flag = "🇮🇳" if is_indian(t) else "🇺🇸"
        lines.append(f"  {i}. `{t}` {flag}")
    lines += ["", "Use /scan to analyse all tickers.", "Use `/setalert 03:45` for a daily morning scan."]
    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


async def add_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid  = update.effective_user.id
    args = context.args
    if not args:
        await update.message.reply_text(
            "Usage: `/add TCS.NS RELIANCE.NS HDFCBANK.NS`", parse_mode="Markdown"
        )
        return
    added, already = add_tickers(uid, args)
    lines = []
    if added:
        lines.append("✅ Added: " + ", ".join(f"`{t}`" for t in added))
    if already:
        lines.append("ℹ️ Already saved: " + ", ".join(f"`{t}`" for t in already))
    total = get_watchlist(uid)
    lines.append(f"\n📋 Watchlist: *{len(total)}* ticker(s). Use /scan to analyse them.")
    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


async def remove_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid  = update.effective_user.id
    args = context.args
    if not args:
        await update.message.reply_text("Usage: `/remove TCS.NS RELIANCE.NS`", parse_mode="Markdown")
        return
    removed, not_found = remove_tickers(uid, args)
    lines = []
    if removed:
        lines.append("🗑️ Removed: " + ", ".join(f"`{t}`" for t in removed))
    if not_found:
        lines.append("⚠️ Not in watchlist: " + ", ".join(f"`{t}`" for t in not_found))
    total = get_watchlist(uid)
    lines.append(f"\n📋 Watchlist: *{len(total)}* ticker(s).")
    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


async def clear_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    clear_watchlist(update.effective_user.id)
    await update.message.reply_text("🗑️ Watchlist cleared.", parse_mode="Markdown")


async def scan_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid     = update.effective_user.id
    tickers = get_watchlist(uid)
    if not tickers:
        await update.message.reply_text(
            "📋 Watchlist is empty.\n\nUse `/add TCS.NS RELIANCE.NS` to add tickers.",
            parse_mode="Markdown",
        )
        return
    msg = await update.message.reply_text(
        f"🔍 Scanning *{len(tickers)}* ticker(s)...", parse_mode="Markdown"
    )
    await msg.edit_text(build_scan_message(tickers), parse_mode="Markdown")

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
            "_(3:45 AM UTC = 9:15 AM IST — NSE open)_",
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
            "❌ Invalid format. Use HH:MM (UTC).\nExample: `/setalert 03:45`",
            parse_mode="Markdown",
        )
        return

    set_alert(uid, chat_id, hour, minute)
    schedule_alert(context.application, uid, chat_id, hour, minute)
    tickers = get_watchlist(uid)
    wl_note = (
        f"Your watchlist has *{len(tickers)}* ticker(s)."
        if tickers
        else "Watchlist is empty — use `/add TCS.NS RELIANCE.NS` to add tickers."
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
            "No daily alert set.\n\nUse `/setalert 03:45` to set one.", parse_mode="Markdown"
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
    msg = "✅ Daily alert cancelled." if removed else "You don't have an active daily alert."
    await update.message.reply_text(msg, parse_mode="Markdown")

# ─────────────────────────────────────────────────────────────────────────────
# /nifty — NSE Market Dashboard
# ─────────────────────────────────────────────────────────────────────────────

async def nifty_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = await update.message.reply_text(
        "📊 Loading NSE Market Dashboard...", parse_mode="Markdown"
    )

    # Fetch index data
    index_data = {}
    for ticker in ["^NSEI", "^NSEBANK"]:
        try:
            index_data[ticker] = analyze(ticker)
        except Exception as e:
            logger.warning(f"Nifty index fetch error {ticker}: {e}")

    # Breadth scan
    breadth = {"STRONG BUY": 0, "BUY": 0, "HOLD / NEUTRAL": 0, "SELL": 0, "STRONG SELL": 0}
    movers  = []
    for ticker in TOP_INDIA:
        try:
            d   = analyze(ticker)
            sig = d["signal"]["action"]
            breadth[sig] = breadth.get(sig, 0) + 1
            movers.append({
                "ticker": ticker,
                "chg":    d["change_pct"],
                "rsi":    d["rsi"],
                "signal": sig,
                "price":  d["last_close"],
            })
        except Exception as e:
            logger.warning(f"Breadth scan error {ticker}: {e}")

    movers.sort(key=lambda x: x["chg"], reverse=True)
    gainers = movers[:3]
    losers  = list(reversed(movers[-3:])) if len(movers) >= 3 else []

    total_bull    = breadth.get("STRONG BUY", 0) + breadth.get("BUY", 0)
    total_bear    = breadth.get("STRONG SELL", 0) + breadth.get("SELL", 0)
    total_neutral = breadth.get("HOLD / NEUTRAL", 0)
    b_icon  = "🟢" if total_bull > total_bear else ("🔴" if total_bear > total_bull else "🟡")
    b_label = "Bullish" if total_bull > total_bear else ("Bearish" if total_bear > total_bull else "Neutral")

    status_str, time_str = market_status_ist()

    lines = ["📊 *NSE Market Dashboard*", "━━━━━━━━━━━━━━━━━━━━", ""]

    # Index cards
    index_labels = {"^NSEI": ("🔵", "Nifty 50"), "^NSEBANK": ("🏦", "Bank Nifty")}
    for ticker, (em, label) in index_labels.items():
        d = index_data.get(ticker)
        if d:
            ema_dir = "↑ Bull" if d["ema9"] > d["ema21"] else "↓ Bear"
            lines.append(
                f"{em} *{label}* `{fmt(d['last_close'], ticker)}` "
                f"{chg_emoji(d['change_pct'])} `{chg_str(d['change_pct'])}`"
            )
            lines.append(
                f"   RSI `{d['rsi']}` | EMA `{ema_dir}` | {sig_icon(d['signal']['action'])} {d['signal']['action']}"
            )
            lines.append("")
        else:
            lines.append(f"{em} *{label}* — data unavailable")
            lines.append("")

    # Market breadth
    lines.append("━━━━━━━━━━━━━━━━━━━━")
    lines.append(f"📊 *NSE Breadth ({len(movers)} stocks):* {b_icon} *{b_label}*")
    lines.append(
        f"  🟢🟢`{breadth.get('STRONG BUY',0)}` "
        f"🟢`{breadth.get('BUY',0)}` "
        f"🟡`{breadth.get('HOLD / NEUTRAL',0)}` "
        f"🔴`{breadth.get('SELL',0)}` "
        f"🔴🔴`{breadth.get('STRONG SELL',0)}`"
    )
    lines.append(f"  Bull: `{total_bull}` | Bear: `{total_bear}` | Neutral: `{total_neutral}`")
    lines.append("")

    # Gainers
    if gainers:
        lines.append("🚀 *Top Gainers:*")
        for m in gainers:
            short = m["ticker"].replace(".NS", "").replace(".BO", "")
            lines.append(
                f"  📈 *{short}* `{chg_str(m['chg'])}` | RSI `{m['rsi']}` {sig_icon(m['signal'])}"
            )
        lines.append("")

    # Losers
    if losers:
        lines.append("💥 *Top Losers:*")
        for m in losers:
            short = m["ticker"].replace(".NS", "").replace(".BO", "")
            lines.append(
                f"  📉 *{short}* `{chg_str(m['chg'])}` | RSI `{m['rsi']}` {sig_icon(m['signal'])}"
            )
        lines.append("")

    # Market status
    lines.append("━━━━━━━━━━━━━━━━━━━━")
    lines.append(f"🕐 *{time_str}*   {status_str}")
    lines.append("_NSE: 9:15 AM – 3:30 PM IST | F&O: Thursday_")
    lines.append("")
    lines.append("_/breakout — active breakouts | /top — top signals_")
    lines.append(DISCLAIMER)

    await msg.edit_text("\n".join(lines), parse_mode="Markdown")

# ─────────────────────────────────────────────────────────────────────────────
# /signal — Quick AI signal card
# ─────────────────────────────────────────────────────────────────────────────

async def signal_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = context.args
    if not args:
        await update.message.reply_text(
            "Usage: `/signal TICKER`\n\nExamples:\n"
            "  `/signal TCS.NS`\n  `/signal ^NSEI`",
            parse_mode="Markdown",
        )
        return
    ticker = args[0].upper().strip()
    msg    = await update.message.reply_text(f"⚡ Getting signal for `{ticker}`...", parse_mode="Markdown")
    try:
        data = analyze(ticker)
    except Exception as e:
        logger.exception(f"Signal error {ticker}: {e}")
        await msg.edit_text(f"❌ Could not fetch data for `{ticker}`.", parse_mode="Markdown")
        return

    sig     = data["signal"]["action"]
    price   = data["last_close"]
    chg     = data["change_pct"]
    rsi     = data["rsi"]
    swing   = data["swing"]
    brk     = data["breakout"]
    vol     = data["volume"]
    ema_dir = "Bullish ↑" if data["ema9"] > data["ema21"] else "Bearish ↓"
    vr      = vol["volume_ratio"]
    vol_tag = " 🔥 High volume!" if vr >= 2.0 else (" ⬆️ Vol" if vr >= 1.5 else "")

    lines = [
        f"⚡ *Signal — `{ticker}`*",
        f"_({data['name']})_",
        "━━━━━━━━━━━━━━━━━━━━",
        "",
        f"💰 `{fmt(price, ticker)}`  {chg_emoji(chg)} `{chg_str(chg)}`",
        f"🎯 *{sig_icon(sig)} {sig}*",
        f"📉 RSI: `{rsi}` — {rsi_zone(rsi)}",
        f"📐 EMA: `{ema_dir}`",
        f"📦 Volume: `{vr}x avg`{vol_tag}",
        "",
    ]

    if brk["breakout_up"]:
        lines.append("🚀 *BREAKOUT UP!* — Resistance cleared")
    elif brk["breakout_down"]:
        lines.append("💥 *BREAKDOWN!* — Support broken")

    dir_a = "⬆️" if swing["direction"] == "LONG" else "⬇️"
    lines += [
        "",
        f"🏹 Swing: {dir_a} {swing['direction']} `{swing['confidence']}%`",
        f"  SL `{fmt(swing['stop_loss'], ticker)}`",
        f"  T1 `{fmt(swing['target1'], ticker)}`",
        f"  T2 `{fmt(swing['target2'], ticker)}`",
        "",
        "━━━━━━━━━━━━━━━━━━━━",
        DISCLAIMER,
    ]
    await msg.edit_text("\n".join(lines), parse_mode="Markdown")

# ─────────────────────────────────────────────────────────────────────────────
# /swing — Detailed swing trade setup
# ─────────────────────────────────────────────────────────────────────────────

async def swing_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = context.args
    if not args:
        await update.message.reply_text(
            "Usage: `/swing TICKER`\n\nExamples:\n"
            "  `/swing RELIANCE.NS`\n  `/swing TCS.NS`",
            parse_mode="Markdown",
        )
        return
    ticker = args[0].upper().strip()
    msg    = await update.message.reply_text(f"🏹 Building swing setup for `{ticker}`...", parse_mode="Markdown")
    try:
        data = analyze(ticker)
    except Exception as e:
        logger.exception(f"Swing error {ticker}: {e}")
        await msg.edit_text(f"❌ Could not fetch data for `{ticker}`.", parse_mode="Markdown")
        return

    price = data["last_close"]
    swing = data["swing"]
    brk   = data["breakout"]
    sig   = data["signal"]["action"]
    rsi   = data["rsi"]

    dir_arrow = "⬆️ LONG" if swing["direction"] == "LONG" else "⬇️ SHORT"
    conf      = swing["confidence"]
    conf_bar  = "●" * (conf // 20) + "○" * (5 - conf // 20)

    rps  = abs(price - swing["stop_loss"])
    rr1  = round(abs(swing["target1"] - price) / rps, 2) if rps else 0
    rr2  = round(abs(swing["target2"] - price) / rps, 2) if rps else 0
    rr1v = "✅" if rr1 >= 2 else ("⚠️" if rr1 >= 1 else "❌")
    rr2v = "✅" if rr2 >= 2 else ("⚠️" if rr2 >= 1 else "❌")

    lines = [
        f"🏹 *Swing Setup — `{ticker}`*",
        f"_({data['name']})_",
        "━━━━━━━━━━━━━━━━━━━━",
        "",
        f"💰 `{fmt(price, ticker)}` {chg_emoji(data['change_pct'])} `{chg_str(data['change_pct'])}`",
        f"🎯 Signal: {sig_icon(sig)} {sig}",
        f"📉 RSI: `{rsi}` — {rsi_zone(rsi)}",
        "",
        f"─────────────────────",
        f"*Direction: {dir_arrow}*",
        f"Confidence: `{conf}%` [{conf_bar}]",
        f"ATR (14):   `{fmt(swing['atr'], ticker)}`",
    ]

    if brk["breakout_up"]:
        lines.append("🚀 *Active Breakout!* Boosts LONG conviction")
    elif brk["breakout_down"]:
        lines.append("💥 *Active Breakdown!* Boosts SHORT conviction")

    lines += [
        "",
        f"─────────────────────",
        f"📍 Entry:    `{fmt(price, ticker)}`",
        f"🛡 Stop:     `{fmt(swing['stop_loss'], ticker)}`",
        f"   Risk/share: `{fmt(round(rps, 2), ticker)}`",
        f"🎯 Target 1: `{fmt(swing['target1'], ticker)}` R:R `{rr1}x` {rr1v}",
        f"🎯 Target 2: `{fmt(swing['target2'], ticker)}` R:R `{rr2}x` {rr2v}",
        "",
        f"─────────────────────",
        f"📊 Key Levels:",
        f"  R: `{fmt(brk['resistance'], ticker)}`",
        f"  S: `{fmt(brk['support'], ticker)}`",
        "",
        "━━━━━━━━━━━━━━━━━━━━",
        "_Use /risk for position sizing._",
        DISCLAIMER,
    ]
    await msg.edit_text("\n".join(lines), parse_mode="Markdown")

# ─────────────────────────────────────────────────────────────────────────────
# /intraday — Intraday bias & levels
# ─────────────────────────────────────────────────────────────────────────────

async def intraday_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = context.args
    if not args:
        await update.message.reply_text(
            "Usage: `/intraday TICKER`\n\nExamples:\n"
            "  `/intraday RELIANCE.NS`\n  `/intraday ^NSEI`",
            parse_mode="Markdown",
        )
        return
    ticker = args[0].upper().strip()
    msg    = await update.message.reply_text(f"📈 Intraday analysis for `{ticker}`...", parse_mode="Markdown")
    try:
        data = analyze(ticker)
    except Exception as e:
        logger.exception(f"Intraday error {ticker}: {e}")
        await msg.edit_text(f"❌ Could not fetch data for `{ticker}`.", parse_mode="Markdown")
        return

    price   = data["last_close"]
    rsi     = data["rsi"]
    ema9    = data["ema9"]
    ema21   = data["ema21"]
    macd    = data["macd"]
    macd_s  = data["macd_signal"]
    vol     = data["volume"]
    brk     = data["breakout"]
    swing   = data["swing"]
    sig     = data["signal"]["action"]
    atr     = swing["atr"]

    # Intraday bias scoring
    score = 0
    notes = []

    if price > ema9:
        score += 1;  notes.append("✅ Price above EMA9")
    else:
        score -= 1;  notes.append("⚠️ Price below EMA9")

    if ema9 > ema21:
        score += 1;  notes.append("✅ EMA9 > EMA21 — trend up")
    else:
        score -= 1;  notes.append("⚠️ EMA9 < EMA21 — trend down")

    if macd > macd_s:
        score += 1;  notes.append("✅ MACD above signal — bullish momentum")
    else:
        score -= 1;  notes.append("⚠️ MACD below signal — bearish momentum")

    if rsi < 35:
        score += 1;  notes.append("✅ RSI oversold — bounce potential")
    elif rsi > 65:
        score -= 1;  notes.append("⚠️ RSI overbought — upside limited")
    else:
        notes.append("➡️ RSI neutral zone")

    if vol["volume_ratio"] >= 1.3:
        score += 1;  notes.append(f"✅ Volume {vol['volume_ratio']}x avg — active session")
    else:
        notes.append(f"➡️ Volume {vol['volume_ratio']}x avg — quiet")

    if score >= 3:    bias = "🟢🟢 Strong Bullish Bias"
    elif score >= 1:  bias = "🟢 Bullish Bias"
    elif score <= -3: bias = "🔴🔴 Strong Bearish Bias"
    elif score <= -1: bias = "🔴 Bearish Bias"
    else:             bias = "🟡 Neutral / Sideways"

    # Tight intraday levels (0.5–0.8× ATR)
    long_sl = round(price - 0.5 * atr, 2)
    long_t1 = round(price + 0.8 * atr, 2)
    long_t2 = round(price + 1.5 * atr, 2)

    status_str, time_str = market_status_ist()

    lines = [
        f"📈 *Intraday Bias — `{ticker}`*",
        f"_({data['name']})_",
        "━━━━━━━━━━━━━━━━━━━━",
        "",
        f"💰 LTP: `{fmt(price, ticker)}` {chg_emoji(data['change_pct'])} `{chg_str(data['change_pct'])}`",
        f"🎯 Daily Signal: {sig_icon(sig)} {sig}",
        "",
        f"─────────────────────",
        f"🧭 *Intraday Bias: {bias}*",
        "",
    ]
    for n in notes:
        lines.append(f"  {n}")
    lines += [
        "",
        "─────────────────────",
        "📍 *Key Intraday Levels:*",
        f"  R: `{fmt(brk['resistance'], ticker)}`",
        f"  S: `{fmt(brk['support'], ticker)}`",
        "",
        "_If bias bullish — approximate levels:_",
        f"  🛡 Stop:   `{fmt(long_sl, ticker)}`",
        f"  🎯 T1:     `{fmt(long_t1, ticker)}`",
        f"  🎯 T2:     `{fmt(long_t2, ticker)}`",
        "",
    ]
    if brk["breakout_up"]:
        lines.append("🚀 *Active Breakout UP!* — momentum may continue")
        lines.append("")
    elif brk["breakout_down"]:
        lines.append("💥 *Active Breakdown!* — selling pressure present")
        lines.append("")

    lines += [
        "─────────────────────",
        f"🕐 *{time_str}* — {status_str}",
        "_NSE: 9:15 AM – 3:30 PM IST_",
        "",
        "━━━━━━━━━━━━━━━━━━━━",
        "_Intraday bias uses daily technicals as proxy._",
        DISCLAIMER,
    ]
    await msg.edit_text("\n".join(lines), parse_mode="Markdown")

# ─────────────────────────────────────────────────────────────────────────────
# /breakout — Scan for active breakouts
# ─────────────────────────────────────────────────────────────────────────────

async def breakout_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    tickers, label = _ticker_arg(context.args)
    msg = await update.message.reply_text(
        f"🔍 Scanning {len(tickers)} stocks for breakouts...", parse_mode="Markdown"
    )

    ups   = []
    downs = []
    errors = []

    for ticker in tickers:
        try:
            data = analyze(ticker)
            brk  = data["breakout"]
            if not (brk["breakout_up"] or brk["breakout_down"]):
                continue
            row = {
                "ticker": ticker,
                "price":  data["last_close"],
                "chg":    data["change_pct"],
                "rsi":    data["rsi"],
                "signal": data["signal"]["action"],
                "score":  data["signal"]["score"],
                "vol":    data["volume"]["volume_ratio"],
                "surge":  brk["volume_surge"],
                "level":  brk["resistance"] if brk["breakout_up"] else brk["support"],
                "up":     brk["breakout_up"],
            }
            (ups if brk["breakout_up"] else downs).append(row)
        except Exception as e:
            logger.warning(f"Breakout scan {ticker}: {e}")
            errors.append(ticker)

    lines = [f"🚨 *Breakout Scanner — {label}*", "━━━━━━━━━━━━━━━━━━━━", ""]

    def row_line(r):
        v = " 🔥" if r["surge"] else (" ⬆️" if r["vol"] >= 1.5 else "")
        return (
            f"{'🚀' if r['up'] else '💥'} *{r['ticker']}* `{fmt(r['price'], r['ticker'])}` ({chg_str(r['chg'])})\n"
            f"  {sig_icon(r['signal'])} {r['signal']} | RSI `{r['rsi']}` | Vol `{r['vol']}x`{v}\n"
            f"  Level cleared: `{fmt(r['level'], r['ticker'])}`"
        )

    if ups:
        lines.append(f"🚀 *Breakouts UP ({len(ups)}):*")
        lines.append("")
        for r in sorted(ups, key=lambda x: -x["score"]):
            lines.append(row_line(r))
            lines.append("")
    else:
        lines.append("🟡 No bullish breakouts right now.")
        lines.append("")

    if downs:
        lines.append(f"💥 *Breakdowns ({len(downs)}):*")
        lines.append("")
        for r in sorted(downs, key=lambda x: x["score"]):
            lines.append(row_line(r))
            lines.append("")

    if errors:
        lines.append(f"_⚠️ {len(errors)} ticker(s) could not be fetched._")

    lines += ["━━━━━━━━━━━━━━━━━━━━", "_Tap any ticker for a full analysis._", DISCLAIMER]
    await msg.edit_text("\n".join(lines), parse_mode="Markdown")

# ─────────────────────────────────────────────────────────────────────────────
# /compare
# ─────────────────────────────────────────────────────────────────────────────

async def compare_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = context.args
    if not args or len(args) < 2:
        await update.message.reply_text(
            "Usage: `/compare RELIANCE.NS TCS.NS INFY.NS` _(2–6 tickers)_\n\n"
            "Compares signal, RSI, EMA, MACD and swing side by side.",
            parse_mode="Markdown",
        )
        return

    tickers = [a.upper().strip() for a in args[:6]]
    msg     = await update.message.reply_text(
        f"🔍 Comparing {', '.join(f'`{t}`' for t in tickers)}...", parse_mode="Markdown"
    )

    rows   = []
    errors = []

    for ticker in tickers:
        try:
            data     = analyze(ticker)
            sig      = data["signal"]["action"]
            ema_dir  = "↑" if data["ema9"] > data["ema21"] else "↓"
            macd_dir = "↑" if data["macd"] > data["macd_signal"] else "↓"
            brk      = data["breakout"]
            brk_tag  = "↑BRK" if brk["breakout_up"] else ("↓BRK" if brk["breakout_down"] else "—")
            rows.append({
                "ticker": ticker,
                "price":  data["last_close"],
                "chg":    chg_str(data["change_pct"]),
                "signal": f"{sig_icon(sig)} {sig}",
                "rsi":    data["rsi"],
                "ema":    ema_dir,
                "macd":   macd_dir,
                "swing":  data["swing"]["direction"],
                "conf":   data["swing"]["confidence"],
                "brk":    brk_tag,
            })
        except Exception as e:
            logger.warning(f"Compare error {ticker}: {e}")
            errors.append(ticker)

    if not rows:
        await msg.edit_text("❌ Could not fetch data for any ticker.", parse_mode="Markdown")
        return

    lines = ["📊 *Stock Comparison*", "━━━━━━━━━━━━━━━━━━━━", ""]
    for r in rows:
        lines.append(f"*{r['ticker']}* — `{fmt(r['price'], r['ticker'])}` ({r['chg']})")
        lines.append(f"  {r['signal']}")
        lines.append(f"  RSI `{r['rsi']}` | EMA `{r['ema']}` | MACD `{r['macd']}`")
        lines.append(f"  Swing: `{r['swing']}` `{r['conf']}%` | Brk: `{r['brk']}`")
        lines.append("")

    if errors:
        lines.append(f"_⚠️ Could not fetch: {', '.join(errors)}_")
        lines.append("")

    lines += ["_Tap a ticker for full analysis._", DISCLAIMER]
    await msg.edit_text("\n".join(lines), parse_mode="Markdown")

# ─────────────────────────────────────────────────────────────────────────────
# /summary
# ─────────────────────────────────────────────────────────────────────────────

async def summary_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = context.args
    if not args:
        await update.message.reply_text(
            "Usage: `/summary RELIANCE.NS`\n\nCombines technicals + news sentiment into a trade brief.",
            parse_mode="Markdown",
        )
        return
    ticker = args[0].upper().strip()
    msg    = await update.message.reply_text(f"⚡ Building trade brief for `{ticker}`...", parse_mode="Markdown")

    try:
        data = analyze(ticker)
    except Exception as e:
        logger.exception(f"Summary error {ticker}: {e}")
        await msg.edit_text(f"❌ Could not fetch data for `{ticker}`.", parse_mode="Markdown")
        return

    try:
        sent = fetch_sentiment(ticker)
    except Exception:
        sent = {"overall": "NEUTRAL", "bullish": 0, "bearish": 0, "neutral": 0, "total": 0}

    sig       = data["signal"]["action"]
    price     = data["last_close"]
    chg       = data["change_pct"]
    swing     = data["swing"]
    brk       = data["breakout"]
    rsi       = data["rsi"]
    ema_dir   = "Bullish" if data["ema9"] > data["ema21"] else "Bearish"
    macd_dir  = "Bullish" if data["macd"] > data["macd_signal"] else "Bearish"
    news_mood = sent["overall"]
    n_icon    = "🟢" if news_mood == "BULLISH" else ("🔴" if news_mood == "BEARISH" else "🟡")

    t_bull = sig in ("BUY", "STRONG BUY")
    t_bear = sig in ("SELL", "STRONG SELL")
    n_bull = news_mood == "BULLISH"
    n_bear = news_mood == "BEARISH"

    if t_bull and n_bull:
        note = "📗 *Technicals and news both bullish* — high-conviction long setup."
    elif t_bear and n_bear:
        note = "📕 *Technicals and news both bearish* — avoid or consider short."
    elif t_bull and n_bear:
        note = "⚠️ *Bullish chart, negative news* — wait for news to settle."
    elif t_bear and n_bull:
        note = "⚠️ *Bearish chart despite positive news* — likely priced in."
    elif t_bull:
        note = "📘 *Bullish technicals, neutral news* — trend-driven. Watch volume."
    elif t_bear:
        note = "📘 *Bearish technicals, neutral news* — manage risk carefully."
    else:
        note = "📘 *Mixed signals* — no clear edge. Wait for confirmation."

    if brk["breakout_up"]:
        brk_line = "🚀 Breakout UP — resistance cleared with volume"
    elif brk["breakout_down"]:
        brk_line = "💥 Breakdown — support broken with volume"
    else:
        brk_line = f"S: `{fmt(brk['support'], ticker)}` — R: `{fmt(brk['resistance'], ticker)}`"

    lines = [
        f"⚡ *Trade Brief — `{ticker}`*",
        f"_({data['name']})_",
        "━━━━━━━━━━━━━━━━━━━━",
        "",
        f"💰 `{fmt(price, ticker)}` {chg_emoji(chg)} `{chg_str(chg)}`",
        f"🎯 Signal: {sig_icon(sig)} *{sig}*",
        f"📰 News: {n_icon} {news_mood} ({sent['bullish']}↑ {sent['bearish']}↓ / {sent['total']})",
        "",
        "📐 *Technicals:*",
        f"  RSI `{rsi}` | EMA `{ema_dir}` | MACD `{macd_dir}`",
        "",
        "📍 *Levels:*",
        f"  {brk_line}",
        "",
        f"🏹 *Swing:* {swing['direction']} `{swing['confidence']}%`",
        f"  SL `{fmt(swing['stop_loss'], ticker)}`",
        f"  T1 `{fmt(swing['target1'], ticker)}`",
        f"  T2 `{fmt(swing['target2'], ticker)}`",
        "",
        "━━━━━━━━━━━━━━━━━━━━",
        f"💡 {note}",
        "",
        DISCLAIMER,
    ]
    await msg.edit_text("\n".join(lines), parse_mode="Markdown")

# ─────────────────────────────────────────────────────────────────────────────
# /movers
# ─────────────────────────────────────────────────────────────────────────────

async def movers_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    tickers, label = _ticker_arg(context.args)
    msg = await update.message.reply_text(
        f"🔍 Fetching movers from {len(tickers)} stocks...", parse_mode="Markdown"
    )

    results = []
    errors  = []
    for ticker in tickers:
        try:
            data = analyze(ticker)
            results.append({
                "ticker": ticker,
                "price":  data["last_close"],
                "chg":    data["change_pct"],
                "rsi":    data["rsi"],
                "signal": data["signal"]["action"],
                "vr":     data["volume"]["volume_ratio"],
            })
        except Exception as e:
            logger.warning(f"Movers error {ticker}: {e}")
            errors.append(ticker)

    if not results:
        await msg.edit_text("❌ Could not fetch data. Please try again.", parse_mode="Markdown")
        return

    results.sort(key=lambda x: x["chg"], reverse=True)
    gainers = results[:5]
    losers  = list(reversed(results[-5:]))

    def vol_tag(vr): return " 🔥" if vr >= 2.0 else (" ⬆️" if vr >= 1.5 else "")

    lines = [f"📈📉 *Top Movers — {label}*", "━━━━━━━━━━━━━━━━━━━━", ""]
    lines.append("🚀 *Top Gainers:*")
    for r in gainers:
        lines.append(
            f"  {sig_icon(r['signal'])} *{r['ticker']}* `{fmt(r['price'], r['ticker'])}` "
            f"`{chg_str(r['chg'])}` RSI`{r['rsi']}`{vol_tag(r['vr'])}"
        )
    lines.append("")
    lines.append("💥 *Top Losers:*")
    for r in losers:
        lines.append(
            f"  {sig_icon(r['signal'])} *{r['ticker']}* `{fmt(r['price'], r['ticker'])}` "
            f"`{chg_str(r['chg'])}` RSI`{r['rsi']}`{vol_tag(r['vr'])}"
        )

    if errors:
        lines.append(f"\n_⚠️ {len(errors)} ticker(s) unavailable._")
    lines += ["", "_Tap any ticker for full analysis._", DISCLAIMER]
    await msg.edit_text("\n".join(lines), parse_mode="Markdown")

# ─────────────────────────────────────────────────────────────────────────────
# /sentiment
# ─────────────────────────────────────────────────────────────────────────────

async def sentiment_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = context.args
    if not args:
        await update.message.reply_text(
            "Usage: `/sentiment RELIANCE.NS`\n\nFetches recent news headlines and gives a sentiment summary.",
            parse_mode="Markdown",
        )
        return
    ticker = args[0].upper().strip()
    msg    = await update.message.reply_text(f"📰 Fetching news for `{ticker}`...", parse_mode="Markdown")

    try:
        s = fetch_sentiment(ticker)
    except Exception as e:
        logger.exception(f"Sentiment error {ticker}: {e}")
        await msg.edit_text(f"⚠️ Could not fetch news for `{ticker}`.", parse_mode="Markdown")
        return

    overall = s["overall"]
    o_icon  = "🟢 BULLISH" if overall == "BULLISH" else ("🔴 BEARISH" if overall == "BEARISH" else "🟡 NEUTRAL")

    lines = [
        f"📰 *News Sentiment — `{ticker}`*",
        "━━━━━━━━━━━━━━━━━━━━",
        "",
        f"Overall: *{o_icon}*",
        f"Scanned: `{s['total']}` articles",
        f"🟢`{s['bullish']}` Bullish  🔴`{s['bearish']}` Bearish  🟡`{s['neutral']}` Neutral",
        "",
    ]
    if s["headlines"]:
        lines.append("*Recent Headlines:*")
        lines.append("")
        for h in s["headlines"]:
            icon  = "🟢" if h["score"] > 0 else ("🔴" if h["score"] < 0 else "🟡")
            title = h["title"][:88] + ("…" if len(h["title"]) > 88 else "")
            lines.append(f"{icon} {title}")
    else:
        lines.append("_No recent headlines found._")

    lines += ["", "⚠️ _Sentiment is keyword-based. Verify news independently._"]
    await msg.edit_text("\n".join(lines), parse_mode="Markdown")

# ─────────────────────────────────────────────────────────────────────────────
# /top
# ─────────────────────────────────────────────────────────────────────────────

async def top_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    tickers, label = _ticker_arg(context.args)
    msg = await update.message.reply_text(
        f"🔍 Scanning {len(tickers)} stocks for top signals...", parse_mode="Markdown"
    )

    hits   = []
    errors = []
    for ticker in tickers:
        try:
            data  = analyze(ticker)
            sig   = data["signal"]["action"]
            score = data["signal"]["score"]
            brk   = data["breakout"]

            brk_active = brk["breakout_up"] or brk["breakout_down"]
            if not ("STRONG" in sig or (sig in ("BUY", "SELL") and brk_active)):
                continue

            brk_tag = " 🚨↑" if brk["breakout_up"] else (" 💥↓" if brk["breakout_down"] else "")
            hits.append({
                "rank":  SIGNAL_RANK.get(sig, 9),
                "score": abs(score),
                "line": (
                    f"{sig_icon(sig)} *{ticker}* `{fmt(data['last_close'], ticker)}` "
                    f"({chg_str(data['change_pct'])}) RSI`{data['rsi']}` "
                    f"{data['swing']['direction']}{brk_tag}"
                ),
            })
        except Exception as e:
            logger.warning(f"Top scan error {ticker}: {e}")
            errors.append(ticker)

    hits.sort(key=lambda x: (x["rank"], -x["score"]))

    lines = [f"🏆 *Top Signals — {label}*", "━━━━━━━━━━━━━━━━━━━━", ""]
    if hits:
        lines.append("_Strong signals & active breakouts only:_")
        lines.append("")
        for h in hits:
            lines.append(h["line"])
    else:
        lines.append("🟡 No strong signals right now — market is neutral.")
        lines.append("Try later or use /scan on your watchlist.")

    if errors:
        lines.append(f"\n_⚠️ {len(errors)} ticker(s) unavailable._")

    lines += ["", "_Tap any ticker for full analysis._", DISCLAIMER]
    await msg.edit_text("\n".join(lines), parse_mode="Markdown")

# ─────────────────────────────────────────────────────────────────────────────
# Main ticker message handler
# ─────────────────────────────────────────────────────────────────────────────

async def analyze_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text   = update.message.text.strip()
    if text.startswith("/"):
        return
    ticker = text.split()[0].upper()
    msg    = await update.message.reply_text(f"🔍 Analysing `{ticker}`...", parse_mode="Markdown")
    try:
        data   = analyze(ticker)
        report = format_report(data)
        await msg.edit_text(report, parse_mode="Markdown")
    except ValueError as e:
        await msg.edit_text(
            f"❌ {e}\n\nTips:\n"
            "• NSE: `TCS.NS`  `RELIANCE.NS`\n"
            "• Nifty 50: `^NSEI`\n"
            "• Bank Nifty: `^NSEBANK`",
            parse_mode="Markdown",
        )
    except Exception as e:
        logger.exception(f"Analyze error {ticker}: {e}")
        await msg.edit_text(
            f"⚠️ Could not analyse `{ticker}`.\n\n"
            "_Possible issues:_\n"
            "• Add `.NS` for NSE stocks (e.g. `TCS.NS`)\n"
            "• Use `^NSEI` for Nifty 50\n"
            "• Check spelling and try again",
            parse_mode="Markdown",
        )

# ─────────────────────────────────────────────────────────────────────────────
# /gainers52w
# ─────────────────────────────────────────────────────────────────────────────

async def gainers52w_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    import yfinance as yf
    tickers, label = _ticker_arg(context.args)
    msg = await update.message.reply_text(
        f"🔍 Scanning {len(tickers)} stocks for 52-week high setups...", parse_mode="Markdown"
    )

    hits   = []
    errors = []
    for ticker in tickers:
        try:
            stock  = yf.Ticker(ticker)
            fi     = stock.fast_info
            high52 = getattr(fi, "year_high", None)
            low52  = getattr(fi, "year_low", None)
            price  = getattr(fi, "last_price", None)

            if not high52 or not price:
                info   = stock.info
                high52 = info.get("fiftyTwoWeekHigh") or high52
                low52  = info.get("fiftyTwoWeekLow") or low52
                price  = info.get("currentPrice") or info.get("regularMarketPrice") or price

            if not high52 or not price:
                continue

            price, high52 = round(float(price), 2), round(float(high52), 2)
            low52 = round(float(low52), 2) if low52 else 0

            pct_below = round(((high52 - price) / high52) * 100, 1)
            if pct_below > 10:
                continue

            data = analyze(ticker)
            sig  = data["signal"]["action"]
            if sig not in ("BUY", "STRONG BUY"):
                continue

            rng_pct = round(((price - low52) / (high52 - low52)) * 100, 1) if high52 != low52 else 50
            vr      = data["volume"]["volume_ratio"]
            brk_tag = " 🚨BRK↑" if data["breakout"]["breakout_up"] else ""
            vol_tag = " 🔥" if vr >= 2.0 else (" ⬆️" if vr >= 1.5 else "")

            hits.append({
                "pct": pct_below,
                "line": (
                    f"{'🟢🟢' if 'STRONG' in sig else '🟢'} *{ticker}* `{fmt(price, ticker)}` ({chg_str(data['change_pct'])})\n"
                    f"  `{pct_below}%` below 52w high `{fmt(high52, ticker)}`\n"
                    f"  Range pos: `{rng_pct}%` | RSI `{data['rsi']}`{vol_tag}{brk_tag}"
                ),
            })
        except Exception as e:
            logger.warning(f"52w scan {ticker}: {e}")
            errors.append(ticker)

    hits.sort(key=lambda x: x["pct"])
    lines = [f"📈 *Near 52-Week Highs — {label}*", "━━━━━━━━━━━━━━━━━━━━", ""]
    lines.append("_Bullish stocks within 10% of 52w high:_")
    lines.append("")

    if hits:
        for h in hits:
            lines.append(h["line"])
            lines.append("")
    else:
        lines.append("No stocks meet the criteria right now.")

    if errors:
        lines.append(f"_⚠️ {len(errors)} ticker(s) unavailable._")
    lines += ["_Tap any ticker for full analysis._", DISCLAIMER]
    await msg.edit_text("\n".join(lines), parse_mode="Markdown")

# ─────────────────────────────────────────────────────────────────────────────
# /oversold
# ─────────────────────────────────────────────────────────────────────────────

async def oversold_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    tickers, label = _ticker_arg(context.args)
    msg = await update.message.reply_text(
        f"🔍 Scanning {len(tickers)} stocks for oversold dip-buy setups...", parse_mode="Markdown"
    )

    hits   = []
    errors = []
    for ticker in tickers:
        try:
            data  = analyze(ticker)
            rsi   = data["rsi"]
            if rsi >= 35:
                continue

            price  = data["last_close"]
            ema9   = data["ema9"];  ema21 = data["ema21"]
            ema50  = data["ema50"]; ema200 = data["ema200"]

            if not ((ema50 > ema200) or (price > ema50) or (ema9 > ema21)):
                continue

            swing   = data["swing"]
            vol     = data["volume"]
            macd_ok = data["macd"] > data["macd_signal"]

            q = 0
            if ema50 > ema200: q += 2
            if price > ema50:  q += 1
            if ema9 > ema21:   q += 1
            if macd_ok:        q += 1
            if vol["obv_trend"] == "Rising": q += 1
            if rsi < 25:       q += 1

            parts = []
            if ema50 > ema200: parts.append("EMA50>200")
            if price > ema50:  parts.append("P>EMA50")
            if ema9 > ema21:   parts.append("EMA9>21")

            hits.append({
                "rsi": rsi, "q": q,
                "line": (
                    f"🔵 *{ticker}* `{fmt(price, ticker)}` ({chg_str(data['change_pct'])}) RSI`{rsi}`\n"
                    f"  Structure: `{'|'.join(parts) or 'partial'}`\n"
                    f"  Swing: `{swing['direction']}` SL `{fmt(swing['stop_loss'], ticker)}` T1 `{fmt(swing['target1'], ticker)}`"
                ),
            })
        except Exception as e:
            logger.warning(f"Oversold scan {ticker}: {e}")
            errors.append(ticker)

    hits.sort(key=lambda x: (-x["q"], x["rsi"]))
    lines = [f"🔵 *Oversold Dip-Buy Setups — {label}*", "━━━━━━━━━━━━━━━━━━━━", ""]
    lines.append("_RSI < 35 with a bullish EMA structure:_")
    lines.append("")

    if hits:
        for h in hits:
            lines.append(h["line"])
            lines.append("")
    else:
        lines.append("No oversold setups currently. Market may be in a strong uptrend.")

    if errors:
        lines.append(f"_⚠️ {len(errors)} ticker(s) unavailable._")
    lines += ["_Tap any ticker for full analysis._", DISCLAIMER]
    await msg.edit_text("\n".join(lines), parse_mode="Markdown")

# ─────────────────────────────────────────────────────────────────────────────
# /report — Full printable analysis report
# ─────────────────────────────────────────────────────────────────────────────

async def report_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = context.args
    if not args:
        await update.message.reply_text(
            "Usage: `/report RELIANCE.NS`\n\nGenerates a full report you can forward to others.",
            parse_mode="Markdown",
        )
        return
    ticker = args[0].upper().strip()
    msg    = await update.message.reply_text(f"📄 Generating full report for `{ticker}`...", parse_mode="Markdown")

    try:
        data = analyze(ticker)
    except Exception as e:
        logger.exception(f"Report error {ticker}: {e}")
        await msg.edit_text(f"❌ Could not fetch data for `{ticker}`.", parse_mode="Markdown")
        return

    try:
        sent = fetch_sentiment(ticker)
    except Exception:
        sent = {"overall": "NEUTRAL", "bullish": 0, "bearish": 0, "neutral": 0, "total": 0, "headlines": []}

    from datetime import datetime, timezone
    now   = datetime.now(timezone.utc).strftime("%d %b %Y, %H:%M UTC")
    price = data["last_close"]
    swing = data["swing"]
    brk   = data["breakout"]
    vol   = data["volume"]
    sig   = data["signal"]["action"]

    if price > data["bb_upper"]:   bb_pos = "Above upper ⚠️"
    elif price < data["bb_lower"]: bb_pos = "Below lower ✅"
    else:                           bb_pos = "Inside bands ✅"

    if brk["breakout_up"]:   brk_str = "🚀 BREAKOUT UP — resistance cleared"
    elif brk["breakout_down"]: brk_str = "💥 BREAKDOWN — support broken"
    else:                       brk_str = f"No breakout | S:{fmt(brk['support'],ticker)} R:{fmt(brk['resistance'],ticker)}"

    n_icon    = {"BULLISH": "🟢", "BEARISH": "🔴"}.get(sent["overall"], "🟡")
    reasons   = "\n".join(f"  • {r}" for r in data["signal"]["reasons"])
    ema_trend = "Bullish ↑" if data["ema9"] > data["ema21"] else "Bearish ↓"
    m_trend   = "Bullish" if data["macd"] > data["macd_signal"] else "Bearish"

    hl_lines = ""
    if sent["headlines"]:
        hl = []
        for h in sent["headlines"][:4]:
            icon  = "🟢" if h["score"] > 0 else ("🔴" if h["score"] < 0 else "🟡")
            title = h["title"][:78] + ("…" if len(h["title"]) > 78 else "")
            hl.append(f"  {icon} {title}")
        hl_lines = "\n".join(hl)
    else:
        hl_lines = "  No recent headlines found."

    lines = [
        f"📊 *ANALYSIS REPORT*",
        f"*{data['name']}* (`{ticker}`)",
        f"_{now}_",
        "━━━━━━━━━━━━━━━━━━━━",
        "",
        f"💰 *Price:* `{fmt(price, ticker)}` ({chg_str(data['change_pct'])})",
        f"🎯 *Signal:* {sig_icon(sig)} *{sig}*",
        f"{reasons}",
        "",
        "─────────────────────",
        f"📉 *RSI (14):* `{data['rsi']}` — {rsi_zone(data['rsi'])}",
        "",
        "─────────────────────",
        f"📐 *EMA:* `{ema_trend}`",
        f"  9: `{fmt(data['ema9'],ticker)}`  21: `{fmt(data['ema21'],ticker)}`",
        f"  50: `{fmt(data['ema50'],ticker)}`  200: `{fmt(data['ema200'],ticker)}`",
        "",
        "─────────────────────",
        f"📊 *MACD:* `{m_trend}`",
        f"  `{fmt_macd(data['macd'])}` / `{fmt_macd(data['macd_signal'])}` / `{fmt_macd(data['macd_hist'])}`",
        "",
        "─────────────────────",
        f"📏 *Bollinger Bands (20):* {bb_pos}",
        f"  U:`{fmt(data['bb_upper'],ticker)}`  M:`{fmt(data['bb_mid'],ticker)}`  L:`{fmt(data['bb_lower'],ticker)}`",
        "",
        "─────────────────────",
        f"📦 *Volume:* `{vol['volume_ratio']}x` avg | OBV: `{vol['obv_trend']}`",
        f"  Today: `{vol['last_volume']:,}` | Avg20: `{vol['avg_volume_20d']:,}`",
        "",
        "─────────────────────",
        f"🚨 *Breakout:* {brk_str}",
        "",
        "─────────────────────",
        f"🏹 *Swing:* {swing['direction']} `{swing['confidence']}%`",
        f"  ATR: `{fmt(swing['atr'],ticker)}`",
        f"  SL:  `{fmt(swing['stop_loss'],ticker)}`",
        f"  T1:  `{fmt(swing['target1'],ticker)}`",
        f"  T2:  `{fmt(swing['target2'],ticker)}`",
        "",
        "─────────────────────",
        f"📰 *News:* {n_icon} {sent['overall']} ({sent['bullish']}↑ {sent['bearish']}↓)",
        hl_lines,
        "",
        "━━━━━━━━━━━━━━━━━━━━",
        DISCLAIMER,
        "_Generated by MarketMasteryAI Bot_",
    ]
    await msg.edit_text("\n".join(lines), parse_mode="Markdown")

# ─────────────────────────────────────────────────────────────────────────────
# /sector
# ─────────────────────────────────────────────────────────────────────────────

async def sector_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    tickers = TOP_INDIA + TOP_US
    msg     = await update.message.reply_text(
        f"🔍 Scanning {len(tickers)} stocks across sectors...", parse_mode="Markdown"
    )

    sectors: dict[str, list] = {}
    errors = []

    for ticker in tickers:
        sector = SECTOR_MAP.get(ticker, "🔹 Other")
        try:
            data = analyze(ticker)
            sectors.setdefault(sector, []).append({
                "ticker":       ticker,
                "rsi":          data["rsi"],
                "signal":       data["signal"]["action"],
                "score":        data["signal"]["score"],
                "chg":          data["change_pct"],
                "breakout_up":  data["breakout"]["breakout_up"],
                "breakout_down":data["breakout"]["breakout_down"],
            })
        except Exception as e:
            logger.warning(f"Sector scan {ticker}: {e}")
            errors.append(ticker)

    def dominant(stocks):
        c = {}
        for s in stocks:
            c[s["signal"]] = c.get(s["signal"], 0) + 1
        return max(c, key=lambda x: c[x])

    summaries = []
    for sec, stocks in sectors.items():
        dom = dominant(stocks)
        summaries.append({
            "sector":    sec,
            "count":     len(stocks),
            "avg_rsi":   round(sum(s["rsi"] for s in stocks) / len(stocks), 1),
            "avg_chg":   round(sum(s["chg"] for s in stocks) / len(stocks), 2),
            "dom":       dom,
            "avg_score": round(sum(s["score"] for s in stocks) / len(stocks), 1),
            "breakouts": sum(1 for s in stocks if s["breakout_up"] or s["breakout_down"]),
            "stocks":    stocks,
        })
    summaries.sort(key=lambda x: -x["avg_score"])

    lines = ["🏭 *Sector Strength Overview*", "━━━━━━━━━━━━━━━━━━━━", ""]
    for sec in summaries:
        brk_tag  = f" 🚨{sec['breakouts']} brk" if sec["breakouts"] else ""
        tkr_list = " ".join(
            f"`{s['ticker'].replace('.NS','').replace('.BO','')}`"
            for s in sorted(sec["stocks"], key=lambda x: -x["score"])
        )
        lines.append(f"{sig_icon(sec['dom'])} *{sec['sector']}* ({sec['count']})")
        lines.append(f"  `{sec['dom']}` | RSI `{sec['avg_rsi']}` | `{chg_str(sec['avg_chg'])}`{brk_tag}")
        lines.append(f"  {tkr_list}")
        lines.append("")

    if errors:
        lines.append(f"_⚠️ {len(errors)} ticker(s) unavailable._")
    lines += ["_Tap any ticker for full analysis._", DISCLAIMER]
    await msg.edit_text("\n".join(lines), parse_mode="Markdown")

# ─────────────────────────────────────────────────────────────────────────────
# /heatmap
# ─────────────────────────────────────────────────────────────────────────────

async def heatmap_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    tickers = TOP_INDIA
    msg     = await update.message.reply_text(
        f"🗺️ Building NSE heatmap for {len(tickers)} stocks...", parse_mode="Markdown"
    )

    results: dict[str, dict | None] = {}
    for ticker in tickers:
        try:
            data = analyze(ticker)
            results[ticker] = {
                "signal": data["signal"]["action"],
                "score":  data["signal"]["score"],
                "rsi":    data["rsi"],
                "chg":    data["change_pct"],
            }
        except Exception as e:
            logger.warning(f"Heatmap error {ticker}: {e}")
            results[ticker] = None

    def cell(t: str) -> str:
        r = results.get(t)
        if not r:
            return f"⬜`{t.replace('.NS','')}`"
        return f"{sig_icon(r['signal'])}`{t.replace('.NS','').replace('.BO','')}`"

    sb  = sum(1 for r in results.values() if r and "STRONG BUY" in r["signal"])
    b   = sum(1 for r in results.values() if r and r["signal"] == "BUY")
    h   = sum(1 for r in results.values() if r and r["signal"] == "HOLD / NEUTRAL")
    s   = sum(1 for r in results.values() if r and r["signal"] == "SELL")
    ss  = sum(1 for r in results.values() if r and "STRONG SELL" in r["signal"])
    tb  = sb + b
    ts  = ss + s
    bd  = "Bullish" if tb > ts else ("Bearish" if ts > tb else "Neutral")
    bdi = "🟢" if bd == "Bullish" else ("🔴" if bd == "Bearish" else "🟡")

    avg_rsis = [r["rsi"] for r in results.values() if r]
    avg_rsi  = round(sum(avg_rsis) / len(avg_rsis), 1) if avg_rsis else 0

    sector_tickers: dict[str, list] = {}
    for t in tickers:
        sector_tickers.setdefault(SECTOR_MAP.get(t, "🔹 Other"), []).append(t)

    lines = ["🗺️ *NSE Market Heatmap*", "━━━━━━━━━━━━━━━━━━━━", ""]
    for sec in SECTOR_ORDER:
        grp = sector_tickers.get(sec)
        if not grp:
            continue
        grp_sorted = sorted(grp, key=lambda t: -(results.get(t) or {}).get("score", 0))
        lines.append(f"*{sec}*")
        lines.append("  " + "  ".join(cell(t) for t in grp_sorted))
        lines.append("")

    lines += [
        "━━━━━━━━━━━━━━━━━━━━",
        f"📊 *Breadth:* {bdi} *{bd}*",
        f"  🟢🟢`{sb}` 🟢`{b}` 🟡`{h}` 🔴`{s}` 🔴🔴`{ss}`",
        f"  Bull:`{tb}` | Bear:`{ts}` | Avg RSI:`{avg_rsi}`",
        "",
        "_Tap any ticker for full analysis._",
        DISCLAIMER,
    ]
    await msg.edit_text("\n".join(lines), parse_mode="Markdown")

# ─────────────────────────────────────────────────────────────────────────────
# /risk — Position sizing
# ─────────────────────────────────────────────────────────────────────────────

async def risk_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = context.args
    if len(args) < 2:
        await update.message.reply_text(
            "Usage: `/risk TICKER CAPITAL [RISK%]`\n\n"
            "Examples:\n"
            "  `/risk RELIANCE.NS 100000`\n"
            "  `/risk TCS.NS 50000 1`\n"
            "  `/risk HDFCBANK.NS 200000 3`\n\n"
            "_RISK% defaults to 2% if not provided._",
            parse_mode="Markdown",
        )
        return

    ticker = args[0].upper().strip()
    try:
        capital = float(args[1].replace(",", "").replace("$", "").replace("₹", ""))
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
            risk_pct = float(args[2].replace("%", ""))
            risk_pct = max(0.1, min(risk_pct, 20.0))
        except ValueError:
            pass

    msg = await update.message.reply_text(
        f"📐 Calculating position size for `{ticker}`...", parse_mode="Markdown"
    )
    try:
        data = analyze(ticker)
    except Exception as e:
        logger.exception(f"Risk calc error {ticker}: {e}")
        await msg.edit_text(f"❌ Could not fetch data for `{ticker}`.", parse_mode="Markdown")
        return

    price     = data["last_close"]
    swing     = data["swing"]
    stop_loss = swing["stop_loss"]
    target1   = swing["target1"]
    target2   = swing["target2"]
    atr       = swing["atr"]
    direction = swing["direction"]
    sig       = data["signal"]["action"]

    rps = abs(price - stop_loss)
    if rps == 0:
        await msg.edit_text("⚠️ Stop loss equals price — cannot calculate.", parse_mode="Markdown")
        return

    max_risk  = round(capital * (risk_pct / 100), 2)
    shares    = max(1, int(max_risk / rps))
    pos_val   = round(shares * price, 2)
    act_risk  = round(shares * rps, 2)
    act_pct   = round((act_risk / capital) * 100, 2)
    reward1   = round(shares * abs(target1 - price), 2)
    reward2   = round(shares * abs(target2 - price), 2)
    rr1       = round(reward1 / act_risk, 2) if act_risk else 0
    rr2       = round(reward2 / act_risk, 2) if act_risk else 0
    leftover  = round(capital - pos_val, 2)
    fits      = pos_val <= capital

    rr1v = "✅ Good" if rr1 >= 2 else ("⚠️ Marginal" if rr1 >= 1 else "❌ Poor")
    rr2v = "✅ Good" if rr2 >= 2 else ("⚠️ Marginal" if rr2 >= 1 else "❌ Poor")
    curr = "₹" if is_indian(ticker) else "$"
    da   = "⬆️" if direction == "LONG" else "⬇️"

    lines = [
        f"📐 *Position Sizing — `{ticker}`*",
        "━━━━━━━━━━━━━━━━━━━━",
        "",
        f"💰 Price:   `{fmt(price, ticker)}` | {sig_icon(sig)} {sig}",
        f"📊 ATR(14): `{fmt(atr, ticker)}`   | {da} {direction}",
        "",
        "─────────────────────",
        f"💼 Capital:       `{curr}{capital:,.0f}`",
        f"⚠️ Risk/trade:    `{risk_pct}%` = `{curr}{max_risk:,.0f}`",
        "",
        "─────────────────────",
        f"📦 *Position:*",
        f"  Qty:       `{shares:,}` shares",
        f"  Value:     `{curr}{pos_val:,.0f}`" + (" ✅" if fits else " ⚠️ exceeds capital"),
        f"  Remaining: `{curr}{leftover:,.0f}`",
        "",
        "─────────────────────",
        f"🛡 *Risk:*",
        f"  Entry:    `{fmt(price, ticker)}`",
        f"  Stop:     `{fmt(stop_loss, ticker)}`  (−`{fmt(round(rps, 2), ticker)}`/sh)",
        f"  Max loss: `{curr}{act_risk:,.0f}` ({act_pct}%)",
        "",
        "─────────────────────",
        f"🎯 *Targets:*",
        f"  T1: `{fmt(target1, ticker)}` → `{curr}{reward1:,.0f}` R:R `{rr1}x` {rr1v}",
        f"  T2: `{fmt(target2, ticker)}` → `{curr}{reward2:,.0f}` R:R `{rr2}x` {rr2v}",
        "",
        "━━━━━━━━━━━━━━━━━━━━",
        f"💡 `/risk {ticker} {int(capital)} 1` to change risk to 1%",
        "",
        DISCLAIMER,
    ]
    await msg.edit_text("\n".join(lines), parse_mode="Markdown")

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

    ticker    = args[0].upper().strip()
    direction = args[1].lower().strip()
    if direction not in ("long", "short"):
        await update.message.reply_text("❌ Direction must be `long` or `short`.", parse_mode="Markdown")
        return

    try:
        entry  = float(args[2].replace("₹","").replace("$","").replace(",",""))
        exit_p = float(args[3].replace("₹","").replace("$","").replace(",",""))
        shares = float(args[4].replace(",","")) if len(args) >= 5 else 1.0
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
        f"  P&L: `{fmt_pnl(trade['pnl'], ticker)}` ({trade['pnl_pct']}%) — {w_icon}\n\n"
        "Use /trades to view history or /pnl for stats.",
        parse_mode="Markdown",
    )


async def trades_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid    = update.effective_user.id
    trades = get_trades(uid)
    if not trades:
        await update.message.reply_text(
            "📒 No trades logged yet.\n\nUse `/journal TCS.NS long 3800 4100 10`",
            parse_mode="Markdown",
        )
        return

    recent = list(reversed(trades[-20:]))
    lines  = [f"📒 *Trade Journal* ({len(trades)} total)", "━━━━━━━━━━━━━━━━━━━━", ""]
    for t in recent:
        w_icon = "✅" if t["won"] else "❌"
        d_icon = "⬆️" if t["direction"] == "LONG" else "⬇️"
        lines.append(
            f"{w_icon} #{t['id']} {d_icon} *{t['ticker']}* `{t['date']}`\n"
            f"  `{fmt(t['entry'], t['ticker'])}` → `{fmt(t['exit'], t['ticker'])}` ×{t['shares']}\n"
            f"  `{fmt_pnl(t['pnl'], t['ticker'])}` ({t['pnl_pct']}%)"
        )
        lines.append("")

    lines.append("_/pnl for stats | `/deltrade ID` to remove_")
    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


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

    # Use best/worst ticker for currency context
    bt = best.get("ticker", "")
    wt = worst.get("ticker", "")

    lines = [
        "📊 *P&L Statistics*",
        "━━━━━━━━━━━━━━━━━━━━",
        "",
        f"{p_icon} *Total P&L:* `{fmt_pnl(stats['total_pnl'], bt)}`",
        f"📈 *Win Rate:* `{stats['win_rate']}%` ({stats['wins']}W/{stats['losses']}L/{stats['total']} trades)",
        f"⚖️ *Profit Factor:* `{pf}`",
        "",
        "─────────────────────",
        f"✅ *Avg Win:*   `{fmt_pnl(stats['avg_win'], bt)}`",
        f"❌ *Avg Loss:*  `{fmt_pnl(abs(stats['avg_loss']), wt)}`",
        "",
        "─────────────────────",
        f"🏆 *Best:*  #{best['id']} {best['ticker']} `{fmt_pnl(best['pnl'], bt)}` ({best['pnl_pct']}%)",
        f"💥 *Worst:* #{worst['id']} {worst['ticker']} `{fmt_pnl(worst['pnl'], wt)}` ({worst['pnl_pct']}%)",
        "",
        "━━━━━━━━━━━━━━━━━━━━",
    ]

    if stats["win_rate"] >= 60 and stats["total_pnl"] > 0:
        lines.append("💡 _Solid performance — stay disciplined._")
    elif stats["win_rate"] < 40:
        lines.append("💡 _Win rate is low — review your entry criteria._")
    elif stats["total_pnl"] < 0:
        lines.append("💡 _Positive win rate but net loss — losses > wins._")
    else:
        lines.append("💡 _Keep journaling to track improvement._")

    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


async def deltrade_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = context.args
    if not args:
        await update.message.reply_text("Usage: `/deltrade 3`\n\nUse /trades to see IDs.", parse_mode="Markdown")
        return
    try:
        tid = int(args[0])
    except ValueError:
        await update.message.reply_text("❌ Provide a valid trade ID.", parse_mode="Markdown")
        return

    removed = delete_trade(update.effective_user.id, tid)
    msg = f"🗑️ Trade #{tid} deleted." if removed else f"⚠️ No trade found with ID #{tid}. Use /trades."
    await update.message.reply_text(msg, parse_mode="Markdown")


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
        f"You're on a *{data['streak_count']}-trade {s_label}!* 💪 Keep it up."
        if data["streak_type"] == "win"
        else f"You're on a *{data['streak_count']}-trade {s_label}.* Stay patient."
    )

    pnl     = data["final_pnl"]
    p_icon  = "🟢" if pnl >= 0 else "🔴"
    cum     = data["cumulative"]
    n       = data["trade_count"]

    lines = [
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
        f"  Peak: `{max(cum):,.2f}`",
        f"  `{data['sparkline']}`",
        f"  Low:  `{min(cum):,.2f}`",
        f"  Trade #1 ─────── #{n}",
        "",
        "─────────────────────",
        f"{p_icon} *Cumulative P&L:* `{pnl:,.2f}`",
        f"📉 *Max Drawdown:*   `{data['max_drawdown']:,.2f}`",
        "",
        "━━━━━━━━━━━━━━━━━━━━",
        "_/pnl for full stats | /trades to review entries_",
    ]
    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")

# ─────────────────────────────────────────────────────────────────────────────
# /backtest
# ─────────────────────────────────────────────────────────────────────────────

async def backtest_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = context.args
    if not args:
        await update.message.reply_text(
            "Usage: `/backtest TICKER [PERIOD]`\n\n"
            "_Runs an EMA 9/21 crossover strategy on historical data._\n\n"
            "Periods: `6mo`  `1y`  `2y`  `5y` _(default: 1y)_\n\n"
            "Examples:\n"
            "  `/backtest TCS.NS`\n"
            "  `/backtest RELIANCE.NS 2y`\n"
            "  `/backtest ^NSEI 5y`",
            parse_mode="Markdown",
        )
        return

    ticker = args[0].upper().strip()
    period = args[1].lower().strip() if len(args) >= 2 else "1y"
    if period not in {"6mo", "1y", "2y", "5y"}:
        await update.message.reply_text(
            f"❌ Invalid period `{period}`. Use: `6mo` `1y` `2y` `5y`",
            parse_mode="Markdown",
        )
        return

    msg = await update.message.reply_text(
        f"⚙️ Running EMA 9/21 backtest on `{ticker}` ({period})...", parse_mode="Markdown"
    )
    try:
        result = run_backtest(ticker, period)
    except Exception as e:
        logger.exception(f"Backtest error {ticker}: {e}")
        await msg.edit_text(f"❌ Could not fetch data for `{ticker}`.", parse_mode="Markdown")
        return

    if result is None:
        await msg.edit_text(
            f"⚠️ Not enough data for `{ticker}`. Try a longer period.",
            parse_mode="Markdown",
        )
        return

    if result["total"] == 0:
        await msg.edit_text(
            f"📊 *Backtest — `{ticker}` ({period})*\n\n"
            f"No EMA 9/21 crossovers found.\n"
            f"Buy & Hold: `{result['buy_hold']}%`",
            parse_mode="Markdown",
        )
        return

    r      = result
    vs_bh  = r["total_return"] - r["buy_hold"]
    pf_str = str(r["profit_factor"]) if r["profit_factor"] != float("inf") else "∞"

    def pct(v): return f"+{v}%" if v >= 0 else f"{v}%"

    recent = r["trades"][-5:]
    trade_lines = [
        f"  {'✅' if t['won'] else '❌'} `{t['entry_date']}→{t['exit_date']}` `{pct(t['pnl_pct'])}`"
        + (" 🔓" if t.get("open") else "")
        for t in recent
    ]

    lines = [
        f"📊 *Backtest — `{ticker}` ({period})*",
        "_Strategy: EMA 9/21 crossover_",
        "━━━━━━━━━━━━━━━━━━━━",
        "",
        f"📋 *Summary*",
        f"  Trades:     `{r['total']}` ({r['wins']}W/{r['losses']}L)",
        f"  Win rate:   `{r['win_rate']}%`",
        f"  Profit fac: `{pf_str}`",
        "",
        "─────────────────────",
        f"💰 *Returns*",
        f"  {'🟢' if r['total_return'] >= 0 else '🔴'} Strategy:   `{pct(r['total_return'])}`",
        f"  {'🟢' if r['buy_hold'] >= 0 else '🔴'} Buy & Hold: `{pct(r['buy_hold'])}`",
        f"  {'✅' if vs_bh >= 0 else '❌'} Outperforms:`{pct(round(vs_bh, 2))}`",
        "",
        "─────────────────────",
        f"📈 *Per-Trade Stats*",
        f"  Avg win:    `+{r['avg_win']}%`",
        f"  Avg loss:   `{r['avg_loss']}%`",
        f"  Max DD:     `-{r['max_drawdown']}%`",
        "",
        "─────────────────────",
        f"📉 *Equity Curve*",
        f"  `{r['sparkline']}`",
        f"  #1 {'─' * max(1, min(len(r['sparkline'])-2, 14))} #{r['total']}",
        "",
        f"🕒 *Last {len(recent)} Trades*",
    ] + trade_lines + [
        "",
        "━━━━━━━━━━━━━━━━━━━━",
        "🔓 _= still open at period end_",
        DISCLAIMER,
    ]
    await msg.edit_text("\n".join(lines), parse_mode="Markdown")

# ─────────────────────────────────────────────────────────────────────────────
# Price alert check job + handlers
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
                price = getattr(yf.Ticker(ticker).fast_info, "last_price", None)
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
                            f"{'Above' if condition == 'above' else 'Below'} your target: `{fmt(target, ticker)}`\n\n"
                            f"_Send `{ticker}` for the full analysis._\n\n"
                            + DISCLAIMER
                        ),
                        parse_mode="Markdown",
                    )
                    remove_triggered_alert(uid, alert_id)
                    logger.info(f"Alert triggered: {ticker} {condition} {target} user {uid}")
            except Exception as e:
                logger.warning(f"Alert check failed {ticker} user {uid}: {e}")


async def alert_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = context.args
    if len(args) < 3:
        await update.message.reply_text(
            "Usage: `/alert TICKER above PRICE`\n\n"
            "Examples:\n"
            "  `/alert RELIANCE.NS above 3000`\n"
            "  `/alert TCS.NS below 3500`\n\n"
            "_Alerts fire once when price crosses your target._",
            parse_mode="Markdown",
        )
        return

    ticker    = args[0].upper().strip()
    condition = args[1].lower().strip()
    if condition not in ("above", "below"):
        await update.message.reply_text(
            "❌ Condition must be `above` or `below`.", parse_mode="Markdown"
        )
        return

    try:
        target = float(args[2].replace("₹","").replace("$","").replace(",",""))
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
        "_Checked every 15 minutes. Use /alerts to view all._",
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

    lines = ["🔔 *Your Price Alerts:*", ""]
    for a in alerts:
        arrow = "⬆️" if a["condition"] == "above" else "⬇️"
        lines.append(f"  #{a['id']} {arrow} *{a['ticker']}* {a['condition']} `{fmt(a['target'], a['ticker'])}`")
    lines += ["", "_Use `/delalert ID` to cancel._"]
    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


async def delalert_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = context.args
    if not args:
        await update.message.reply_text("Usage: `/delalert 1`\n\nUse /alerts to see IDs.", parse_mode="Markdown")
        return
    try:
        alert_id = int(args[0])
    except ValueError:
        await update.message.reply_text("❌ Provide a valid alert ID.", parse_mode="Markdown")
        return

    uid     = update.effective_user.id
    removed = remove_price_alert(uid, alert_id)
    msg = f"✅ Alert #{alert_id} cancelled." if removed else f"⚠️ No alert #{alert_id} found. Use /alerts."
    await update.message.reply_text(msg, parse_mode="Markdown")

# ─────────────────────────────────────────────────────────────────────────────
# Startup: restore saved daily alerts
# ─────────────────────────────────────────────────────────────────────────────

async def restore_alerts(app):
    all_alerts = get_all_alerts()
    count = 0
    for uid_str, config in all_alerts.items():
        try:
            schedule_alert(
                app,
                user_id=int(uid_str),
                chat_id=config["chat_id"],
                hour=config["hour"],
                minute=config["minute"],
            )
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
        raise RuntimeError("TELEGRAM_BOT_TOKEN environment variable is not set.")

    app = (
        ApplicationBuilder()
        .token(token)
        .post_init(restore_alerts)
        .build()
    )

    # Price alert checker — every 15 minutes
    app.job_queue.run_repeating(check_price_alerts, interval=900, first=60)

    # ── Analysis ──────────────────────────────────────
    app.add_handler(CommandHandler("start",       start_handler))
    app.add_handler(CommandHandler("help",        help_handler))
    app.add_handler(CommandHandler("about",       about_handler))

    app.add_handler(CommandHandler("nifty",       nifty_handler))
    app.add_handler(CommandHandler("signal",      signal_handler))
    app.add_handler(CommandHandler("swing",       swing_handler))
    app.add_handler(CommandHandler("intraday",    intraday_handler))
    app.add_handler(CommandHandler("summary",     summary_handler))
    app.add_handler(CommandHandler("report",      report_handler))
    app.add_handler(CommandHandler("sentiment",   sentiment_handler))

    # ── Market screeners ──────────────────────────────
    app.add_handler(CommandHandler("top",         top_handler))
    app.add_handler(CommandHandler("movers",      movers_handler))
    app.add_handler(CommandHandler("compare",     compare_handler))
    app.add_handler(CommandHandler("breakout",    breakout_handler))
    app.add_handler(CommandHandler("gainers52w",  gainers52w_handler))
    app.add_handler(CommandHandler("oversold",    oversold_handler))
    app.add_handler(CommandHandler("sector",      sector_handler))
    app.add_handler(CommandHandler("heatmap",     heatmap_handler))

    # ── Watchlist ─────────────────────────────────────
    app.add_handler(CommandHandler("watchlist",   watchlist_handler))
    app.add_handler(CommandHandler("add",         add_handler))
    app.add_handler(CommandHandler("remove",      remove_handler))
    app.add_handler(CommandHandler("clear",       clear_handler))
    app.add_handler(CommandHandler("scan",        scan_handler))

    # ── Alerts ────────────────────────────────────────
    app.add_handler(CommandHandler("setalert",    setalert_handler))
    app.add_handler(CommandHandler("myalert",     myalert_handler))
    app.add_handler(CommandHandler("cancelalert", cancelalert_handler))
    app.add_handler(CommandHandler("alert",       alert_handler))
    app.add_handler(CommandHandler("alerts",      list_alerts_handler))
    app.add_handler(CommandHandler("delalert",    delalert_handler))

    # ── Risk & backtesting ────────────────────────────
    app.add_handler(CommandHandler("risk",        risk_handler))
    app.add_handler(CommandHandler("backtest",    backtest_handler))

    # ── Trade journal ─────────────────────────────────
    app.add_handler(CommandHandler("journal",     journal_handler))
    app.add_handler(CommandHandler("trades",      trades_handler))
    app.add_handler(CommandHandler("pnl",         pnl_handler))
    app.add_handler(CommandHandler("deltrade",    deltrade_handler))
    app.add_handler(CommandHandler("streak",      streak_handler))

    # ── Catch-all ticker message ──────────────────────
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, analyze_handler))

    logger.info("MarketMasteryAI Bot starting — all handlers registered.")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
