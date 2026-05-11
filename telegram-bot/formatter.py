"""
formatter.py — Mobile-first Telegram message formatter.

Design rules:
- Lines ≤ 38 chars where possible for mobile readability.
- Monospace (`backtick`) for all numbers.
- Bold only for headings and signal actions.
- Plain English explanations for beginners.
- One blank line between sections.
"""

from utils import (
    fmt, fmt_macd, sig_icon,
    chg_str, chg_emoji, rsi_zone, rsi_tip,
)


def _bb_note(price: float, upper: float, lower: float, mid: float) -> str:
    if price > upper:
        return "⚠️ Above upper band — overbought stretch"
    if price < lower:
        return "🔵 Below lower band — oversold stretch"
    if price > mid:
        return "✅ Upper half of bands — mild bullish"
    return "➡️ Lower half of bands — mild bearish"


def format_report(data: dict) -> str:
    t     = data["ticker"]
    price = data["last_close"]
    chg   = data["change_pct"]
    sig   = data["signal"]
    swing = data["swing"]
    brk   = data["breakout"]
    vol   = data["volume"]
    rsi   = data["rsi"]

    icon      = sig_icon(sig["action"])
    ema_bull  = data["ema9"] > data["ema21"]
    macd_bull = data["macd"] > data["macd_signal"]
    accel     = data.get("macd_accel", False)
    bull_n    = sig.get("bull_count", 3)
    total_n   = sig.get("total_factors", 6)

    L = []  # lines

    # ── Header ────────────────────────────────────────
    L.append(f"📊 *{data['name']}*")
    L.append(f"`{t}`")
    L.append("━━━━━━━━━━━━━━━━━━━━")

    # ── Price & Signal ─────────────────────────────────
    L.append(f"")
    L.append(f"💰 *{fmt(price, t)}*  {chg_emoji(chg)} `{chg_str(chg)}`")
    L.append(f"🎯 *{icon} {sig['action']}*")
    L.append(f"_{bull_n}/{total_n} indicators aligned_")

    L.append("")
    L.append("*Why:*")
    for r in sig["reasons"]:
        L.append(f"  • {r}")

    # ── RSI ───────────────────────────────────────────
    L.append("")
    L.append("━━━━━━━━━━━━━━━━━━━━")
    L.append(f"📉 *RSI (14):* `{rsi}`")
    L.append(f"   {rsi_zone(rsi)}")
    L.append(f"   _💡 {rsi_tip(rsi)}_")

    # ── EMA ───────────────────────────────────────────
    ema_lbl = "🟢 Bullish ↑" if ema_bull else "🔴 Bearish ↓"
    L.append("")
    L.append(f"📐 *EMA Trend:* {ema_lbl}")
    L.append(f"   EMA 9:   `{fmt(data['ema9'],  t)}`")
    L.append(f"   EMA 21:  `{fmt(data['ema21'], t)}`")
    L.append(f"   EMA 50:  `{fmt(data['ema50'], t)}`")
    L.append(f"   EMA 200: `{fmt(data['ema200'],t)}`")

    long_bull = data["ema50"] > data["ema200"]
    struct = "🟢 Bull structure (EMA50>200)" if long_bull else "🔴 Bear structure (EMA50<200)"
    L.append(f"   {struct}")
    L.append(f"   _💡 EMA200 = long-term trend baseline_")

    # ── MACD ──────────────────────────────────────────
    macd_lbl  = "🟢 Bullish" if macd_bull else "🔴 Bearish"
    hist_dir  = "↑ accelerating" if accel else "↓ decelerating"
    hist_sign = "+" if data["macd_hist"] >= 0 else ""
    L.append("")
    L.append(f"📊 *MACD (12/26/9):* {macd_lbl}")
    L.append(f"   MACD:    `{fmt_macd(data['macd'])}`")
    L.append(f"   Signal:  `{fmt_macd(data['macd_signal'])}`")
    L.append(f"   Hist:    `{hist_sign}{fmt_macd(data['macd_hist'])}` {hist_dir}")
    L.append(f"   _💡 Histogram {hist_dir.split()[0]} = momentum {'building' if accel else 'fading'}_")

    # ── Bollinger Bands ───────────────────────────────
    bb_pct = data.get("bb_pct", 50.0)
    L.append("")
    L.append(f"📏 *Bollinger Bands (20, 2σ):*")
    L.append(f"   Upper: `{fmt(data['bb_upper'], t)}`")
    L.append(f"   Mid:   `{fmt(data['bb_mid'],   t)}`")
    L.append(f"   Lower: `{fmt(data['bb_lower'], t)}`")
    L.append(f"   Pos:   `{bb_pct:.0f}%` in band")
    L.append(f"   {_bb_note(price, data['bb_upper'], data['bb_lower'], data['bb_mid'])}")
    L.append(f"   _💡 >80% = near upper band; squeeze = breakout risk_")

    # ── Volume ────────────────────────────────────────
    vr = vol["volume_ratio"]
    if vr >= 2.0:   vol_lbl = "🔥 Very high — strong conviction"
    elif vr >= 1.5: vol_lbl = "⬆️ Above average — confirmed move"
    elif vr >= 0.8: vol_lbl = "➡️ Average — normal activity"
    else:           vol_lbl = "⬇️ Low — weak conviction"

    L.append("")
    L.append(f"📦 *Volume:*")
    L.append(f"   Today:  `{vol['last_volume']:,}`")
    L.append(f"   Avg 20: `{vol['avg_volume_20d']:,}`")
    L.append(f"   Ratio:  `{vr}x` — {vol_lbl}")
    L.append(f"   OBV:    `{vol['obv_trend']}`")
    L.append(f"   _💡 High volume = institutions active_")

    # ── Breakout / S&R ────────────────────────────────
    L.append("")
    L.append(f"🚨 *Breakout / Support & Resistance:*")
    L.append(f"   R: `{fmt(brk['resistance'], t)}`")
    L.append(f"   S: `{fmt(brk['support'],    t)}`")
    if brk["breakout_up"]:
        v_note = " + 🔥 volume spike" if brk["volume_surge"] else ""
        L.append(f"   🚀 *BREAKOUT UP!* Resistance cleared{v_note}")
    elif brk["breakout_down"]:
        v_note = " + 🔥 volume spike" if brk["volume_surge"] else ""
        L.append(f"   💥 *BREAKDOWN!* Support broken{v_note}")
    else:
        L.append(f"   ➡️ No active breakout — consolidating")
    L.append(f"   _💡 Breakout with volume = high probability move_")

    # ── Swing Setup ───────────────────────────────────
    d     = swing["direction"]
    conf  = swing["confidence"]
    bar   = "●" * (conf // 20) + "○" * (5 - conf // 20)
    rps   = abs(price - swing["stop_loss"])
    rr1   = round(abs(swing["target1"] - price) / rps, 1) if rps else 0
    rr2   = round(abs(swing["target2"] - price) / rps, 1) if rps else 0
    d_arr = "⬆️" if d == "LONG" else "⬇️"

    L.append("")
    L.append("━━━━━━━━━━━━━━━━━━━━")
    L.append(f"🏹 *Swing Setup: {d_arr} {d}*")
    L.append(f"   Confidence: `{conf}%` `[{bar}]`")
    L.append(f"   ATR (14):   `{fmt(swing['atr'], t)}`")
    L.append(f"")
    L.append(f"   📍 Entry: `{fmt(price,             t)}`")
    L.append(f"   🛡 Stop:  `{fmt(swing['stop_loss'],t)}`  (1.5× ATR)")
    L.append(f"   🎯 T1:    `{fmt(swing['target1'],  t)}`  R:R `{rr1}x`")
    L.append(f"   🎯 T2:    `{fmt(swing['target2'],  t)}`  R:R `{rr2}x`")
    L.append(f"   _💡 Only trade if R:R ≥ 2x. Always set your stop._")

    # ── Disclaimer ────────────────────────────────────
    L.append("")
    L.append("━━━━━━━━━━━━━━━━━━━━")
    L.append("⚠️ _Educational only. Not financial advice._")
    L.append("_Consult a SEBI-registered advisor before trading._")

    return "\n".join(L)
