import os
import logging
from datetime import time as dtime
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes
from analysis import analyze
from formatter import format_report
from watchlist import get_watchlist, add_tickers, remove_tickers, clear_watchlist
from alerts import set_alert, remove_alert, get_alert, get_all_alerts
from sentiment import fetch_sentiment
from journal import add_trade, get_trades, delete_trade, get_pnl_stats, get_streak_and_equity
from backtest import run_backtest
from utils import fmt, fmt_pnl, sig_icon, chg_str, chg_emoji, rsi_zone, is_indian
from price_alerts import (
    add_price_alert, get_user_alerts, remove_price_alert,
    remove_triggered_alert, get_all_price_alerts,
)

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

DISCLAIMER = "⚠️ _For educational purposes only. Not financial advice. Always consult a SEBI-registered advisor._"

HELP_TEXT = """
🤖 *MarketMasteryAI Bot*
_Your AI-powered Indian Stock Market Assistant_

━━━━━━━━━━━━━━━━━━━━

📌 *Quick Start*
Just type any ticker to get full analysis:
  `RELIANCE.NS` `TCS.NS` `HDFCBANK.NS`
  `^NSEI` (Nifty 50)  `^NSEBANK` (Bank Nifty)

━━━━━━━━━━━━━━━━━━━━

📊 *Analysis Commands*
  /signal RELIANCE.NS   — Quick AI signal card
  /swing RELIANCE.NS    — Swing trade setup (Entry/SL/Targets)
  /intraday RELIANCE.NS — Intraday bias & key levels
  /report RELIANCE.NS   — Full premium analysis report
  /summary RELIANCE.NS  — Technicals + sentiment brief
  /sentiment RELIANCE.NS — News sentiment analysis

━━━━━━━━━━━━━━━━━━━━

🔍 *Market Screeners*
  /top               — Top signals (Indian + US)
  /top india         — Indian stocks only
  /top us            — US stocks only
  /breakout          — Active breakouts right now
  /gainers52w        — Near 52-week highs with momentum
  /gainers52w india  — Indian only
  /oversold          — Oversold dip-buy setups
  /oversold india    — Indian only
  /movers            — Today's top gainers & losers

━━━━━━━━━━━━━━━━━━━━

🗺️ *Market Overview*
  /heatmap  — Visual signal grid of all stocks
  /sector   — Sector strength & RSI overview
  /compare RELIANCE.NS TCS.NS — Side-by-side comparison

━━━━━━━━━━━━━━━━━━━━

📋 *Watchlist*
  /watchlist           — View your saved tickers
  /add TCS.NS INFY.NS  — Add tickers
  /remove TCS.NS       — Remove a ticker
  /scan                — Analyse your full watchlist
  /clear               — Clear watchlist

━━━━━━━━━━━━━━━━━━━━

🔔 *Alerts*
  /alert RELIANCE.NS above 3000 — Price alert
  /alert HDFCBANK.NS below 1600 — Price alert
  /alerts              — View active alerts
  /delalert 1          — Cancel alert by ID
  /setalert 03:45      — Daily watchlist scan (UTC)
  /myalert             — Check your daily alert time
  /cancelalert         — Cancel daily alert

━━━━━━━━━━━━━━━━━━━━

📒 *Trade Journal*
  /journal TCS.NS long 3800 4100 10 — Log a trade
  /trades              — View trade history
  /pnl                 — P&L stats & profit factor
  /streak              — Win streak & equity curve
  /deltrade 3          — Delete a trade by ID

━━━━━━━━━━━━━━━━━━━━

📐 *Risk & Backtesting*
  /risk RELIANCE.NS 100000 — Position sizing for your capital
  /risk RELIANCE.NS 100000 1 — 1% risk per trade
  /backtest TCS.NS      — EMA 9/21 backtest (1 year)
  /backtest TCS.NS 2y   — Specify period: 6mo 1y 2y 5y

━━━━━━━━━━━━━━━━━━━━

💡 *Indian Market Tips*
  • NSE stocks: add `.NS`  e.g. `TCS.NS`
  • BSE stocks: add `.BO`  e.g. `TCS.BO`
  • Nifty 50 Index: `^NSEI`
  • Bank Nifty:     `^NSEBANK`
  • Market hours: 9:15 AM – 3:30 PM IST

⚠️ _For educational purposes only. Not financial advice._
"""

ABOUT_TEXT = """
🤖 *MarketMasteryAI Bot*

_A premium AI-powered Indian stock market assistant_

━━━━━━━━━━━━━━━━━━━━

*Indicators computed:*
• RSI (14) — Relative Strength Index
• EMA 9, 21, 50, 200 — Trend direction
• MACD (12/26/9) — Momentum
• Bollinger Bands (20, 2σ) — Volatility
• ATR (14) — Average True Range
• OBV — On-Balance Volume trend
• Support & Resistance (20-day)

*Features:*
• 🇮🇳 Indian NSE/BSE stocks (₹ INR)
• 📊 Buy/Sell/Hold AI signals
• 🏹 Swing trade setups with SL & Targets
• 🚨 Breakout detection
• 📋 Personal watchlist
• 🔔 Price & daily alerts
• 📒 Trade journal & P&L tracker
• 📈 Equity curve & streak tracking
• 🧪 EMA crossover backtesting
• 📐 Position sizing & risk calculator

*Data source:* Yahoo Finance (yfinance)
*Indices:* Nifty 50, Bank Nifty supported

⚠️ _For educational purposes only._
_Not financial advice. Past performance ≠ future results._
"""


# ──────────────────────────────────────────────
# Indian market stock lists
# ──────────────────────────────────────────────

TOP_INDIA = [
    "RELIANCE.NS", "TCS.NS", "INFY.NS", "HDFCBANK.NS", "ICICIBANK.NS",
    "SBIN.NS", "WIPRO.NS", "BAJFINANCE.NS", "AXISBANK.NS", "KOTAKBANK.NS",
    "LT.NS", "MARUTI.NS", "TATAMOTORS.NS", "SUNPHARMA.NS", "ADANIENT.NS",
    "HINDALCO.NS", "NTPC.NS", "TATASTEEL.NS", "BHARTIARTL.NS", "POWERGRID.NS",
]

TOP_US = [
    "AAPL", "MSFT", "NVDA", "GOOGL", "AMZN",
    "META", "TSLA", "AMD", "NFLX", "JPM",
    "V", "MA", "BAC", "DIS", "INTC",
]

NIFTY_INDICES = ["^NSEI", "^NSEBANK"]

SIGNAL_RANK = {
    "STRONG BUY": 0,
    "STRONG SELL": 1,
    "BUY": 2,
    "SELL": 3,
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
    "LT.NS":         "🏗️ Infra",
    "MARUTI.NS":     "🚗 Auto",
    "TATAMOTORS.NS": "🚗 Auto",
    "HINDALCO.NS":   "🔩 Metals",
    "TATASTEEL.NS":  "🔩 Metals",
    "NTPC.NS":       "⚡ Power",
    "POWERGRID.NS":  "⚡ Power",
    "SUNPHARMA.NS":  "💊 Pharma",
    "ADANIENT.NS":   "🏗️ Infra",
    "AAPL":          "💻 Tech (US)",
    "MSFT":          "💻 Tech (US)",
    "NVDA":          "💻 Tech (US)",
    "GOOGL":         "💻 Tech (US)",
    "AMZN":          "💻 Tech (US)",
    "META":          "💻 Tech (US)",
    "AMD":           "💻 Tech (US)",
    "NFLX":          "🎬 Media (US)",
    "INTC":          "💻 Tech (US)",
    "TSLA":          "🚗 Auto (US)",
    "JPM":           "🏦 Finance (US)",
    "V":             "🏦 Finance (US)",
    "MA":            "🏦 Finance (US)",
    "BAC":           "🏦 Finance (US)",
    "DIS":           "🎬 Media (US)",
}

SECTOR_ORDER = [
    "💻 IT / Tech", "🏦 Banking", "💰 NBFC",
    "⚡ Energy & Retail", "⚡ Power", "📡 Telecom",
    "🚗 Auto", "🔩 Metals", "🏗️ Infra", "💊 Pharma",
    "💻 Tech (US)", "🏦 Finance (US)", "🚗 Auto (US)", "🎬 Media (US)",
]


# ──────────────────────────────────────────────
# Helper: build scan message row
# ──────────────────────────────────────────────

def _sig_icon_str(sig: str) -> str:
    return sig_icon(sig)


def build_scan_message(tickers: list[str]) -> str:
    results = []
    errors  = []
    for ticker in tickers:
        try:
            data    = analyze(ticker)
            sig     = data["signal"]["action"]
            rsi     = data["rsi"]
            chg     = data["change_pct"]
            price   = data["last_close"]
            brk     = data["breakout"]
            swing_d = data["swing"]["direction"]
            icon    = sig_icon(sig)
            brk_tag = " 🚨BRK↑" if brk["breakout_up"] else (" 💥BRK↓" if brk["breakout_down"] else "")
            results.append(
                f"{icon} *{ticker}* `{fmt(price, ticker)}` ({chg_str(chg)}) | RSI `{rsi}` | {swing_d}{brk_tag}"
            )
        except Exception as e:
            logger.warning(f"Scan error for {ticker}: {e}")
            errors.append(f"⚠️ `{ticker}` — could not fetch data")

    lines = [f"📊 *Watchlist Scan — {len(tickers)} ticker(s)*", "━━━━━━━━━━━━━━━━━━━━", ""]
    lines.extend(results)
    if errors:
        lines.append("")
        lines.extend(errors)
    lines.append("")
    lines.append("_Tap any ticker symbol to get the full analysis._")
    lines.append(DISCLAIMER)
    return "\n".join(lines)


# ──────────────────────────────────────────────
# Daily alert job
# ──────────────────────────────────────────────

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
    text = f"⏰ *Daily Watchlist Alert*\n\n" + build_scan_message(tickers)
    await context.bot.send_message(chat_id=chat_id, text=text, parse_mode="Markdown")


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


# ──────────────────────────────────────────────
# /start  /help  /about
# ──────────────────────────────────────────────

async def start_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🤖 *Welcome to MarketMasteryAI Bot!*\n"
        "_Your AI-powered Indian Stock Market Assistant_\n\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        "📌 *How to use:*\n"
        "Just type any stock ticker to get a full analysis:\n"
        "  `RELIANCE.NS` — Reliance Industries\n"
        "  `TCS.NS`      — Tata Consultancy Services\n"
        "  `HDFCBANK.NS` — HDFC Bank\n"
        "  `^NSEI`       — Nifty 50 Index\n"
        "  `^NSEBANK`    — Bank Nifty Index\n\n"
        "🎯 *Quick commands:*\n"
        "  /signal TCS.NS  — AI signal card\n"
        "  /swing TCS.NS   — Swing trade setup\n"
        "  /heatmap        — Market heatmap\n"
        "  /top india      — Top Indian signals\n"
        "  /breakout       — Active breakout stocks\n\n"
        "📋 /watchlist | /scan | /help\n\n"
        "🇮🇳 _Specialised for NSE/BSE traders. Prices in ₹ INR._\n\n"
        "⚠️ _For educational purposes only. Not financial advice._",
        parse_mode="Markdown",
    )


