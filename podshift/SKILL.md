---
name: Podshift
description: Read the owner's Whoop recovery and shift Eight Sleep Pod temperature before bed. Use for Whoop login, recovery checks, and Pod temperature changes.
metadata:
  version: "0.2.0"
---

# Podshift

Personal controller. Tokens live in `$PODSHIFT_HOME` (`/workspace/.podshift` on this agent, otherwise `~/.podshift`). Never print client secrets, access tokens, or refresh tokens. Set `PODSHIFT_DISABLED=1` to skip the Pod write. Set `PODSHIFT_AWAY=1` to skip the write while away from home; there is no location signal, and leaving it unset does not skip. Primary schedule is `Podshift bedtime` at 9:00pm America/Chicago. Fallback daemon runs at 9:25pm on this container and skips if `last_run.json` already shows tonight applied. Pause only the fallback with `$PODSHIFT_HOME/fallback.paused`.

## Whoop login

Redirect URI registered in the Whoop app: `http://localhost:8787/callback`.

```bash
uv run --env-file /workspace/.env /workspace/.claude/skills/podshift/whoop_auth.py
```

That starts the callback server and writes the authorize URL to `/workspace/.podshift/authorize_url.txt`. After the browser hits the callback, tokens are saved and the latest recovery is printed without tokens.

If the browser cannot reach this container's localhost, paste the full redirected URL:

```bash
uv run --env-file /workspace/.env /workspace/.claude/skills/podshift/whoop_auth.py --callback-url 'http://localhost:8787/callback?code=...&state=podshift'
```

## Read recovery

```bash
uv run --env-file /workspace/.env --with requests python3 /workspace/.claude/skills/podshift/whoop_recovery.py
```

## Apply the bedtime offset

Baseline levels live in `/workspace/.podshift/baseline.json`. Offsets are computed from that file, not from the current Pod values. The apply script never turns the Pod on. If a write changes power state, it restores the previous state.

Bands: 67–100 offset 0, 34–66 offset -5, 0–33 offset -10. Skip the write when recovery is missing, unscored, or still calibrating.

```bash
uv run --env-file /workspace/.env --with requests python3 /workspace/.claude/skills/podshift/apply.py --dry-run
uv run --env-file /workspace/.env --with requests python3 /workspace/.claude/skills/podshift/apply.py
```
