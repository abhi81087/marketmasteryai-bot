import json
import os
from datetime import datetime, timezone

JOURNAL_FILE = os.path.join(os.path.dirname(__file__), "journal.json")


def _load() -> dict:
    if not os.path.exists(JOURNAL_FILE):
        return {}
    try:
        with open(JOURNAL_FILE, "r") as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError):
        return {}


def _save(data: dict):
    with open(JOURNAL_FILE, "w") as f:
        json.dump(data, f, indent=2)


def _next_id(trades: list) -> int:
    return max((t["id"] for t in trades), default=0) + 1


def add_trade(user_id: int, ticker: str, direction: str, entry: float,
              exit_price: float, shares: float) -> dict:
    data = _load()
    key = str(user_id)
    trades = data.get(key, [])

    pnl_per_share = (exit_price - entry) if direction == "LONG" else (entry - exit_price)
    pnl = round(pnl_per_share * shares, 2)
    pnl_pct = round((pnl_per_share / entry) * 100, 2)

    trade = {
        "id": _next_id(trades),
        "ticker": ticker.upper(),
        "direction": direction.upper(),
        "entry": round(entry, 2),
        "exit": round(exit_price, 2),
        "shares": shares,
        "pnl": pnl,
        "pnl_pct": pnl_pct,
        "date": datetime.now(timezone.utc).strftime("%d %b %Y"),
        "won": pnl > 0,
    }
    trades.append(trade)
    data[key] = trades
    _save(data)
    return trade


def get_trades(user_id: int) -> list:
    data = _load()
    return data.get(str(user_id), [])


def delete_trade(user_id: int, trade_id: int) -> bool:
    data = _load()
    key = str(user_id)
    trades = data.get(key, [])
    new_trades = [t for t in trades if t["id"] != trade_id]
    if len(new_trades) == len(trades):
        return False
    data[key] = new_trades
    _save(data)
    return True


def get_pnl_stats(user_id: int) -> dict:
    trades = get_trades(user_id)
    if not trades:
        return None

    total_pnl = round(sum(t["pnl"] for t in trades), 2)
    wins = [t for t in trades if t["won"]]
    losses = [t for t in trades if not t["won"]]
    win_rate = round(len(wins) / len(trades) * 100, 1)

    avg_win = round(sum(t["pnl"] for t in wins) / len(wins), 2) if wins else 0
    avg_loss = round(sum(t["pnl"] for t in losses) / len(losses), 2) if losses else 0
    best = max(trades, key=lambda t: t["pnl"])
    worst = min(trades, key=lambda t: t["pnl"])
    profit_factor = round(
        sum(t["pnl"] for t in wins) / abs(sum(t["pnl"] for t in losses)), 2
    ) if losses and sum(t["pnl"] for t in losses) != 0 else float("inf")

    return {
        "total": len(trades),
        "wins": len(wins),
        "losses": len(losses),
        "win_rate": win_rate,
        "total_pnl": total_pnl,
        "avg_win": avg_win,
        "avg_loss": avg_loss,
        "best": best,
        "worst": worst,
        "profit_factor": profit_factor,
    }
