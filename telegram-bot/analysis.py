import yfinance as yf
import pandas as pd
import numpy as np
from datetime import datetime, timedelta


def fetch_data(ticker: str, period: str = "6mo") -> pd.DataFrame:
    stock = yf.Ticker(ticker)
    df = stock.history(period=period)
    if df.empty:
        raise ValueError(f"No data found for ticker '{ticker}'. Please check the symbol.")
    return df


def compute_ema(series: pd.Series, span: int) -> pd.Series:
    return series.ewm(span=span, adjust=False).mean()


def compute_rsi(series: pd.Series, period: int = 14) -> pd.Series:
    delta = series.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(com=period - 1, min_periods=period).mean()
    avg_loss = loss.ewm(com=period - 1, min_periods=period).mean()
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


def compute_macd(series: pd.Series):
    ema12 = compute_ema(series, 12)
    ema26 = compute_ema(series, 26)
    macd_line = ema12 - ema26
    signal_line = compute_ema(macd_line, 9)
    histogram = macd_line - signal_line
    return macd_line, signal_line, histogram


def compute_bollinger_bands(series: pd.Series, period: int = 20):
    sma = series.rolling(window=period).mean()
    std = series.rolling(window=period).std()
    upper = sma + (2 * std)
    lower = sma - (2 * std)
    return upper, sma, lower


def compute_atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    high_low = df["High"] - df["Low"]
    high_close = (df["High"] - df["Close"].shift()).abs()
    low_close = (df["Low"] - df["Close"].shift()).abs()
    true_range = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
    return true_range.rolling(window=period).mean()


def detect_breakout(df: pd.DataFrame) -> dict:
    recent = df.tail(20)
    resistance = recent["High"].max()
    support = recent["Low"].min()
    last_close = df["Close"].iloc[-1]
    prev_close = df["Close"].iloc[-2]

    breakout_up = last_close > resistance and prev_close <= resistance
    breakout_down = last_close < support and prev_close >= support

    avg_vol = df["Volume"].tail(20).mean()
    last_vol = df["Volume"].iloc[-1]
    vol_surge = last_vol > avg_vol * 1.5

    return {
        "resistance": round(resistance, 2),
        "support": round(support, 2),
        "breakout_up": breakout_up,
        "breakout_down": breakout_down,
        "volume_surge": vol_surge,
        "last_volume": int(last_vol),
        "avg_volume": int(avg_vol),
    }


def volume_analysis(df: pd.DataFrame) -> dict:
    avg_vol = df["Volume"].tail(20).mean()
    last_vol = df["Volume"].iloc[-1]
    vol_ratio = last_vol / avg_vol if avg_vol > 0 else 1.0

    obv = (np.sign(df["Close"].diff()) * df["Volume"]).fillna(0).cumsum()
    obv_trend = "Rising" if obv.iloc[-1] > obv.iloc[-5] else "Falling"

    return {
        "last_volume": int(last_vol),
        "avg_volume_20d": int(avg_vol),
        "volume_ratio": round(vol_ratio, 2),
        "obv_trend": obv_trend,
    }


def swing_trade_setup(df: pd.DataFrame, rsi: float, ema9: float, ema21: float, macd: float, signal: float) -> dict:
    close = df["Close"].iloc[-1]
    atr = compute_atr(df).iloc[-1]

    bullish_signals = 0
    bearish_signals = 0

    if rsi < 40:
        bullish_signals += 1
    elif rsi > 60:
        bearish_signals += 1

    if ema9 > ema21:
        bullish_signals += 1
    else:
        bearish_signals += 1

    if macd > signal:
        bullish_signals += 1
    else:
        bearish_signals += 1

    if close > ema21:
        bullish_signals += 1
    else:
        bearish_signals += 1

    direction = "LONG" if bullish_signals > bearish_signals else "SHORT"
    confidence = max(bullish_signals, bearish_signals) / 4

    stop_loss = round(close - 1.5 * atr, 2) if direction == "LONG" else round(close + 1.5 * atr, 2)
    target1 = round(close + 2 * atr, 2) if direction == "LONG" else round(close - 2 * atr, 2)
    target2 = round(close + 3.5 * atr, 2) if direction == "LONG" else round(close - 3.5 * atr, 2)

    return {
        "direction": direction,
        "confidence": round(confidence * 100),
        "stop_loss": stop_loss,
        "target1": target1,
        "target2": target2,
        "atr": round(atr, 2),
    }


