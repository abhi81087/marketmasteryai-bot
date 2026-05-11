"""
analysis.py — All technical indicators and signal generation.

Speed notes:
- stock.info is very slow (3-8s). Names are cached to name_cache.json.
- Default period is 1y (~252 bars) for reliable EMA200 computation.
- For quick scans (screeners), callers may pass period="6mo".
"""

import json
import math
import os

import numpy as np
import pandas as pd
import yfinance as yf

# ── Persistent name cache ─────────────────────────────────────────────────────
_CACHE_PATH = os.path.join(os.path.dirname(__file__), "name_cache.json")
_NAME_CACHE: dict[str, str] = {}


def _load_name_cache():
    global _NAME_CACHE
    try:
        if os.path.exists(_CACHE_PATH):
            with open(_CACHE_PATH) as f:
                _NAME_CACHE = json.load(f)
    except Exception:
        _NAME_CACHE = {}


def _save_name_cache():
    try:
        with open(_CACHE_PATH, "w") as f:
            json.dump(_NAME_CACHE, f)
    except Exception:
        pass


_load_name_cache()


def _get_name(ticker: str) -> str:
    if ticker in _NAME_CACHE:
        return _NAME_CACHE[ticker]
    try:
        info = yf.Ticker(ticker).info
        name = (
            info.get("shortName")
            or info.get("longName")
            or info.get("displayName")
            or ticker
        )
        # Trim excessively long names
        if len(name) > 40:
            name = name[:38] + "…"
    except Exception:
        name = ticker
    _NAME_CACHE[ticker] = name
    _save_name_cache()
    return name


# ── Safe float extraction ─────────────────────────────────────────────────────

def _safe(value) -> float:
    """Convert to Python float; return NaN on failure."""
    try:
        v = float(value)
        return v if math.isfinite(v) else float("nan")
    except (TypeError, ValueError):
        return float("nan")


def _safe_last(series: pd.Series) -> float:
    v = series.dropna()
    return _safe(v.iloc[-1]) if not v.empty else float("nan")


# ── Indicator computation ─────────────────────────────────────────────────────

def fetch_data(ticker: str, period: str = "1y") -> pd.DataFrame:
    df = yf.Ticker(ticker).history(period=period, auto_adjust=True)
    if df is None or df.empty:
        raise ValueError(
            f"No market data found for '{ticker}'.\n"
            "Tips:\n• NSE stocks: add .NS  (e.g. TCS.NS)\n"
            "• Nifty 50: ^NSEI  Bank Nifty: ^NSEBANK\n"
            "• BSE stocks: add .BO  (e.g. TCS.BO)"
        )
    if len(df) < 30:
        raise ValueError(
            f"Not enough historical data for '{ticker}' ({len(df)} bars). "
            "Try a more liquid stock or index."
        )
    # Ensure Close is a plain Series
    if isinstance(df["Close"], pd.DataFrame):
        df["Close"] = df["Close"].iloc[:, 0]
    return df


def compute_ema(series: pd.Series, span: int) -> pd.Series:
    return series.ewm(span=span, adjust=False).mean()


def compute_rsi(series: pd.Series, period: int = 14) -> pd.Series:
    delta    = series.diff()
    gain     = delta.clip(lower=0)
    loss     = (-delta).clip(lower=0)
    avg_gain = gain.ewm(com=period - 1, min_periods=period).mean()
    avg_loss = loss.ewm(com=period - 1, min_periods=period).mean()
    rs       = avg_gain / avg_loss.replace(0, float("nan"))
    return 100 - (100 / (1 + rs))


def compute_macd(series: pd.Series):
    ema12    = compute_ema(series, 12)
    ema26    = compute_ema(series, 26)
    macd     = ema12 - ema26
    signal   = compute_ema(macd, 9)
    hist     = macd - signal
    return macd, signal, hist


def compute_bollinger_bands(series: pd.Series, period: int = 20):
    sma   = series.rolling(window=period).mean()
    std   = series.rolling(window=period).std()
    upper = sma + 2 * std
    lower = sma - 2 * std
    return upper, sma, lower


def compute_atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    h  = df["High"]
    l  = df["Low"]
    pc = df["Close"].shift()
    tr = pd.concat([h - l, (h - pc).abs(), (l - pc).abs()], axis=1).max(axis=1)
    return tr.rolling(window=period).mean()


