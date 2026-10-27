# Podshift nightly scheduler

Supabase project `occbockorwzmykztvziu` runs Edge Function `podshift-fallback` at
9:25 p.m. America/Chicago. An unscored night is retried at 10:25 p.m. and
11:25 p.m. America/Chicago. This is the primary Podshift scheduler. The function
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

Each Chicago date is claimed in `podshift_private.runs` before any WHOOP or
Eight Sleep call. The first claim inserts `running`. If that row is later
`unscored`, a later call the same Chicago date claims it again: `outcome`
returns to `running` and `attempted_at` is refreshed. A row with any other
outcome returns `already_checked` and is left alone. Unscored or calibrating
recovery records `unscored` and does not write. `enabled = false` returns
`disabled` and does not claim the date. A dry run is still allowed while
paused; it does not claim the date and does not write.

This function is authorized by the `X-Podshift-Cron` header, not by a user JWT.

Eight Sleep email and password, and the WHOOP credentials, are Edge Function
secrets, read from the environment only. Never put those values in GitHub, the
SQL editor, a chat, or this repository. The Eight Sleep app client id and
secret are the fixed public pair in `podshift/pyeight/constants.py`.

## What a night records

`podshift_private.runs` keeps the original columns and adds four nullable ones
in `supabase/migrations/podshift_runs_observability.sql`:

| Column | Meaning |
| --- | --- |
| `outcome` | `running`, then `applied`, `unscored`, or `error` |
| `recovery` | WHOOP recovery score when one was read |
| `recovery_offset` | 0, -5, or -10. The HTTP body still calls this field `offset` |
| `matched_before` | true when the three live smart levels already equaled the target before the PUT |
| `expected` | the three target levels |
| `before_levels` | the three live smart levels read before the PUT |
| `error_code` | short failure reason. A failed write still stores recovery_offset, match, expected, and before levels when they were known |

`already_checked` is the HTTP response when today's row exists and its outcome
is not `unscored`. That row is left alone. An `unscored` row is claimed again.
`already_at_target` is no longer written. Older rows may still have it.

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
`WHOOP_INITIAL_REFRESH_TOKEN`, `EIGHT_SLEEP_EMAIL`, and
`EIGHT_SLEEP_PASSWORD` outside git. `EIGHT_SLEEP_CLIENT_ID` and
`EIGHT_SLEEP_CLIENT_SECRET` are optional. Unset, the function uses the same
fixed Eight Sleep app client pair as `podshift/pyeight/constants.py`. Eight
Sleep does not issue developer credentials. Those values are not account
secrets. Obtain the WHOOP refresh token using the existing
`podshift/whoop_auth.py` with the offline scope. Once the function uses it,
the rotated token lives in the project's private database state.

The private baseline holds the green-day values the offset is applied to.
Compare these with the current `baseline.json` before relying on a night.

On a database that already ran `podshift_fallback.sql`, apply:

`supabase/migrations/podshift_runs_observability.sql`

`supabase/migrations/podshift_unscored_retry.sql`

`supabase/migrations/podshift_private_rls.sql` is already applied on this
project. Apply it on a new database after `podshift_fallback.sql`. A new
database needs `podshift_fallback.sql` first, then the observability migration,
the retry schedule, and the RLS file.

This repository change does not run `podshift_unscored_retry.sql` and does not
deploy the function. Retries at 10:25 and 11:25 p.m. need both: the cron
predicate only posts then, and only the updated function reclaims an
`unscored` row.

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
`before_levels`. In that JSON, `offset` is the same number stored in the
`recovery_offset` column. It does not claim the date and does not PUT. Only after a
successful dry run, enable the scheduled job:

```sql
update podshift_private.state set enabled = true where id = 1;
```

Pause it with `update podshift_private.state set enabled = false where id = 1;`.
The cron entry remains installed but sends no request while paused.
Daily results live in `podshift_private.runs`. An `unscored` night is retried
at 10:25 p.m. and 11:25 p.m. Chicago. A day with an error is not automatically
retried; inspect the error first because the Pod write may have completed
before the response failed.

## Schedule

pg_cron job `podshift-fallback-2125-chicago` uses `25 2,3,4,5 * * *`. Those
four UTC minutes cover 9:25, 10:25, and 11:25 p.m. America/Chicago across
daylight and standard time:

| UTC | Chicago during daylight (CDT) | Chicago during standard (CST) |
| --- | --- | --- |
| 02:25 | 9:25 p.m. | 8:25 p.m. (no post) |
| 03:25 | 10:25 p.m. | 9:25 p.m. |
| 04:25 | 11:25 p.m. | 10:25 p.m. |
| 05:25 | 12:25 a.m. (no post) | 11:25 p.m. |

The job posts when `podshift_private.state` is enabled and the Chicago hour is
21, or the Chicago hour is 22 or 23 and today's row is missing or still
`unscored`. Any other outcome, including `applied`, `error`, and `running`,
does not get another call. `supabase/migrations/podshift_fallback.sql` installed
the earlier `25 2,3 * * *` schedule. `podshift_unscored_retry.sql` replaces
that job.

## Access

`podshift_private` is deny-all. `supabase/migrations/podshift_private_rls.sql`
enables row level security on `state` and `runs` and revokes tables, sequences,
and schema usage from `anon`, `authenticated`, and `service_role`. There are
no policies. That migration is already applied on this project; the file
records it. The function uses its database connection, not those API roles.

## Limits

- No away/home check. `podshift_private.state` has no column for it. `PODSHIFT_AWAY` is honored only by the Python `apply.py` path. Pause this function with `enabled = false`.
- The function does not coordinate with Gamut or with `apply.py`. If a deprecated Gamut job or a manual `apply.py` runs the same night, both can write the same target. Leave Gamut off.
- WHOOP and Eight Sleep API behavior may change.
- Account secrets must be supplied to this project before activation. Do not commit them. The Eight Sleep app client id and secret are the fixed public pair already in `podshift/pyeight/constants.py` and do not have to be set.
- This function still uses the hand-rolled Eight Sleep client and still writes `/temperature/pod`. Python `apply.py` uses pyEight and writes `/temperature`. Client id and secret fall back to that library's app pair on both paths.
