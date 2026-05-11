import math
from datetime import datetime, timezone, timedelta

# ── Indian ticker detection ───────────────────────────────────────────────────

INDIAN_INDICES = {
    "^NSEI", "^NSEBANK", "^CNXFMCG", "^CNXAUTO",
    "^CNXIT", "^CNXPHARMA", "^NSMIDCP", "^CNXINFRA",
    "^CNXMIDCAP", "^CNXSMALLCAP",
}


def is_indian(ticker: str) -> bool:
    t = ticker.upper()
    return (
        t.endswith(".NS")
        or t.endswith(".BO")
        or t in INDIAN_INDICES
        or t.startswith("^NSE")
        or t.startswith("^CNX")
    )


# ── Currency formatting ───────────────────────────────────────────────────────

def fmt(value: float, ticker: str = "") -> str:
    """Format a price value with the correct currency symbol."""
    if value is None or (isinstance(value, float) and (math.isnan(value) or math.isinf(value))):
        return "N/A"
    # Suppress -0.0
    if value == 0:
        value = 0.0
    if is_indian(ticker):
        if abs(value) >= 10000:
            return f"₹{value:,.0f}"
        if abs(value) >= 1000:
            return f"₹{value:,.1f}"
        return f"₹{value:,.2f}"
    # US / default
    if abs(value) >= 1:
        return f"${value:,.2f}"
    return f"${value:.4f}"


def fmt_pnl(value: float, ticker: str = "") -> str:
    """Format a P&L value with sign and currency symbol."""
    if value is None or (isinstance(value, float) and (math.isnan(value) or math.isinf(value))):
        return "N/A"
    sym = "₹" if is_indian(ticker) else "$"
    if abs(value) >= 10000 and is_indian(ticker):
        return f"+{sym}{abs(value):,.0f}" if value >= 0 else f"-{sym}{abs(value):,.0f}"
    return f"+{sym}{abs(value):,.2f}" if value >= 0 else f"-{sym}{abs(value):,.2f}"


def fmt_macd(value: float) -> str:
    """Format MACD/signal/hist — no currency, 2 decimal places."""
    if value is None or (isinstance(value, float) and (math.isnan(value) or math.isinf(value))):
        return "N/A"
    return f"{value:.2f}"


# ── Signal helpers ────────────────────────────────────────────────────────────

def sig_icon(sig: str) -> str:
    if "STRONG BUY" in sig:   return "🟢🟢"
    if "BUY" in sig:           return "🟢"
    if "STRONG SELL" in sig:  return "🔴🔴"
    if "SELL" in sig:          return "🔴"
    return "🟡"


def chg_str(pct: float) -> str:
    if pct is None:
        return "N/A"
    return f"+{pct:.2f}%" if pct >= 0 else f"{pct:.2f}%"


def chg_emoji(pct: float) -> str:
    if pct is None:
        return "➡️"
    if pct >= 3:    return "🚀"
    if pct >= 0.5:  return "📈"
    if pct > -0.5:  return "➡️"
    if pct > -3:    return "📉"
    return "💥"


def rsi_zone(rsi: float) -> str:
    if rsi < 25:    return "🔵 Extremely Oversold"
    if rsi < 35:    return "🔵 Oversold"
    if rsi < 45:    return "🟦 Below Midline"
    if rsi < 55:    return "⬜ Neutral"
    if rsi < 65:    return "🟧 Above Midline"
    if rsi < 75:    return "🟠 Overbought"
    return "🔴 Extremely Overbought"


def rsi_tip(rsi: float) -> str:
    if rsi < 30:
        return "RSI < 30: possibly oversold — watch for a bounce"
    if rsi > 70:
        return "RSI > 70: possibly overbought — gains may slow"
    return "RSI 30–70: normal trading range"


# ── Market status (IST) ───────────────────────────────────────────────────────

def market_status_ist() -> tuple[str, str]:
    """Returns (status_line, time_str) in IST."""
    ist = timezone(timedelta(hours=5, minutes=30))
    now = datetime.now(ist)
    time_str = now.strftime("%I:%M %p IST")
    wd = now.weekday()  # 0 = Monday

    if wd >= 5:
        return "🔴 Closed — Weekend", time_str
    h, m = now.hour, now.minute
    if h == 9 and m < 8:
        return "🟡 Pre-open bidding (9:00–9:08 AM)", time_str
    if h == 9 and m < 15:
        return "🟡 Pre-open (opens 9:15 AM)", time_str
    if (h == 9 and m >= 15) or (10 <= h <= 14) or (h == 15 and m <= 30):
        return "🟢 Market OPEN", time_str
    return "🔴 Market Closed", time_str