async def help_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(HELP_TEXT, parse_mode="Markdown")


async def about_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(ABOUT_TEXT, parse_mode="Markdown")


# ──────────────────────────────────────────────
# Watchlist handlers
# ──────────────────────────────────────────────

async def watchlist_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    tickers = get_watchlist(user_id)
    if not tickers:
        await update.message.reply_text(
            "📋 Your watchlist is empty.\n\nUse `/add TCS.NS RELIANCE.NS` to add tickers.",
            parse_mode="Markdown",
        )
        return
    lines = ["📋 *Your Watchlist:*", ""]
    for i, t in enumerate(tickers, 1):
        ind = " 🇮🇳" if is_indian(t) else " 🇺🇸"
        lines.append(f"  {i}. `{t}`{ind}")
    lines.append("")
    lines.append("Use /scan to analyse all tickers at once.")
    lines.append("Use `/setalert 03:45` to get a daily morning scan.")
    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


async def add_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    args = context.args
    if not args:
        await update.message.reply_text(
            "Usage: `/add TCS.NS RELIANCE.NS HDFCBANK.NS`\n\nYou can add up to 20 tickers.",
            parse_mode="Markdown",
        )
        return
    added, already = add_tickers(user_id, args)
    lines = []
    if added:
        lines.append("✅ Added: " + ", ".join(f"`{t}`" for t in added))
    if already:
        lines.append("ℹ️ Already in watchlist: " + ", ".join(f"`{t}`" for t in already))
    total = get_watchlist(user_id)
    lines.append(f"\n📋 Watchlist now has *{len(total)}* ticker(s). Use /scan to analyse them.")
    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


async def remove_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    args = context.args
    if not args:
        await update.message.reply_text("Usage: `/remove TCS.NS RELIANCE.NS`", parse_mode="Markdown")
        return
    removed, not_found = remove_tickers(user_id, args)
    lines = []
    if removed:
        lines.append("🗑️ Removed: " + ", ".join(f"`{t}`" for t in removed))
    if not_found:
        lines.append("⚠️ Not in watchlist: " + ", ".join(f"`{t}`" for t in not_found))
    total = get_watchlist(user_id)
    lines.append(f"\n📋 Watchlist now has *{len(total)}* ticker(s).")
    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


async def clear_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    clear_watchlist(user_id)
    await update.message.reply_text("🗑️ Your watchlist has been cleared.", parse_mode="Markdown")


async def scan_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    tickers = get_watchlist(user_id)
    if not tickers:
        await update.message.reply_text(
            "📋 Your watchlist is empty.\n\nUse `/add TCS.NS RELIANCE.NS` to add tickers first.",
            parse_mode="Markdown",
        )
        return
    msg = await update.message.reply_text(
        f"🔍 Scanning *{len(tickers)}* ticker(s)... please wait.",
        parse_mode="Markdown",
    )
    await msg.edit_text(build_scan_message(tickers), parse_mode="Markdown")


# ──────────────────────────────────────────────
# Alert schedule handlers
# ──────────────────────────────────────────────

async def setalert_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    args = context.args
    if not args:
        await update.message.reply_text(
            "Usage: `/setalert HH:MM` (24-hour UTC)\n\n"
            "Example: `/setalert 03:45` — 3:45 AM UTC = 9:15 AM IST\n\n"
            "💡 IST = UTC + 5:30. NSE opens at 9:15 AM IST (3:45 AM UTC).",
            parse_mode="Markdown",
        )
        return
    try:
        parts  = args[0].split(":")
        hour   = int(parts[0])
        minute = int(parts[1])
        if not (0 <= hour <= 23 and 0 <= minute <= 59):
            raise ValueError()
    except (ValueError, IndexError):
        await update.message.reply_text(
            "❌ Invalid format. Use HH:MM in 24-hour UTC.\n\nExample: `/setalert 03:45`",
            parse_mode="Markdown",
        )
        return

    set_alert(user_id, chat_id, hour, minute)
    schedule_alert(context.application, user_id, chat_id, hour, minute)
    tickers = get_watchlist(user_id)
    wl_note = (
        f"Your watchlist has *{len(tickers)}* ticker(s)."
        if tickers
        else "Your watchlist is empty — use `/add TCS.NS RELIANCE.NS` to add tickers."
    )
    await update.message.reply_text(
        f"⏰ Daily alert set for *{hour:02d}:{minute:02d} UTC* every day.\n\n{wl_note}",
        parse_mode="Markdown",
    )


async def myalert_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    alert   = get_alert(user_id)
    if not alert:
        await update.message.reply_text(
            "You have no daily alert set.\n\nUse `/setalert 03:45` to set one.",
            parse_mode="Markdown",
        )
        return
    h, m = alert["hour"], alert["minute"]
    await update.message.reply_text(
        f"⏰ Your daily alert is set for *{h:02d}:{m:02d} UTC*.\n\nUse /cancelalert to remove it.",
        parse_mode="Markdown",
    )


async def cancelalert_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    removed = remove_alert(user_id)
    for job in context.application.job_queue.get_jobs_by_name(f"alert_{user_id}"):
        job.schedule_removal()
    if removed:
        await update.message.reply_text("✅ Your daily alert has been cancelled.", parse_mode="Markdown")
    else:
        await update.message.reply_text("You don't have an active alert.", parse_mode="Markdown")


# ──────────────────────────────────────────────
# /signal — Quick AI signal card
# ──────────────────────────────────────────────

async def signal_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = context.args
    if not args:
        await update.message.reply_text(
            "Usage: `/signal TICKER`\n\nExamples:\n  `/signal RELIANCE.NS`\n  `/signal TCS.NS`\n  `/signal ^NSEI`",
            parse_mode="Markdown",
        )
        return

    ticker = args[0].upper().strip()
    msg    = await update.message.reply_text(f"⚡ Getting signal for `{ticker}`...", parse_mode="Markdown")

    try:
        data = analyze(ticker)
    except Exception as e:
        logger.exception(f"Signal error for {ticker}: {e}")
        await msg.edit_text(f"❌ Could not fetch data for `{ticker}`.", parse_mode="Markdown")
        return

    sig     = data["signal"]["action"]
    icon    = sig_icon(sig)
    price   = data["last_close"]
    chg     = data["change_pct"]
    rsi     = data["rsi"]
    swing   = data["swing"]
    brk     = data["breakout"]
    vol     = data["volume"]
    ema_dir = "Bullish ↑" if data["ema9"] > data["ema21"] else "Bearish ↓"

    brk_line = ""
    if brk["breakout_up"]:
        brk_line = "🚨 *BREAKOUT UP!* — Resistance cleared"
    elif brk["breakout_down"]:
        brk_line = "💥 *BREAKDOWN!* — Support broken"

    vol_note = ""
    if vol["volume_ratio"] >= 2.0:
        vol_note = " 🔥 High volume surge!"
    elif vol["volume_ratio"] >= 1.5:
        vol_note = " ⬆️ Above average volume"

    dir_arrow = "⬆️" if swing["direction"] == "LONG" else "⬇️"

    lines = [
        f"⚡ *Signal Card — `{ticker}`*",
        f"_({data['name']})_",
        "━━━━━━━━━━━━━━━━━━━━",
        "",
        f"💰 Price:   `{fmt(price, ticker)}` {chg_emoji(chg)} `{chg_str(chg)}`",
        f"🎯 Signal:  {icon} *{sig}*",
        f"📉 RSI:     `{rsi}` — {rsi_zone(rsi)}",
        f"📐 EMA:     `{ema_dir}`",
        "",
    ]
    if brk_line:
        lines.append(brk_line)
        lines.append("")
    lines += [
        f"🏹 Swing:  {dir_arrow} {swing['direction']} | Conf: `{swing['confidence']}%`",
        f"   SL: `{fmt(swing['stop_loss'], ticker)}` | T1: `{fmt(swing['target1'], ticker)}` | T2: `{fmt(swing['target2'], ticker)}`",
        f"   Volume: `{vol['volume_ratio']}x`{vol_note}",
        "",
        "━━━━━━━━━━━━━━━━━━━━",
        DISCLAIMER,
    ]
    await msg.edit_text("\n".join(lines), parse_mode="Markdown")


# ──────────────────────────────────────────────
# /swing — Detailed swing trade setup
# ──────────────────────────────────────────────

