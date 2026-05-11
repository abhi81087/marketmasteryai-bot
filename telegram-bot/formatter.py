from utils import (
    fmt, sig_icon, chg_str, chg_emoji,
    rsi_zone, rsi_tip, fmt_macd, is_indian,
)


def format_report(data: dict) -> str:
    t      = data["ticker"]
    name   = data["name"]
    price  = data["last_close"]
    chg    = data["change_pct"]
    signal = data["signal"]
    swing  = data["swing"]
    brk    = data["breakout"]
    vol    = data["volume"]
    rsi    = data["rsi"]

    icon     = sig_icon(signal["action"])
    ema_bull = data["ema9"] > data["ema21"]
    macd_bull = data["macd"] > data["macd_signal"]

    lines = []

    # ── Header ────────────────────────────────────────
    lines.append(f"📊 *{name}*")
    lines.append(f"🏷 `{t}`")
    lines.append("━━━━━━━━━━━━━━━━━━━━")
    lines.append("")

    # ── Price & Signal ─────────────────────────────────
    lines.append(
        f"💰 *{fmt(price, t)}*   {chg_emoji(chg)} `{chg_str(chg)}`"
    )
    lines.append(f"🎯 *Signal: {icon} {signal['action']}*")
    lines.append("")
    lines.append("_Why this signal:_")
    for r in signal["reasons"]:
        lines.append(f"  • {r}")
    lines.append("")

    # ── RSI ───────────────────────────────────────────
    lines.append("━━━━━━━━━━━━━━━━━━━━")
    lines.append(f"📉 *RSI (14):* `{rsi}` — {rsi_zone(rsi)}")
    lines.append(f"   _💡 {rsi_tip(rsi)}_")
    lines.append("")

    # ── EMA ───────────────────────────────────────────
    ema_icon = "🟢" if ema_bull else "🔴"
    ema_dir  = "Bullish ↑" if ema_bull else "Bearish ↓"
    lines.append(f"📐 *EMA Trend:* {ema_icon} `{ema_dir}`")
    lines.append(f"  EMA9:    `{fmt(data['ema9'],  t)}`")
    lines.append(f"  EMA21:   `{fmt(data['ema21'], t)}`")
    lines.append(f"  EMA50:   `{fmt(data['ema50'], t)}`")
    lines.append(f"  EMA200:  `{fmt(data['ema200'],t)}`")
    lines.append(f"  _💡 EMA9 > EMA21 = short-term bullish_")
    lines.append("")

    # ── MACD ──────────────────────────────────────────
    m_icon  = "🟢" if macd_bull else "🔴"
    m_label = "Bullish — buyers in control" if macd_bull else "Bearish — sellers in control"
    lines.append(f"📊 *MACD (12/26/9):* {m_icon} {m_label}")
    lines.append(
        f"  `{fmt_macd(data['macd'])}` / `{fmt_macd(data['macd_signal'])}` / `{fmt_macd(data['macd_hist'])}`"
    )
    lines.append(f"  _(MACD / Signal / Histogram)_")
    lines.append("")

    # ── Bollinger Bands ───────────────────────────────
    bb_u = data["bb_upper"]
    bb_m = data["bb_mid"]
    bb_l = data["bb_lower"]
    if price > bb_u:
        bb_pos = "⚠️ Above upper — may be overbought"
    elif price < bb_l:
        bb_pos = "✅ Below lower — potential bounce"
    else:
        bb_pos = "✅ Inside bands — normal range"
    lines.append(f"📏 *Bollinger Bands (20, 2σ):*")
    lines.append(f"  U: `{fmt(bb_u, t)}`  M: `{fmt(bb_m, t)}`")
    lines.append(f"  L: `{fmt(bb_l, t)}`")
    lines.append(f"  {bb_pos}")
    lines.append(f"  _💡 Price outside bands often signals reversal_")
    lines.append("")

    # ── Volume ────────────────────────────────────────
    vr = vol["volume_ratio"]
    if vr >= 2.0:
        vol_label = "🔥 Very high volume surge!"
    elif vr >= 1.5:
        vol_label = "⬆️ Above average volume"
    elif vr >= 1.0:
        vol_label = "➡️ Average volume"
    else:
        vol_label = "⬇️ Below average volume"

    lines.append(f"📦 *Volume:* `{vr}x avg` — {vol_label}")
    lines.append(f"  Today: `{vol['last_volume']:,}`")
    lines.append(f"  Avg20: `{vol['avg_volume_20d']:,}`")
    lines.append(f"  OBV:   `{vol['obv_trend']}`")
    lines.append(f"  _💡 Volume > 1.5x avg confirms the move_")
    lines.append("")

    # ── Breakout / S&R ────────────────────────────────
    lines.append(f"🚨 *Breakout / S&R:*")
    lines.append(
        f"  R: `{fmt(brk['resistance'], t)}`  S: `{fmt(brk['support'], t)}`"
    )
    if brk["breakout_up"]:
        vol_note = " (with volume spike 🔥)" if brk["volume_surge"] else ""
        lines.append(f"  🚀 *BREAKOUT UP!* Resistance cleared{vol_note}")
    elif brk["breakout_down"]:
        vol_note = " (with volume spike 🔥)" if brk["volume_surge"] else ""
        lines.append(f"  💥 *BREAKDOWN!* Support broken{vol_note}")
    else:
        lines.append(f"  ➡️ No active breakout — price consolidating")
    lines.append("")

    # ── Swing Trade Setup ─────────────────────────────
    dir_emoji = "⬆️ LONG" if swing["direction"] == "LONG" else "⬇️ SHORT"
    conf      = swing["confidence"]
    conf_bar  = "●" * (conf // 20) + "○" * (5 - conf // 20)

    rps = abs(price - swing["stop_loss"])
    rw1 = abs(swing["target1"] - price)
    rw2 = abs(swing["target2"] - price)
    rr1 = round(rw1 / rps, 2) if rps else 0
    rr2 = round(rw2 / rps, 2) if rps else 0

    lines.append("━━━━━━━━━━━━━━━━━━━━")
    lines.append(f"🏹 *Swing Setup: {dir_emoji}*")
    lines.append(f"   Confidence: `{conf}%` [{conf_bar}]")
    lines.append(f"   ATR(14): `{fmt(swing['atr'], t)}`")
    lines.append("")
    lines.append(f"  📍 Entry:    `{fmt(price, t)}`")
    lines.append(f"  🛡 Stop:     `{fmt(swing['stop_loss'], t)}`")
    lines.append(f"  🎯 Target 1: `{fmt(swing['target1'], t)}`  R:R `{rr1}x`")
    lines.append(f"  🎯 Target 2: `{fmt(swing['target2'], t)}`  R:R `{rr2}x`")
    lines.append(f"  _💡 Stop = 1.5× ATR from entry. Always respect it._")
    lines.append("")

    # ── Footer ────────────────────────────────────────
    lines.append("━━━━━━━━━━━━━━━━━━━━")
    lines.append("⚠️ _Educational only. Not financial advice._")
    lines.append("_Consult a SEBI-registered advisor before trading._")

    return "\n".join(lines)
