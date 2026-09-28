#!/usr/bin/env python3
"""Apply a Whoop recovery offset to saved Eight Sleep Autopilot levels.

Does not turn the Pod on. If a write changes power state, the previous state is restored.
"""

import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import requests

TOKEN_URL = "https://api.prod.whoop.com/oauth/oauth2/token"
WHOOP_API = "https://api.prod.whoop.com/developer/v2"
AUTH_URL = "https://auth-api.8slp.net/v1/tokens"
CLIENT_API = "https://client-api.8slp.net/v1"
APP_API = "https://app-api.8slp.net/v1"
CLIENT_ID = "0894c7f33bb94800a03f1f4df13a4f38"
CLIENT_SECRET = "f0954a3ed5763ba3d06834c73731a32f15f168f47d4f164751275def86db0c76"
ROOT = Path("/workspace/.podshift")
WHOOP_SESSION = ROOT / "whoop_session.json"
EIGHT_SESSION = ROOT / "eight_session.json"
BASELINE_PATH = ROOT / "baseline.json"
LOG_PATH = ROOT / "last_run.json"
TZ = ZoneInfo("America/Chicago")
STAGES = ("bedTimeLevel", "initialSleepLevel", "finalSleepLevel")


def clamp(level: int) -> int:
    return max(-100, min(100, level))


def offset_for(score: float) -> int:
    if score >= 67:
        return 0
    if score >= 34:
        return -5
    return -10


def save_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload))
    path.chmod(0o600)


def whoop_session() -> dict:
    if not WHOOP_SESSION.exists():
        raise SystemExit("no Whoop session")
    return json.loads(WHOOP_SESSION.read_text())


def refresh_whoop(session: dict) -> dict:
    response = requests.post(
        TOKEN_URL,
        data={
            "grant_type": "refresh_token",
            "refresh_token": session["refresh_token"],
            "client_id": os.environ["WHOOP_CLIENT_ID"],
            "client_secret": os.environ["WHOOP_CLIENT_SECRET"],
            "scope": "offline",
        },
        timeout=30,
    )
    if response.status_code != 200:
        raise SystemExit(f"whoop refresh failed: {response.status_code}")
    updated = response.json()
    updated["obtained_at"] = int(time.time())
    save_json(WHOOP_SESSION, updated)
    return updated


def whoop_token() -> str:
    session = whoop_session()
    obtained = session.get("obtained_at", 0)
    expires = session.get("expires_in", 0)
    if not obtained or time.time() > obtained + expires - 60:
        session = refresh_whoop(session)
    return session["access_token"]


def whoop_get(path: str, token: str, params: dict | None = None) -> requests.Response:
    return requests.get(
        f"{WHOOP_API}{path}",
        headers={"Authorization": f"Bearer {token}"},
        params=params,
        timeout=30,
    )


def latest_recovery() -> dict:
    token = whoop_token()
    cycles = whoop_get("/cycle", token, {"limit": 1})
    if cycles.status_code == 401:
        token = refresh_whoop(whoop_session())["access_token"]
        cycles = whoop_get("/cycle", token, {"limit": 1})
    if cycles.status_code != 200:
        raise SystemExit(f"whoop cycle failed: {cycles.status_code}")
    records = cycles.json().get("records") or []
    if not records:
        return {"status": "no_cycle"}
    cycle_id = records[0]["id"]
    recovery = whoop_get(f"/cycle/{cycle_id}/recovery", token)
    if recovery.status_code == 404:
        return {"status": "no_recovery", "cycle_id": cycle_id}
    if recovery.status_code != 200:
        raise SystemExit(f"whoop recovery failed: {recovery.status_code}")
    body = recovery.json()
    score = body.get("score") or {}
    return {
        "status": "ok",
        "cycle_id": cycle_id,
        "score_state": body.get("score_state"),
        "recovery_score": score.get("recovery_score"),
        "user_calibrating": score.get("user_calibrating"),
        "hrv_rmssd_milli": score.get("hrv_rmssd_milli"),
        "resting_heart_rate": score.get("resting_heart_rate"),
    }


def eight_headers(token: str) -> dict:
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
        "Content-Type": "application/json",
        "User-Agent": "okhttp/4.9.3",
    }


def eight_login() -> str:
    response = requests.post(
        AUTH_URL,
        data={
            "grant_type": "password",
            "username": os.environ["EIGHT_SLEEP_EMAIL"],
            "password": os.environ["EIGHT_SLEEP_PASSWORD"],
            "client_id": CLIENT_ID,
            "client_secret": CLIENT_SECRET,
        },
        headers={"Content-Type": "application/x-www-form-urlencoded", "User-Agent": "okhttp/4.9.3"},
        timeout=30,
    )
    if response.status_code != 200:
        raise SystemExit(f"eight login failed: {response.status_code}")
    payload = response.json()
    save_json(
        EIGHT_SESSION,
        {
            "access_token": payload["access_token"],
            "refresh_token": payload.get("refresh_token"),
            "expires_in": payload.get("expires_in"),
            "userId": payload.get("userId"),
            "obtained_at": int(time.time()),
        },
    )
    return payload["access_token"]


