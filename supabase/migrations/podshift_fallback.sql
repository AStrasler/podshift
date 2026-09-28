create schema if not exists podshift_private;
create extension if not exists pg_cron with schema extensions;
create extension if not exists pg_net with schema extensions;

create table if not exists podshift_private.state (
  id integer primary key default 1 check (id = 1),
  cron_key text not null default encode(gen_random_bytes(32), 'hex'),
  whoop_refresh_token text,
  baseline jsonb,
  eight_user_id text,
  enabled boolean not null default false,
  updated_at timestamptz not null default now()
);
insert into podshift_private.state (id) values (1) on conflict do nothing;

create table if not exists podshift_private.runs (
  local_date date primary key,
  attempted_at timestamptz not null default now(),
  outcome text not null,
  scheduler text not null default 'supabase',
  recovery integer,
  error_code text
);
revoke all on schema podshift_private from public, anon, authenticated;
revoke all on all tables in schema podshift_private from public, anon, authenticated;

-- 02:25 UTC during daylight time; 03:25 UTC during standard time.
-- The local-hour predicate selects exactly one invocation on each date.
select cron.schedule(
  'podshift-fallback-2125-chicago',
  '25 2,3 * * *',
  $$
  select net.http_post(
    url := 'https://occbockorwzmykztvziu.supabase.co/functions/v1/podshift-fallback',
    headers := jsonb_build_object('Content-Type','application/json','X-Podshift-Cron',s.cron_key),
    body := '{}'::jsonb
  )
  from podshift_private.state s
  where s.id = 1
    and s.enabled
    and extract(hour from now() at time zone 'America/Chicago') = 21;
  $$
);
