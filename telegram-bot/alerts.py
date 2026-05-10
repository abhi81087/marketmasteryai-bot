import json
import os

ALERTS_FILE = os.path.join(os.path.dirname(__file__), "alerts.json")


def _load() -> dict:
    if not os.path.exists(ALERTS_FILE):
        return {}
    try:
        with open(ALERTS_FILE, "r") as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError):
        return {}


def _save(data: dict):
    with open(ALERTS_FILE, "w") as f:
        json.dump(data, f, indent=2)


def set_alert(user_id: int, chat_id: int, hour: int, minute: int):
    data = _load()
    data[str(user_id)] = {"chat_id": chat_id, "hour": hour, "minute": minute}
    _save(data)


def remove_alert(user_id: int) -> bool:
    data = _load()
    key = str(user_id)
    if key in data:
        del data[key]
        _save(data)
        return True
    return False


def get_alert(user_id: int) -> dict | None:
    data = _load()
    return data.get(str(user_id))


def get_all_alerts() -> dict:
    return _load()
