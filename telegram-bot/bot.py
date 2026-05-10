import os
import logging
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes
from analysis import analyze
from formatter import format_report
from watchlist import get_watchlist, add_tickers, remove_tickers, clear_watchlist

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

*Commands:*
  /start             — Welcome message
  /help              — Show this help
  /about             — About this bot
  /watchlist         — View your saved tickers
  /add AAPL TSLA     — Add tickers to watchlist
  /remove AAPL       — Remove a ticker
  /scan              — Analyse all watchlist tickers
  /clear             — Clear your watchlist
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


async def start_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 Welcome to *Stock Analysis Bot*!\n\n"
        "Send me a stock ticker like `AAPL`, `TSLA`, or `TCS.NS` to get a full technical analysis.\n\n"
        "Use /watchlist to save your favourite tickers, then /scan to analyse them all at once.",
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
    lines.append("Use /scan to analyse all tickers.")
    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


async def add_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    args = context.args
    if not args:
        await update.message.reply_text(
            "Usage: `/add AAPL TSLA TCS.NS`", parse_mode="Markdown"
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
        await update.message.reply_text(
            "Usage: `/remove AAPL TSLA`", parse_mode="Markdown"
        )
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


def main():
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    if not token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN environment variable is not set.")

    app = ApplicationBuilder().token(token).build()

    app.add_handler(CommandHandler("start", start_handler))
    app.add_handler(CommandHandler("help", help_handler))
    app.add_handler(CommandHandler("about", about_handler))
    app.add_handler(CommandHandler("watchlist", watchlist_handler))
    app.add_handler(CommandHandler("add", add_handler))
    app.add_handler(CommandHandler("remove", remove_handler))
    app.add_handler(CommandHandler("clear", clear_handler))
    app.add_handler(CommandHandler("scan", scan_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, analyze_handler))

    logger.info("Bot is starting...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
