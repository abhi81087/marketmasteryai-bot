import os
import logging
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes
from analysis import analyze
from formatter import format_report

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
  `NIFTY50` — Nifty 50 Index
  `^NSEI` — Nifty 50 (Yahoo Finance format)

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


async def start_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 Welcome to *Stock Analysis Bot*!\n\nSend me a stock ticker symbol like `AAPL`, `TSLA`, or `TCS.NS` to get a full technical analysis.",
        parse_mode="Markdown",
    )


async def help_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(HELP_TEXT, parse_mode="Markdown")


async def about_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(ABOUT_TEXT, parse_mode="Markdown")


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
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, analyze_handler))

    logger.info("Bot is starting...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
