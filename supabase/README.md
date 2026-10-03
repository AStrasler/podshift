# Podshift Supabase fallback

Supabase project `occbockorwzmykztvziu` runs an independent Edge Function at
9:25 p.m. America/Chicago. Gamut's 9:00 p.m. job stays primary. The function
reads the latest scored WHOOP recovery, calculates from the saved green-day
baseline, reads Eight Sleep Autopilot levels, and **skips the write if the Pod
is already at the desired levels**. It never turns the Pod on.

This fallback is initially **disabled**. It needs a separate WHOOP refresh
token and its own Eight Sleep credentials in this project's Edge Function
Secrets. Never put these values in GitHub, the SQL editor, or a chat.

## Provisioning

In the [Podshift project Edge Function Secrets](https://supabase.com/dashboard/project/occbockorwzmykztvziu/functions/secrets),
set `WHOOP_CLIENT_ID`, `WHOOP_CLIENT_SECRET`,
`WHOOP_INITIAL_REFRESH_TOKEN`, `EIGHT_SLEEP_EMAIL`,
`EIGHT_SLEEP_PASSWORD`, `EIGHT_SLEEP_CLIENT_ID`, and
`EIGHT_SLEEP_CLIENT_SECRET` outside git. Obtain the WHOOP refresh token using the existing
`podshift/whoop_auth.py` with the offline scope. Once the function uses it,
the rotated token lives in the project's private database state.

The private baseline currently holds the green-day values last reported by
the existing Podshift dry run: bedtime +32, initial sleep +30, final sleep -10.
Compare these with the current `baseline.json` before enabling.

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

Inspect the corresponding response in `net._http_response`. Only after a
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

- No away/home check. `podshift_private.state` has no column for it, and none is added here. `PODSHIFT_AWAY` is honored only by the Python `apply.py` path.

- Gamut and Supabase do not share a lock or completion record. Supabase reads
  the Pod's actual target levels, so a successful Gamut write usually leads
  to a skip. If Gamut and Supabase overlap, both may write the same values.
- If Gamut applies a green-day target already on the Pod, Supabase cannot tell
  which scheduler did so; it records `already_at_target`.
- WHOOP and Eight Sleep API behavior may change. Keep the Gamut job enabled
  until the Supabase dry run and at least one scheduled night succeed.
- Secrets must be supplied to this separate project before activation.
