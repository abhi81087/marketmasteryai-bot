# Stock Analysis Telegram Bot

A Telegram bot that performs full technical analysis on any stock ticker and returns buy/sell signals, RSI, EMA, MACD, Bollinger Bands, volume analysis, breakout alerts, and swing trade setups.

## Run & Operate

- `cd telegram-bot && python bot.py` — run the Telegram bot (via the "Stock Analysis Telegram Bot" workflow)
- Required secret: `TELEGRAM_BOT_TOKEN` — from @BotFather on Telegram

## Stack

- Python 3.11
- python-telegram-bot v20+ (async polling)
- yfinance — market data from Yahoo Finance
- pandas + numpy — indicator computations (no ta-lib dependency)

## Where things live

- `telegram-bot/bot.py` — main bot entry point, command + message handlers
- `telegram-bot/analysis.py` — all technical indicators (RSI, EMA, MACD, Bollinger, ATR, OBV, breakout, swing setup)
- `telegram-bot/formatter.py` — formats analysis dict into a Telegram Markdown message
- `telegram-bot/requirements.txt` — Python dependencies

## Architecture decisions

- All indicators implemented from scratch using pandas/numpy — no ta-lib required, avoids C-library install issues
- Async handlers using python-telegram-bot v20+ ApplicationBuilder pattern
- Swing trade stop loss / targets derived from ATR (14) for dynamic risk sizing
- Breakout detection uses rolling 20-day high/low + volume surge threshold (1.5x avg)
- Signal score combines RSI zone, EMA cross, MACD cross, and price vs EMA21

## Product

Users send any ticker symbol (e.g. `AAPL`, `TSLA`, `TCS.NS`) and receive:
- RSI (14) with zone labeling
- EMA 9 / 21 / 50 / 200
- MACD + signal + histogram
- Bollinger Bands (20, 2σ)
- Volume analysis + OBV trend
- Breakout / Breakdown alerts (20-day S/R with volume confirmation)
- Swing trade setup: direction, stop loss, Target 1 & 2 (ATR-based)
- Overall Buy / Sell / Hold signal with reasoning

## User preferences

- Python bot (not Node.js)
- No external TA library required — pure pandas/numpy implementation

## Gotchas

- Indian stocks need `.NS` suffix (NSE) or `.BO` (BSE), e.g. `TCS.NS`, `RELIANCE.NS`
- Nifty 50 index: use `^NSEI`
- yfinance may rate-limit on rapid repeated requests
- Always run `pip install -r telegram-bot/requirements.txt` after a fresh environment
