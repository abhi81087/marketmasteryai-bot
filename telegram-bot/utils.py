INDIAN_INDICES = {
    "^NSEI", "^NSEBANK", "^CNXFMCG", "^CNXAUTO",
    "^CNXIT", "^CNXPHARMA", "^NSMIDCP", "^CNXINFRA",
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


def fmt(value: float, ticker: str = "") -> str:
    if is_indian(ticker):
        if value >= 1000:
            return f"₹{value:,.1f}"
        return f"₹{value:,.2f}"
    if abs(value) >= 1:
        return f"${value:,.2f}"
    return f"${value:.4f}"


def fmt_pnl(value: float, ticker: str = "") -> str:
    sym = "₹" if is_indian(ticker) else "$"
    if value >= 0:
        return f"+{sym}{abs(value):,.2f}"
    return f"-{sym}{abs(value):,.2f}"


def sig_icon(sig: str) -> str:
    if "STRONG BUY" in sig:   return "🟢🟢"
    if "BUY" in sig:           return "🟢"
    if "STRONG SELL" in sig:  return "🔴🔴"
    if "SELL" in sig:          return "🔴"
    return "🟡"


def chg_str(pct: float) -> str:
    return f"+{pct}%" if pct >= 0 else f"{pct}%"


def chg_emoji(pct: float) -> str:
    if pct >= 3:    return "🚀"
    if pct >= 0.5:  return "📈"
    if pct == 0:    return "➡️"
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
        return "💡 RSI below 30 = stock may be oversold. Watch for a bounce."
    if rsi > 70:
        return "💡 RSI above 70 = stock may be overbought. Gains may slow."
    return "💡 RSI between 30–70 = normal trading range."
