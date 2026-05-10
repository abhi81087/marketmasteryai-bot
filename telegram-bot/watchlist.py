import json
import os

WATCHLIST_FILE = os.path.join(os.path.dirname(__file__), "watchlists.json")


def _load() -> dict:
    if not os.path.exists(WATCHLIST_FILE):
        return {}
    try:
        with open(WATCHLIST_FILE, "r") as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError):
        return {}


def _save(data: dict):
    with open(WATCHLIST_FILE, "w") as f:
        json.dump(data, f, indent=2)


def get_watchlist(user_id: int) -> list[str]:
    data = _load()
    return data.get(str(user_id), [])


def add_tickers(user_id: int, tickers: list[str]) -> tuple[list[str], list[str]]:
    data = _load()
    key = str(user_id)
    current = data.get(key, [])
    added = []
    already = []
    for t in tickers:
        t = t.upper().strip()
        if t in current:
            already.append(t)
        else:
            current.append(t)
            added.append(t)
    data[key] = current
    _save(data)
    return added, already


def remove_tickers(user_id: int, tickers: list[str]) -> tuple[list[str], list[str]]:
    data = _load()
    key = str(user_id)
    current = data.get(key, [])
    removed = []
    not_found = []
    for t in tickers:
        t = t.upper().strip()
        if t in current:
            current.remove(t)
            removed.append(t)
        else:
            not_found.append(t)
    data[key] = current
    _save(data)
    return removed, not_found


def clear_watchlist(user_id: int):
    data = _load()
    data[str(user_id)] = []
    _save(data)
