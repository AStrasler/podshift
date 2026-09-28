#!/usr/bin/env python3
"""One-time Whoop OAuth for Podshift. Tokens stay on disk; never printed."""

import argparse
import json
import os
import threading
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import requests

from home import home

AUTH_URL = "https://api.prod.whoop.com/oauth/oauth2/auth"
TOKEN_URL = "https://api.prod.whoop.com/oauth/oauth2/token"
def redirect_uri() -> str:
    return os.environ.get("WHOOP_REDIRECT_URI", "http://localhost:8787/callback")
STATE = "podshift"
SCOPES = " ".join(
    [
        "read:recovery",
        "read:cycles",
        "read:sleep",
        "read:workout",
        "read:profile",
        "read:body_measurement",
        "offline",
    ]
)
def session_path() -> Path:
    return home() / "whoop_session.json"


def url_path() -> Path:
    return home() / "authorize_url.txt"


def session_dir() -> None:
    session_path().parent.mkdir(parents=True, exist_ok=True)


def authorize_url() -> str:
    query = urllib.parse.urlencode(
        {
            "client_id": os.environ["WHOOP_CLIENT_ID"],
            "redirect_uri": redirect_uri(),
            "response_type": "code",
            "scope": SCOPES,
            "state": STATE,
        }
    )
    return f"{AUTH_URL}?{query}"


def exchange(code: str) -> dict:
    response = requests.post(
        TOKEN_URL,
        data={
            "grant_type": "authorization_code",
            "code": code,
            "client_id": os.environ["WHOOP_CLIENT_ID"],
            "client_secret": os.environ["WHOOP_CLIENT_SECRET"],
            "redirect_uri": redirect_uri(),
        },
        timeout=30,
    )
    if response.status_code != 200:
        raise SystemExit(f"token exchange failed: {response.status_code} {response.text[:300]}")
    payload = response.json()
    if "access_token" not in payload:
        raise SystemExit("token response missing access_token")
    session_dir()
    session_path().write_text(json.dumps(payload))
    session_path().chmod(0o600)
    return payload


def code_from_callback(raw: str) -> str:
    parsed = urllib.parse.urlparse(raw)
    params = urllib.parse.parse_qs(parsed.query)
    if params.get("state", [STATE])[0] != STATE:
        raise SystemExit("state mismatch")
    if "error" in params:
        raise SystemExit(f"whoop denied access: {params['error'][0]}")
    if "code" not in params:
        raise SystemExit("callback URL has no code")
    return params["code"][0]


def serve_once() -> str:
    holder: dict[str, str] = {}
    done = threading.Event()

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            parsed = urllib.parse.urlparse(self.path)
            if parsed.path != "/callback":
                self.send_response(404)
                self.end_headers()
                return
            params = urllib.parse.parse_qs(parsed.query)
            holder["query"] = parsed.query
            body = b"Podshift connected. You can close this tab."
            if params.get("state", [""])[0] != STATE or "code" not in params:
                body = b"Podshift could not read the Whoop code. Paste the full URL back."
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            done.set()

        def log_message(self, fmt: str, *args) -> None:
            return

    server = ThreadingHTTPServer(("127.0.0.1", 8787), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    if not done.wait(timeout=600):
        server.shutdown()
        raise SystemExit("timed out waiting for Whoop callback")
    server.shutdown()
    return code_from_callback(f"http://localhost:8787/callback?{holder['query']}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--callback-url")
    parser.add_argument("--print-url", action="store_true")
    args = parser.parse_args()
    session_dir()
    url = authorize_url()
    url_path().write_text(url)
    if args.print_url:
        print(url)
        return
    code = code_from_callback(args.callback_url) if args.callback_url else serve_once()
    payload = exchange(code)
    print(
        json.dumps(
            {
                "saved": str(session_path()),
                "has_refresh_token": "refresh_token" in payload,
                "expires_in": payload.get("expires_in"),
                "scope": payload.get("scope"),
            }
        )
    )


if __name__ == "__main__":
    main()
