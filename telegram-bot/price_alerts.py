import json
import os

PRICE_ALERTS_FILE = os.path.join(os.path.dirname(__file__), "price_alerts.json")


def _load() -> dict:
    if not os.path.exists(PRICE_ALERTS_FILE):
        return {}
    try:
        with open(PRICE_ALERTS_FILE, "r") as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError):
        return {}


def _save(data: dict):
    with open(PRICE_ALERTS_FILE, "w") as f:
        json.dump(data, f, indent=2)


def _next_id(alerts: list) -> int:
    return max((a["id"] for a in alerts), default=0) + 1


def add_price_alert(user_id: int, chat_id: int, ticker: str, condition: str, target: float) -> int:
    data = _load()
    key = str(user_id)
    alerts = data.get(key, [])
    alert_id = _next_id(alerts)
    alerts.append({
        "id": alert_id,
        "ticker": ticker.upper(),
        "condition": condition,
        "target": target,
        "chat_id": chat_id,
    })
    data[key] = alerts
    _save(data)
    return alert_id


def get_user_alerts(user_id: int) -> list:
    data = _load()
    return data.get(str(user_id), [])


def remove_price_alert(user_id: int, alert_id: int) -> bool:
    data = _load()
    key = str(user_id)
    alerts = data.get(key, [])
    new_alerts = [a for a in alerts if a["id"] != alert_id]
    if len(new_alerts) == len(alerts):
        return False
    data[key] = new_alerts
    _save(data)
    return True


def remove_triggered_alert(user_id: int, alert_id: int):
    remove_price_alert(user_id, alert_id)


def get_all_price_alerts() -> dict:
    return _load()
