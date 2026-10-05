# Podshift

Personal bridge from WHOOP recovery to an Eight Sleep Pod. Once a night it reads the latest scored recovery and rewrites the saved Autopilot temperature levels. It does not turn the Pod on.

This repository is public so WHOOP can load [PRIVACY.md](PRIVACY.md). Do not commit `.env`, session files, or `baseline.json`.

Eight Sleep has no official public API. The clients talk to the same cloud endpoints the mobile app uses. Those endpoints can change without notice.

Python (`apply.py` and `eight_status.py`) uses [pyEight](podshift/pyeight/VENDORED.md). The copy in this repo is the newer client vendored from [lukas-clarke/eight_sleep](https://github.com/lukas-clarke/eight_sleep) (`30093a3`, pyEight files through 2026-08-29), not the older standalone [lukas-clarke/pyEight](https://github.com/lukas-clarke/pyEight) (`d394d454`, 2025-07-15). The Home Assistant tree is not a pip package, so it is vendored. It keeps that library's built-in app client id and secret. Eight Sleep does not issue developer credentials. Python reads and writes `https://app-api.8slp.net/v1/users/{userId}/temperature`, which is pyEight's Autopilot route. The edge function still uses `/temperature/pod`.

The Supabase edge function is still the hand-rolled client. This stage does not change it. A later change can move that function after the Python path has been proven.

## What triggers it

The nightly run is the Supabase Edge Function `podshift-fallback` on project `occbockorwzmykztvziu`. The slug is historical. The function is the primary scheduler: pg_cron calls it at 9:25 p.m. America/Chicago, it claims that Chicago date once, and it does not depend on any other job. Setup, pause, and the runs table are in [supabase/README.md](supabase/README.md).

`apply.py` is the same temperature rules for a manual run. It does not have to be running for the night to happen.

The Gamut task `Podshift bedtime` (9:00 p.m. America/Chicago) is deprecated. Do not schedule it. The Supabase function does not read Gamut and does not skip a write because the Pod already shows the target levels. The container daemon `podshift/fallback_daemon.py` only existed to cover a missed Gamut run. Leave that daemon stopped.

Both the function and `apply.py` use the latest scored WHOOP cycle. Neither waits for a webhook.

## What it changes

It sends one update to the saved smart levels:

- `bedTimeLevel`
- `initialSleepLevel`
- `finalSleepLevel`

The offset is applied to the green-day baseline, not to whatever the Pod is currently set to, so repeated nights do not stack. Locally that file is `$PODSHIFT_HOME/baseline.json`. The Supabase function uses `podshift_private.state.baseline`.

| Recovery | Offset |
| --- | --- |
| 67–100 | 0 |
| 34–66 | -5 |
| 0–33 | -10 |

Levels are clamped to -100..100. Neither path skips because the live levels already match the target. On a claimed scored night the Supabase function always writes the three levels and records a pre-write match as `matched_before`. The write is skipped when recovery is missing, not `SCORED`, or still calibrating.

Power is left alone. If that write unexpectedly changes the power state, the previous state is restored. Autopilot is expected to turn the Pod on by itself.

## Schedulers

Primary: Supabase Edge Function `podshift-fallback`, 9:25 p.m. America/Chicago. pg_cron fires at 02:25 and 03:25 UTC and the SQL predicate keeps the call that falls at 21:00 Chicago. The function inserts `podshift_private.runs` for that Chicago date before it calls WHOOP or Eight Sleep. A second call the same date returns `already_checked` and does not write. After a scored recovery it always PUTs `bedTimeLevel`, `initialSleepLevel`, and `finalSleepLevel`. If those levels already matched, the row still says `applied` and `matched_before` is true. The row also stores `recovery_offset`, `expected`, and `before_levels` after `supabase/migrations/podshift_runs_observability.sql` is applied. The HTTP body still calls the offset field `offset`.

Pause the nightly function:

```sql
update podshift_private.state set enabled = false where id = 1;
```

Set `enabled` back to true to resume. The cron entry stays installed. While paused, the schedule sends no request. A direct call with the cron header returns `{"outcome":"disabled"}` and does not claim the date. `PODSHIFT_DISABLED` does not affect Supabase. It only affects `apply.py`.

Deprecated: the Gamut task `Podshift bedtime` at 9:00 p.m., and the agent-container daemon `podshift/fallback_daemon.py` (9:25 p.m.) that ran `fallback.py` when `$PODSHIFT_HOME/last_run.json` did not already show tonight applied. Those paths were how a local run avoided writing over Gamut. The Supabase function does not read `last_run.json` and does not skip when the Pod already matches the target. Leave the Gamut schedule off. If that daemon is still running, stop it:

```bash
kill "$(cat "${PODSHIFT_HOME:-$HOME/.podshift}/fallback.pid")"
```

`fallback.paused` only affects that deprecated process.

`apply.py` remains the local command and the statement of the temperature rules. Its once-per-night file lock still stops a second local run the same Chicago date. That lock is not shared with Supabase. Do not run `apply.py` on a schedule while the Supabase function is enabled. The two do not share a lock, so both would write the same target.

## Pause or disable

- Skip the Supabase night: `update podshift_private.state set enabled = false where id = 1;`
- Skip a local `apply.py` write: `PODSHIFT_DISABLED=1`.
- Skip a local `apply.py` write while away from home: `PODSHIFT_AWAY=1`.

There is no GPS, geofence, or other presence signal in this repo. `PODSHIFT_AWAY=1` (`true` and `yes` also count) makes `apply.py` skip the Eight Sleep write and record `skipped` as `away`. Leave it unset and a local run still writes. The Supabase function does not read `PODSHIFT_AWAY`. `podshift_private.state` has no away column. Pause that function with `enabled = false`.

`--dry-run` on `apply.py` reads WHOOP and the Pod and does not update `last_run.json`. A Supabase dry run (`{"dry_run":true}`) reads both and does not claim the date or write the Pod. The dry-run JSON includes `matched_before`, `offset`, `expected`, and `before_levels`.

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
| `PODSHIFT_AWAY` | `1`, `true`, or `yes` skips the Pod write while away. Unset does nothing |
| `EIGHT_SLEEP_CLIENT_ID` | Optional Python override. Unset uses pyEight's built-in app client id. Still required by the Supabase function |
| `EIGHT_SLEEP_CLIENT_SECRET` | Optional Python override. Unset uses pyEight's built-in app client secret. Still required by the Supabase function |

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

The installed nightly schedule is the Supabase function. Confirm it with the dry-run SQL in [supabase/README.md](supabase/README.md). Leave the deprecated Gamut task off.

Local read, then an optional local write:

```bash
.venv/bin/python podshift/apply.py --dry-run
.venv/bin/python podshift/apply.py
```

A separate machine can run the same rules with cron. That is optional, and it must not run on a night the Supabase function is also enabled. Set `CRON_TZ` or the system timezone to `America/Chicago` if you use this cron.

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

Python logs in with `EIGHT_SLEEP_EMAIL` and `EIGHT_SLEEP_PASSWORD` through pyEight on each run. There is no separate OAuth app, and `apply.py` does not read or write `eight_session.json`. Leave client id and secret unset unless you need to override the library defaults. The Supabase function still expects `EIGHT_SLEEP_CLIENT_ID` and `EIGHT_SLEEP_CLIENT_SECRET` in that project's secrets.

1. Put the current password in `EIGHT_SLEEP_PASSWORD`.
2. Run `podshift/eight_status.py` or `apply.py --dry-run`.

## Tests

```bash
cd podshift && ../.venv/bin/python -m unittest test_levels.py
```

The unit tests do not call WHOOP or Eight Sleep. They cover the offset bands and the local dry-run path. `--dry-run` is the live read-only check.
