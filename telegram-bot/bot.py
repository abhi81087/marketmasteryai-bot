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
from price_alerts import (
    add_price_alert, get_user_alerts, remove_price_alert,
    remove_triggered_alert, get_all_price_alerts,
)

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

HELP_TEXT = """
👋 *Stock Analysis Bot*

Send me any stock ticker symbol to get a full technical analysis.

*Examples:*
  `AAPL` — Apple Inc.
  `TSLA` — Tesla
  `RELIANCE.NS` — Reliance (NSE)
  `TCS.NS` — TCS (NSE)
  `^NSEI` — Nifty 50 Index

*What you get:*
  📉 RSI (14) with overbought/oversold zones
  📐 EMA 9 / 21 / 50 / 200
  📊 MACD + Signal + Histogram
  📏 Bollinger Bands (20)
  📦 Volume analysis + OBV trend
  🚨 Breakout / Breakdown alerts
  🏹 Swing trade setup with Stop Loss & Targets
  🎯 Buy / Sell / Hold signal

*Watchlist commands:*
  /watchlist         — View your saved tickers
  /add AAPL TSLA     — Add tickers to watchlist
  /remove AAPL       — Remove a ticker
  /scan              — Analyse all watchlist tickers
  /clear             — Clear your watchlist

*Alert commands:*
  /setalert 09:15    — Get daily watchlist scan at this time (24h UTC)
  /myalert           — Check your current alert time
  /cancelalert       — Cancel your daily alert

*Market commands:*
  /top               — Top signals from popular US + Indian stocks
  /top us            — Top signals from US stocks only
  /top india         — Top signals from Indian stocks only
  /compare AAPL TSLA  — Side-by-side comparison of 2–6 stocks
  /sentiment AAPL     — News sentiment summary for a stock
  /movers             — Today's top gainers & losers
  /movers us          — US gainers & losers only
  /movers india       — Indian gainers & losers only
  /summary AAPL       — Combined technicals + sentiment trade brief

*Price alert commands:*
  /alert AAPL above 220 — Notify when AAPL crosses above $220
  /alert AAPL below 190 — Notify when AAPL drops below $190
  /alerts               — View all your active price alerts
  /delalert 1           — Cancel price alert by ID

*Screener commands:*
  /gainers52w           — Stocks near 52-week high with strong momentum
  /gainers52w us        — US stocks only
  /gainers52w india     — Indian stocks only
  /oversold             — RSI dip-buy setups with bullish EMA structure
  /oversold us          — US stocks only
  /oversold india       — Indian stocks only
  /report AAPL          — Full shareable analysis report for a stock
  /sector               — Avg RSI & dominant signal by market sector
  /heatmap              — Colour-coded signal grid of all 30 stocks
  /risk AAPL 10000      — Position sizing & risk/reward for your capital

*Trade journal:*
  /journal AAPL long 150 165 10 — Log a completed trade
  /trades                        — View your trade history
  /pnl                           — P&L stats (win rate, profit factor)
  /deltrade 3                    — Delete trade by ID
  /streak                        — Win/loss streak & equity curve

*Other commands:*
  /start — Welcome message
  /help  — Show this help
  /about — About this bot
"""

ABOUT_TEXT = """
🤖 *Stock Analysis Bot*

A technical analysis bot for traders and investors.

*Indicators computed:*
• RSI (Relative Strength Index)
• EMA 9, 21, 50, 200
• MACD (12/26/9)
• Bollinger Bands (20, 2σ)
• ATR (Average True Range)
• OBV (On-Balance Volume)
• Support & Resistance (20-day)

*Data source:* Yahoo Finance (yfinance)

⚠️ _Not financial advice. Always do your own research._
"""


# ──────────────────────────────────────────────
# Shared scan logic (used by /scan and daily job)
# ──────────────────────────────────────────────

def build_scan_message(tickers: list[str]) -> str:
    results = []
    errors = []
    for ticker in tickers:
        try:
            data = analyze(ticker)
            sig = data["signal"]["action"]
            rsi = data["rsi"]
            chg = data["change_pct"]
            price = data["last_close"]
            brk = data["breakout"]
            swing_dir = data["swing"]["direction"]

            if "STRONG BUY" in sig:
                sig_icon = "🟢🟢"
            elif "BUY" in sig:
                sig_icon = "🟢"
            elif "STRONG SELL" in sig:
                sig_icon = "🔴🔴"
            elif "SELL" in sig:
                sig_icon = "🔴"
            else:
                sig_icon = "🟡"

            breakout_tag = ""
            if brk["breakout_up"]:
                breakout_tag = " 🚨BRK↑"
            elif brk["breakout_down"]:
                breakout_tag = " 💥BRK↓"

            chg_str = f"{'+' if chg >= 0 else ''}{chg}%"
            results.append(
                f"{sig_icon} *{ticker}* `${price}` ({chg_str}) | RSI `{rsi}` | {swing_dir}{breakout_tag}"
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
    lines.append("_Tap any ticker to get the full analysis._")
    lines.append("⚠️ _Not financial advice._")
    return "\n".join(lines)


# ──────────────────────────────────────────────
# Daily alert job callback
# ──────────────────────────────────────────────

async def daily_alert_job(context):
    user_id = context.job.data["user_id"]
    chat_id = context.job.data["chat_id"]
    tickers = get_watchlist(user_id)
    if not tickers:
        await context.bot.send_message(
            chat_id=chat_id,
            text="⏰ *Daily Alert*\n\nYour watchlist is empty. Use `/add AAPL TSLA` to add tickers.",
            parse_mode="Markdown",
        )
        return
    header = f"⏰ *Daily Alert — Watchlist Scan*\n\n"
    text = header + build_scan_message(tickers)
    await context.bot.send_message(chat_id=chat_id, text=text, parse_mode="Markdown")


def schedule_alert(app, user_id: int, chat_id: int, hour: int, minute: int):
    job_name = f"alert_{user_id}"
    current_jobs = app.job_queue.get_jobs_by_name(job_name)
    for job in current_jobs:
        job.schedule_removal()
    app.job_queue.run_daily(
        daily_alert_job,
        time=dtime(hour=hour, minute=minute),
        name=job_name,
        data={"user_id": user_id, "chat_id": chat_id},
    )


# ──────────────────────────────────────────────
# Command handlers
# ──────────────────────────────────────────────

async def start_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 Welcome to *Stock Analysis Bot*!\n\n"
        "Send me a stock ticker like `AAPL`, `TSLA`, or `TCS.NS` to get a full technical analysis.\n\n"
        "📋 Use /watchlist to save your favourite tickers, then /scan to analyse them all at once.\n"
        "⏰ Use `/setalert 09:15` to get a daily scan delivered automatically.",
        parse_mode="Markdown",
    )


async def help_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(HELP_TEXT, parse_mode="Markdown")


async def about_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(ABOUT_TEXT, parse_mode="Markdown")


async def watchlist_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    tickers = get_watchlist(user_id)
    if not tickers:
        await update.message.reply_text(
            "📋 Your watchlist is empty.\n\nUse `/add AAPL TSLA` to add tickers.",
            parse_mode="Markdown",
        )
        return
    lines = ["📋 *Your Watchlist:*", ""]
    for i, t in enumerate(tickers, 1):
        lines.append(f"  {i}. `{t}`")
    lines.append("")
    lines.append("Use /scan to analyse all tickers or `/setalert 09:15` for a daily alert.")
    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


async def add_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    args = context.args
    if not args:
        await update.message.reply_text("Usage: `/add AAPL TSLA TCS.NS`", parse_mode="Markdown")
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
        await update.message.reply_text("Usage: `/remove AAPL TSLA`", parse_mode="Markdown")
        return
    removed, not_found = remove_tickers(user_id, args)
    lines = []
    if removed:
        lines.append("🗑️ Removed: " + ", ".join(f"`{t}`" for t in removed))
    if not_found:
        lines.append("⚠️ Not found: " + ", ".join(f"`{t}`" for t in not_found))
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
            "📋 Your watchlist is empty.\n\nUse `/add AAPL TSLA` to add tickers first.",
            parse_mode="Markdown",
        )
        return
    msg = await update.message.reply_text(
        f"🔍 Scanning *{len(tickers)}* ticker(s)... please wait.",
        parse_mode="Markdown",
    )
    text = build_scan_message(tickers)
    await msg.edit_text(text, parse_mode="Markdown")


