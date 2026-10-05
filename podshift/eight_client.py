"""Eight Sleep auth and Autopilot level I/O through the vendored pyEight client.

Email and password come from the environment. Client id and secret are optional
overrides; when they are unset, pyEight uses its built-in app credentials.
"""

from __future__ import annotations

import asyncio
import os
from typing import Any

import httpx

from pyeight.constants import APP_API_URL, CLIENT_API_URL, POSSIBLE_SLEEP_STAGES
from pyeight.eight import EightSleep
from pyeight.exceptions import RequestError

STAGES = tuple(POSSIBLE_SLEEP_STAGES)


def temperature_url(user_id: str) -> str:
    return f"{APP_API_URL}v1/users/{user_id}/temperature"


def merged_smart(current: dict | None, levels: dict) -> dict:
    """Return the smart object pyEight writes, with Podshift's three stages set.

    Other keys already on the smart schedule are kept. Levels are clamped to
    the same -100..100 range as apply.py.
    """
    smart = dict(current or {})
    for stage in STAGES:
        try:
            smart[stage] = max(-100, min(100, int(levels[stage])))
        except (KeyError, TypeError, ValueError):
            raise SystemExit("eight smart update failed") from None
    return smart


def _status(err: RequestError) -> int | str:
    return err.status if err.status is not None else "error"


class EightPod:
    """One pyEight session for the logged-in user's temperature document."""

    def __init__(self) -> None:
        self._loop: asyncio.AbstractEventLoop | None = None
        self._session: Any = None
        self._eight: EightSleep | None = None
        self._user_id: str | None = None

    @property
    def user_id(self) -> str | None:
        return self._user_id

    def connect(self) -> None:
        self._loop = asyncio.new_event_loop()
        try:
            self._loop.run_until_complete(self._connect())
        except BaseException:
            self.close()
            raise

    def close(self) -> None:
        loop = self._loop
        if loop is None:
            return
        self._loop = None
        if loop.is_closed():
            return
        try:
            loop.run_until_complete(self._close())
        finally:
            loop.close()

    def read(self) -> dict:
        try:
            return self._run(self._read())
        except RequestError as err:
            raise SystemExit(f"eight temperature read failed: {_status(err)}") from None

    def write_smart(self, levels: dict) -> None:
        try:
            self._run(self._write_smart(levels))
        except RequestError as err:
            raise SystemExit(f"eight smart update failed: {_status(err)}") from None

    def set_power(self, state: str) -> None:
        try:
            self._run(self._set_power(state))
        except RequestError as err:
            raise SystemExit(f"eight power restore failed: {_status(err)}") from None

    def profile(self) -> dict:
        try:
            body = self._run(self._profile())
        except RequestError as err:
            raise SystemExit(f"users/me failed: {_status(err)}") from None
        if not isinstance(body, dict):
            raise SystemExit("users/me failed")
        return body

    def _run(self, coro):
        if self._loop is None or self._eight is None or not self._user_id:
            raise SystemExit("eight client is closed")
        return self._loop.run_until_complete(coro)

    async def _connect(self) -> None:
        from aiohttp import ClientSession

        email = os.environ["EIGHT_SLEEP_EMAIL"]
        password = os.environ["EIGHT_SLEEP_PASSWORD"]
        self._session = ClientSession()
        self._eight = EightSleep(
            email,
            password,
            "America/Chicago",
            client_id=os.environ.get("EIGHT_SLEEP_CLIENT_ID") or None,
            client_secret=os.environ.get("EIGHT_SLEEP_CLIENT_SECRET") or None,
            client_session=self._session,
        )
        try:
            token = await self._eight.token
        except (RequestError, KeyError, TypeError, httpx.HTTPError):
            raise SystemExit("eight login failed") from None
        user_id = getattr(token, "main_id", None)
        if not user_id:
            try:
                me = await self._eight.api_request("GET", f"{CLIENT_API_URL}/users/me")
            except RequestError:
                raise SystemExit("eight user lookup failed") from None
            user_id = (me.get("user") or {}).get("userId") if isinstance(me, dict) else None
        if not user_id:
            raise SystemExit("eight user id missing")
        self._user_id = str(user_id)

    async def _close(self) -> None:
        eight = self._eight
        if eight is not None:
            httpx_client = getattr(eight, "_httpx_client", None)
            if httpx_client is not None:
                await httpx_client.aclose()
                eight._httpx_client = None
        session = self._session
        self._session = None
        if session is not None and not session.closed:
            await session.close()

    async def _read(self) -> dict:
        assert self._eight is not None and self._user_id is not None
        body = await self._eight.api_request("GET", temperature_url(self._user_id))
        if not isinstance(body, dict):
            raise SystemExit("eight temperature read failed")
        return body

    async def _write_smart(self, levels: dict) -> None:
        assert self._eight is not None and self._user_id is not None
        url = temperature_url(self._user_id)
        current = await self._eight.api_request("GET", url)
        source = current.get("smart") if isinstance(current, dict) else None
        if source is not None and not isinstance(source, dict):
            source = None
        await self._eight.api_request(
            "PUT",
            url,
            data={"smart": merged_smart(source, levels)},
            return_json=False,
        )

    async def _set_power(self, state: str) -> None:
        assert self._eight is not None and self._user_id is not None
        await self._eight.api_request(
            "PUT",
            temperature_url(self._user_id),
            data={"currentState": {"type": state}},
            return_json=False,
        )

    async def _profile(self) -> dict:
        assert self._eight is not None
        return await self._eight.api_request("GET", f"{CLIENT_API_URL}/users/me")


def open_eight() -> EightPod:
    pod = EightPod()
    pod.connect()
    return pod
