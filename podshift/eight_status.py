#!/usr/bin/env python3
"""Read-only Eight Sleep login and Pod status. Does not change temperature."""

import json
import os
from pathlib import Path

import requests

from home import home

AUTH_URL = "https://auth-api.8slp.net/v1/tokens"
CLIENT_API = "https://client-api.8slp.net/v1"
APP_API = "https://app-api.8slp.net/v1"

def session_path() -> Path:
    return home() / "eight_session.json"


def save(payload: dict) -> None:
    session_path().parent.mkdir(parents=True, exist_ok=True)
    session_path().write_text(json.dumps(payload))
    session_path().chmod(0o600)


def login() -> dict:
    response = requests.post(
        AUTH_URL,
        data={
            "grant_type": "password",
            "username": os.environ["EIGHT_SLEEP_EMAIL"],
            "password": os.environ["EIGHT_SLEEP_PASSWORD"],
            "client_id": os.environ["EIGHT_SLEEP_CLIENT_ID"],
            "client_secret": os.environ["EIGHT_SLEEP_CLIENT_SECRET"],
        },
        headers={"Content-Type": "application/x-www-form-urlencoded", "User-Agent": "okhttp/4.9.3"},
        timeout=30,
    )
    if response.status_code != 200:
        raise SystemExit(f"eight login failed: {response.status_code}")
    payload = response.json()
    if not payload.get("access_token"):
        raise SystemExit("eight login returned no access token")
    save(
        {
            "access_token": payload["access_token"],
            "refresh_token": payload.get("refresh_token"),
            "expires_in": payload.get("expires_in"),
            "userId": payload.get("userId"),
        }
    )
    return payload


def get(url: str, token: str) -> requests.Response:
    return requests.get(
        url,
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
            "User-Agent": "okhttp/4.9.3",
        },
        timeout=30,
    )


def main() -> None:
    payload = login()
    token = payload["access_token"]
    user_id = payload.get("userId")
    me = get(f"{CLIENT_API}/users/me", token)
    if me.status_code != 200:
        raise SystemExit(f"users/me failed: {me.status_code}")
    user = me.json().get("user") or {}
    user_id = user_id or user.get("userId")
    temp = get(f"{APP_API}/users/{user_id}/temperature", token)
    if temp.status_code != 200:
        raise SystemExit(f"temperature failed: {temp.status_code}")
    body = temp.json()
    smart = body.get("smart") or {}
    print(
        json.dumps(
            {
                "user_id": user_id,
                "device_id": (user.get("currentDevice") or {}).get("id"),
                "devices": user.get("devices"),
                "current_level": body.get("currentLevel"),
                "current_state": (body.get("currentState") or {}).get("type"),
                "smart_keys": sorted(smart.keys()) if isinstance(smart, dict) else None,
                "smart": smart,
            },
            default=str,
        )
    )


if __name__ == "__main__":
    main()
