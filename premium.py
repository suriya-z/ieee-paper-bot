"""
Premium key management for the IEEE Paper Generator Bot.

Keys format: SURIYA-XXXXXXXXXX (alphanumeric suffix)
Storage: keys.json (generated at runtime, gitignored)
"""

import json
import os
import random
import string

KEYS_FILE = os.path.join(os.path.dirname(__file__), "keys.json")
KEY_PREFIX = "SURIYA"
SUFFIX_LEN = 10
FREE_PAGE_LIMIT = 4


# ─── Persistence ──────────────────────────────────────────────────────────────

def _load() -> dict:
    if os.path.exists(KEYS_FILE):
        try:
            with open(KEYS_FILE, "r") as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def _save(data: dict) -> None:
    with open(KEYS_FILE, "w") as f:
        json.dump(data, f, indent=2)


# ─── Key operations ───────────────────────────────────────────────────────────

def generate_key() -> str:
    """Generate a new unique SURIYA-XXXXXXXXXX premium key."""
    data = _load()
    while True:
        suffix = "".join(random.choices(string.ascii_uppercase + string.digits, k=SUFFIX_LEN))
        key = f"{KEY_PREFIX}-{suffix}"
        if key not in data:
            data[key] = {"used": False, "used_by": None}
            _save(data)
            return key


def redeem_key(key: str, user_id: int) -> tuple[bool, str]:
    """
    Attempt to redeem a key for a user.
    Returns (success: bool, message: str).
    """
    data = _load()
    key = key.strip().upper()

    if key not in data:
        return False, "❌ Invalid key. Please check and try again."

    entry = data[key]
    if entry["used"]:
        if entry["used_by"] == user_id:
            return False, "⚠️ You already redeemed this key."
        return False, "❌ This key has already been used."

    data[key]["used"] = True
    data[key]["used_by"] = user_id
    _save(data)
    return True, "✅ Premium activated! You can now generate up to 20 pages."


def is_premium(user_id: int) -> bool:
    """Check if a user has redeemed any valid premium key."""
    data = _load()
    return any(
        v["used"] and v["used_by"] == user_id
        for v in data.values()
    )


def list_keys() -> list[dict]:
    """Return all keys with their status."""
    data = _load()
    return [
        {"key": k, "used": v["used"], "used_by": v["used_by"]}
        for k, v in data.items()
    ]


def delete_key(key: str) -> bool:
    """Delete a key (owner only). Returns True if found and deleted."""
    data = _load()
    key = key.strip().upper()
    if key in data:
        del data[key]
        _save(data)
        return True
    return False
