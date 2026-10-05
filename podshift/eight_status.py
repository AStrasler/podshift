#!/usr/bin/env python3
"""Read-only Eight Sleep login and Pod status. Does not change temperature."""

import json

from eight_client import open_eight


def main() -> None:
    pod = open_eight()
    try:
        me = pod.profile()
        body = pod.read()
        user_id = pod.user_id
    finally:
        pod.close()
    user = me.get("user") or {}
    user_id = user_id or user.get("userId")
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