async def swing_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = context.args
    if not args:
        await update.message.reply_text(
            "Usage: `/swing TICKER`\n\nExamples:\n  `/swing RELIANCE.NS`\n  `/swing TCS.NS`",
            parse_mode="Markdown",
        )
        return

    ticker = args[0].upper().strip()
    msg    = await update.message.reply_text(f"🏹 Building swing setup for `{ticker}`...", parse_mode="Markdown")

    try:
        data = analyze(ticker)
    except Exception as e:
        logger.exception(f"Swing error for {ticker}: {e}")
        await msg.edit_text(f"❌ Could not fetch data for `{ticker}`.", parse_mode="Markdown")
        return

    price  = data["last_close"]
    swing  = data["swing"]
    brk    = data["breakout"]
    sig    = data["signal"]["action"]
    icon   = sig_icon(sig)
    rsi    = data["rsi"]

    dir_arrow = "⬆️ LONG" if swing["direction"] == "LONG" else "⬇️ SHORT"
    conf      = swing["confidence"]
    conf_bar  = "●" * (conf // 20) + "○" * (5 - conf // 20)

    risk_per_share = abs(price - swing["stop_loss"])
    reward1        = abs(swing["target1"] - price)
    reward2        = abs(swing["target2"] - price)
    rr1            = round(reward1 / risk_per_share, 2) if risk_per_share else 0
    rr2            = round(reward2 / risk_per_share, 2) if risk_per_share else 0

    rr1_v = "✅ Good" if rr1 >= 2 else ("⚠️ Marginal" if rr1 >= 1 else "❌ Poor")
    rr2_v = "✅ Good" if rr2 >= 2 else ("⚠️ Marginal" if rr2 >= 1 else "❌ Poor")

    brk_note = ""
    if brk["breakout_up"]:
        brk_note = "\n🚨 *Active Breakout!* — Adds conviction to LONG setup"
    elif brk["breakout_down"]:
        brk_note = "\n💥 *Active Breakdown!* — Adds conviction to SHORT setup"

    lines = [
        f"🏹 *Swing Trade Setup — `{ticker}`*",
        f"_({data['name']})_",
        "━━━━━━━━━━━━━━━━━━━━",
        "",
        f"💰 Current Price: `{fmt(price, ticker)}` `{chg_str(data['change_pct'])}`",
        f"🎯 AI Signal:     {icon} {sig}",
        f"📉 RSI (14):      `{rsi}` — {rsi_zone(rsi)}",
        "",
        f"─────────────────────────",
        f"🏹 *Direction: {dir_arrow}*",
        f"   Confidence: `{conf}%`  [{conf_bar}]",
        f"   ATR (14):   `{fmt(swing['atr'], ticker)}`",
        brk_note,
        "",
        f"─────────────────────────",
        f"📍 *Trade Levels:*",
        f"   Entry (now): `{fmt(price, ticker)}`",
        f"   🛡️ Stop Loss: `{fmt(swing['stop_loss'], ticker)}`  (−`{fmt(round(risk_per_share, 2), ticker)}` per share)",
        f"   🎯 Target 1:  `{fmt(swing['target1'], ticker)}`  → R:R `{rr1}x` {rr1_v}",
        f"   🎯 Target 2:  `{fmt(swing['target2'], ticker)}`  → R:R `{rr2}x` {rr2_v}",
        "",
        f"─────────────────────────",
        f"📊 *Key Levels:*",
        f"   Resistance: `{fmt(brk['resistance'], ticker)}`",
        f"   Support:    `{fmt(brk['support'], ticker)}`",
        "",
        "━━━━━━━━━━━━━━━━━━━━",
        "💡 _Use /risk to calculate your position size._",
        DISCLAIMER,
    ]
    await msg.edit_text("\n".join([l for l in lines if l is not None]), parse_mode="Markdown")


# ──────────────────────────────────────────────
# /intraday — Intraday bias & key levels
# ──────────────────────────────────────────────

async def intraday_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = context.args
    if not args:
        await update.message.reply_text(
            "Usage: `/intraday TICKER`\n\nExamples:\n  `/intraday RELIANCE.NS`\n  `/intraday ^NSEI`",
            parse_mode="Markdown",
        )
        return

    ticker = args[0].upper().strip()
    msg    = await update.message.reply_text(f"📈 Calculating intraday bias for `{ticker}`...", parse_mode="Markdown")

    try:
        data = analyze(ticker)
    except Exception as e:
        logger.exception(f"Intraday error for {ticker}: {e}")
        await msg.edit_text(f"❌ Could not fetch data for `{ticker}`.", parse_mode="Markdown")
        return

    price  = data["last_close"]
    rsi    = data["rsi"]
    ema9   = data["ema9"]
    ema21  = data["ema21"]
    macd   = data["macd"]
    macd_s = data["macd_signal"]
    macd_h = data["macd_hist"]
    vol    = data["volume"]
    brk    = data["breakout"]
    swing  = data["swing"]
    sig    = data["signal"]["action"]

    # Intraday bias scoring
    bias_score = 0
    bias_notes = []

    if price > ema9:
        bias_score += 1
        bias_notes.append("✅ Price above EMA9 — short-term bullish")
    else:
        bias_score -= 1
        bias_notes.append("⚠️ Price below EMA9 — short-term bearish")

    if ema9 > ema21:
        bias_score += 1
        bias_notes.append("✅ EMA9 > EMA21 — trend is up")
    else:
        bias_score -= 1
        bias_notes.append("⚠️ EMA9 < EMA21 — trend is down")

    if macd > macd_s:
        bias_score += 1
        bias_notes.append("✅ MACD above signal — bullish momentum")
    else:
        bias_score -= 1
        bias_notes.append("⚠️ MACD below signal — bearish momentum")

    if 35 < rsi < 65:
        bias_notes.append("✅ RSI neutral — no extreme zones")
    elif rsi <= 35:
        bias_score += 1
        bias_notes.append("✅ RSI oversold — potential bounce")
    else:
        bias_score -= 1
        bias_notes.append("⚠️ RSI overbought — upside limited")

    if vol["volume_ratio"] >= 1.3:
        bias_score += 1
        bias_notes.append(f"✅ Volume {vol['volume_ratio']}x avg — active session")
    else:
        bias_notes.append(f"➡️ Volume {vol['volume_ratio']}x avg — quiet session")

    if bias_score >= 3:
        bias_label = "🟢🟢 *Strong Bullish Bias*"
    elif bias_score >= 1:
        bias_label = "🟢 *Bullish Bias*"
    elif bias_score <= -3:
        bias_label = "🔴🔴 *Strong Bearish Bias*"
    elif bias_score <= -1:
        bias_label = "🔴 *Bearish Bias*"
    else:
        bias_label = "🟡 *Neutral / Sideways*"

    # Tight intraday levels (0.5x ATR)
    atr      = swing["atr"]
    long_sl  = round(price - 0.5 * atr, 2)
    short_sl = round(price + 0.5 * atr, 2)
    long_t1  = round(price + 0.8 * atr, 2)
    long_t2  = round(price + 1.5 * atr, 2)

    brk_line = ""
    if brk["breakout_up"]:
        brk_line = "🚨 *Active Breakout UP* — momentum may continue"
    elif brk["breakout_down"]:
        brk_line = "💥 *Active Breakdown* — selling pressure present"

    lines = [
        f"📈 *Intraday Bias — `{ticker}`*",
        f"_({data['name']})_",
        "━━━━━━━━━━━━━━━━━━━━",
        "",
        f"💰 LTP: `{fmt(price, ticker)}` {chg_emoji(data['change_pct'])} `{chg_str(data['change_pct'])}`",
        f"📊 Overall Signal: {sig_icon(sig)} {sig}",
        "",
        f"─────────────────────────",
        f"🧭 *Intraday Bias: {bias_label}*",
        "",
    ] + [f"   {n}" for n in bias_notes] + [
        "",
        f"─────────────────────────",
        f"📍 *Key Intraday Levels:*",
        f"   Resistance: `{fmt(brk['resistance'], ticker)}`",
        f"   Support:    `{fmt(brk['support'], ticker)}`",
        "",
        f"   If bullish — Entry ~`{fmt(price, ticker)}`",
        f"   🛡️ SL: `{fmt(long_sl, ticker)}`  |  🎯 T1: `{fmt(long_t1, ticker)}`  T2: `{fmt(long_t2, ticker)}`",
        "",
    ]
    if brk_line:
        lines.append(brk_line)
        lines.append("")
    lines += [
        f"─────────────────────────",
        f"🕐 *Market Hours (IST):*",
        f"   Pre-open:  9:00 AM — 9:08 AM",
        f"   Session:   9:15 AM — 3:30 PM",
        f"   F&O expiry: Thursday",
        "",
        "━━━━━━━━━━━━━━━━━━━━",
        "💡 _Intraday bias is based on daily technicals. Use with caution._",
        DISCLAIMER,
    ]
    await msg.edit_text("\n".join(lines), parse_mode="Markdown")


# ──────────────────────────────────────────────
# /breakout — Scan for active breakouts
# ──────────────────────────────────────────────

async def breakout_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    arg = " ".join(context.args).lower().strip() if context.args else ""
    if arg == "us":
        tickers = TOP_US
        label   = "🇺🇸 US Stocks"
    elif arg in ("india", "in"):
        tickers = TOP_INDIA
        label   = "🇮🇳 Indian Stocks"
    else:
        tickers = TOP_INDIA
        label   = "🇮🇳 Indian Stocks"

    msg = await update.message.reply_text(
        f"🔍 Scanning {len(tickers)} stocks for active breakouts...", parse_mode="Markdown"
    )

    breakouts_up   = []
    breakdowns     = []
    errors         = []

    for ticker in tickers:
        try:
            data = analyze(ticker)
            brk  = data["breakout"]
            sig  = data["signal"]["action"]
            price = data["last_close"]
            vol   = data["volume"]
            chg   = data["change_pct"]
            if brk["breakout_up"]:
                vol_tag = " 🔥Vol!" if brk["volume_surge"] else ""
                breakouts_up.append({
                    "ticker": ticker,
                    "score": data["signal"]["score"],
                    "line": (
                        f"🚨 *{ticker}* `{fmt(price, ticker)}` ({chg_str(chg)})\n"
                        f"   {sig_icon(sig)} {sig} | RSI `{data['rsi']}` | Vol `{vol['volume_ratio']}x`{vol_tag}\n"
                        f"   Resistance cleared: `{fmt(brk['resistance'], ticker)}`"
                    ),
                })
            elif brk["breakout_down"]:
                vol_tag = " 🔥Vol!" if brk["volume_surge"] else ""
                breakdowns.append({
                    "ticker": ticker,
                    "score": data["signal"]["score"],
                    "line": (
                        f"💥 *{ticker}* `{fmt(price, ticker)}` ({chg_str(chg)})\n"
                        f"   {sig_icon(sig)} {sig} | RSI `{data['rsi']}` | Vol `{vol['volume_ratio']}x`{vol_tag}\n"
                        f"   Support broken: `{fmt(brk['support'], ticker)}`"
                    ),
                })
        except Exception as e:
            logger.warning(f"Breakout scan error for {ticker}: {e}")
            errors.append(ticker)

    lines = [f"🚨 *Breakout Scanner — {label}*", "━━━━━━━━━━━━━━━━━━━━", ""]

    if breakouts_up:
        lines.append(f"🚀 *Breakout UP — {len(breakouts_up)} stock(s):*")
        lines.append("")
        for b in sorted(breakouts_up, key=lambda x: -x["score"]):
            lines.append(b["line"])
            lines.append("")
    else:
        lines.append("🟡 No bullish breakouts detected right now.")
        lines.append("")

    if breakdowns:
        lines.append(f"💥 *Breakdown — {len(breakdowns)} stock(s):*")
        lines.append("")
        for b in sorted(breakdowns, key=lambda x: x["score"]):
            lines.append(b["line"])
            lines.append("")

    if errors:
        lines.append(f"_⚠️ {len(errors)} ticker(s) could not be fetched._")

    lines.append("━━━━━━━━━━━━━━━━━━━━")
    lines.append("_Tap any ticker for a full analysis._")
    lines.append(DISCLAIMER)
    await msg.edit_text("\n".join(lines), parse_mode="Markdown")


# ──────────────────────────────────────────────
# /compare
# ──────────────────────────────────────────────

async def compare_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = context.args
    if not args or len(args) < 2:
        await update.message.reply_text(
            "Usage: `/compare RELIANCE.NS TCS.NS INFY.NS` (2–6 tickers)\n\nCompares signal, RSI, EMA, MACD, and swing setup side by side.",
            parse_mode="Markdown",
        )
        return

    tickers = [a.upper().strip() for a in args[:6]]
    msg = await update.message.reply_text(
        f"🔍 Comparing {', '.join(f'`{t}`' for t in tickers)}...",
        parse_mode="Markdown",
    )

    rows   = []
    errors = []

    for ticker in tickers:
        try:
            data     = analyze(ticker)
            sig      = data["signal"]["action"]
            ema_dir  = "↑ Bull" if data["ema9"] > data["ema21"] else "↓ Bear"
            macd_dir = "↑" if data["macd"] > data["macd_signal"] else "↓"
            bb_pos   = (
                "Above" if data["last_close"] > data["bb_upper"]
                else "Below" if data["last_close"] < data["bb_lower"]
                else "Inside"
            )
            brk     = data["breakout"]
            brk_tag = "↑BRK" if brk["breakout_up"] else ("↓BRK" if brk["breakout_down"] else "—")
            rows.append({
                "ticker":   ticker,
                "price":    data["last_close"],
                "chg":      chg_str(data["change_pct"]),
                "signal":   f"{sig_icon(sig)} {sig}",
                "rsi":      data["rsi"],
                "ema":      ema_dir,
                "macd":     macd_dir,
                "bb":       bb_pos,
                "swing":    data["swing"]["direction"],
                "conf":     data["swing"]["confidence"],
                "brk":      brk_tag,
            })
        except Exception as e:
            logger.warning(f"Compare error for {ticker}: {e}")
            errors.append(ticker)

    if not rows:
        await msg.edit_text("❌ Could not fetch data for any of the tickers.", parse_mode="Markdown")
        return

    lines = ["📊 *Stock Comparison*", "━━━━━━━━━━━━━━━━━━━━", ""]

    for r in rows:
        lines.append(f"*{r['ticker']}* — `{fmt(r['price'], r['ticker'])}` ({r['chg']})")
        lines.append(f"  Signal:   {r['signal']}")
        lines.append(f"  RSI:      `{r['rsi']}`  |  EMA: `{r['ema']}`  |  MACD: `{r['macd']}`")
        lines.append(f"  BB:       `{r['bb']}`  |  Swing: `{r['swing']}` (`{r['conf']}%`)")
        lines.append(f"  Breakout: `{r['brk']}`")
        lines.append("")

    if errors:
        lines.append(f"_⚠️ Could not fetch: {', '.join(errors)}_")
        lines.append("")

    lines.append("_Tap a ticker for its full analysis._")
    lines.append(DISCLAIMER)
    await msg.edit_text("\n".join(lines), parse_mode="Markdown")


# ──────────────────────────────────────────────
# /summary
# ──────────────────────────────────────────────

async def summary_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = context.args
    if not args:
        await update.message.reply_text(
            "Usage: `/summary RELIANCE.NS`\n\nCombines technicals + news sentiment into a concise trade brief.",
            parse_mode="Markdown",
        )
        return

    ticker = args[0].upper().strip()
    msg    = await update.message.reply_text(f"⚡ Building trade brief for `{ticker}`...", parse_mode="Markdown")

    try:
        data = analyze(ticker)
    except Exception as e:
        logger.exception(f"Summary error for {ticker}: {e}")
        await msg.edit_text(f"❌ Could not fetch data for `{ticker}`.", parse_mode="Markdown")
        return

    try:
        sent = fetch_sentiment(ticker)
    except Exception:
        sent = {"overall": "NEUTRAL", "bullish": 0, "bearish": 0, "neutral": 0, "total": 0}

    sig        = data["signal"]["action"]
    price      = data["last_close"]
    chg        = data["change_pct"]
    swing      = data["swing"]
    brk        = data["breakout"]
    rsi        = data["rsi"]
    ema_trend  = "Bullish" if data["ema9"] > data["ema21"] else "Bearish"
    macd_dir   = "Bullish" if data["macd"] > data["macd_signal"] else "Bearish"
    news_mood  = sent["overall"]
    news_icon  = "🟢" if news_mood == "BULLISH" else ("🔴" if news_mood == "BEARISH" else "🟡")

    tech_bull = sig in ("BUY", "STRONG BUY")
    tech_bear = sig in ("SELL", "STRONG SELL")
    news_bull = news_mood == "BULLISH"
    news_bear = news_mood == "BEARISH"

    if tech_bull and news_bull:
        trader_note = "📗 *Technicals and news both bullish* — high-conviction long setup."
    elif tech_bear and news_bear:
        trader_note = "📕 *Technicals and news both bearish* — avoid or consider short."
    elif tech_bull and news_bear:
        trader_note = "⚠️ *Bullish chart but negative news* — wait for news to settle before entering."
    elif tech_bear and news_bull:
        trader_note = "⚠️ *Bearish chart despite positive news* — news may be priced in."
    elif tech_bull:
        trader_note = "📘 *Bullish technicals, neutral news* — trend-driven setup. Watch volume."
    elif tech_bear:
        trader_note = "📘 *Bearish technicals, neutral news* — manage risk carefully."
    else:
        trader_note = "📘 *Mixed signals* — no clear edge. Wait for confirmation."

    if brk["breakout_up"]:
        brk_line = "🚨 Active breakout UP — 20-day resistance cleared with volume"
    elif brk["breakout_down"]:
        brk_line = "💥 Active breakdown — 20-day support broken with volume"
    else:
        brk_line = f"S: `{fmt(brk['support'], ticker)}` — R: `{fmt(brk['resistance'], ticker)}`"

    lines = [
        f"⚡ *Trade Brief — {data['name']} (`{ticker}`)*",
        "━━━━━━━━━━━━━━━━━━━━",
        "",
        f"💰 *Price:* `{fmt(price, ticker)}` ({chg_str(chg)} {chg_emoji(chg)})",
        f"🎯 *Signal:* {sig_icon(sig)} {sig}",
        f"📰 *News:* {news_icon} {news_mood} ({sent['bullish']}↑ {sent['bearish']}↓ / {sent['total']} articles)",
        "",
        "📐 *Key Technicals:*",
        f"  RSI `{rsi}` | EMA `{ema_trend}` | MACD `{macd_dir}`",
        f"  EMA9 `{fmt(data['ema9'], ticker)}` | EMA21 `{fmt(data['ema21'], ticker)}`",
        "",
        "📍 *Key Levels:*",
        f"  {brk_line}",
        "",
        f"🏹 *Swing:* {swing['direction']} (conf `{swing['confidence']}%`)",
        f"  SL `{fmt(swing['stop_loss'], ticker)}` | T1 `{fmt(swing['target1'], ticker)}` | T2 `{fmt(swing['target2'], ticker)}`",
        "",
        "━━━━━━━━━━━━━━━━━━━━",
        f"💡 {trader_note}",
        "",
        DISCLAIMER,
    ]
    await msg.edit_text("\n".join(lines), parse_mode="Markdown")


# ──────────────────────────────────────────────
# /movers
# ──────────────────────────────────────────────

async def movers_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    arg = " ".join(context.args).lower().strip() if context.args else ""
    if arg == "us":
        tickers = TOP_US
        label   = "🇺🇸 US Stocks"
    elif arg in ("india", "in"):
        tickers = TOP_INDIA
        label   = "🇮🇳 Indian Stocks"
    else:
        tickers = TOP_INDIA
        label   = "🇮🇳 Indian Stocks"

    msg = await update.message.reply_text(
        f"🔍 Fetching top movers from {len(tickers)} stocks...", parse_mode="Markdown"
    )

    results = []
    errors  = []

    for ticker in tickers:
        try:
            data = analyze(ticker)
            results.append({
                "ticker":       ticker,
                "price":        data["last_close"],
                "chg":          data["change_pct"],
                "rsi":          data["rsi"],
                "signal":       data["signal"]["action"],
                "volume_ratio": data["volume"]["volume_ratio"],
            })
        except Exception as e:
            logger.warning(f"Movers fetch error for {ticker}: {e}")
            errors.append(ticker)

    if not results:
        await msg.edit_text("❌ Could not fetch data. Please try again later.", parse_mode="Markdown")
        return

    results.sort(key=lambda x: x["chg"], reverse=True)
    gainers = results[:5]
    losers  = list(reversed(results[-5:]))

    def vol_tag(ratio):
        return " 🔥" if ratio >= 2.0 else (" ⬆️" if ratio >= 1.5 else "")

    lines = [f"📈📉 *Top Movers — {label}*", "━━━━━━━━━━━━━━━━━━━━", ""]
    lines.append("🚀 *Top Gainers:*")
    for r in gainers:
        lines.append(
            f"  {sig_icon(r['signal'])} *{r['ticker']}* `{fmt(r['price'], r['ticker'])}` "
            f"`{chg_str(r['chg'])}` | RSI `{r['rsi']}`{vol_tag(r['volume_ratio'])}"
        )

    lines.append("")
    lines.append("💥 *Top Losers:*")
    for r in losers:
        lines.append(
            f"  {sig_icon(r['signal'])} *{r['ticker']}* `{fmt(r['price'], r['ticker'])}` "
            f"`{chg_str(r['chg'])}` | RSI `{r['rsi']}`{vol_tag(r['volume_ratio'])}"
        )

    if errors:
        lines.append(f"\n_⚠️ {len(errors)} ticker(s) could not be fetched._")

    lines.append("")
    lines.append("_Tap any ticker for the full analysis._")
    lines.append(DISCLAIMER)
    await msg.edit_text("\n".join(lines), parse_mode="Markdown")


# ──────────────────────────────────────────────
# /sentiment
# ──────────────────────────────────────────────

async def sentiment_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = context.args
    if not args:
        await update.message.reply_text(
            "Usage: `/sentiment RELIANCE.NS`\n\nFetches recent news and gives a bullish/bearish/neutral sentiment summary.",
            parse_mode="Markdown",
        )
        return

    ticker = args[0].upper().strip()
    msg    = await update.message.reply_text(f"📰 Fetching news for `{ticker}`...", parse_mode="Markdown")

    try:
        s = fetch_sentiment(ticker)
    except Exception as e:
        logger.exception(f"Sentiment error for {ticker}: {e}")
        await msg.edit_text(f"⚠️ Could not fetch news for `{ticker}`. Try again later.", parse_mode="Markdown")
        return

    overall      = s["overall"]
    overall_icon = "🟢 BULLISH" if overall == "BULLISH" else ("🔴 BEARISH" if overall == "BEARISH" else "🟡 NEUTRAL")

    lines = [
        f"📰 *News Sentiment — `{ticker}`*",
        "━━━━━━━━━━━━━━━━━━━━",
        "",
        f"Overall: *{overall_icon}*",
        f"Articles scanned: `{s['total']}`",
        f"🟢 Bullish: `{s['bullish']}`  🔴 Bearish: `{s['bearish']}`  🟡 Neutral: `{s['neutral']}`",
        "",
    ]

    if s["headlines"]:
        lines.append("*Recent Headlines:*")
        lines.append("")
        for h in s["headlines"]:
            icon  = "🟢" if h["score"] > 0 else ("🔴" if h["score"] < 0 else "🟡")
            title = h["title"][:90] + ("..." if len(h["title"]) > 90 else "")
            lines.append(f"{icon} {title}")
    else:
        lines.append("_No recent headlines found for this ticker._")

    lines.append("")
    lines.append("⚠️ _Sentiment is keyword-based. Always verify news independently._")
    await msg.edit_text("\n".join(lines), parse_mode="Markdown")


# ──────────────────────────────────────────────
# /top
# ──────────────────────────────────────────────

async def top_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    arg = " ".join(context.args).lower().strip() if context.args else ""
    if arg == "us":
        tickers = TOP_US
        label   = "🇺🇸 US Stocks"
    elif arg in ("india", "in"):
        tickers = TOP_INDIA
        label   = "🇮🇳 Indian Stocks"
    else:
        tickers = TOP_INDIA
        label   = "🇮🇳 Indian Stocks"

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
            price = data["last_close"]
            chg   = data["change_pct"]

            if not ("STRONG" in sig or (sig in ("BUY", "SELL") and (brk["breakout_up"] or brk["breakout_down"]))):
                continue

            brk_tag = " 🚨BRK↑" if brk["breakout_up"] else (" 💥BRK↓" if brk["breakout_down"] else "")
            hits.append({
                "rank":  SIGNAL_RANK.get(sig, 9),
                "score": abs(score),
                "line":  (
                    f"{sig_icon(sig)} *{ticker}* `{fmt(price, ticker)}` ({chg_str(chg)}) "
                    f"| RSI `{data['rsi']}` | {data['swing']['direction']}{brk_tag}"
                ),
            })
        except Exception as e:
            logger.warning(f"Top scan error for {ticker}: {e}")
            errors.append(ticker)

    hits.sort(key=lambda x: (x["rank"], -x["score"]))

    lines = [f"🏆 *Top Signals — {label}*", "━━━━━━━━━━━━━━━━━━━━", ""]

    if hits:
        lines.append("_Strong signals only (STRONG BUY / STRONG SELL / breakout):_")
        lines.append("")
        for h in hits:
            lines.append(h["line"])
    else:
        lines.append("🟡 No strong signals right now — market is mostly neutral.")
        lines.append("Try again later or use /scan on your own watchlist.")

    if errors:
        lines.append(f"\n_⚠️ {len(errors)} ticker(s) could not be fetched._")

    lines.append("")
    lines.append("_Tap any ticker for the full analysis._")
    lines.append(DISCLAIMER)
    await msg.edit_text("\n".join(lines), parse_mode="Markdown")


# ──────────────────────────────────────────────
# Main ticker message handler
# ──────────────────────────────────────────────

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
            f"❌ {e}\n\nTry: `RELIANCE.NS`, `TCS.NS`, `HDFCBANK.NS`, `^NSEI`",
            parse_mode="Markdown",
        )
    except Exception as e:
        logger.exception(f"Error analyzing {ticker}: {e}")
        await msg.edit_text(
            f"⚠️ Could not analyse `{ticker}`.\n\nCheck the ticker symbol:\n"
            f"• NSE: add `.NS` e.g. `TCS.NS`\n"
            f"• Nifty: use `^NSEI`\n"
            f"• Bank Nifty: use `^NSEBANK`",
            parse_mode="Markdown",
        )