async def setalert_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    args = context.args
    if not args:
        await update.message.reply_text(
            "Usage: `/setalert HH:MM` (24-hour UTC)\n\nExample: `/setalert 09:15`",
            parse_mode="Markdown",
        )
        return
    try:
        parts = args[0].split(":")
        if len(parts) != 2:
            raise ValueError()
        hour = int(parts[0])
        minute = int(parts[1])
        if not (0 <= hour <= 23 and 0 <= minute <= 59):
            raise ValueError()
    except ValueError:
        await update.message.reply_text(
            "❌ Invalid time format. Use HH:MM in 24-hour UTC.\n\nExample: `/setalert 09:15`",
            parse_mode="Markdown",
        )
        return

    set_alert(user_id, chat_id, hour, minute)
    schedule_alert(context.application, user_id, chat_id, hour, minute)

    tickers = get_watchlist(user_id)
    watchlist_note = (
        f"Your watchlist has *{len(tickers)}* ticker(s)."
        if tickers
        else "Your watchlist is empty — use `/add AAPL TSLA` to add tickers."
    )
    await update.message.reply_text(
        f"⏰ Daily alert set for *{hour:02d}:{minute:02d} UTC* every day.\n\n"
        f"{watchlist_note}",
        parse_mode="Markdown",
    )


async def myalert_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    alert = get_alert(user_id)
    if not alert:
        await update.message.reply_text(
            "You have no daily alert set.\n\nUse `/setalert 09:15` to set one.",
            parse_mode="Markdown",
        )
        return
    h = alert["hour"]
    m = alert["minute"]
    await update.message.reply_text(
        f"⏰ Your daily alert is set for *{h:02d}:{m:02d} UTC*.\n\nUse /cancelalert to remove it.",
        parse_mode="Markdown",
    )


async def cancelalert_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    removed = remove_alert(user_id)
    job_name = f"alert_{user_id}"
    for job in context.application.job_queue.get_jobs_by_name(job_name):
        job.schedule_removal()
    if removed:
        await update.message.reply_text("✅ Your daily alert has been cancelled.", parse_mode="Markdown")
    else:
        await update.message.reply_text("You don't have an active alert.", parse_mode="Markdown")


TOP_US = [
    "AAPL", "MSFT", "NVDA", "GOOGL", "AMZN",
    "META", "TSLA", "AMD", "NFLX", "JPM",
    "V", "MA", "BAC", "DIS", "INTC",
]

TOP_INDIA = [
    "RELIANCE.NS", "TCS.NS", "INFY.NS", "HDFCBANK.NS", "ICICIBANK.NS",
    "SBIN.NS", "WIPRO.NS", "BAJFINANCE.NS", "AXISBANK.NS", "KOTAKBANK.NS",
    "LT.NS", "MARUTI.NS", "TATAMOTORS.NS", "SUNPHARMA.NS", "ADANIENT.NS",
]

SIGNAL_RANK = {
    "STRONG BUY": 0,
    "STRONG SELL": 1,
    "BUY": 2,
    "SELL": 3,
    "HOLD / NEUTRAL": 4,
}


async def compare_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = context.args
    if not args or len(args) < 2:
        await update.message.reply_text(
            "Usage: `/compare AAPL TSLA MSFT` (2–6 tickers)\n\nCompares signal, RSI, EMA trend, MACD, and swing direction side by side.",
            parse_mode="Markdown",
        )
        return

    tickers = [a.upper().strip() for a in args[:6]]

    msg = await update.message.reply_text(
        f"🔍 Comparing {', '.join(f'`{t}`' for t in tickers)}...",
        parse_mode="Markdown",
    )

    rows = []
    errors = []

    for ticker in tickers:
        try:
            data = analyze(ticker)
            sig = data["signal"]["action"]
            if "STRONG BUY" in sig:
                sig_icon = "🟢🟢"
            elif "BUY" in sig:
                sig_icon = "🟢"
            elif "STRONG SELL" in sig:
                sig_icon = "🔴🔴"
            elif "SELL" in sig:
                sig_icon = "🔴"
            else:
                sig_icon = "🟡"

            ema_trend = "↑ Bull" if data["ema9"] > data["ema21"] else "↓ Bear"
            macd_trend = "↑" if data["macd"] > data["macd_signal"] else "↓"
            bb_pos = (
                "Above" if data["last_close"] > data["bb_upper"]
                else "Below" if data["last_close"] < data["bb_lower"]
                else "Inside"
            )
            brk = data["breakout"]
            brk_tag = "↑BRK" if brk["breakout_up"] else ("↓BRK" if brk["breakout_down"] else "—")
            chg = data["change_pct"]
            chg_str = f"{'+' if chg >= 0 else ''}{chg}%"

            rows.append({
                "ticker": ticker,
                "price": data["last_close"],
                "chg": chg_str,
                "signal": f"{sig_icon} {sig}",
                "rsi": data["rsi"],
                "ema_trend": ema_trend,
                "macd": macd_trend,
                "bb": bb_pos,
                "swing": data["swing"]["direction"],
                "brk": brk_tag,
            })
        except Exception as e:
            logger.warning(f"Compare error for {ticker}: {e}")
            errors.append(ticker)

    if not rows:
        await msg.edit_text("❌ Could not fetch data for any of the tickers provided.", parse_mode="Markdown")
        return

    lines = [f"📊 *Stock Comparison*", "━━━━━━━━━━━━━━━━━━━━", ""]

    for r in rows:
        lines.append(f"*{r['ticker']}* — `${r['price']}` ({r['chg']})")
        lines.append(f"  Signal:   {r['signal']}")
        lines.append(f"  RSI:      `{r['rsi']}`")
        lines.append(f"  EMA:      `{r['ema_trend']}`  |  MACD: `{r['macd']}`")
        lines.append(f"  BB:       `{r['bb']}`  |  Swing: `{r['swing']}`")
        lines.append(f"  Breakout: `{r['brk']}`")
        lines.append("")

    if errors:
        lines.append(f"_⚠️ Could not fetch: {', '.join(errors)}_")
        lines.append("")

    lines.append("_Tap a ticker for its full analysis._")
    lines.append("⚠️ _Not financial advice._")

    await msg.edit_text("\n".join(lines), parse_mode="Markdown")


