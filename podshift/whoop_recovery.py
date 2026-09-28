#!/usr/bin/env python3
"""Print the latest Whoop recovery score. Refreshes the access token if needed."""

import json
import os
import time
from pathlib import Path

import requests

from home import home

TOKEN_URL = "https://api.prod.whoop.com/oauth/oauth2/token"
API = "https://api.prod.whoop.com/developer/v2"
def session_path() -> Path:
    return home() / "whoop_session.json"


def load() -> dict:
    if not session_path().exists():
        raise SystemExit("no Whoop session; run whoop_auth.py first")
    return json.loads(session_path().read_text())


def save(payload: dict) -> None:
    session_path().write_text(json.dumps(payload))
    session_path().chmod(0o600)


def refresh(session: dict) -> dict:
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
        raise SystemExit(f"refresh failed: {response.status_code}")
    updated = response.json()
    updated["obtained_at"] = int(time.time())
    save(updated)
    return updated


def token(session: dict) -> str:
    obtained = session.get("obtained_at", 0)
    expires = session.get("expires_in", 0)
    if obtained and time.time() > obtained + expires - 60 and session.get("refresh_token"):
        session = refresh(session)
    return session["access_token"]


def get(path: str, access: str, params: dict | None = None) -> requests.Response:
    return requests.get(
        f"{API}{path}",
        headers={"Authorization": f"Bearer {access}"},
        params=params,
        timeout=30,
    )


def main() -> None:
    session = load()
    if "obtained_at" not in session:
        session["obtained_at"] = int(time.time())
        save(session)
    access = token(session)
    cycles = get("/cycle", access, {"limit": 1})
    if cycles.status_code == 401 and session.get("refresh_token"):
        access = token(refresh(load()))
        cycles = get("/cycle", access, {"limit": 1})
    if cycles.status_code != 200:
        raise SystemExit(f"cycle lookup failed: {cycles.status_code} {cycles.text[:200]}")
    records = cycles.json().get("records") or []
    if not records:
        raise SystemExit("no Whoop cycle yet")
    cycle_id = records[0]["id"]
    recovery = get(f"/cycle/{cycle_id}/recovery", access)
    if recovery.status_code == 404:
        print(json.dumps({"cycle_id": cycle_id, "recovery": None}))
        return
    if recovery.status_code != 200:
        raise SystemExit(f"recovery lookup failed: {recovery.status_code} {recovery.text[:200]}")
    body = recovery.json()
    score = body.get("score") or {}
    print(
        json.dumps(
            {
                "cycle_id": cycle_id,
                "score_state": body.get("score_state"),
                "recovery_score": score.get("recovery_score"),
                "hrv_rmssd_milli": score.get("hrv_rmssd_milli"),
                "resting_heart_rate": score.get("resting_heart_rate"),
                "user_calibrating": score.get("user_calibrating"),
            }
        )
    )


if __name__ == "__main__":
    main()
