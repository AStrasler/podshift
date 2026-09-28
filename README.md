# Podshift

Personal bridge from WHOOP recovery to an Eight Sleep Pod. Once a night it reads the latest scored recovery and rewrites the saved Autopilot temperature levels. It does not turn the Pod on.

This repository is public so WHOOP can load [PRIVACY.md](PRIVACY.md). Do not commit `.env`, session files, or `baseline.json`.

Eight Sleep has no official public API. The client talks to the same cloud endpoints the mobile app uses. Those endpoints can change without notice.

## What triggers it

Nothing in this repo runs by itself. A scheduler has to start `apply.py`.

- This deployment: a daily agent schedule named `Podshift bedtime`, cron `0 21 * * *` in `America/Chicago`.
- Anywhere else: the same cron entry, or run the command by hand.

The script always uses the latest scored WHOOP cycle. It does not wait for a webhook.

## What it changes

It sends one update to the saved smart levels:

- `bedTimeLevel`
- `initialSleepLevel`
- `finalSleepLevel`

The offset is applied to `$PODSHIFT_HOME/baseline.json`, not to whatever the Pod is currently set to, so repeated nights do not stack.

| Recovery | Offset |
| --- | --- |
| 67–100 | 0 |
| 34–66 | -5 |
| 0–33 | -10 |

Levels are clamped to -100..100. The write is skipped when recovery is missing, not `SCORED`, or still calibrating.

Power is left alone. If that write unexpectedly changes the power state, the previous state is restored. Autopilot is expected to turn the Pod on by itself.

## Pause or disable

- Skip tonight's write without deleting the schedule: `PODSHIFT_DISABLED=1`.
- Stop the daily run on this agent: pause or cancel the `Podshift bedtime` schedule.
- Stop an independent cron job: remove or comment out its crontab line.

`--dry-run` reads WHOOP and the Pod and writes nothing.

## Setup

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
cp .env.example .env
mkdir -p "${PODSHIFT_HOME:-$HOME/.podshift}"
cp baseline.example.json "${PODSHIFT_HOME:-$HOME/.podshift}/baseline.json"
```

Edit `.env`. Edit `baseline.json` to the Autopilot levels you want on a green day. `PODSHIFT_HOME` defaults to `~/.podshift` when unset.

Required environment variables:

| Name | Purpose |
| --- | --- |
| `WHOOP_CLIENT_ID` | WHOOP developer app client id |
| `WHOOP_CLIENT_SECRET` | WHOOP developer app client secret |
| `EIGHT_SLEEP_EMAIL` | Eight Sleep account email |
| `EIGHT_SLEEP_PASSWORD` | Eight Sleep account password |

Optional:

| Name | Purpose |
| --- | --- |
| `WHOOP_REDIRECT_URI` | Must match the WHOOP app. Default `http://localhost:8787/callback` |
| `PODSHIFT_HOME` | Directory for tokens, baseline, and `last_run.json` |
| `PODSHIFT_DISABLED` | `1`, `true`, or `yes` skips the Pod write |

WHOOP app scopes: `read:recovery`, `read:cycles`, `read:sleep`, `read:workout`, `read:profile`, `read:body_measurement`. Request `offline` in the authorize URL. It is not a checkbox on the app form. Privacy policy URL for that app is the `PRIVACY.md` file in this repo.

## Connect WHOOP

```bash
set -a && source .env && set +a
export PODSHIFT_HOME="${PODSHIFT_HOME:-$HOME/.podshift}"
.venv/bin/python podshift/whoop_auth.py --print-url
```

Open the printed URL, approve access, and paste the full callback URL even if the localhost page does not load:

```bash
.venv/bin/python podshift/whoop_auth.py --callback-url 'http://localhost:8787/callback?code=...&state=podshift'
```

## Check, then schedule

```bash
.venv/bin/python podshift/apply.py --dry-run
.venv/bin/python podshift/apply.py
```

Independent cron, 9:00pm local time. Set `CRON_TZ` or the system timezone to `America/Chicago` if that is the intended clock.

```cron
0 21 * * * cd /path/to/podshift && set -a && . ./.env && set +a && .venv/bin/python podshift/apply.py
```

## Reconnect WHOOP

Access tokens expire in about an hour. `apply.py` refreshes them. Reconnect only when refresh fails, the app is revoked, or the client secret changes.

1. In the WHOOP app or developer dashboard, confirm the app is still authorized.
2. If you rotated the client secret, put the new value in `WHOOP_CLIENT_SECRET`.
3. Delete `$PODSHIFT_HOME/whoop_session.json`.
4. Run the connect steps above again. The redirect URI must still match the WHOOP app exactly.

## Reconnect Eight Sleep

There is no separate OAuth app. Login uses the account email and password.

1. Put the current password in `EIGHT_SLEEP_PASSWORD`.
2. Delete `$PODSHIFT_HOME/eight_session.json`.
3. Run `podshift/eight_status.py` or `apply.py --dry-run`. A 401 on the next real run also triggers a fresh login.

## Tests

```bash
cd podshift && ../.venv/bin/python -m unittest test_levels.py
```

The unit tests do not call WHOOP or Eight Sleep. `--dry-run` is the live read-only check.