async def summary_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = context.args
    if not args:
        await update.message.reply_text(
            "Usage: `/summary AAPL`\n\nCombines technical analysis + news sentiment into a concise trade brief.",
            parse_mode="Markdown",
        )
        return

    ticker = args[0].upper().strip()
    msg = await update.message.reply_text(
        f"⚡ Building trade brief for `{ticker}`...", parse_mode="Markdown"
    )

    try:
        data = analyze(ticker)
    except Exception as e:
        logger.exception(f"Summary analysis error for {ticker}: {e}")
        await msg.edit_text(f"❌ Could not fetch data for `{ticker}`.", parse_mode="Markdown")
        return

    try:
        sent = fetch_sentiment(ticker)
    except Exception:
        sent = {"overall": "NEUTRAL", "bullish": 0, "bearish": 0, "neutral": 0, "total": 0}

    sig = data["signal"]["action"]
    rsi = data["rsi"]
    chg = data["change_pct"]
    price = data["last_close"]
    swing = data["swing"]
    brk = data["breakout"]
    ema_trend = "Bullish" if data["ema9"] > data["ema21"] else "Bearish"
    macd_dir = "Bullish" if data["macd"] > data["macd_signal"] else "Bearish"
    news_mood = sent["overall"]

    if "STRONG BUY" in sig:   sig_icon = "🟢🟢"
    elif "BUY" in sig:         sig_icon = "🟢"
    elif "STRONG SELL" in sig: sig_icon = "🔴🔴"
    elif "SELL" in sig:        sig_icon = "🔴"
    else:                      sig_icon = "🟡"

    news_icon = "🟢" if news_mood == "BULLISH" else ("🔴" if news_mood == "BEARISH" else "🟡")

    tech_bullish = sig in ("BUY", "STRONG BUY")
    tech_bearish = sig in ("SELL", "STRONG SELL")
    news_bullish = news_mood == "BULLISH"
    news_bearish = news_mood == "BEARISH"

    if tech_bullish and news_bullish:
        trader_note = "📗 Technicals and news align bullish — higher-conviction long setup."
    elif tech_bearish and news_bearish:
        trader_note = "📕 Technicals and news both bearish — short or avoid."
    elif tech_bullish and news_bearish:
        trader_note = "⚠️ Bullish chart but negative news — wait for news to settle before entering."
    elif tech_bearish and news_bullish:
        trader_note = "⚠️ Bearish chart despite positive news — news may already be priced in."
    elif tech_bullish:
        trader_note = "📘 Bullish technicals with neutral news — trend-driven setup, watch volume."
    elif tech_bearish:
        trader_note = "📘 Bearish technicals with neutral news — trend-driven short, manage risk."
    else:
        trader_note = "📘 Mixed signals — no clear edge right now. Wait for confirmation."

    if brk["breakout_up"]:
        breakout_line = "🚨 Active breakout UP (20-day resistance cleared with volume)"
    elif brk["breakout_down"]:
        breakout_line = "💥 Active breakdown DOWN (20-day support broken with volume)"
    else:
        breakout_line = f"Support `${brk['support']}` — Resistance `${brk['resistance']}`"

    chg_str = f"{'+' if chg >= 0 else ''}{chg}%"

    lines = [
        f"⚡ *Trade Brief — {data['name']} (`{ticker}`)*",
        "━━━━━━━━━━━━━━━━━━━━",
        "",
        f"💵 *Price:* `${price}` ({chg_str})",
        f"🎯 *Signal:* {sig_icon} {sig}",
        f"📰 *News:* {news_icon} {news_mood} ({sent['bullish']}↑ {sent['bearish']}↓ from {sent['total']} articles)",
        "",
        "📐 *Key Technicals:*",
        f"  RSI `{rsi}` | EMA `{ema_trend}` | MACD `{macd_dir}`",
        f"  EMA9 `${data['ema9']}` | EMA21 `${data['ema21']}` | EMA50 `${data['ema50']}`",
        "",
        "📍 *Key Levels:*",
        f"  {breakout_line}",
        "",
        f"🏹 *Swing Setup:* {swing['direction']} (confidence `{swing['confidence']}%`)",
        f"  Stop Loss `${swing['stop_loss']}` | T1 `${swing['target1']}` | T2 `${swing['target2']}`",
        "",
        "━━━━━━━━━━━━━━━━━━━━",
        f"💡 {trader_note}",
        "",
        "⚠️ _Not financial advice. Always do your own research._",
    ]

    await msg.edit_text("\n".join(lines), parse_mode="Markdown")


