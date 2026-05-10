def emoji_signal(action: str) -> str:
    mapping = {
        "STRONG BUY": "🟢🟢",
        "BUY": "🟢",
        "HOLD / NEUTRAL": "🟡",
        "SELL": "🔴",
        "STRONG SELL": "🔴🔴",
    }
    return mapping.get(action, "⚪")


def rsi_bar(rsi: float) -> str:
    if rsi < 30:
        return "🔵 Oversold"
    elif rsi < 45:
        return "🟦 Below mid"
    elif rsi < 55:
        return "⬜ Neutral"
    elif rsi < 70:
        return "🟧 Above mid"
    else:
        return "🔴 Overbought"


def change_emoji(pct: float) -> str:
    if pct >= 2:
        return "🚀"
    elif pct > 0:
        return "📈"
    elif pct == 0:
        return "➡️"
    elif pct > -2:
        return "📉"
    else:
        return "💥"


def format_report(data: dict) -> str:
    t = data["ticker"]
    name = data["name"]
    price = data["last_close"]
    chg = data["change_pct"]
    signal = data["signal"]
    swing = data["swing"]
    brk = data["breakout"]
    vol = data["volume"]

    lines = []
    lines.append(f"📊 *{name}* (`{t}`)")
    lines.append(f"💵 Price: *${price}* {change_emoji(chg)} `{'+' if chg >= 0 else ''}{chg}%`")
    lines.append("")

    # Signal
    sig_emoji = emoji_signal(signal["action"])
    lines.append(f"🎯 *Signal: {sig_emoji} {signal['action']}*")
    for r in signal["reasons"]:
        lines.append(f"   • {r}")
    lines.append("")

    # RSI
    lines.append(f"📉 *RSI (14):* `{data['rsi']}` — {rsi_bar(data['rsi'])}")
    lines.append("")

    # EMA
    lines.append("📐 *EMA Levels:*")
    lines.append(f"   EMA 9:   `${data['ema9']}`")
    lines.append(f"   EMA 21:  `${data['ema21']}`")
    lines.append(f"   EMA 50:  `${data['ema50']}`")
    lines.append(f"   EMA 200: `${data['ema200']}`")
    lines.append("")

    # MACD
    macd_trend = "Bullish" if data["macd"] > data["macd_signal"] else "Bearish"
    macd_emoji = "🟢" if macd_trend == "Bullish" else "🔴"
    lines.append(f"📊 *MACD:* {macd_emoji} {macd_trend}")
    lines.append(f"   MACD: `{data['macd']}` | Signal: `{data['macd_signal']}` | Hist: `{data['macd_hist']}`")
    lines.append("")

    # Bollinger Bands
    lines.append("📏 *Bollinger Bands (20):*")
    lines.append(f"   Upper: `${data['bb_upper']}` | Mid: `${data['bb_mid']}` | Lower: `${data['bb_lower']}`")
    bb_pos = ""
    if data["last_close"] > data["bb_upper"]:
        bb_pos = "⚠️ Price above upper band (overbought zone)"
    elif data["last_close"] < data["bb_lower"]:
        bb_pos = "⚠️ Price below lower band (oversold zone)"
    else:
        bb_pos = "✅ Price within bands"
    lines.append(f"   {bb_pos}")
    lines.append("")

    # Volume
    lines.append("📦 *Volume Analysis:*")
    vol_emoji = "🔥" if vol["volume_ratio"] >= 1.5 else ("⬆️" if vol["volume_ratio"] >= 1.1 else "➡️")
    lines.append(f"   Last Vol:  `{vol['last_volume']:,}` {vol_emoji}")
    lines.append(f"   Avg (20d): `{vol['avg_volume_20d']:,}`")
    lines.append(f"   Ratio:     `{vol['volume_ratio']}x`")
    lines.append(f"   OBV Trend: `{vol['obv_trend']}`")
    lines.append("")

    # Breakout
    lines.append("🚨 *Breakout / Support-Resistance:*")
    lines.append(f"   Resistance: `${brk['resistance']}` | Support: `${brk['support']}`")
    if brk["breakout_up"]:
        lines.append("   🔥 *BREAKOUT UP detected!*" + (" (Volume surge!)" if brk["volume_surge"] else ""))
    elif brk["breakout_down"]:
        lines.append("   💥 *BREAKDOWN detected!*" + (" (Volume surge!)" if brk["volume_surge"] else ""))
    else:
        lines.append("   ➡️ No active breakout")
    lines.append("")

    # Swing Trade Setup
    dir_emoji = "⬆️" if swing["direction"] == "LONG" else "⬇️"
    lines.append(f"🏹 *Swing Trade Setup:* {dir_emoji} {swing['direction']}")
    lines.append(f"   Confidence: `{swing['confidence']}%`")
    lines.append(f"   Stop Loss:  `${swing['stop_loss']}`")
    lines.append(f"   Target 1:   `${swing['target1']}`")
    lines.append(f"   Target 2:   `${swing['target2']}`")
    lines.append(f"   ATR (14):   `${swing['atr']}`")
    lines.append("")

    lines.append("━━━━━━━━━━━━━━━━━━━━")
    lines.append("⚠️ _For educational purposes only. Not financial advice._")

    return "\n".join(lines)
