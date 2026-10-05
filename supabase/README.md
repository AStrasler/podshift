# Podshift nightly scheduler

Supabase project `occbockorwzmykztvziu` runs Edge Function `podshift-fallback` at
9:25 p.m. America/Chicago. This is the primary Podshift scheduler. The function
slug and the cron job name `podshift-fallback-2125-chicago` are historical.
Nothing else is expected to run first.

The function reads the latest scored WHOOP recovery and writes the three
Autopilot smart levels from the saved green-day baseline plus the offset in
`podshift/apply.py`:

| Recovery | Offset |
| --- | --- |
| 67–100 | 0 |
| 34–66 | -5 |
| 0–33 | -10 |

On a claimed night with a scored recovery it always PUTs those three levels,
including when the Pod already has them. It does not return `already_at_target`.
That early return existed so the function would not fight Gamut. Gamut is
deprecated and is not a coordination partner.

It never turns the Pod on. If the write changes power state, it restores the
previous state, then checks that the three levels match.

Each Chicago date is claimed once in `podshift_private.runs` before any WHOOP
or Eight Sleep call. A second invocation returns `already_checked`. Unscored or
calibrating recovery records `unscored` and does not write. `enabled = false`
returns `disabled` and does not claim the date. A dry run is still allowed
while paused; it does not claim the date and does not write.

This function is authorized by the `X-Podshift-Cron` header, not by a user JWT.

Eight Sleep and WHOOP credentials are Edge Function secrets, read from the
environment only. Never put those values in GitHub, the SQL editor, a chat, or
this repository.

## What a night records

`podshift_private.runs` keeps the original columns and adds four nullable ones
in `supabase/migrations/podshift_runs_observability.sql`:

| Column | Meaning |
| --- | --- |
| `outcome` | `running`, then `applied`, `unscored`, or `error` |
| `recovery` | WHOOP recovery score when one was read |
| `offset` | 0, -5, or -10 |
| `matched_before` | true when the three live smart levels already equaled the target before the PUT |
| `expected` | the three target levels |
| `before_levels` | the three live smart levels read before the PUT |
| `error_code` | short failure reason. A failed write still stores offset, match, expected, and before levels when they were known |

`already_checked` is only the HTTP response for a date that was already claimed.
The existing row is left alone. `already_at_target` is no longer written. Older
rows may still have it.

Apply the observability migration before deploying the function that fills the
new columns. This repository change does not run that migration and does not
deploy the function. If the columns are missing, the function still saves
`outcome`, `recovery`, and `error_code`, and the HTTP body still includes the
new fields.

Readers of `local_date`, `outcome`, `scheduler`, `recovery`, and `error_code`
do not need to change. A night that already matched is `outcome = applied`
with `matched_before = true`, not a distinct outcome.

## Provisioning

In the [Podshift project Edge Function Secrets](https://supabase.com/dashboard/project/occbockorwzmykztvziu/functions/secrets),
set `WHOOP_CLIENT_ID`, `WHOOP_CLIENT_SECRET`,
`WHOOP_INITIAL_REFRESH_TOKEN`, `EIGHT_SLEEP_EMAIL`,
`EIGHT_SLEEP_PASSWORD`, `EIGHT_SLEEP_CLIENT_ID`, and
`EIGHT_SLEEP_CLIENT_SECRET` outside git. Obtain the WHOOP refresh token using the existing
`podshift/whoop_auth.py` with the offline scope. Once the function uses it,
the rotated token lives in the project's private database state.

The private baseline holds the green-day values the offset is applied to.
Compare these with the current `baseline.json` before relying on a night.

On a database that already ran `podshift_fallback.sql`, apply only:

`supabase/migrations/podshift_runs_observability.sql`

A new database needs that file after `podshift_fallback.sql`.

## Dry run

Run a read-only dry run from the Supabase SQL editor. This SQL passes the
private invocation key from the database without printing it:

```sql
select net.http_post(
  url := 'https://occbockorwzmykztvziu.supabase.co/functions/v1/podshift-fallback',
  headers := jsonb_build_object(
    'Content-Type', 'application/json',
    'X-Podshift-Cron', (select cron_key from podshift_private.state where id = 1)
  ),
  body := '{"dry_run":true}'::jsonb
);
```

Inspect the corresponding response in `net._http_response`. A dry run returns
`dry_run` plus `score`, `offset`, `matched_before`, `expected`, and
`before_levels`. It does not claim the date and does not PUT. Only after a
successful dry run, enable the scheduled job:

```sql
update podshift_private.state set enabled = true where id = 1;
```

Pause it with `update podshift_private.state set enabled = false where id = 1;`.
The cron entry remains installed but sends no request while paused.
Daily results live in `podshift_private.runs`. A day with an error is not
automatically retried; inspect the error first because the Pod write may have
completed before the response failed.

## Limits

- No away/home check. `podshift_private.state` has no column for it. `PODSHIFT_AWAY` is honored only by the Python `apply.py` path. Pause this function with `enabled = false`.
- The function does not coordinate with Gamut or with `apply.py`. If a deprecated Gamut job or a manual `apply.py` runs the same night, both can write the same target. Leave Gamut off.
- WHOOP and Eight Sleep API behavior may change.
- Secrets must be supplied to this project before activation. Do not commit them.