async def movers_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    arg = " ".join(context.args).lower().strip() if context.args else ""

    if arg == "us":
        tickers = TOP_US
        label = "🇺🇸 US Stocks"
    elif arg in ("india", "in"):
        tickers = TOP_INDIA
        label = "🇮🇳 Indian Stocks"
    else:
        tickers = TOP_US + TOP_INDIA
        label = "🌍 US + Indian Stocks"

    msg = await update.message.reply_text(
        f"🔍 Fetching movers from {len(tickers)} popular stocks...",
        parse_mode="Markdown",
    )

    results = []
    errors = []

    for ticker in tickers:
        try:
            data = analyze(ticker)
            results.append({
                "ticker": ticker,
                "price": data["last_close"],
                "chg": data["change_pct"],
                "rsi": data["rsi"],
                "signal": data["signal"]["action"],
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
    losers = list(reversed(results[-5:]))

    def sig_icon(sig):
        if "STRONG BUY" in sig: return "🟢🟢"
        if "BUY" in sig: return "🟢"
        if "STRONG SELL" in sig: return "🔴🔴"
        if "SELL" in sig: return "🔴"
        return "🟡"

    def vol_tag(ratio):
        if ratio >= 2.0: return " 🔥Vol"
        if ratio >= 1.5: return " ⬆️Vol"
        return ""

    lines = [f"📈📉 *Top Movers — {label}*", "━━━━━━━━━━━━━━━━━━━━", ""]

    lines.append("🚀 *Top Gainers:*")
    for r in gainers:
        chg_str = f"+{r['chg']}%" if r["chg"] >= 0 else f"{r['chg']}%"
        lines.append(
            f"  {sig_icon(r['signal'])} *{r['ticker']}* `${r['price']}` `{chg_str}` | RSI `{r['rsi']}`{vol_tag(r['volume_ratio'])}"
        )

    lines.append("")
    lines.append("💥 *Top Losers:*")
    for r in losers:
        chg_str = f"{r['chg']}%"
        lines.append(
            f"  {sig_icon(r['signal'])} *{r['ticker']}* `${r['price']}` `{chg_str}` | RSI `{r['rsi']}`{vol_tag(r['volume_ratio'])}"
        )

    if errors:
        lines.append(f"\n_⚠️ {len(errors)} ticker(s) could not be fetched._")

    lines.append("")
    lines.append("_Tap any ticker for the full analysis._")
    lines.append("⚠️ _Not financial advice._")

    await msg.edit_text("\n".join(lines), parse_mode="Markdown")


async def sentiment_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = context.args
    if not args:
        await update.message.reply_text(
            "Usage: `/sentiment AAPL`\n\nFetches recent news headlines and gives a bullish/bearish/neutral sentiment summary.",
            parse_mode="Markdown",
        )
        return

    ticker = args[0].upper().strip()
    msg = await update.message.reply_text(
        f"📰 Fetching news sentiment for `{ticker}`...", parse_mode="Markdown"
    )

    try:
        s = fetch_sentiment(ticker)
    except Exception as e:
        logger.exception(f"Sentiment error for {ticker}: {e}")
        await msg.edit_text(
            f"⚠️ Could not fetch news for `{ticker}`. Try again later.", parse_mode="Markdown"
        )
        return

    overall = s["overall"]
    if overall == "BULLISH":
        overall_icon = "🟢 BULLISH"
    elif overall == "BEARISH":
        overall_icon = "🔴 BEARISH"
    else:
        overall_icon = "🟡 NEUTRAL"

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
            if h["score"] > 0:
                icon = "🟢"
            elif h["score"] < 0:
                icon = "🔴"
            else:
                icon = "🟡"
            title = h["title"]
            if len(title) > 90:
                title = title[:87] + "..."
            lines.append(f"{icon} {title}")
    else:
        lines.append("_No recent headlines found for this ticker._")

    lines.append("")
    lines.append("⚠️ _Sentiment is keyword-based. Always verify news independently._")

    await msg.edit_text("\n".join(lines), parse_mode="Markdown")


async def top_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    arg = " ".join(context.args).lower().strip() if context.args else ""

    if arg == "us":
        tickers = TOP_US
        label = "🇺🇸 US Stocks"
    elif arg in ("india", "in"):
        tickers = TOP_INDIA
        label = "🇮🇳 Indian Stocks"
    else:
        tickers = TOP_US + TOP_INDIA
        label = "🌍 US + Indian Stocks"

    msg = await update.message.reply_text(
        f"🔍 Scanning {len(tickers)} popular stocks for top signals...",
        parse_mode="Markdown",
    )

    hits = []
    errors = []

    for ticker in tickers:
        try:
            data = analyze(ticker)
            sig = data["signal"]["action"]
            score = data["signal"]["score"]
            rsi = data["rsi"]
            chg = data["change_pct"]
            price = data["last_close"]
            brk = data["breakout"]
            swing_dir = data["swing"]["direction"]

            breakout_active = brk["breakout_up"] or brk["breakout_down"]
            is_strong = "STRONG" in sig
            is_buy_sell = sig in ("BUY", "SELL")

            if not (is_strong or (is_buy_sell and breakout_active)):
                continue

            if "STRONG BUY" in sig:
                sig_icon = "🟢🟢"
            elif "BUY" in sig:
                sig_icon = "🟢"
            elif "STRONG SELL" in sig:
                sig_icon = "🔴🔴"
            else:
                sig_icon = "🔴"

            breakout_tag = ""
            if brk["breakout_up"]:
                breakout_tag = " 🚨BRK↑"
            elif brk["breakout_down"]:
                breakout_tag = " 💥BRK↓"

            chg_str = f"{'+' if chg >= 0 else ''}{chg}%"
            hits.append({
                "rank": SIGNAL_RANK.get(sig, 9),
                "score": abs(score),
                "line": f"{sig_icon} *{ticker}* `${price}` ({chg_str}) | RSI `{rsi}` | {swing_dir}{breakout_tag}",
            })
        except Exception as e:
            logger.warning(f"Top scan error for {ticker}: {e}")
            errors.append(ticker)

    hits.sort(key=lambda x: (x["rank"], -x["score"]))

    lines = [f"🏆 *Top Signals — {label}*", "━━━━━━━━━━━━━━━━━━━━", ""]

    if hits:
        lines.append("*Strong signals only (STRONG BUY / STRONG SELL / breakout):*")
        lines.append("")
        for h in hits:
            lines.append(h["line"])
    else:
        lines.append("No strong signals right now — market is mostly neutral.")
        lines.append("Try again later or use /scan on your own watchlist.")

    if errors:
        lines.append(f"\n_⚠️ {len(errors)} ticker(s) could not be fetched._")

    lines.append("")
    lines.append("_Tap any ticker for the full analysis._")
    lines.append("⚠️ _Not financial advice._")

    await msg.edit_text("\n".join(lines), parse_mode="Markdown")


async def analyze_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    if text.startswith("/"):
        return
    ticker = text.split()[0].upper()
    msg = await update.message.reply_text(f"🔍 Fetching data for `{ticker}`...", parse_mode="Markdown")
    try:
        data = analyze(ticker)
        report = format_report(data)
        await msg.edit_text(report, parse_mode="Markdown")
    except ValueError as e:
        await msg.edit_text(f"❌ {e}\n\nTry a valid ticker like `AAPL`, `TSLA`, or `TCS.NS`.", parse_mode="Markdown")
    except Exception as e:
        logger.exception(f"Error analyzing {ticker}: {e}")
        await msg.edit_text(
            f"⚠️ Could not analyze `{ticker}`. Please check the ticker symbol and try again.\n\nExample: `AAPL`, `RELIANCE.NS`",
            parse_mode="Markdown",
        )


# ──────────────────────────────────────────────
# Price alert job + handlers
# ──────────────────────────────────────────────

async def gainers52w_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    import yfinance as yf

    arg = " ".join(context.args).lower().strip() if context.args else ""
    if arg == "us":
        tickers = TOP_US
        label = "🇺🇸 US Stocks"
    elif arg in ("india", "in"):
        tickers = TOP_INDIA
        label = "🇮🇳 Indian Stocks"
    else:
        tickers = TOP_US + TOP_INDIA
        label = "🌍 US + Indian Stocks"

    msg = await update.message.reply_text(
        f"🔍 Scanning {len(tickers)} stocks for 52-week high setups...",
        parse_mode="Markdown",
    )

    hits = []
    errors = []

    for ticker in tickers:
        try:
            stock = yf.Ticker(ticker)
            fi = stock.fast_info
            high52 = getattr(fi, "year_high", None)
            low52 = getattr(fi, "year_low", None)
            price = getattr(fi, "last_price", None)

            if not high52 or not price:
                info = stock.info
                high52 = info.get("fiftyTwoWeekHigh") or high52
                low52 = info.get("fiftyTwoWeekLow") or low52
                price = info.get("currentPrice") or info.get("regularMarketPrice") or price

            if not high52 or not price:
                continue

            price = round(float(price), 2)
            high52 = round(float(high52), 2)
            low52 = round(float(low52), 2) if low52 else 0

            pct_from_high = round(((high52 - price) / high52) * 100, 1)
            range_pct = round(((price - low52) / (high52 - low52)) * 100, 1) if high52 != low52 else 50

            if pct_from_high > 10:
                continue

            data = analyze(ticker)
            sig = data["signal"]["action"]

            if sig not in ("BUY", "STRONG BUY"):
                continue

            sig_icon = "🟢🟢" if "STRONG" in sig else "🟢"
            vol_ratio = data["volume"]["volume_ratio"]
            vol_tag = " 🔥Vol" if vol_ratio >= 2.0 else (" ⬆️Vol" if vol_ratio >= 1.5 else "")
            chg = data["change_pct"]
            chg_str = f"{'+' if chg >= 0 else ''}{chg}%"
            brk = data["breakout"]
            brk_tag = " 🚨BRK↑" if brk["breakout_up"] else ""

            hits.append({
                "pct_from_high": pct_from_high,
                "range_pct": range_pct,
                "line": (
                    f"{sig_icon} *{ticker}* `${price}` ({chg_str})\n"
                    f"   📏 `{pct_from_high}%` below 52w high `${high52}` | Range pos: `{range_pct}%`\n"
                    f"   RSI `{data['rsi']}` | Signal: {sig}{vol_tag}{brk_tag}"
                ),
            })
        except Exception as e:
            logger.warning(f"52w scan error for {ticker}: {e}")
            errors.append(ticker)

    hits.sort(key=lambda x: x["pct_from_high"])

    lines = [f"📈 *Near 52-Week Highs — {label}*", "━━━━━━━━━━━━━━━━━━━━", ""]
    lines.append("_Bullish-signal stocks within 10% of their 52-week high, ranked by proximity:_")
    lines.append("")

    if hits:
        for h in hits:
            lines.append(h["line"])
            lines.append("")
    else:
        lines.append("No stocks currently meet the criteria (within 10% of 52w high + bullish signal).")

    if errors:
        lines.append(f"_⚠️ {len(errors)} ticker(s) could not be fetched._")

    lines.append("_Tap any ticker for the full analysis._")
    lines.append("⚠️ _Not financial advice._")

    await msg.edit_text("\n".join(lines), parse_mode="Markdown")


async def oversold_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    arg = " ".join(context.args).lower().strip() if context.args else ""
    if arg == "us":
        tickers = TOP_US
        label = "🇺🇸 US Stocks"
    elif arg in ("india", "in"):
        tickers = TOP_INDIA
        label = "🇮🇳 Indian Stocks"
    else:
        tickers = TOP_US + TOP_INDIA
        label = "🌍 US + Indian Stocks"

    msg = await update.message.reply_text(
        f"🔍 Scanning {len(tickers)} stocks for oversold dip-buy setups...",
        parse_mode="Markdown",
    )

    hits = []
    errors = []

    for ticker in tickers:
        try:
            data = analyze(ticker)
            rsi = data["rsi"]

            if rsi >= 35:
                continue

            ema9 = data["ema9"]
            ema21 = data["ema21"]
            ema50 = data["ema50"]
            ema200 = data["ema200"]
            price = data["last_close"]

            bullish_structure = (ema50 > ema200) or (price > ema50) or (ema9 > ema21)
            if not bullish_structure:
                continue

            macd_recovering = data["macd"] > data["macd_signal"]
            vol_ratio = data["volume"]["volume_ratio"]
            obv_trend = data["volume"]["obv_trend"]
            chg = data["change_pct"]
            chg_str = f"{'+' if chg >= 0 else ''}{chg}%"
            swing = data["swing"]
            brk = data["breakout"]

            quality = 0
            if ema50 > ema200:       quality += 2
            if price > ema50:        quality += 1
            if ema9 > ema21:         quality += 1
            if macd_recovering:      quality += 1
            if obv_trend == "Rising": quality += 1
            if rsi < 25:             quality += 1

            bb_bounce = price <= data["bb_lower"] * 1.02
            bb_tag = " 📏BB" if bb_bounce else ""
            macd_tag = " 📊MACD↑" if macd_recovering else ""
            vol_tag = " 🔥Vol" if vol_ratio >= 2.0 else (" ⬆️Vol" if vol_ratio >= 1.5 else "")
            brk_down_tag = " 💥BRK↓" if brk["breakout_down"] else ""

            struct_parts = []
            if ema50 > ema200: struct_parts.append("EMA50>200")
            if price > ema50:  struct_parts.append("P>EMA50")
            if ema9 > ema21:   struct_parts.append("EMA9>21")
            struct_str = " | ".join(struct_parts) if struct_parts else "partial"

            hits.append({
                "rsi": rsi,
                "quality": quality,
                "line": (
                    f"🔵 *{ticker}* `${price}` ({chg_str}) | RSI `{rsi}`\n"
                    f"   Structure: `{struct_str}`{macd_tag}{bb_tag}{vol_tag}{brk_down_tag}\n"
                    f"   Swing: `{swing['direction']}` | SL `${swing['stop_loss']}` | T1 `${swing['target1']}`"
                ),
            })
        except Exception as e:
            logger.warning(f"Oversold scan error for {ticker}: {e}")
            errors.append(ticker)

    hits.sort(key=lambda x: (-x["quality"], x["rsi"]))

    lines = [f"🔵 *Oversold Dip-Buy Setups — {label}*", "━━━━━━━━━━━━━━━━━━━━", ""]
    lines.append("_RSI < 35 with a bullish EMA structure (EMA50 > EMA200, price > EMA50, or EMA9 > EMA21):_")
    lines.append("")

    if hits:
        for h in hits:
            lines.append(h["line"])
            lines.append("")
    else:
        lines.append("No stocks currently meet the criteria (RSI < 35 with bullish structure).")
        lines.append("Market may be in a strong uptrend with no meaningful dips yet.")

    if errors:
        lines.append(f"_⚠️ {len(errors)} ticker(s) could not be fetched._")

    lines.append("_Tap any ticker for the full analysis._")
    lines.append("⚠️ _Not financial advice. Mean-reversion setups carry risk — always use a stop loss._")

    await msg.edit_text("\n".join(lines), parse_mode="Markdown")


async def report_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = context.args
    if not args:
        await update.message.reply_text(
            "Usage: `/report AAPL`\n\nGenerates a full shareable analysis report you can forward to others.",
            parse_mode="Markdown",
        )
        return

    ticker = args[0].upper().strip()
    msg = await update.message.reply_text(
        f"📄 Generating full report for `{ticker}`...", parse_mode="Markdown"
    )

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
    now = datetime.now(timezone.utc).strftime("%d %b %Y, %H:%M UTC")

    price = data["last_close"]
    chg = data["change_pct"]
    chg_str = f"{'+' if chg >= 0 else ''}{chg}%"
    sig = data["signal"]["action"]
    rsi = data["rsi"]
    swing = data["swing"]
    brk = data["breakout"]
    vol = data["volume"]
    bb_upper = data["bb_upper"]
    bb_mid = data["bb_mid"]
    bb_lower = data["bb_lower"]

    if "STRONG BUY" in sig:   sig_icon = "🟢🟢"
    elif "BUY" in sig:         sig_icon = "🟢"
    elif "STRONG SELL" in sig: sig_icon = "🔴🔴"
    elif "SELL" in sig:        sig_icon = "🔴"
    else:                      sig_icon = "🟡"

    if rsi < 30:   rsi_zone = "Oversold"
    elif rsi < 45: rsi_zone = "Below mid"
    elif rsi < 55: rsi_zone = "Neutral"
    elif rsi < 70: rsi_zone = "Above mid"
    else:           rsi_zone = "Overbought"

    ema_trend = "Bullish" if data["ema9"] > data["ema21"] else "Bearish"
    macd_trend = "Bullish" if data["macd"] > data["macd_signal"] else "Bearish"
    news_icon = {"BULLISH": "🟢", "BEARISH": "🔴"}.get(sent["overall"], "🟡")

    if price > bb_upper:   bb_pos = "Above upper band ⚠️"
    elif price < bb_lower: bb_pos = "Below lower band ⚠️"
    else:                   bb_pos = "Within bands ✅"

    if brk["breakout_up"]:   brk_str = "🚨 BREAKOUT UP — 20-day resistance cleared with volume"
    elif brk["breakout_down"]: brk_str = "💥 BREAKDOWN — 20-day support broken with volume"
    else:                       brk_str = f"No active breakout | S: ${brk['support']} | R: ${brk['resistance']}"

    reasons_str = "\n".join(f"     • {r}" for r in data["signal"]["reasons"])

    top_headlines = ""
    if sent["headlines"]:
        headline_lines = []
        for h in sent["headlines"][:4]:
            icon = "🟢" if h["score"] > 0 else ("🔴" if h["score"] < 0 else "🟡")
            title = h["title"][:80] + ("..." if len(h["title"]) > 80 else "")
            headline_lines.append(f"  {icon} {title}")
        top_headlines = "\n".join(headline_lines)
    else:
        top_headlines = "  No recent headlines found."

    lines = [
        f"╔══════════════════════════╗",
        f"  📊 STOCK ANALYSIS REPORT",
        f"  {data['name']} ({ticker})",
        f"  {now}",
        f"╚══════════════════════════╝",
        "",
        f"💵 *PRICE*",
        f"  Current:  `${price}` ({chg_str})",
        f"  Signal:   {sig_icon} *{sig}*",
        "",
        f"  Reasons:",
        f"{reasons_str}",
        "",
        "─────────────────────────",
        f"📉 *RSI (14)*",
        f"  Value: `{rsi}` — {rsi_zone}",
        "",
        "─────────────────────────",
        f"📐 *EMA LEVELS*",
        f"  EMA 9:   `${data['ema9']}`",
        f"  EMA 21:  `${data['ema21']}`",
        f"  EMA 50:  `${data['ema50']}`",
        f"  EMA 200: `${data['ema200']}`",
        f"  Trend:   `{ema_trend}`",
        "",
        "─────────────────────────",
        f"📊 *MACD (12 / 26 / 9)*",
        f"  MACD:    `{data['macd']}`",
        f"  Signal:  `{data['macd_signal']}`",
        f"  Hist:    `{data['macd_hist']}`",
        f"  Trend:   `{macd_trend}`",
        "",
        "─────────────────────────",
        f"📏 *BOLLINGER BANDS (20)*",
        f"  Upper: `${bb_upper}` | Mid: `${bb_mid}` | Lower: `${bb_lower}`",
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
        f"  ATR (14):   `${swing['atr']}`",
        f"  Stop Loss:  `${swing['stop_loss']}`",
        f"  Target 1:   `${swing['target1']}`",
        f"  Target 2:   `${swing['target2']}`",
        "",
        "─────────────────────────",
        f"📰 *NEWS SENTIMENT*",
        f"  Overall: {news_icon} {sent['overall']} "
        f"({sent['bullish']}↑ {sent['bearish']}↓ / {sent['total']} articles)",
        f"{top_headlines}",
        "",
        "═════════════════════════",
        f"⚠️ _For educational purposes only._",
        f"_Not financial advice. Generated by Stock Analysis Bot._",
    ]

    await msg.edit_text("\n".join(lines), parse_mode="Markdown")


SECTOR_MAP = {
    "AAPL":          "💻 Tech",
    "MSFT":          "💻 Tech",
    "NVDA":          "💻 Tech",
    "GOOGL":         "💻 Tech",
    "AMZN":          "💻 Tech",
    "META":          "💻 Tech",
    "AMD":           "💻 Tech",
    "NFLX":          "🎬 Media",
    "INTC":          "💻 Tech",
    "TSLA":          "🚗 Auto / EV",
    "JPM":           "🏦 Finance",
    "V":             "🏦 Finance",
    "MA":            "🏦 Finance",
    "BAC":           "🏦 Finance",
    "DIS":           "🎬 Media",
    "RELIANCE.NS":   "⚡ Energy",
    "TCS.NS":        "💻 Tech",
    "INFY.NS":       "💻 Tech",
    "WIPRO.NS":      "💻 Tech",
    "HDFCBANK.NS":   "🏦 Finance",
    "ICICIBANK.NS":  "🏦 Finance",
    "SBIN.NS":       "🏦 Finance",
    "AXISBANK.NS":   "🏦 Finance",
    "KOTAKBANK.NS":  "🏦 Finance",
    "BAJFINANCE.NS": "🏦 Finance",
    "LT.NS":         "🏗️ Infra",
    "MARUTI.NS":     "🚗 Auto / EV",
    "TATAMOTORS.NS": "🚗 Auto / EV",
    "SUNPHARMA.NS":  "💊 Pharma",
    "ADANIENT.NS":   "⚡ Energy",
}

SIGNAL_ORDER = ["STRONG BUY", "BUY", "HOLD / NEUTRAL", "SELL", "STRONG SELL"]


async def sector_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    tickers = TOP_US + TOP_INDIA
    msg = await update.message.reply_text(
        f"🔍 Scanning {len(tickers)} stocks across sectors...", parse_mode="Markdown"
    )

    sectors: dict[str, list] = {}
    errors = []

    for ticker in tickers:
        sector = SECTOR_MAP.get(ticker, "🔹 Other")
        try:
            data = analyze(ticker)
            sectors.setdefault(sector, []).append({
                "ticker": ticker,
                "rsi": data["rsi"],
                "signal": data["signal"]["action"],
                "score": data["signal"]["score"],
                "chg": data["change_pct"],
                "breakout_up": data["breakout"]["breakout_up"],
                "breakout_down": data["breakout"]["breakout_down"],
            })
        except Exception as e:
            logger.warning(f"Sector scan error for {ticker}: {e}")
            errors.append(ticker)

    def dominant_signal(stocks: list) -> str:
        counts = {}
        for s in stocks:
            counts[s["signal"]] = counts.get(s["signal"], 0) + 1
        return max(counts, key=lambda x: counts[x])

    def sector_icon(sig: str) -> str:
        if "STRONG BUY" in sig:   return "🟢🟢"
        if "BUY" in sig:           return "🟢"
        if "STRONG SELL" in sig:  return "🔴🔴"
        if "SELL" in sig:          return "🔴"
        return "🟡"

    sector_summaries = []
    for sector, stocks in sectors.items():
        avg_rsi = round(sum(s["rsi"] for s in stocks) / len(stocks), 1)
        avg_chg = round(sum(s["chg"] for s in stocks) / len(stocks), 2)
        dom_sig = dominant_signal(stocks)
        avg_score = round(sum(s["score"] for s in stocks) / len(stocks), 1)
        breakouts = sum(1 for s in stocks if s["breakout_up"] or s["breakout_down"])
        sector_summaries.append({
            "sector": sector,
            "avg_rsi": avg_rsi,
            "avg_chg": avg_chg,
            "dom_sig": dom_sig,
            "avg_score": avg_score,
            "count": len(stocks),
            "breakouts": breakouts,
            "stocks": stocks,
        })

    sector_summaries.sort(key=lambda x: -x["avg_score"])

    lines = ["🏭 *Sector Overview*", "━━━━━━━━━━━━━━━━━━━━", ""]

    for sec in sector_summaries:
        icon = sector_icon(sec["dom_sig"])
        chg_str = f"{'+' if sec['avg_chg'] >= 0 else ''}{sec['avg_chg']}%"
        brk_tag = f" | 🚨 {sec['breakouts']} breakout(s)" if sec["breakouts"] else ""
        ticker_list = " ".join(f"`{s['ticker']}`" for s in sorted(sec["stocks"], key=lambda x: -x["score"]))

        lines.append(f"{icon} *{sec['sector']}* ({sec['count']} stocks)")
        lines.append(f"  Dominant: `{sec['dom_sig']}` | Avg RSI: `{sec['avg_rsi']}` | Avg Chg: `{chg_str}`{brk_tag}")
        lines.append(f"  Tickers: {ticker_list}")
        lines.append("")

    if errors:
        lines.append(f"_⚠️ {len(errors)} ticker(s) could not be fetched._")

    lines.append("_Tap any ticker for a full analysis._")
    lines.append("⚠️ _Not financial advice._")

    await msg.edit_text("\n".join(lines), parse_mode="Markdown")


async def heatmap_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    tickers = TOP_US + TOP_INDIA
    msg = await update.message.reply_text(
        f"🗺️ Building heatmap for {len(tickers)} stocks...", parse_mode="Markdown"
    )

    results = {}
    errors = []

    for ticker in tickers:
        try:
            data = analyze(ticker)
            sig = data["signal"]["action"]
            results[ticker] = {
                "signal": sig,
                "score": data["signal"]["score"],
                "rsi": data["rsi"],
                "chg": data["change_pct"],
            }
        except Exception as e:
            logger.warning(f"Heatmap error for {ticker}: {e}")
            errors.append(ticker)
            results[ticker] = None

    def cell(ticker: str) -> str:
        r = results.get(ticker)
        if not r:
            return f"⬜`{ticker}`"
        sig = r["signal"]
        if "STRONG BUY" in sig:   icon = "🟢🟢"
        elif "BUY" in sig:         icon = "🟢 "
        elif "STRONG SELL" in sig: icon = "🔴🔴"
        elif "SELL" in sig:        icon = "🔴 "
        else:                      icon = "🟡 "
        short = ticker.replace(".NS", "★").replace(".BO", "◆")
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
    avg_rsi = round(sum(avg_rsi_vals) / len(avg_rsi_vals), 1) if avg_rsi_vals else 0

    lines = ["🗺️ *Market Heatmap — 30 Stocks*", "━━━━━━━━━━━━━━━━━━━━", ""]

    sector_order = ["💻 Tech", "🏦 Finance", "🚗 Auto / EV", "🎬 Media", "⚡ Energy", "🏗️ Infra", "💊 Pharma"]
    sector_tickers: dict[str, list[str]] = {}
    for t in tickers:
        sec = SECTOR_MAP.get(t, "🔹 Other")
        sector_tickers.setdefault(sec, []).append(t)

    for sec in sector_order:
        group = sector_tickers.get(sec)
        if not group:
            continue
        group_sorted = sorted(group, key=lambda t: -(results[t]["score"] if results.get(t) else 0))
        lines.append(f"*{sec}*")
        row = "  " + "  ".join(cell(t) for t in group_sorted)
        lines.append(row)
        lines.append("")

    lines.append("━━━━━━━━━━━━━━━━━━━━")
    lines.append(f"📊 *Market Breadth:* {breadth_icon} {breadth}")
    lines.append(
        f"  🟢🟢 `{strong_buy}`  🟢 `{buy}`  🟡 `{hold}`  🔴 `{sell}`  🔴🔴 `{strong_sell}`"
    )
    lines.append(f"  Avg RSI (30 stocks): `{avg_rsi}`")
    lines.append(f"  Bull: `{total_bull}` stocks | Bear: `{total_bear}` stocks")
    lines.append("")
    lines.append("_★ = NSE (.NS)  |  Tap any ticker for full analysis_")
    lines.append("⚠️ _Not financial advice._")

    await msg.edit_text("\n".join(lines), parse_mode="Markdown")


async def risk_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = context.args
    if len(args) < 2:
        await update.message.reply_text(
            "Usage: `/risk AAPL 10000`\n\n"
            "Calculates position sizing, max loss, and risk/reward based on your capital and ATR stop loss.\n\n"
            "Capital is in the same currency as the stock (USD for US stocks, INR for Indian stocks).",
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
            "❌ Invalid capital amount. Example: `/risk AAPL 10000`", parse_mode="Markdown"
        )
        return

    risk_pct_arg = 2.0
    if len(args) >= 3:
        try:
            risk_pct_arg = float(args[2].replace("%", ""))
            risk_pct_arg = max(0.1, min(risk_pct_arg, 20.0))
        except ValueError:
            pass

    msg = await update.message.reply_text(
        f"📐 Calculating position size for `{ticker}`...", parse_mode="Markdown"
    )

    try:
        data = analyze(ticker)
    except Exception as e:
        logger.exception(f"Risk calc error for {ticker}: {e}")
        await msg.edit_text(f"❌ Could not fetch data for `{ticker}`.", parse_mode="Markdown")
        return

    price     = data["last_close"]
    atr       = data["swing"]["atr"]
    stop_loss = data["swing"]["stop_loss"]
    target1   = data["swing"]["target1"]
    target2   = data["swing"]["target2"]
    direction = data["swing"]["direction"]
    sig       = data["signal"]["action"]

    risk_per_share = abs(price - stop_loss)
    if risk_per_share == 0:
        await msg.edit_text("⚠️ Stop loss equals current price — cannot calculate risk.", parse_mode="Markdown")
        return

    max_risk_amount  = round(capital * (risk_pct_arg / 100), 2)
    shares           = max(1, int(max_risk_amount / risk_per_share))
    position_value   = round(shares * price, 2)
    actual_risk      = round(shares * risk_per_share, 2)
    actual_risk_pct  = round((actual_risk / capital) * 100, 2)
    reward1          = round(shares * abs(target1 - price), 2)
    reward2          = round(shares * abs(target2 - price), 2)
    rr1              = round(reward1 / actual_risk, 2) if actual_risk else 0
    rr2              = round(reward2 / actual_risk, 2) if actual_risk else 0
    leftover         = round(capital - position_value, 2)

    fits_in_capital = position_value <= capital

    if "STRONG BUY" in sig:   sig_icon = "🟢🟢"
    elif "BUY" in sig:         sig_icon = "🟢"
    elif "STRONG SELL" in sig: sig_icon = "🔴🔴"
    elif "SELL" in sig:        sig_icon = "🔴"
    else:                       sig_icon = "🟡"

    dir_arrow = "⬆️" if direction == "LONG" else "⬇️"

    rr1_verdict = "✅ Good" if rr1 >= 2 else ("⚠️ Marginal" if rr1 >= 1 else "❌ Poor")
    rr2_verdict = "✅ Good" if rr2 >= 2 else ("⚠️ Marginal" if rr2 >= 1 else "❌ Poor")

    lines = [
        f"📐 *Position Sizing — `{ticker}`*",
        "━━━━━━━━━━━━━━━━━━━━",
        "",
        f"💵 Price:    `${price}`  |  Signal: {sig_icon} {sig}",
        f"📊 ATR(14): `${atr}`  |  Swing: {dir_arrow} {direction}",
        "",
        "─────────────────────────",
        f"💰 *Your Capital:* `${capital:,.2f}`",
        f"⚠️ *Risk per trade:* `{risk_pct_arg}%` = `${max_risk_amount:,.2f}`",
        "",
        "─────────────────────────",
        f"📦 *Position Sizing:*",
        f"  Shares to buy:     `{shares:,}`",
        f"  Position value:    `${position_value:,.2f}`" + (" ✅" if fits_in_capital else " ⚠️ exceeds capital"),
        f"  Capital remaining: `${leftover:,.2f}`",
        "",
        "─────────────────────────",
        f"🛡️ *Risk Management:*",
        f"  Entry:      `${price}`",
        f"  Stop Loss:  `${stop_loss}`  (−`${round(risk_per_share, 2)}` per share)",
        f"  Max Loss:   `${actual_risk:,.2f}` ({actual_risk_pct}% of capital)",
        "",
        "─────────────────────────",
        f"🎯 *Reward Targets:*",
        f"  Target 1:  `${target1}`  → Profit `${reward1:,.2f}`  R:R `{rr1}x` {rr1_verdict}",
        f"  Target 2:  `${target2}`  → Profit `${reward2:,.2f}`  R:R `{rr2}x` {rr2_verdict}",
        "",
        "━━━━━━━━━━━━━━━━━━━━",
        "💡 *Tip:* Add your risk % after the capital to customise:",
        "  `/risk AAPL 10000 1` for 1% risk per trade.",
        "",
        "⚠️ _Not financial advice. Always use a stop loss._",
    ]

    await msg.edit_text("\n".join(lines), parse_mode="Markdown")


async def journal_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = context.args
    if len(args) < 4:
        await update.message.reply_text(
            "Usage: `/journal TICKER DIRECTION ENTRY EXIT [SHARES]`\n\n"
            "Examples:\n"
            "  `/journal AAPL long 150 165 10` — 10 shares AAPL long\n"
            "  `/journal TSLA short 280 260` — 1 share TSLA short\n\n"
            "Direction: `long` or `short`",
            parse_mode="Markdown",
        )
        return

    ticker    = args[0].upper().strip()
    direction = args[1].lower().strip()
    if direction not in ("long", "short"):
        await update.message.reply_text(
            "❌ Direction must be `long` or `short`.\n\nExample: `/journal AAPL long 150 165`",
            parse_mode="Markdown",
        )
        return

    try:
        entry  = float(args[2].replace("$", "").replace(",", ""))
        exit_p = float(args[3].replace("$", "").replace(",", ""))
        shares = float(args[4].replace(",", "")) if len(args) >= 5 else 1.0
        if entry <= 0 or exit_p <= 0 or shares <= 0:
            raise ValueError()
    except ValueError:
        await update.message.reply_text(
            "❌ Invalid numbers. Example: `/journal AAPL long 150 165 10`", parse_mode="Markdown"
        )
        return

    user_id = update.effective_user.id
    trade   = add_trade(user_id, ticker, direction, entry, exit_p, shares)

    won_icon = "✅ Win" if trade["won"] else "❌ Loss"
    pnl_str  = f"+${trade['pnl']:,.2f}" if trade["pnl"] >= 0 else f"-${abs(trade['pnl']):,.2f}"
    dir_icon = "⬆️" if trade["direction"] == "LONG" else "⬇️"

    await update.message.reply_text(
        f"📒 *Trade logged!* #{trade['id']}\n\n"
        f"{dir_icon} *{ticker}* {trade['direction']} | {trade['shares']} shares\n"
        f"  Entry: `${trade['entry']}` → Exit: `${trade['exit']}`\n"
        f"  P&L: `{pnl_str}` ({trade['pnl_pct']}%) — {won_icon}\n\n"
        f"Use /trades to see your history or /pnl for stats.",
        parse_mode="Markdown",
    )


async def trades_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    trades  = get_trades(user_id)

    if not trades:
        await update.message.reply_text(
            "📒 No trades logged yet.\n\nUse `/journal AAPL long 150 165 10` to log one.",
            parse_mode="Markdown",
        )
        return

    recent = list(reversed(trades[-20:]))
    lines  = [f"📒 *Trade Journal* ({len(trades)} total)", "━━━━━━━━━━━━━━━━━━━━", ""]

    for t in recent:
        won_icon = "✅" if t["won"] else "❌"
        pnl_str  = f"+${t['pnl']:,.2f}" if t["pnl"] >= 0 else f"-${abs(t['pnl']):,.2f}"
        dir_icon = "⬆️" if t["direction"] == "LONG" else "⬇️"
        lines.append(
            f"{won_icon} #{t['id']} {dir_icon} *{t['ticker']}* | `{t['date']}`\n"
            f"   `${t['entry']}` → `${t['exit']}` × {t['shares']} sh → `{pnl_str}` ({t['pnl_pct']}%)"
        )
        lines.append("")

    lines.append("_Use /pnl for statistics or `/deltrade ID` to remove._")
    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


async def pnl_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    stats   = get_pnl_stats(user_id)

    if not stats:
        await update.message.reply_text(
            "📊 No trades logged yet.\n\nUse `/journal AAPL long 150 165 10` to log one.",
            parse_mode="Markdown",
        )
        return

    total_icon = "🟢" if stats["total_pnl"] >= 0 else "🔴"
    pnl_str    = f"+${stats['total_pnl']:,.2f}" if stats["total_pnl"] >= 0 else f"-${abs(stats['total_pnl']):,.2f}"
    pf_str     = f"{stats['profit_factor']}" if stats["profit_factor"] != float("inf") else "∞"
    best       = stats["best"]
    worst      = stats["worst"]
    best_str   = f"+${best['pnl']:,.2f}" if best["pnl"] >= 0 else f"-${abs(best['pnl']):,.2f}"
    worst_str  = f"+${worst['pnl']:,.2f}" if worst["pnl"] >= 0 else f"-${abs(worst['pnl']):,.2f}"

    lines = [
        "📊 *P&L Statistics*",
        "━━━━━━━━━━━━━━━━━━━━",
        "",
        f"{total_icon} *Total P&L:* `{pnl_str}`",
        f"📈 *Win Rate:*  `{stats['win_rate']}%` ({stats['wins']}W / {stats['losses']}L / {stats['total']} trades)",
        f"⚖️ *Profit Factor:* `{pf_str}`",
        "",
        "─────────────────────────",
        f"✅ *Avg Win:*  `+${stats['avg_win']:,.2f}`",
        f"❌ *Avg Loss:* `-${abs(stats['avg_loss']):,.2f}`",
        "",
        "─────────────────────────",
        f"🏆 *Best Trade:*  #{best['id']} {best['ticker']} `{best_str}` ({best['pnl_pct']}%)",
        f"💥 *Worst Trade:* #{worst['id']} {worst['ticker']} `{worst_str}` ({worst['pnl_pct']}%)",
        "",
        "━━━━━━━━━━━━━━━━━━━━",
    ]

    if stats["win_rate"] >= 60 and stats["total_pnl"] > 0:
        lines.append("💡 _Solid performance — keep your discipline and stick to your stop losses._")
    elif stats["win_rate"] < 40:
        lines.append("💡 _Win rate is low — review your entry criteria and consider tighter setups._")
    elif stats["total_pnl"] < 0:
        lines.append("💡 _Positive win rate but net loss — check if your losses are larger than your wins._")
    else:
        lines.append("💡 _Consistent results — keep journaling to track improvements over time._")

    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


async def deltrade_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = context.args
    if not args:
        await update.message.reply_text(
            "Usage: `/deltrade 3`\n\nUse /trades to see your trade IDs.", parse_mode="Markdown"
        )
        return
    try:
        trade_id = int(args[0])
    except ValueError:
        await update.message.reply_text("❌ Provide a valid trade ID number. Use /trades to see them.", parse_mode="Markdown")
        return

    user_id = update.effective_user.id
    removed = delete_trade(user_id, trade_id)
    if removed:
        await update.message.reply_text(f"🗑️ Trade #{trade_id} deleted.", parse_mode="Markdown")
    else:
        await update.message.reply_text(
            f"⚠️ No trade found with ID #{trade_id}. Use /trades to see your entries.", parse_mode="Markdown"
        )


async def streak_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    data    = get_streak_and_equity(user_id)

    if not data:
        await update.message.reply_text(
            "📒 No trades logged yet.\n\nUse `/journal AAPL long 150 165 10` to log one.",
            parse_mode="Markdown",
        )
        return

    streak_icon = "🔥" if data["streak_type"] == "win" else "🧊"
    streak_label = "Win streak" if data["streak_type"] == "win" else "Loss streak"
    streak_msg   = (
        f"You're on a *{data['streak_count']}-trade {streak_label}!* 💪 Keep it up."
        if data["streak_type"] == "win"
        else f"You're on a *{data['streak_count']}-trade {streak_label}.* Stay patient and stick to your rules."
    )

    pnl_final = data["final_pnl"]
    pnl_str   = f"+${pnl_final:,.2f}" if pnl_final >= 0 else f"-${abs(pnl_final):,.2f}"
    pnl_icon  = "🟢" if pnl_final >= 0 else "🔴"

    # Label first and last trade on the equity axis
    curve = data["sparkline"]
    n     = data["trade_count"]

    # Build a mini scale for the curve
    cumulative = data["cumulative"]
    mn = min(cumulative)
    mx = max(cumulative)

    lines = [
        f"📈 *Streak & Equity Curve*",
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
        f"  High: `${mx:,.2f}`",
        f"  `{curve}`",
        f"  Low:  `${mn:,.2f}`",
        f"  Trade #1 ───────────── #{n}",
        "",
        "─────────────────────────",
        f"{pnl_icon} *Cumulative P&L:*  `{pnl_str}`",
        f"📉 *Max Drawdown:*    `-${data['max_drawdown']:,.2f}`",
        "",
        "━━━━━━━━━━━━━━━━━━━━",
        "_Use /pnl for full statistics or /trades to review your entries._",
    ]

    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


async def check_price_alerts(context):
    all_alerts = get_all_price_alerts()
    for user_id_str, alerts in all_alerts.items():
        user_id = int(user_id_str)
        for alert in list(alerts):
            ticker = alert["ticker"]
            condition = alert["condition"]
            target = alert["target"]
            chat_id = alert["chat_id"]
            alert_id = alert["id"]
            try:
                import yfinance as yf
                price = yf.Ticker(ticker).fast_info.get("last_price") or yf.Ticker(ticker).history(period="1d")["Close"].iloc[-1]
                price = round(float(price), 2)
                triggered = (condition == "above" and price >= target) or (condition == "below" and price <= target)
                if triggered:
                    arrow = "⬆️" if condition == "above" else "⬇️"
                    await context.bot.send_message(
                        chat_id=chat_id,
                        text=(
                            f"🔔 *Price Alert Triggered!*\n\n"
                            f"{arrow} *{ticker}* is now `${price}` — "
                            f"{'above' if condition == 'above' else 'below'} your target of `${target}`.\n\n"
                            f"_Send `{ticker}` for the full analysis._"
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
            "Usage: `/alert AAPL above 220` or `/alert TSLA below 190`\n\n"
            "Alerts fire once when the price crosses your target.",
            parse_mode="Markdown",
        )
        return

    ticker = args[0].upper().strip()
    condition = args[1].lower().strip()
    if condition not in ("above", "below"):
        await update.message.reply_text(
            "❌ Condition must be `above` or `below`.\n\nExample: `/alert AAPL above 220`",
            parse_mode="Markdown",
        )
        return

    try:
        target = float(args[2].replace("$", "").replace(",", ""))
    except ValueError:
        await update.message.reply_text("❌ Invalid price. Example: `/alert AAPL above 220`", parse_mode="Markdown")
        return

    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    alert_id = add_price_alert(user_id, chat_id, ticker, condition, target)

    arrow = "⬆️" if condition == "above" else "⬇️"
    await update.message.reply_text(
        f"🔔 Alert set! #{alert_id}\n\n"
        f"{arrow} You'll be notified when *{ticker}* goes *{condition}* `${target}`.\n\n"
        f"Checked every 15 minutes. Use /alerts to view all your alerts.",
        parse_mode="Markdown",
    )


async def list_alerts_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    alerts = get_user_alerts(user_id)
    if not alerts:
        await update.message.reply_text(
            "🔕 You have no active price alerts.\n\nUse `/alert AAPL above 220` to set one.",
            parse_mode="Markdown",
        )
        return

    lines = ["🔔 *Your Price Alerts:*", ""]
    for a in alerts:
        arrow = "⬆️" if a["condition"] == "above" else "⬇️"
        lines.append(f"  #{a['id']} — {arrow} *{a['ticker']}* {a['condition']} `${a['target']}`")
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
        await update.message.reply_text("❌ Please provide a valid alert ID number. Use /alerts to see them.", parse_mode="Markdown")
        return

    user_id = update.effective_user.id
    removed = remove_price_alert(user_id, alert_id)
    if removed:
        await update.message.reply_text(f"✅ Price alert #{alert_id} has been cancelled.", parse_mode="Markdown")
    else:
        await update.message.reply_text(f"⚠️ No alert found with ID #{alert_id}. Use /alerts to see your active alerts.", parse_mode="Markdown")


# ──────────────────────────────────────────────
# Startup: restore saved alerts
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
            logger.warning(f"Could not restore alert for user {user_id_str}: {e}")
    if count:
        logger.info(f"Restored {count} daily alert(s).")

    app.job_queue.run_repeating(check_price_alerts, interval=900, first=30, name="price_alert_checker")


# ──────────────────────────────────────────────
# Main
# ──────────────────────────────────────────────

def main():
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    if not token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN environment variable is not set.")

    app = ApplicationBuilder().token(token).post_init(restore_alerts).build()

    app.add_handler(CommandHandler("start", start_handler))
    app.add_handler(CommandHandler("help", help_handler))
    app.add_handler(CommandHandler("about", about_handler))
    app.add_handler(CommandHandler("watchlist", watchlist_handler))
    app.add_handler(CommandHandler("add", add_handler))
    app.add_handler(CommandHandler("remove", remove_handler))
    app.add_handler(CommandHandler("clear", clear_handler))
    app.add_handler(CommandHandler("scan", scan_handler))
    app.add_handler(CommandHandler("top", top_handler))
    app.add_handler(CommandHandler("compare", compare_handler))
    app.add_handler(CommandHandler("sentiment", sentiment_handler))
    app.add_handler(CommandHandler("movers", movers_handler))
    app.add_handler(CommandHandler("summary", summary_handler))
    app.add_handler(CommandHandler("gainers52w", gainers52w_handler))
    app.add_handler(CommandHandler("oversold", oversold_handler))
    app.add_handler(CommandHandler("report", report_handler))
    app.add_handler(CommandHandler("sector", sector_handler))
    app.add_handler(CommandHandler("heatmap", heatmap_handler))
    app.add_handler(CommandHandler("risk", risk_handler))
    app.add_handler(CommandHandler("journal", journal_handler))
    app.add_handler(CommandHandler("trades", trades_handler))
    app.add_handler(CommandHandler("pnl", pnl_handler))
    app.add_handler(CommandHandler("deltrade", deltrade_handler))
    app.add_handler(CommandHandler("streak", streak_handler))
    app.add_handler(CommandHandler("alert", alert_handler))
    app.add_handler(CommandHandler("alerts", list_alerts_handler))
    app.add_handler(CommandHandler("delalert", delalert_handler))
    app.add_handler(CommandHandler("setalert", setalert_handler))
    app.add_handler(CommandHandler("myalert", myalert_handler))
    app.add_handler(CommandHandler("cancelalert", cancelalert_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, analyze_handler))

    logger.info("Bot is starting...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
