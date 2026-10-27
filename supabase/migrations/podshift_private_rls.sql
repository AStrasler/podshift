-- Already applied on project occbockorwzmykztvziu. Recorded so the repository
-- matches production. Deny-all: row level security is on, and the API roles
-- cannot use this schema. There are no policies.
alter table podshift_private.state enable row level security;
alter table podshift_private.runs  enable row level security;
revoke all on all tables    in schema podshift_private from anon, authenticated, service_role;
revoke all on all sequences in schema podshift_private from anon, authenticated, service_role;
revoke usage on schema podshift_private from anon, authenticated, service_role;