def detect_breakout(df: pd.DataFrame) -> dict:
    n          = min(20, len(df))
    recent     = df.tail(n)
    last_close = _safe(df["Close"].iloc[-1])
    prev_close = _safe(df["Close"].iloc[-2]) if len(df) >= 2 else last_close

    resistance = _safe(recent["High"].max())
    support    = _safe(recent["Low"].min())

    breakout_up   = bool(last_close > resistance and prev_close <= resistance)
    breakout_down = bool(last_close < support  and prev_close >= support)

    avg_vol = df["Volume"].tail(n).mean()
    last_vol = _safe(df["Volume"].iloc[-1])
    vol_surge = bool(last_vol > avg_vol * 1.5) if avg_vol > 0 else False

    return {
        "resistance":   round(resistance, 2),
        "support":      round(support, 2),
        "breakout_up":  breakout_up,
        "breakout_down": breakout_down,
        "volume_surge": vol_surge,
        "last_volume":  int(last_vol) if math.isfinite(last_vol) else 0,
        "avg_volume":   int(avg_vol)  if math.isfinite(avg_vol)  else 0,
    }


def volume_analysis(df: pd.DataFrame) -> dict:
    avg_vol  = df["Volume"].tail(20).mean()
    last_vol = _safe(df["Volume"].iloc[-1])
    vol_ratio = round(last_vol / avg_vol, 2) if avg_vol > 0 else 1.0

    obv       = (np.sign(df["Close"].diff()) * df["Volume"]).fillna(0).cumsum()
    obv_trend = "Rising" if _safe(obv.iloc[-1]) > _safe(obv.iloc[-5]) else "Falling"

    return {
        "last_volume":    int(last_vol) if math.isfinite(last_vol) else 0,
        "avg_volume_20d": int(avg_vol)  if math.isfinite(avg_vol)  else 0,
        "volume_ratio":   round(vol_ratio, 2),
        "obv_trend":      obv_trend,
    }


# ── Signal generation — 6-factor model ───────────────────────────────────────
# Each factor contributes exactly ±1 so the score is symmetric and bounded.
# Score range: −6 … +6
#   ≥ 4  → STRONG BUY   (≥ 5 of 6 factors bullish or 4 strongly aligned)
#   ≥ 2  → BUY
#   −1…1 → HOLD / NEUTRAL
#   ≤ −2 → SELL
#   ≤ −4 → STRONG SELL
#
# The EMA50 > EMA200 check is the macro trend filter.
# Without it aligned, STRONG BUY requires 5 of the remaining 5 — very hard.
# This significantly reduces false signals in bear markets.

def generate_signal(
    rsi: float,
    ema9: float, ema21: float, ema50: float, ema200: float,
    macd: float, macd_signal: float,
    close: float,
) -> dict:
    score   = 0
    reasons = []

    # 1. RSI zone (momentum oscillator)
    if rsi < 32:
        score += 1
        reasons.append("RSI oversold (<32) — potential bounce zone")
    elif rsi > 68:
        score -= 1
        reasons.append("RSI overbought (>68) — potential pullback zone")
    else:
        reasons.append(f"RSI neutral zone ({rsi:.0f}) — no extreme momentum")

    # 2. Short-term trend: EMA 9 vs EMA 21
    if ema9 > ema21:
        score += 1
        reasons.append("EMA9 > EMA21 — short-term bullish crossover")
    else:
        score -= 1
        reasons.append("EMA9 < EMA21 — short-term bearish crossover")

    # 3. MACD momentum
    if macd > macd_signal:
        score += 1
        reasons.append("MACD above signal line — bullish momentum")
    else:
        score -= 1
        reasons.append("MACD below signal line — bearish momentum")

    # 4. Price vs EMA21 (immediate price action)
    if close > ema21:
        score += 1
        reasons.append("Price above EMA21 — buyers in short-term control")
    else:
        score -= 1
        reasons.append("Price below EMA21 — sellers in short-term control")

    # 5. Price vs EMA50 (medium-term trend)
    if close > ema50:
        score += 1
        reasons.append("Price above EMA50 — medium-term uptrend intact")
    else:
        score -= 1
        reasons.append("Price below EMA50 — medium-term downtrend")

    # 6. EMA50 vs EMA200 (macro trend — golden/death cross region)
    if ema50 > ema200:
        score += 1
        reasons.append("EMA50 > EMA200 — long-term bull structure (golden cross zone)")
    else:
        score -= 1
        reasons.append("EMA50 < EMA200 — long-term bear structure (death cross zone)")

    # Derive action
    if score >= 4:
        action = "STRONG BUY"
    elif score >= 2:
        action = "BUY"
    elif score <= -4:
        action = "STRONG SELL"
    elif score <= -2:
        action = "SELL"
    else:
        action = "HOLD / NEUTRAL"

    bull_count = (6 + score) // 2  # how many of the 6 factors are bullish

    return {
        "action":       action,
        "score":        score,
        "reasons":      reasons,
        "bull_count":   bull_count,    # e.g. 5
        "total_factors": 6,
    }