def generate_signal(rsi: float, ema9: float, ema21: float, macd: float, signal: float, close: float) -> dict:
    score = 0
    reasons = []

    if rsi < 30:
        score += 2
        reasons.append("RSI oversold (<30)")
    elif rsi < 45:
        score += 1
        reasons.append("RSI below midline")
    elif rsi > 70:
        score -= 2
        reasons.append("RSI overbought (>70)")
    elif rsi > 55:
        score -= 1
        reasons.append("RSI above midline")

    if ema9 > ema21:
        score += 1
        reasons.append("EMA9 > EMA21 (bullish cross)")
    else:
        score -= 1
        reasons.append("EMA9 < EMA21 (bearish cross)")

    if macd > signal:
        score += 1
        reasons.append("MACD above signal")
    else:
        score -= 1
        reasons.append("MACD below signal")

    if close > ema21:
        score += 1
        reasons.append("Price above EMA21")
    else:
        score -= 1
        reasons.append("Price below EMA21")

    if score >= 3:
        action = "STRONG BUY"
    elif score >= 1:
        action = "BUY"
    elif score <= -3:
        action = "STRONG SELL"
    elif score <= -1:
        action = "SELL"
    else:
        action = "HOLD / NEUTRAL"

    return {"action": action, "score": score, "reasons": reasons}


def analyze(ticker: str) -> dict:
    ticker = ticker.upper().strip()
    df = fetch_data(ticker)

    close = df["Close"]
    last_close = close.iloc[-1]
    prev_close = close.iloc[-2]
    change_pct = ((last_close - prev_close) / prev_close) * 100

    rsi = compute_rsi(close).iloc[-1]
    ema9 = compute_ema(close, 9).iloc[-1]
    ema21 = compute_ema(close, 21).iloc[-1]
    ema50 = compute_ema(close, 50).iloc[-1]
    ema200 = compute_ema(close, 200).iloc[-1]

    macd_line, signal_line, histogram = compute_macd(close)
    macd = macd_line.iloc[-1]
    signal = signal_line.iloc[-1]
    hist = histogram.iloc[-1]

    bb_upper, bb_mid, bb_lower = compute_bollinger_bands(close)

    breakout = detect_breakout(df)
    volume = volume_analysis(df)
    swing = swing_trade_setup(df, rsi, ema9, ema21, macd, signal)
    buy_sell = generate_signal(rsi, ema9, ema21, macd, signal, last_close)

    stock = yf.Ticker(ticker)
    info = stock.info
    name = info.get("shortName") or info.get("longName") or ticker

    return {
        "ticker": ticker,
        "name": name,
        "last_close": round(last_close, 2),
        "change_pct": round(change_pct, 2),
        "rsi": round(rsi, 2),
        "ema9": round(ema9, 2),
        "ema21": round(ema21, 2),
        "ema50": round(ema50, 2),
        "ema200": round(ema200, 2),
        "macd": round(macd, 4),
        "macd_signal": round(signal, 4),
        "macd_hist": round(hist, 4),
        "bb_upper": round(bb_upper.iloc[-1], 2),
        "bb_mid": round(bb_mid.iloc[-1], 2),
        "bb_lower": round(bb_lower.iloc[-1], 2),
        "breakout": breakout,
        "volume": volume,
        "swing": swing,
        "signal": buy_sell,
    }
