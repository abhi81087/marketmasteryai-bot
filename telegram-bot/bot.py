import os
import logging
from datetime import time as dtime
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes
from analysis import analyze
from formatter import format_report
from watchlist import get_watchlist, add_tickers, remove_tickers, clear_watchlist
from alerts import set_alert, remove_alert, get_alert, get_all_alerts

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
    app.add_handler(CommandHandler("setalert", setalert_handler))
    app.add_handler(CommandHandler("myalert", myalert_handler))
    app.add_handler(CommandHandler("cancelalert", cancelalert_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, analyze_handler))

    logger.info("Bot is starting...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