# ── Swing trade setup — 5-factor direction model ──────────────────────────────

def swing_trade_setup(
    df: pd.DataFrame,
    rsi: float, ema9: float, ema21: float, ema50: float, ema200: float,
    macd: float, macd_signal: float,
) -> dict:
    close = _safe(df["Close"].iloc[-1])
    atr   = _safe_last(compute_atr(df))

    if not math.isfinite(atr) or atr <= 0:
        atr = close * 0.015  # fallback: 1.5% of price

    bull = 0
    bear = 0

    if rsi < 40:  bull += 1
    elif rsi > 60: bear += 1

    if ema9 > ema21:    bull += 1
    else:               bear += 1

    if macd > macd_signal: bull += 1
    else:                   bear += 1

    if close > ema21:   bull += 1
    else:               bear += 1

    if ema50 > ema200:  bull += 1
    else:               bear += 1

    direction  = "LONG" if bull >= bear else "SHORT"
    confidence = round(max(bull, bear) / 5 * 100)

    if direction == "LONG":
        stop_loss = round(close - 1.5 * atr, 2)
        target1   = round(close + 2.0 * atr, 2)
        target2   = round(close + 3.5 * atr, 2)
    else:
        stop_loss = round(close + 1.5 * atr, 2)
        target1   = round(close - 2.0 * atr, 2)
        target2   = round(close - 3.5 * atr, 2)

    return {
        "direction":  direction,
        "confidence": confidence,
        "stop_loss":  stop_loss,
        "target1":    target1,
        "target2":    target2,
        "atr":        round(atr, 2),
    }


# ── Main entry point ──────────────────────────────────────────────────────────

def analyze(ticker: str, period: str = "1y") -> dict:
    ticker = ticker.upper().strip()
    df     = fetch_data(ticker, period=period)

    close_s   = df["Close"]
    last_close = _safe(close_s.iloc[-1])
    prev_close = _safe(close_s.iloc[-2]) if len(df) >= 2 else last_close
    change_pct = round(((last_close - prev_close) / prev_close) * 100, 2) if prev_close else 0.0

    rsi   = round(_safe_last(compute_rsi(close_s)), 2)
    ema9  = round(_safe_last(compute_ema(close_s, 9)),   2)
    ema21 = round(_safe_last(compute_ema(close_s, 21)),  2)
    ema50 = round(_safe_last(compute_ema(close_s, 50)),  2)
    ema200 = round(_safe_last(compute_ema(close_s, 200)), 2)

    macd_s, signal_s, hist_s = compute_macd(close_s)
    macd      = round(_safe_last(macd_s),   4)
    macd_sig  = round(_safe_last(signal_s), 4)
    macd_hist = round(_safe_last(hist_s),   4)

    # MACD histogram direction (is momentum accelerating or decelerating?)
    hist_vals = hist_s.dropna()
    macd_hist_prev = round(_safe(hist_vals.iloc[-2]), 4) if len(hist_vals) >= 2 else macd_hist
    macd_accel = macd_hist > macd_hist_prev  # True = histogram growing (momentum strengthening)

    bb_upper_s, bb_mid_s, bb_lower_s = compute_bollinger_bands(close_s)
    bb_upper = round(_safe_last(bb_upper_s), 2)
    bb_mid   = round(_safe_last(bb_mid_s),   2)
    bb_lower = round(_safe_last(bb_lower_s), 2)

    # Bollinger Band position as a percentile (0 = at lower, 100 = at upper)
    bb_range = bb_upper - bb_lower
    bb_pct   = round((last_close - bb_lower) / bb_range * 100, 1) if bb_range > 0 else 50.0

    breakout = detect_breakout(df)
    volume   = volume_analysis(df)

    swing    = swing_trade_setup(df, rsi, ema9, ema21, ema50, ema200, macd, macd_sig)
    signal   = generate_signal(rsi, ema9, ema21, ema50, ema200, macd, macd_sig, last_close)

    name = _get_name(ticker)

    return {
        "ticker":      ticker,
        "name":        name,
        "last_close":  round(last_close, 2),
        "change_pct":  change_pct,
        "rsi":         rsi,
        "ema9":        ema9,
        "ema21":       ema21,
        "ema50":       ema50,
        "ema200":      ema200,
        "macd":        macd,
        "macd_signal": macd_sig,
        "macd_hist":   macd_hist,
        "macd_accel":  macd_accel,
        "bb_upper":    bb_upper,
        "bb_mid":      bb_mid,
        "bb_lower":    bb_lower,
        "bb_pct":      bb_pct,
        "breakout":    breakout,
        "volume":      volume,
        "swing":       swing,
        "signal":      signal,
    }