def eight_token() -> str:
    if EIGHT_SESSION.exists():
        session = json.loads(EIGHT_SESSION.read_text())
        if session.get("access_token"):
            return session["access_token"]
    return eight_login()


def eight_get_temperature(token: str, user_id: str) -> tuple[str, dict]:
    response = requests.get(
        f"{APP_API}/users/{user_id}/temperature",
        headers=eight_headers(token),
        timeout=30,
    )
    if response.status_code == 401:
        token = eight_login()
        response = requests.get(
            f"{APP_API}/users/{user_id}/temperature",
            headers=eight_headers(token),
            timeout=30,
        )
    if response.status_code != 200:
        raise SystemExit(f"eight temperature read failed: {response.status_code}")
    return token, response.json()


def user_id_for(token: str) -> tuple[str, str]:
    session = json.loads(EIGHT_SESSION.read_text()) if EIGHT_SESSION.exists() else {}
    user_id = session.get("userId")
    if user_id:
        return token, user_id
    me = requests.get(f"{CLIENT_API}/users/me", headers=eight_headers(token), timeout=30)
    if me.status_code == 401:
        token = eight_login()
        me = requests.get(f"{CLIENT_API}/users/me", headers=eight_headers(token), timeout=30)
    if me.status_code != 200:
        raise SystemExit(f"eight user lookup failed: {me.status_code}")
    user_id = (me.json().get("user") or {}).get("userId")
    if not user_id:
        raise SystemExit("eight user id missing")
    return token, user_id


def power_state(body: dict) -> str | None:
    state = body.get("currentState") or {}
    if isinstance(state, dict):
        return state.get("type")
    return None


def set_power(token: str, user_id: str, state: str) -> None:
    response = requests.put(
        f"{APP_API}/users/{user_id}/temperature/pod",
        params={"ignoreDeviceErrors": "true"},
        headers=eight_headers(token),
        json={"currentState": {"type": state}},
        timeout=30,
    )
    if response.status_code >= 300:
        raise SystemExit(f"eight power restore failed: {response.status_code}")


def write_smart(token: str, user_id: str, levels: dict) -> None:
    response = requests.put(
        f"{APP_API}/users/{user_id}/temperature/pod",
        params={"ignoreDeviceErrors": "true"},
        headers=eight_headers(token),
        json={"smart": {stage: levels[stage] for stage in STAGES}},
        timeout=30,
    )
    if response.status_code >= 300:
        raise SystemExit(f"eight smart update failed: {response.status_code} {response.text[:200]}")


def target_levels(recovery: dict) -> tuple[dict, int] | None:
    if recovery.get("status") != "ok":
        return None
    if recovery.get("score_state") != "SCORED" or recovery.get("user_calibrating"):
        return None
    score = recovery.get("recovery_score")
    if score is None:
        return None
    baseline = json.loads(BASELINE_PATH.read_text())
    delta = offset_for(float(score))
    levels = {stage: clamp(int(baseline[stage]) + delta) for stage in STAGES}
    return levels, delta


def main() -> None:
    dry_run = "--dry-run" in sys.argv
    now = datetime.now(TZ).isoformat(timespec="seconds")
    recovery = latest_recovery()
    planned = target_levels(recovery)
    token = eight_token()
    token, user_id = user_id_for(token)
    token, before = eight_get_temperature(token, user_id)
    before_power = power_state(before)
    result = {
        "at": now,
        "dry_run": dry_run,
        "recovery_score": recovery.get("recovery_score"),
        "score_state": recovery.get("score_state"),
        "before_power": before_power,
        "before_smart": before.get("smart"),
        "applied": False,
    }
    if planned is None:
        result["skipped"] = recovery.get("status") or "unscored"
        save_json(LOG_PATH, result)
        print(json.dumps(result))
        return
    levels, delta = planned
    result["offset"] = delta
    result["target"] = levels
    if dry_run:
        save_json(LOG_PATH, result)
        print(json.dumps(result))
        return
    write_smart(token, user_id, levels)
    token, after = eight_get_temperature(token, user_id)
    after_power = power_state(after)
    if before_power and after_power and after_power != before_power:
        set_power(token, user_id, before_power)
        token, after = eight_get_temperature(token, user_id)
        result["power_restored"] = True
    result["applied"] = True
    result["after_power"] = power_state(after)
    result["after_smart"] = after.get("smart")
    save_json(LOG_PATH, result)
    print(json.dumps(result))


if __name__ == "__main__":
    main()
