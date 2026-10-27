-- 02:25 and 03:25 UTC are 9:25 p.m. Chicago (daylight and standard time).
-- 03:25 and 04:25 UTC are 10:25 p.m. Chicago.
-- 04:25 and 05:25 UTC are 11:25 p.m. Chicago.
-- Hour 21 always posts. Hours 22 and 23 post only when today's row is
-- missing or still unscored. The same job name replaces the prior schedule.
select cron.schedule(
  'podshift-fallback-2125-chicago',
  '25 2,3,4,5 * * *',
  $$
  select net.http_post(
    url := 'https://occbockorwzmykztvziu.supabase.co/functions/v1/podshift-fallback',
    headers := jsonb_build_object('Content-Type','application/json','X-Podshift-Cron',s.cron_key),
    body := '{}'::jsonb
  )
  from podshift_private.state s
  where s.id = 1
    and s.enabled
    and (
      extract(hour from now() at time zone 'America/Chicago') = 21
      or (
        extract(hour from now() at time zone 'America/Chicago') in (22, 23)
        and not exists (
          select 1
          from podshift_private.runs r
          where r.local_date = (now() at time zone 'America/Chicago')::date
            and r.outcome <> 'unscored'
        )
      )
    );
  $$
);
