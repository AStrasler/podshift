-- Additive columns for the primary nightly scheduler.
-- Apply this on the existing project before deploying the podshift-fallback
-- function that writes these columns. Nullable so current rows and any reader
-- of local_date, outcome, scheduler, recovery, or error_code stay valid.
-- Historical already_at_target rows are left as they are; new nights do not
-- use that outcome.

alter table podshift_private.runs
  add column if not exists offset integer,
  add column if not exists matched_before boolean,
  add column if not exists expected jsonb,
  add column if not exists before_levels jsonb;

comment on column podshift_private.runs.offset is
  'Recovery offset applied to the green-day baseline: 0, -5, or -10.';
comment on column podshift_private.runs.matched_before is
  'True when the three live smart levels already equaled the target before the nightly PUT.';
comment on column podshift_private.runs.expected is
  'Target bedTimeLevel, initialSleepLevel, and finalSleepLevel for that night.';
comment on column podshift_private.runs.before_levels is
  'The three live smart levels read before the PUT.';