# ──────────────────────────────────────────────
# /gainers52w
# ──────────────────────────────────────────────

async def gainers52w_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    import yfinance as yf

    arg = " ".join(context.args).lower().strip() if context.args else ""
    if arg == "us":
        tickers = TOP_US
        label   = "🇺🇸 US Stocks"
    elif arg in ("india", "in"):
        tickers = TOP_INDIA
        label   = "🇮🇳 Indian Stocks"
    else:
        tickers = TOP_INDIA
        label   = "🇮🇳 Indian Stocks"

    msg = await update.message.reply_text(
        f"🔍 Scanning {len(tickers)} stocks for 52-week high breakouts...", parse_mode="Markdown"
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

            price  = round(float(price), 2)
            high52 = round(float(high52), 2)
            low52  = round(float(low52), 2) if low52 else 0

            pct_from_high = round(((high52 - price) / high52) * 100, 1)
            range_pct     = round(((price - low52) / (high52 - low52)) * 100, 1) if high52 != low52 else 50

            if pct_from_high > 10:
                continue

            data = analyze(ticker)
            sig  = data["signal"]["action"]
            if sig not in ("BUY", "STRONG BUY"):
                continue

            vol_ratio = data["volume"]["volume_ratio"]
            vol_tag   = " 🔥Vol" if vol_ratio >= 2.0 else (" ⬆️Vol" if vol_ratio >= 1.5 else "")
            brk       = data["breakout"]
            brk_tag   = " 🚨BRK↑" if brk["breakout_up"] else ""

            hits.append({
                "pct_from_high": pct_from_high,
                "range_pct":     range_pct,
                "line": (
                    f"{'🟢🟢' if 'STRONG' in sig else '🟢'} *{ticker}* `{fmt(price, ticker)}` ({chg_str(data['change_pct'])})\n"
                    f"   📏 `{pct_from_high}%` below 52w high `{fmt(high52, ticker)}` | Range: `{range_pct}%`\n"
                    f"   RSI `{data['rsi']}` | Signal: {sig}{vol_tag}{brk_tag}"
                ),
            })
        except Exception as e:
            logger.warning(f"52w scan error for {ticker}: {e}")
            errors.append(ticker)

    hits.sort(key=lambda x: x["pct_from_high"])

    lines = [f"📈 *Near 52-Week Highs — {label}*", "━━━━━━━━━━━━━━━━━━━━", ""]
    lines.append("_Bullish stocks within 10% of 52-week high, ranked by proximity:_")
    lines.append("")

    if hits:
        for h in hits:
            lines.append(h["line"])
            lines.append("")
    else:
        lines.append("No stocks currently near 52-week highs with bullish signals.")

    if errors:
        lines.append(f"_⚠️ {len(errors)} ticker(s) could not be fetched._")

    lines.append("_Tap any ticker for the full analysis._")
    lines.append(DISCLAIMER)
    await msg.edit_text("\n".join(lines), parse_mode="Markdown")


# ──────────────────────────────────────────────
# /oversold
# ──────────────────────────────────────────────

async def oversold_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    arg = " ".join(context.args).lower().strip() if context.args else ""
    if arg == "us":
        tickers = TOP_US
        label   = "🇺🇸 US Stocks"
    elif arg in ("india", "in"):
        tickers = TOP_INDIA
        label   = "🇮🇳 Indian Stocks"
    else:
        tickers = TOP_INDIA
        label   = "🇮🇳 Indian Stocks"

    msg = await update.message.reply_text(
        f"🔍 Scanning {len(tickers)} stocks for oversold dip-buy setups...", parse_mode="Markdown"
    )

    hits   = []
    errors = []

    for ticker in tickers:
        try:
            data = analyze(ticker)
            rsi  = data["rsi"]

            if rsi >= 35:
                continue

            ema9  = data["ema9"]
            ema21 = data["ema21"]
            ema50 = data["ema50"]
            ema200 = data["ema200"]
            price = data["last_close"]

            bullish_structure = (ema50 > ema200) or (price > ema50) or (ema9 > ema21)
            if not bullish_structure:
                continue

            macd_rec = data["macd"] > data["macd_signal"]
            vol      = data["volume"]
            swing    = data["swing"]
            brk      = data["breakout"]
            quality  = 0

            if ema50 > ema200:         quality += 2
            if price > ema50:          quality += 1
            if ema9 > ema21:           quality += 1
            if macd_rec:               quality += 1
            if vol["obv_trend"] == "Rising": quality += 1
            if rsi < 25:               quality += 1

            struct_parts = []
            if ema50 > ema200: struct_parts.append("EMA50>200✅")
            if price > ema50:  struct_parts.append("P>EMA50✅")
            if ema9 > ema21:   struct_parts.append("EMA9>21✅")
            struct_str = " | ".join(struct_parts) if struct_parts else "partial"

            hits.append({
                "rsi":     rsi,
                "quality": quality,
                "line": (
                    f"🔵 *{ticker}* `{fmt(price, ticker)}` ({chg_str(data['change_pct'])}) | RSI `{rsi}`\n"
                    f"   Structure: `{struct_str}`\n"
                    f"   Swing: `{swing['direction']}` | SL `{fmt(swing['stop_loss'], ticker)}` | T1 `{fmt(swing['target1'], ticker)}`"
                ),
            })
        except Exception as e:
            logger.warning(f"Oversold scan error for {ticker}: {e}")
            errors.append(ticker)

    hits.sort(key=lambda x: (-x["quality"], x["rsi"]))

    lines = [f"🔵 *Oversold Dip-Buy Setups — {label}*", "━━━━━━━━━━━━━━━━━━━━", ""]
    lines.append("_RSI < 35 with a bullish EMA structure — potential bounce setups:_")
    lines.append("")

    if hits:
        for h in hits:
            lines.append(h["line"])
            lines.append("")
    else:
        lines.append("No oversold setups currently. Market may be in a strong uptrend.")

    if errors:
        lines.append(f"_⚠️ {len(errors)} ticker(s) could not be fetched._")

    lines.append("_Tap any ticker for the full analysis._")
    lines.append(DISCLAIMER)
    await msg.edit_text("\n".join(lines), parse_mode="Markdown")


# ──────────────────────────────────────────────
# /report
# ──────────────────────────────────────────────

async def report_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = context.args
    if not args:
        await update.message.reply_text(
            "Usage: `/report RELIANCE.NS`\n\nGenerates a full premium analysis report you can forward to others.",
            parse_mode="Markdown",
        )
        return

    ticker = args[0].upper().strip()
    msg    = await update.message.reply_text(f"📄 Generating full report for `{ticker}`...", parse_mode="Markdown")

    try:
        data = analyze(ticker)
    except Exception as e:
        logger.exception(f"Report error for {ticker}: {e}")
        await msg.edit_text(f"❌ Could not fetch data for `{ticker}`.", parse_mode="Markdown")
        return

    try:
        sent = fetch_sentiment(ticker)
    except Exception:
        sent = {"overall": "NEUTRAL", "bullish": 0, "bearish": 0, "neutral": 0, "total": 0, "headlines": []}

    from datetime import datetime, timezone
    now   = datetime.now(timezone.utc).strftime("%d %b %Y, %H:%M UTC")
    price = data["last_close"]
    chg   = data["change_pct"]
    sig   = data["signal"]["action"]
    rsi   = data["rsi"]
    swing = data["swing"]
    brk   = data["breakout"]
    vol   = data["volume"]

    if price > data["bb_upper"]:   bb_pos = "Above upper band ⚠️"
    elif price < data["bb_lower"]: bb_pos = "Below lower band — potential bounce ✅"
    else:                           bb_pos = "Within bands ✅"

    if brk["breakout_up"]:   brk_str = "🚨 BREAKOUT UP — Resistance cleared with volume"
    elif brk["breakout_down"]: brk_str = "💥 BREAKDOWN — Support broken with volume"
    else:                       brk_str = f"No breakout | S: {fmt(brk['support'], ticker)} | R: {fmt(brk['resistance'], ticker)}"

    news_icon   = {"BULLISH": "🟢", "BEARISH": "🔴"}.get(sent["overall"], "🟡")
    reasons_str = "\n".join(f"     • {r}" for r in data["signal"]["reasons"])

    top_headlines = ""
    if sent["headlines"]:
        hl = []
        for h in sent["headlines"][:4]:
            icon  = "🟢" if h["score"] > 0 else ("🔴" if h["score"] < 0 else "🟡")
            title = h["title"][:80] + ("..." if len(h["title"]) > 80 else "")
            hl.append(f"  {icon} {title}")
        top_headlines = "\n".join(hl)
    else:
        top_headlines = "  No recent headlines found."

    ema_trend  = "Bullish" if data["ema9"] > data["ema21"] else "Bearish"
    macd_trend = "Bullish" if data["macd"] > data["macd_signal"] else "Bearish"

    lines = [
        f"╔══════════════════════════╗",
        f"  📊 ANALYSIS REPORT",
        f"  {data['name']} ({ticker})",
        f"  {now}",
        f"╚══════════════════════════╝",
        "",
        f"💰 *PRICE*",
        f"  Current:  `{fmt(price, ticker)}` ({chg_str(chg)} {chg_emoji(chg)})",
        f"  Signal:   {sig_icon(sig)} *{sig}*",
        f"",
        f"  Signal reasons:",
        f"{reasons_str}",
        "",
        "─────────────────────────",
        f"📉 *RSI (14)*",
        f"  Value: `{rsi}` — {rsi_zone(rsi)}",
        "",
        "─────────────────────────",
        f"📐 *EMA LEVELS*",
        f"  EMA 9:    `{fmt(data['ema9'], ticker)}`",
        f"  EMA 21:   `{fmt(data['ema21'], ticker)}`",
        f"  EMA 50:   `{fmt(data['ema50'], ticker)}`",
        f"  EMA 200:  `{fmt(data['ema200'], ticker)}`",
        f"  Trend:    `{ema_trend}`",
        "",
        "─────────────────────────",
        f"📊 *MACD (12/26/9)*",
        f"  MACD:    `{data['macd']}`",
        f"  Signal:  `{data['macd_signal']}`",
        f"  Hist:    `{data['macd_hist']}`",
        f"  Trend:   `{macd_trend}`",
        "",
        "─────────────────────────",
        f"📏 *BOLLINGER BANDS (20)*",
        f"  Upper: `{fmt(data['bb_upper'], ticker)}` | Mid: `{fmt(data['bb_mid'], ticker)}` | Lower: `{fmt(data['bb_lower'], ticker)}`",
        f"  Position: {bb_pos}",
        "",
        "─────────────────────────",
        f"📦 *VOLUME*",
        f"  Last:      `{vol['last_volume']:,}`",
        f"  Avg (20d): `{vol['avg_volume_20d']:,}`",
        f"  Ratio:     `{vol['volume_ratio']}x`",
        f"  OBV:       `{vol['obv_trend']}`",
        "",
        "─────────────────────────",
        f"🚨 *BREAKOUT / S\\&R*",
        f"  {brk_str}",
        "",
        "─────────────────────────",
        f"🏹 *SWING TRADE SETUP*",
        f"  Direction:  `{swing['direction']}` (conf. `{swing['confidence']}%`)",
        f"  ATR (14):   `{fmt(swing['atr'], ticker)}`",
        f"  Stop Loss:  `{fmt(swing['stop_loss'], ticker)}`",
        f"  Target 1:   `{fmt(swing['target1'], ticker)}`",
        f"  Target 2:   `{fmt(swing['target2'], ticker)}`",
        "",
        "─────────────────────────",
        f"📰 *NEWS SENTIMENT*",
        f"  Overall: {news_icon} {sent['overall']} ({sent['bullish']}↑ {sent['bearish']}↓ / {sent['total']} articles)",
        f"{top_headlines}",
        "",
        "═════════════════════════",
        DISCLAIMER,
        f"_Generated by MarketMasteryAI Bot_",
    ]

    await msg.edit_text("\n".join(lines), parse_mode="Markdown")


# ──────────────────────────────────────────────
# /sector
# ──────────────────────────────────────────────

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
            logger.warning(f"Sector scan error for {ticker}: {e}")
            errors.append(ticker)

    def dominant_signal(stocks):
        counts = {}
        for s in stocks:
            counts[s["signal"]] = counts.get(s["signal"], 0) + 1
        return max(counts, key=lambda x: counts[x])

    def sector_icon(sig):
        if "STRONG BUY" in sig: return "🟢🟢"
        if "BUY" in sig:         return "🟢"
        if "STRONG SELL" in sig: return "🔴🔴"
        if "SELL" in sig:        return "🔴"
        return "🟡"

    summaries = []
    for sector, stocks in sectors.items():
        avg_rsi  = round(sum(s["rsi"] for s in stocks) / len(stocks), 1)
        avg_chg  = round(sum(s["chg"] for s in stocks) / len(stocks), 2)
        dom_sig  = dominant_signal(stocks)
        avg_sc   = round(sum(s["score"] for s in stocks) / len(stocks), 1)
        breakouts = sum(1 for s in stocks if s["breakout_up"] or s["breakout_down"])
        summaries.append({
            "sector": sector, "avg_rsi": avg_rsi, "avg_chg": avg_chg,
            "dom_sig": dom_sig, "avg_score": avg_sc, "count": len(stocks),
            "breakouts": breakouts, "stocks": stocks,
        })

    summaries.sort(key=lambda x: -x["avg_score"])

    lines = ["🏭 *Sector Strength Overview*", "━━━━━━━━━━━━━━━━━━━━", ""]

    for sec in summaries:
        icon     = sector_icon(sec["dom_sig"])
        brk_tag  = f" | 🚨 {sec['breakouts']} breakout(s)" if sec["breakouts"] else ""
        tkr_list = " ".join(f"`{s['ticker'].replace('.NS','').replace('.BO','')}`" for s in sorted(sec["stocks"], key=lambda x: -x["score"]))
        lines.append(f"{icon} *{sec['sector']}* ({sec['count']} stocks)")
        lines.append(f"  Dominant: `{sec['dom_sig']}` | Avg RSI: `{sec['avg_rsi']}` | Avg Chg: `{chg_str(sec['avg_chg'])}`{brk_tag}")
        lines.append(f"  Tickers: {tkr_list}")
        lines.append("")

    if errors:
        lines.append(f"_⚠️ {len(errors)} ticker(s) could not be fetched._")

    lines.append("_Tap any ticker for a full analysis._")
    lines.append(DISCLAIMER)
    await msg.edit_text("\n".join(lines), parse_mode="Markdown")


# ──────────────────────────────────────────────
# /heatmap
# ──────────────────────────────────────────────

async def heatmap_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    tickers = TOP_INDIA
    msg     = await update.message.reply_text(
        f"🗺️ Building heatmap for {len(tickers)} Indian stocks...", parse_mode="Markdown"
    )

    results = {}
    errors  = []

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
            logger.warning(f"Heatmap error for {ticker}: {e}")
            errors.append(ticker)
            results[ticker] = None

    def cell(ticker: str) -> str:
        r = results.get(ticker)
        if not r:
            return f"⬜`{ticker.replace('.NS','')}`"
        icon  = sig_icon(r["signal"])
        short = ticker.replace(".NS", "").replace(".BO", "")
        return f"{icon}`{short}`"

    strong_buy  = sum(1 for r in results.values() if r and "STRONG BUY" in r["signal"])
    buy         = sum(1 for r in results.values() if r and r["signal"] == "BUY")
    hold        = sum(1 for r in results.values() if r and r["signal"] == "HOLD / NEUTRAL")
    sell        = sum(1 for r in results.values() if r and r["signal"] == "SELL")
    strong_sell = sum(1 for r in results.values() if r and "STRONG SELL" in r["signal"])
    total_bull  = strong_buy + buy
    total_bear  = strong_sell + sell
    breadth     = "Bullish" if total_bull > total_bear else ("Bearish" if total_bear > total_bull else "Neutral")
    breadth_icon = "🟢" if breadth == "Bullish" else ("🔴" if breadth == "Bearish" else "🟡")

    avg_rsi_vals = [r["rsi"] for r in results.values() if r]
    avg_rsi      = round(sum(avg_rsi_vals) / len(avg_rsi_vals), 1) if avg_rsi_vals else 0

    lines = ["🗺️ *NSE Market Heatmap*", "━━━━━━━━━━━━━━━━━━━━", ""]

    sector_tickers: dict[str, list[str]] = {}
    for t in tickers:
        sec = SECTOR_MAP.get(t, "🔹 Other")
        sector_tickers.setdefault(sec, []).append(t)

    for sec in SECTOR_ORDER:
        group = sector_tickers.get(sec)
        if not group:
            continue
        group_sorted = sorted(group, key=lambda t: -(results[t]["score"] if results.get(t) else 0))
        lines.append(f"*{sec}*")
        row = "  " + "  ".join(cell(t) for t in group_sorted)
        lines.append(row)
        lines.append("")

    lines.append("━━━━━━━━━━━━━━━━━━━━")
    lines.append(f"📊 *Market Breadth:* {breadth_icon} *{breadth}*")
    lines.append(f"  🟢🟢 `{strong_buy}`  🟢 `{buy}`  🟡 `{hold}`  🔴 `{sell}`  🔴🔴 `{strong_sell}`")
    lines.append(f"  Avg RSI ({len(tickers)} stocks): `{avg_rsi}`")
    lines.append(f"  Bull: `{total_bull}` | Bear: `{total_bear}`")
    lines.append("")
    lines.append("_Tap any ticker for full analysis._")
    lines.append(DISCLAIMER)
    await msg.edit_text("\n".join(lines), parse_mode="Markdown")


# ──────────────────────────────────────────────
# /risk
# ──────────────────────────────────────────────

async def risk_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = context.args
    if len(args) < 2:
        await update.message.reply_text(
            "Usage: `/risk TICKER CAPITAL [RISK%]`\n\n"
            "Calculates position sizing, max loss, and risk/reward using ATR-based stop loss.\n\n"
            "Examples:\n"
            "  `/risk RELIANCE.NS 100000`      — 2% risk (default)\n"
            "  `/risk TCS.NS 50000 1`          — 1% risk\n"
            "  `/risk HDFCBANK.NS 200000 3`    — 3% risk",
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
            "❌ Invalid capital amount.\nExample: `/risk RELIANCE.NS 100000`", parse_mode="Markdown"
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
        logger.exception(f"Risk error for {ticker}: {e}")
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

    risk_per_share = abs(price - stop_loss)
    if risk_per_share == 0:
        await msg.edit_text("⚠️ Stop loss equals price — cannot calculate.", parse_mode="Markdown")
        return

    max_risk     = round(capital * (risk_pct / 100), 2)
    shares       = max(1, int(max_risk / risk_per_share))
    pos_value    = round(shares * price, 2)
    actual_risk  = round(shares * risk_per_share, 2)
    actual_pct   = round((actual_risk / capital) * 100, 2)
    reward1      = round(shares * abs(target1 - price), 2)
    reward2      = round(shares * abs(target2 - price), 2)
    rr1          = round(reward1 / actual_risk, 2) if actual_risk else 0
    rr2          = round(reward2 / actual_risk, 2) if actual_risk else 0
    leftover     = round(capital - pos_value, 2)
    fits         = pos_value <= capital

    rr1_v = "✅ Good" if rr1 >= 2 else ("⚠️ Marginal" if rr1 >= 1 else "❌ Poor")
    rr2_v = "✅ Good" if rr2 >= 2 else ("⚠️ Marginal" if rr2 >= 1 else "❌ Poor")
    dir_a = "⬆️" if direction == "LONG" else "⬇️"
    curr  = "₹" if is_indian(ticker) else "$"

    lines = [
        f"📐 *Position Sizing — `{ticker}`*",
        "━━━━━━━━━━━━━━━━━━━━",
        "",
        f"💰 Price:    `{fmt(price, ticker)}`  |  Signal: {sig_icon(sig)} {sig}",
        f"📊 ATR(14): `{fmt(atr, ticker)}`  |  Swing: {dir_a} {direction}",
        "",
        "─────────────────────────",
        f"💼 *Your Capital:* `{curr}{capital:,.2f}`",
        f"⚠️ *Risk per trade:* `{risk_pct}%` = `{curr}{max_risk:,.2f}`",
        "",
        "─────────────────────────",
        f"📦 *Position Sizing:*",
        f"  Shares / Qty:      `{shares:,}`",
        f"  Position value:    `{curr}{pos_value:,.2f}`" + (" ✅" if fits else " ⚠️ exceeds capital"),
        f"  Capital remaining: `{curr}{leftover:,.2f}`",
        "",
        "─────────────────────────",
        f"🛡️ *Risk Management:*",
        f"  Entry:      `{fmt(price, ticker)}`",
        f"  Stop Loss:  `{fmt(stop_loss, ticker)}`  (−`{fmt(round(risk_per_share, 2), ticker)}` per share)",
        f"  Max Loss:   `{curr}{actual_risk:,.2f}` ({actual_pct}% of capital)",
        "",
        "─────────────────────────",
        f"🎯 *Reward Targets:*",
        f"  Target 1:  `{fmt(target1, ticker)}`  → Profit `{curr}{reward1:,.2f}`  R:R `{rr1}x` {rr1_v}",
        f"  Target 2:  `{fmt(target2, ticker)}`  → Profit `{curr}{reward2:,.2f}`  R:R `{rr2}x` {rr2_v}",
        "",
        "━━━━━━━━━━━━━━━━━━━━",
        f"💡 _Add risk% after capital: `/risk {ticker} {int(capital)} 1` for 1% risk._",
        "",
        DISCLAIMER,
    ]

    await msg.edit_text("\n".join(lines), parse_mode="Markdown")


# ──────────────────────────────────────────────
# Trade journal handlers
# ──────────────────────────────────────────────

async def journal_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = context.args
    if len(args) < 4:
        await update.message.reply_text(
            "Usage: `/journal TICKER DIRECTION ENTRY EXIT [SHARES]`\n\n"
            "Examples:\n"
            "  `/journal TCS.NS long 3800 4100 10`\n"
            "  `/journal RELIANCE.NS short 2900 2750 5`\n\n"
            "Direction: `long` or `short`",
            parse_mode="Markdown",
        )
        return

    ticker    = args[0].upper().strip()
    direction = args[1].lower().strip()
    if direction not in ("long", "short"):
        await update.message.reply_text(
            "❌ Direction must be `long` or `short`.", parse_mode="Markdown"
        )
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

    user_id = update.effective_user.id
    trade   = add_trade(user_id, ticker, direction, entry, exit_p, shares)

    won_icon = "✅ Win" if trade["won"] else "❌ Loss"
    pnl_str  = fmt_pnl(trade["pnl"], ticker)
    dir_icon = "⬆️" if trade["direction"] == "LONG" else "⬇️"

    await update.message.reply_text(
        f"📒 *Trade logged!* #{trade['id']}\n\n"
        f"{dir_icon} *{ticker}* {trade['direction']} | {trade['shares']} shares\n"
        f"  Entry: `{fmt(trade['entry'], ticker)}` → Exit: `{fmt(trade['exit'], ticker)}`\n"
        f"  P&L: `{pnl_str}` ({trade['pnl_pct']}%) — {won_icon}\n\n"
        f"Use /trades to see history or /pnl for stats.",
        parse_mode="Markdown",
    )


async def trades_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    trades  = get_trades(user_id)

    if not trades:
        await update.message.reply_text(
            "📒 No trades logged yet.\n\nUse `/journal TCS.NS long 3800 4100 10` to log one.",
            parse_mode="Markdown",
        )
        return

    recent = list(reversed(trades[-20:]))
    lines  = [f"📒 *Trade Journal* ({len(trades)} total)", "━━━━━━━━━━━━━━━━━━━━", ""]

    for t in recent:
        won_icon = "✅" if t["won"] else "❌"
        pnl_str  = fmt_pnl(t["pnl"], t["ticker"])
        dir_icon = "⬆️" if t["direction"] == "LONG" else "⬇️"
        lines.append(
            f"{won_icon} #{t['id']} {dir_icon} *{t['ticker']}* | `{t['date']}`\n"
            f"   `{fmt(t['entry'], t['ticker'])}` → `{fmt(t['exit'], t['ticker'])}` × {t['shares']} → `{pnl_str}` ({t['pnl_pct']}%)"
        )
        lines.append("")

    lines.append("_Use /pnl for statistics or `/deltrade ID` to remove._")
    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


async def pnl_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    stats   = get_pnl_stats(user_id)

    if not stats:
        await update.message.reply_text(
            "📊 No trades logged yet.\n\nUse `/journal TCS.NS long 3800 4100 10` to log one.",
            parse_mode="Markdown",
        )
        return

    total_icon = "🟢" if stats["total_pnl"] >= 0 else "🔴"
    best       = stats["best"]
    worst      = stats["worst"]
    pf_str     = str(stats["profit_factor"]) if stats["profit_factor"] != float("inf") else "∞"

    lines = [
        "📊 *P&L Statistics*",
        "━━━━━━━━━━━━━━━━━━━━",
        "",
        f"{total_icon} *Total P&L:* `{fmt_pnl(stats['total_pnl'], best['ticker'])}`",
        f"📈 *Win Rate:*  `{stats['win_rate']}%` ({stats['wins']}W / {stats['losses']}L / {stats['total']} trades)",
        f"⚖️ *Profit Factor:* `{pf_str}`",
        "",
        "─────────────────────────",
        f"✅ *Avg Win:*  `{fmt_pnl(stats['avg_win'], best['ticker'])}`",
        f"❌ *Avg Loss:* `{fmt_pnl(stats['avg_loss'], worst['ticker'])}`",
        "",
        "─────────────────────────",
        f"🏆 *Best Trade:*  #{best['id']} {best['ticker']} `{fmt_pnl(best['pnl'], best['ticker'])}` ({best['pnl_pct']}%)",
        f"💥 *Worst Trade:* #{worst['id']} {worst['ticker']} `{fmt_pnl(worst['pnl'], worst['ticker'])}` ({worst['pnl_pct']}%)",
        "",
        "━━━━━━━━━━━━━━━━━━━━",
    ]

    if stats["win_rate"] >= 60 and stats["total_pnl"] > 0:
        lines.append("💡 _Solid performance — keep your discipline._")
    elif stats["win_rate"] < 40:
        lines.append("💡 _Win rate is low — review your entry criteria._")
    elif stats["total_pnl"] < 0:
        lines.append("💡 _Positive win rate but net loss — check if losses > wins._")
    else:
        lines.append("💡 _Consistent results — keep journaling to track improvements._")

    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


async def deltrade_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = context.args
    if not args:
        await update.message.reply_text("Usage: `/deltrade 3`\n\nUse /trades to see your trade IDs.", parse_mode="Markdown")
        return
    try:
        trade_id = int(args[0])
    except ValueError:
        await update.message.reply_text("❌ Provide a valid trade ID.", parse_mode="Markdown")
        return

    user_id = update.effective_user.id
    removed = delete_trade(user_id, trade_id)
    if removed:
        await update.message.reply_text(f"🗑️ Trade #{trade_id} deleted.", parse_mode="Markdown")
    else:
        await update.message.reply_text(f"⚠️ No trade found with ID #{trade_id}.", parse_mode="Markdown")


async def streak_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    data    = get_streak_and_equity(user_id)

    if not data:
        await update.message.reply_text(
            "📒 No trades logged yet.\n\nUse `/journal TCS.NS long 3800 4100 10` to log one.",
            parse_mode="Markdown",
        )
        return

    streak_icon  = "🔥" if data["streak_type"] == "win" else "🧊"
    streak_label = "Win streak" if data["streak_type"] == "win" else "Loss streak"
    streak_msg   = (
        f"You're on a *{data['streak_count']}-trade {streak_label}!* 💪 Keep it up."
        if data["streak_type"] == "win"
        else f"You're on a *{data['streak_count']}-trade {streak_label}.* Stay patient — stick to your rules."
    )

    pnl_final  = data["final_pnl"]
    pnl_icon   = "🟢" if pnl_final >= 0 else "🔴"
    cumulative = data["cumulative"]
    mn, mx     = min(cumulative), max(cumulative)
    n          = data["trade_count"]

    lines = [
        "📈 *Streak & Equity Curve*",
        "━━━━━━━━━━━━━━━━━━━━",
        "",
        f"{streak_icon} *Current streak:* {data['streak_count']}× {streak_label.lower()}",
        streak_msg,
        "",
        "─────────────────────────",
        f"🏆 *Longest win streak:*  `{data['longest_win']}` trades",
        f"💥 *Longest loss streak:* `{data['longest_loss']}` trades",
        "",
        "─────────────────────────",
        f"📉 *Equity Curve* ({n} trades)",
        f"  High: `{pnl_final:,.2f}`",
        f"  `{data['sparkline']}`",
        f"  Low:  `{mn:,.2f}`",
        f"  Trade #1 ───────────── #{n}",
        "",
        "─────────────────────────",
        f"{pnl_icon} *Cumulative P&L:* `{pnl_final:,.2f}`",
        f"📉 *Max Drawdown:*    `{data['max_drawdown']:,.2f}`",
        "",
        "━━━━━━━━━━━━━━━━━━━━",
        "_Use /pnl for full statistics or /trades to review your entries._",
    ]

    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


# ──────────────────────────────────────────────
# /backtest
# ──────────────────────────────────────────────

async def backtest_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = context.args
    if not args:
        await update.message.reply_text(
            "Usage: `/backtest TICKER [PERIOD]`\n\n"
            "Runs an EMA 9/21 crossover strategy on historical data.\n\n"
            "Periods: `6mo`  `1y`  `2y`  `5y` (default: `1y`)\n\n"
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
            f"❌ Invalid period `{period}`. Choose from: `6mo` `1y` `2y` `5y`",
            parse_mode="Markdown",
        )
        return

    msg = await update.message.reply_text(
        f"⚙️ Running EMA 9/21 backtest on `{ticker}` ({period})...", parse_mode="Markdown"
    )

    try:
        result = run_backtest(ticker, period)
    except Exception as e:
        logger.exception(f"Backtest error for {ticker}: {e}")
        await msg.edit_text(f"❌ Could not fetch data for `{ticker}`.", parse_mode="Markdown")
        return

    if result is None:
        await msg.edit_text(
            f"⚠️ Not enough data for `{ticker}`. Try a longer period or check the ticker.",
            parse_mode="Markdown",
        )
        return

    if result["total"] == 0:
        await msg.edit_text(
            f"📊 *Backtest — `{ticker}` ({period})*\n\n"
            f"No EMA 9/21 crossovers found.\n"
            f"Buy & Hold return: `{result['buy_hold']}%`",
            parse_mode="Markdown",
        )
        return

    r      = result
    vs_bh  = r["total_return"] - r["buy_hold"]
    pf_str = str(r["profit_factor"]) if r["profit_factor"] != float("inf") else "∞"

    def pct(v): return f"+{v}%" if v >= 0 else f"{v}%"

    recent      = r["trades"][-5:]
    trade_lines = [
        f"  {'✅' if t['won'] else '❌'} `{t['entry_date']}` → `{t['exit_date']}`  `{pct(t['pnl_pct'])}`"
        + (" 🔓" if t.get("open") else "")
        for t in recent
    ]

    lines = [
        f"📊 *Backtest — `{ticker}` ({period})*",
        f"_Strategy: EMA 9 / EMA 21 crossover_",
        "━━━━━━━━━━━━━━━━━━━━",
        "",
        f"📋 *Summary*",
        f"  Total trades:  `{r['total']}` ({r['wins']}W / {r['losses']}L)",
        f"  Win rate:      `{r['win_rate']}%`",
        f"  Profit factor: `{pf_str}`",
        "",
        "─────────────────────────",
        f"💰 *Returns*",
        f"  {'🟢' if r['total_return'] >= 0 else '🔴'} Strategy:    `{pct(r['total_return'])}`",
        f"  {'🟢' if r['buy_hold'] >= 0 else '🔴'} Buy & Hold:  `{pct(r['buy_hold'])}`",
        f"  {'✅' if vs_bh >= 0 else '❌'} Outperforms: `{pct(round(vs_bh, 2))}`",
        "",
        "─────────────────────────",
        f"📈 *Per-Trade Stats*",
        f"  Avg win:       `+{r['avg_win']}%`",
        f"  Avg loss:      `{r['avg_loss']}%`",
        f"  Max drawdown:  `-{r['max_drawdown']}%`",
        f"  Best:          `{pct(r['best']['pnl_pct'])}` ({r['best']['entry_date']})",
        f"  Worst:         `{pct(r['worst']['pnl_pct'])}` ({r['worst']['entry_date']})",
        "",
        "─────────────────────────",
        f"📉 *Equity Curve*",
        f"  `{r['sparkline']}`",
        f"  Trade #1 {'─' * max(1, min(len(r['sparkline'])-4, 16))} #{r['total']}",
        "",
        f"─────────────────────────",
        f"🕒 *Last {len(recent)} Trades*",
    ] + trade_lines + [
        "",
        "━━━━━━━━━━━━━━━━━━━━",
        "⚠️ _Past performance does not guarantee future results._",
        "🔓 _= position still open at end of period_",
        DISCLAIMER,
    ]

    await msg.edit_text("\n".join(lines), parse_mode="Markdown")


# ──────────────────────────────────────────────
# Price alert check job + handlers
# ──────────────────────────────────────────────

async def check_price_alerts(context):
    all_alerts = get_all_price_alerts()
    for user_id_str, alerts in all_alerts.items():
        user_id = int(user_id_str)
        for alert in list(alerts):
            ticker    = alert["ticker"]
            condition = alert["condition"]
            target    = alert["target"]
            chat_id   = alert["chat_id"]
            alert_id  = alert["id"]
            try:
                import yfinance as yf
                fi    = yf.Ticker(ticker).fast_info
                price = getattr(fi, "last_price", None)
                if price is None:
                    price = yf.Ticker(ticker).history(period="1d")["Close"].iloc[-1]
                price     = round(float(price), 2)
                triggered = (condition == "above" and price >= target) or (condition == "below" and price <= target)
                if triggered:
                    arrow = "⬆️" if condition == "above" else "⬇️"
                    await context.bot.send_message(
                        chat_id=chat_id,
                        text=(
                            f"🔔 *Price Alert Triggered!*\n\n"
                            f"{arrow} *{ticker}* is now `{fmt(price, ticker)}` — "
                            f"{'above' if condition == 'above' else 'below'} your target of `{fmt(target, ticker)}`.\n\n"
                            f"_Send `{ticker}` for the full analysis._\n\n"
                            f"{DISCLAIMER}"
                        ),
                        parse_mode="Markdown",
                    )
                    remove_triggered_alert(user_id, alert_id)
                    logger.info(f"Price alert triggered: {ticker} {condition} {target} for user {user_id}")
            except Exception as e:
                logger.warning(f"Price alert check failed for {ticker} (user {user_id}): {e}")


async def alert_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = context.args
    if len(args) < 3:
        await update.message.reply_text(
            "Usage: `/alert TICKER above PRICE` or `/alert TICKER below PRICE`\n\n"
            "Examples:\n"
            "  `/alert RELIANCE.NS above 3000`\n"
            "  `/alert TCS.NS below 3500`\n\n"
            "Alerts fire once when the price crosses your target.",
            parse_mode="Markdown",
        )
        return

    ticker    = args[0].upper().strip()
    condition = args[1].lower().strip()
    if condition not in ("above", "below"):
        await update.message.reply_text(
            "❌ Condition must be `above` or `below`.\n\nExample: `/alert RELIANCE.NS above 3000`",
            parse_mode="Markdown",
        )
        return

    try:
        target = float(args[2].replace("₹","").replace("$","").replace(",",""))
    except ValueError:
        await update.message.reply_text("❌ Invalid price.", parse_mode="Markdown")
        return

    user_id  = update.effective_user.id
    chat_id  = update.effective_chat.id
    alert_id = add_price_alert(user_id, chat_id, ticker, condition, target)
    arrow    = "⬆️" if condition == "above" else "⬇️"

    await update.message.reply_text(
        f"🔔 Alert set! #{alert_id}\n\n"
        f"{arrow} You'll be notified when *{ticker}* goes *{condition}* `{fmt(target, ticker)}`.\n\n"
        f"Checked every 15 minutes. Use /alerts to view all your alerts.",
        parse_mode="Markdown",
    )


async def list_alerts_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    alerts  = get_user_alerts(user_id)
    if not alerts:
        await update.message.reply_text(
            "🔕 No active price alerts.\n\nUse `/alert RELIANCE.NS above 3000` to set one.",
            parse_mode="Markdown",
        )
        return

    lines = ["🔔 *Your Price Alerts:*", ""]
    for a in alerts:
        arrow = "⬆️" if a["condition"] == "above" else "⬇️"
        lines.append(f"  #{a['id']} — {arrow} *{a['ticker']}* {a['condition']} `{fmt(a['target'], a['ticker'])}`")
    lines.append("")
    lines.append("Use `/delalert <id>` to cancel an alert.")
    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


async def delalert_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = context.args
    if not args:
        await update.message.reply_text("Usage: `/delalert 1`\n\nUse /alerts to see your alert IDs.", parse_mode="Markdown")
        return
    try:
        alert_id = int(args[0])
    except ValueError:
        await update.message.reply_text("❌ Please provide a valid alert ID.", parse_mode="Markdown")
        return

    user_id = update.effective_user.id
    removed = remove_price_alert(user_id, alert_id)
    if removed:
        await update.message.reply_text(f"✅ Price alert #{alert_id} cancelled.", parse_mode="Markdown")
    else:
        await update.message.reply_text(f"⚠️ No alert found with ID #{alert_id}. Use /alerts to view yours.", parse_mode="Markdown")


# ──────────────────────────────────────────────
# Restore saved alerts on startup
# ──────────────────────────────────────────────

async def restore_alerts(app):
    all_alerts = get_all_alerts()
    count = 0
    for user_id_str, config in all_alerts.items():
        try:
            schedule_alert(
                app,
                user_id=int(user_id_str),
                chat_id=config["chat_id"],
                hour=config["hour"],
                minute=config["minute"],
            )
            count += 1
        except Exception as e:
            logger.warning(f"Failed to restore alert for user {user_id_str}: {e}")
    if count:
        logger.info(f"Restored {count} daily alert(s).")


# ──────────────────────────────────────────────
# main()
# ──────────────────────────────────────────────

def main():
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    if not token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN not set in environment.")

    app = (
        ApplicationBuilder()
        .token(token)
        .post_init(restore_alerts)
        .build()
    )

    # Price alert job — every 15 minutes
    app.job_queue.run_repeating(check_price_alerts, interval=900, first=60)

    # Register all handlers
    app.add_handler(CommandHandler("start",       start_handler))
    app.add_handler(CommandHandler("help",        help_handler))
    app.add_handler(CommandHandler("about",       about_handler))

    app.add_handler(CommandHandler("watchlist",   watchlist_handler))
    app.add_handler(CommandHandler("add",         add_handler))
    app.add_handler(CommandHandler("remove",      remove_handler))
    app.add_handler(CommandHandler("clear",       clear_handler))
    app.add_handler(CommandHandler("scan",        scan_handler))

    app.add_handler(CommandHandler("setalert",    setalert_handler))
    app.add_handler(CommandHandler("myalert",     myalert_handler))
    app.add_handler(CommandHandler("cancelalert", cancelalert_handler))

    app.add_handler(CommandHandler("signal",      signal_handler))
    app.add_handler(CommandHandler("swing",       swing_handler))
    app.add_handler(CommandHandler("intraday",    intraday_handler))
    app.add_handler(CommandHandler("breakout",    breakout_handler))

    app.add_handler(CommandHandler("top",         top_handler))
    app.add_handler(CommandHandler("movers",      movers_handler))
    app.add_handler(CommandHandler("compare",     compare_handler))
    app.add_handler(CommandHandler("sentiment",   sentiment_handler))
    app.add_handler(CommandHandler("summary",     summary_handler))
    app.add_handler(CommandHandler("gainers52w",  gainers52w_handler))
    app.add_handler(CommandHandler("oversold",    oversold_handler))
    app.add_handler(CommandHandler("report",      report_handler))
    app.add_handler(CommandHandler("sector",      sector_handler))
    app.add_handler(CommandHandler("heatmap",     heatmap_handler))

    app.add_handler(CommandHandler("risk",        risk_handler))
    app.add_handler(CommandHandler("backtest",    backtest_handler))

    app.add_handler(CommandHandler("journal",     journal_handler))
    app.add_handler(CommandHandler("trades",      trades_handler))
    app.add_handler(CommandHandler("pnl",         pnl_handler))
    app.add_handler(CommandHandler("deltrade",    deltrade_handler))
    app.add_handler(CommandHandler("streak",      streak_handler))

    app.add_handler(CommandHandler("alert",       alert_handler))
    app.add_handler(CommandHandler("alerts",      list_alerts_handler))
    app.add_handler(CommandHandler("delalert",    delalert_handler))

    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, analyze_handler))

    logger.info("MarketMasteryAI Bot starting...")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
