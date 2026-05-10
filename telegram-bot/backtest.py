import yfinance as yf
import pandas as pd


def run_backtest(ticker: str, period: str = "1y") -> dict | None:
    df = yf.download(ticker, period=period, interval="1d", progress=False, auto_adjust=True)
    if df is None or df.empty or len(df) < 30:
        return None

    close = df["Close"].squeeze()
    ema9  = close.ewm(span=9,  adjust=False).mean()
    ema21 = close.ewm(span=21, adjust=False).mean()

    trades     = []
    in_trade   = False
    entry_price = None
    entry_date  = None

    for i in range(1, len(close)):
        curr_above = ema9.iloc[i]  > ema21.iloc[i]
        prev_above = ema9.iloc[i-1] > ema21.iloc[i-1]
        price = float(close.iloc[i])
        date  = df.index[i]

        if not in_trade and curr_above and not prev_above:
            in_trade    = True
            entry_price = price
            entry_date  = date

        elif in_trade and not curr_above and prev_above:
            pnl_pct = (price - entry_price) / entry_price * 100
            trades.append({
                "entry_date": entry_date.strftime("%d %b %y"),
                "exit_date":  date.strftime("%d %b %y"),
                "entry":      round(entry_price, 2),
                "exit":       round(price, 2),
                "pnl_pct":    round(pnl_pct, 2),
                "won":        pnl_pct > 0,
                "open":       False,
            })
            in_trade = False

    # Close any open trade at last bar
    if in_trade:
        last_price = float(close.iloc[-1])
        last_date  = df.index[-1].strftime("%d %b %y")
        pnl_pct    = (last_price - entry_price) / entry_price * 100
        trades.append({
            "entry_date": entry_date.strftime("%d %b %y"),
            "exit_date":  f"{last_date} (open)",
            "entry":      round(entry_price, 2),
            "exit":       round(last_price, 2),
            "pnl_pct":    round(pnl_pct, 2),
            "won":        pnl_pct > 0,
            "open":       True,
        })

    # Buy-and-hold return for the same period
    buy_hold = round(
        (float(close.iloc[-1]) - float(close.iloc[0])) / float(close.iloc[0]) * 100, 2
    )

    if not trades:
        return {
            "ticker":       ticker.upper(),
            "period":       period,
            "trades":       [],
            "total":        0,
            "wins":         0,
            "losses":       0,
            "win_rate":     0.0,
            "total_return": 0.0,
            "buy_hold":     buy_hold,
            "avg_win":      0.0,
            "avg_loss":     0.0,
            "best":         None,
            "worst":        None,
            "sparkline":    "",
            "max_drawdown": 0.0,
        }

    wins   = [t for t in trades if t["won"]]
    losses = [t for t in trades if not t["won"]]

    # Compound return (skip still-open trade to keep clean)
    compound = 1.0
    for t in trades:
        if not t.get("open"):
            compound *= 1 + t["pnl_pct"] / 100
    total_return = round((compound - 1) * 100, 2)

    avg_win  = round(sum(t["pnl_pct"] for t in wins)   / len(wins),   2) if wins   else 0.0
    avg_loss = round(sum(t["pnl_pct"] for t in losses) / len(losses), 2) if losses else 0.0

    profit_factor = (
        round(sum(t["pnl_pct"] for t in wins) / abs(sum(t["pnl_pct"] for t in losses)), 2)
        if losses and sum(t["pnl_pct"] for t in losses) != 0
        else float("inf")
    )

    best  = max(trades, key=lambda t: t["pnl_pct"])
    worst = min(trades, key=lambda t: t["pnl_pct"])

    # Equity sparkline (cumulative return points)
    cumulative = []
    running = 1.0
    for t in trades:
        running *= 1 + t["pnl_pct"] / 100
        cumulative.append(running)

    BLOCKS = "▁▂▃▄▅▆▇█"
    mn, mx = min(cumulative), max(cumulative)
    span   = mx - mn if mx != mn else 1
    sparkline = "".join(BLOCKS[min(7, int((v - mn) / span * 7))] for v in cumulative)

    # Max drawdown on the equity curve
    peak   = cumulative[0]
    max_dd = 0.0
    for v in cumulative:
        peak   = max(peak, v)
        max_dd = max(max_dd, (peak - v) / peak * 100)

    return {
        "ticker":         ticker.upper(),
        "period":         period,
        "trades":         trades,
        "total":          len(trades),
        "wins":           len(wins),
        "losses":         len(losses),
        "win_rate":       round(len(wins) / len(trades) * 100, 1),
        "total_return":   total_return,
        "buy_hold":       buy_hold,
        "avg_win":        avg_win,
        "avg_loss":       avg_loss,
        "profit_factor":  profit_factor,
        "best":           best,
        "worst":          worst,
        "sparkline":      sparkline,
        "max_drawdown":   round(max_dd, 2),
    }
