# MarketMasteryAI Bot

AI-powered Indian stock market Telegram bot for NSE/BSE traders.

## Run & Operate

- `cd telegram-bot && python bot.py` — run the Telegram bot (via "Stock Analysis Telegram Bot" workflow)
- Required secret: `TELEGRAM_BOT_TOKEN` — from @BotFather on Telegram

## Stack

- Python 3.11
- python-telegram-bot v20+ (async polling with job-queue)
- yfinance — market data from Yahoo Finance
- pandas + numpy — all indicator computations (no ta-lib)

## File Map

| File | Purpose |
|---|---|
| `bot.py` | Main entry point. All handlers, `_fetch_many()` parallel fetcher, `is_valid_ticker()` validator |
| `analysis.py` | 6-factor signal model, all indicators, persistent name cache |
| `formatter.py` | Mobile-first Telegram message formatter |
| `utils.py` | Currency helpers, signal icons, RSI zone labels, market status |
| `watchlist.py` | Per-user watchlist persistence (JSON) |
| `alerts.py` | Daily scan alert scheduling (JSON) |
| `price_alerts.py` | Price alert persistence and management |
| `journal.py` | Trade journal with P&L, streak, equity curve |
| `backtest.py` | EMA 9/21 crossover backtesting |
| `sentiment.py` | Keyword-based news sentiment via yfinance |
| `name_cache.json` | Persistent stock name cache (avoid repeated slow info calls) |

## Architecture Decisions

### Speed
- `_fetch_many()` in bot.py: async parallel fetcher using `asyncio.to_thread` + `asyncio.Semaphore(5)`
  Makes screeners (20 stocks) ~8× faster: ~10s instead of ~100s
- `name_cache.json`: persistent stock name cache avoids repeated `stock.info` calls (3-8s each)
- All screener commands (`/nifty`, `/top`, `/movers`, `/breakout`, `/heatmap`, `/sector`, `/oversold`, `/gainers52w`) use `_fetch_many()`
- Single-ticker commands (`/signal`, `/swing`, `/intraday`, etc.) use `asyncio.to_thread(analyze, ticker)`

### Signal Quality — 6-Factor Model
Each factor contributes exactly ±1 (score bounded −6 to +6):
1. RSI zone (< 32 oversold = +1, > 68 overbought = −1)
2. EMA9 vs EMA21 cross (short-term trend)
3. MACD vs Signal line (momentum)
4. Price vs EMA21 (immediate price action)
5. Price vs EMA50 (medium-term trend)
6. EMA50 vs EMA200 (macro trend — golden/death cross filter)

Thresholds: STRONG BUY ≥ +4 | BUY ≥ +2 | HOLD −1…+1 | SELL ≤ −2 | STRONG SELL ≤ −4

The EMA50 > EMA200 macro filter significantly reduces false signals in bear markets.
Formatter shows `X/6 indicators aligned` for beginner context.

### Data Period
- Default: `1y` (~252 bars) for reliable EMA200 computation
- All indicators include `_safe()` NaN protection

### Validation
- `is_valid_ticker()`: regex `^[\^A-Z0-9][A-Z0-9\.\-]{0,19}$`
- `_require_ticker()`: shared helper validates + fetches in one step for single-ticker commands
- All bad input returns user-friendly error with .NS / ^NSEI examples

## Commands

Single stock: `/signal` `/swing` `/intraday` `/summary` `/report` `/sentiment`
Market: `/nifty` `/top` `/movers` `/breakout` `/heatmap` `/sector`
Screeners: `/gainers52w` `/oversold` `/compare`
Watchlist: `/watchlist` `/add` `/remove` `/scan` `/clear`
Alerts: `/alert` `/alerts` `/delalert` `/setalert` `/myalert` `/cancelalert`
Journal: `/journal` `/trades` `/pnl` `/streak` `/deltrade`
Risk: `/risk` `/backtest`

## Indian Market Tips

- NSE stocks: `TCS.NS`, `RELIANCE.NS`, `HDFCBANK.NS`
- BSE stocks: `TCS.BO`, `RELIANCE.BO`
- Nifty 50: `^NSEI` | Bank Nifty: `^NSEBANK`
- NSE hours: 9:15 AM – 3:30 PM IST (UTC+5:30)
- yfinance may rate-limit on rapid repeated requests

## User Preferences

- Python bot only (not Node.js)
- No external TA library — pure pandas/numpy implementation
- No new features — focus on quality, stability, speed, UI, and intelligence
- Mobile-first message formatting
- Beginner-friendly explanations in every section
