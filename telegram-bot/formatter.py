from utils import fmt, sig_icon, chg_str, chg_emoji, rsi_zone, rsi_tip, is_indian


def format_report(data: dict) -> str:
    t       = data["ticker"]
    name    = data["name"]
    price   = data["last_close"]
    chg     = data["change_pct"]
    signal  = data["signal"]
    swing   = data["swing"]
    brk     = data["breakout"]
    vol     = data["volume"]
    indian  = is_indian(t)
    curr    = "₹" if indian else "$"

    lines = []

    # ── Header ──────────────────────────────────────
    lines.append(f"┌─────────────────────────────┐")
    lines.append(f"  📊 *{name}*")
    lines.append(f"  🏷️ Ticker: `{t}`")
    lines.append(f"└─────────────────────────────┘")
    lines.append("")

    # ── Price ────────────────────────────────────────
    ce = chg_emoji(chg)
    lines.append(
        f"💰 *Price:* `{fmt(price, t)}`  {ce}  `{chg_str(chg)}`"
    )
    lines.append("")

    # ── Signal Card ──────────────────────────────────
    icon = sig_icon(signal["action"])
    lines.append(f"🎯 *AI Signal:  {icon} {signal['action']}*")
    lines.append("_Why this signal:_")
    for r in signal["reasons"]:
        lines.append(f"   • {r}")
    lines.append("")

    # ── RSI ──────────────────────────────────────────
    zone = rsi_zone(data["rsi"])
    lines.append(f"📉 *RSI (14):* `{data['rsi']}` — {zone}")
    lines.append(f"   _{rsi_tip(data['rsi'])}_")
    lines.append("")

    # ── EMA ──────────────────────────────────────────
    ema_trend = "Bullish ↑" if data["ema9"] > data["ema21"] else "Bearish ↓"
    ema_icon  = "🟢" if data["ema9"] > data["ema21"] else "🔴"
    lines.append(f"📐 *EMA Levels:*  {ema_icon} Trend: `{ema_trend}`")
    lines.append(f"   EMA 9:    `{fmt(data['ema9'], t)}`")
    lines.append(f"   EMA 21:   `{fmt(data['ema21'], t)}`")
    lines.append(f"   EMA 50:   `{fmt(data['ema50'], t)}`")
    lines.append(f"   EMA 200:  `{fmt(data['ema200'], t)}`")
    lines.append(f"   _💡 EMA9 > EMA21 = short-term bullish momentum_")
    lines.append("")

    # ── MACD ─────────────────────────────────────────
    macd_bull = data["macd"] > data["macd_signal"]
    macd_emoji = "🟢" if macd_bull else "🔴"
    macd_trend = "Bullish — Buyers in control" if macd_bull else "Bearish — Sellers in control"
    lines.append(f"📊 *MACD (12/26/9):* {macd_emoji} {macd_trend}")
    lines.append(f"   MACD: `{data['macd']}` | Signal: `{data['macd_signal']}` | Hist: `{data['macd_hist']}`")
    lines.append("")

    # ── Bollinger Bands ───────────────────────────────
    bb_upper = data["bb_upper"]
    bb_mid   = data["bb_mid"]
    bb_lower = data["bb_lower"]
    if price > bb_upper:
        bb_pos = "⚠️ Above upper band — may be overbought"
    elif price < bb_lower:
        bb_pos = "✅ Below lower band — potential bounce zone"
    else:
        bb_pos = "✅ Within bands — normal range"
    lines.append(f"📏 *Bollinger Bands (20):*")
    lines.append(f"   Upper: `{fmt(bb_upper, t)}` | Mid: `{fmt(bb_mid, t)}` | Lower: `{fmt(bb_lower, t)}`")
    lines.append(f"   {bb_pos}")
    lines.append(f"   _💡 Price outside bands often signals reversal_")
    lines.append("")

    # ── Volume ────────────────────────────────────────
    vr = vol["volume_ratio"]
    vol_icon = "🔥 High volume surge!" if vr >= 2.0 else ("⬆️ Above average" if vr >= 1.2 else "➡️ Average")
    lines.append(f"📦 *Volume Analysis:*")
    lines.append(f"   Today:     `{vol['last_volume']:,}` {vol_icon}")
    lines.append(f"   Avg (20d): `{vol['avg_volume_20d']:,}`")
    lines.append(f"   Ratio:     `{vr}x` | OBV: `{vol['obv_trend']}`")
    lines.append(f"   _💡 Volume > 1.5x average confirms the move_")
    lines.append("")

    # ── Breakout ──────────────────────────────────────
    lines.append(f"🚨 *Breakout & Key Levels:*")
    lines.append(
        f"   Resistance: `{fmt(brk['resistance'], t)}`  |  Support: `{fmt(brk['support'], t)}`"
    )
    if brk["breakout_up"]:
        vol_note = " with volume surge 🔥" if brk["volume_surge"] else ""
        lines.append(f"   🚀 *BREAKOUT UP!* Resistance cleared{vol_note}")
    elif brk["breakout_down"]:
        vol_note = " with volume surge 🔥" if brk["volume_surge"] else ""
        lines.append(f"   💥 *BREAKDOWN!* Support broken{vol_note}")
    else:
        lines.append(f"   ➡️ No active breakout — price consolidating")
    lines.append("")

    # ── Swing Trade Setup ─────────────────────────────
    dir_emoji = "⬆️ LONG" if swing["direction"] == "LONG" else "⬇️ SHORT"
    conf      = swing["confidence"]
    conf_bar  = "●" * (conf // 20) + "○" * (5 - conf // 20)
    lines.append(f"🏹 *Swing Trade Setup:*  {dir_emoji}")
    lines.append(f"   Confidence: `{conf}%`  [{conf_bar}]")
    lines.append(f"   ─────────────────────")
    lines.append(f"   📍 Entry:     `{fmt(price, t)}`  _(current price)_")
    lines.append(f"   🛡️ Stop Loss: `{fmt(swing['stop_loss'], t)}`")
    lines.append(f"   🎯 Target 1:  `{fmt(swing['target1'], t)}`")
    lines.append(f"   🎯 Target 2:  `{fmt(swing['target2'], t)}`")
    lines.append(f"   📊 ATR (14):  `{fmt(swing['atr'], t)}`")
    lines.append(f"   _💡 Stop loss is 1.5× ATR from entry. Always respect it._")
    lines.append("")

    # ── Footer ────────────────────────────────────────
    lines.append("━━━━━━━━━━━━━━━━━━━━")
    lines.append("⚠️ _For educational purposes only. Not financial advice._")
    lines.append("_Always do your own research before trading._")

    return "\n".join(lines)
