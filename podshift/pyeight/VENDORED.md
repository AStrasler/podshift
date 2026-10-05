# Vendored pyEight

Python `apply.py` and `eight_status.py` use this snapshot for Eight Sleep auth and Autopilot smart-level reads and writes.

| Source | Commit | When the pyEight tree last moved |
| --- | --- | --- |
| [lukas-clarke/eight_sleep](https://github.com/lukas-clarke/eight_sleep) `custom_components/eight_sleep/pyEight` | `30093a3bcc292e02fb4af37b6e08cb20b6157e8e` (release 1.0.24) | 2026-08-29 (`1e9edeb`) |
| [lukas-clarke/pyEight](https://github.com/lukas-clarke/pyEight) | `d394d454abcc4fb3331eb6296eaea4d4dab71dd0` | 2025-07-15 |

The Home Assistant tree is newer. It is not published as a pip package (it lives inside the integration, and its exceptions import Home Assistant). Podshift vendors that copy instead of installing the older standalone repository.

The only local change is `exceptions.py`: `RequestError` no longer subclasses `homeassistant.exceptions.HomeAssistantError`. The library's built-in app client id and secret in `constants.py` are kept. Eight Sleep does not issue developer client credentials, and Podshift does not invent new ones. Account email and password still come from the environment.

The Supabase edge function does not use this package. It stays hand-rolled until a later change.
