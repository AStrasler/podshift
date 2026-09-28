import postgres from "npm:postgres@3.4.5";

const db = postgres(Deno.env.get("SUPABASE_DB_URL")!, { max: 2 });
const localDate = () => {
  const parts = new Intl.DateTimeFormat("en-US", {
    timeZone: "America/Chicago", year: "numeric", month: "2-digit", day: "2-digit",
  }).formatToParts(new Date());
  const part = (type: string) => parts.find(value => value.type === type)!.value;
  return part("year") + "-" + part("month") + "-" + part("day");
};
const levels = ["bedTimeLevel", "initialSleepLevel", "finalSleepLevel"] as const;
const eightClientId = "0894c7f33bb94800a03f1f4df13a4f38";
const eightClientSecret = "f0954a3ed5763ba3d06834c73731a32f15f168f47d4f164751275def86db0c76";

type State = {
  cron_key: string; whoop_refresh_token: string | null;
  baseline: Record<string, number> | null; enabled: boolean;
};
const env = (name: string) => {
  const value = Deno.env.get(name);
  if (!value) throw new Error("missing_" + name);
  return value;
};
async function request(url: string, init: RequestInit) {
  const response = await fetch(url, { ...init, signal: AbortSignal.timeout(30000) });
  if (!response.ok) throw new Error("upstream_http_" + response.status);
  const body = await response.text();
  return body ? JSON.parse(body) : {};
}
async function recoveryScore(state: State): Promise<number | null> {
  const refreshToken = state.whoop_refresh_token || env("WHOOP_INITIAL_REFRESH_TOKEN");
  const form = new URLSearchParams({
    grant_type: "refresh_token", refresh_token: refreshToken,
    client_id: env("WHOOP_CLIENT_ID"), client_secret: env("WHOOP_CLIENT_SECRET"),
    scope: "offline",
  });
  const session = await request("https://api.prod.whoop.com/oauth/oauth2/token", {
    method: "POST", body: form,
  });
  // Refresh tokens rotate; commit the replacement before making any other API call.
  if (!session.refresh_token) throw new Error("whoop_refresh_token_missing");
  await db`update podshift_private.state set whoop_refresh_token = ${session.refresh_token},
    updated_at = now() where id = 1`;
  const headers = { Authorization: "Bearer " + session.access_token };
  const base = "https://api.prod.whoop.com/developer/v2";
  const cycles = await request(base + "/cycle?limit=1", { headers });
  const cycle = cycles.records?.[0];
  if (!cycle) return null;
  const response = await fetch(base + "/cycle/" + encodeURIComponent(cycle.id) + "/recovery",
    { headers, signal: AbortSignal.timeout(30000) });
  if (response.status === 404) return null;
  if (!response.ok) throw new Error("whoop_recovery_http_" + response.status);
  const recovery = await response.json();
  if (recovery.score_state !== "SCORED" || recovery.score?.user_calibrating) return null;
  const score = recovery.score?.recovery_score;
  return typeof score === "number" && score >= 0 && score <= 100 ? score : null;
}
async function pod() {
  const token = await request("https://auth-api.8slp.net/v1/tokens", {
    method: "POST",
    headers: { "Content-Type": "application/x-www-form-urlencoded", "User-Agent": "okhttp/4.9.3" },
    body: new URLSearchParams({
      grant_type: "password", username: env("EIGHT_SLEEP_EMAIL"),
      password: env("EIGHT_SLEEP_PASSWORD"),
      client_id: eightClientId, client_secret: eightClientSecret,
    }),
  });
  const headers = {
    Authorization: "Bearer " + token.access_token,
    "Content-Type": "application/json", Accept: "application/json",
    "User-Agent": "okhttp/4.9.3",
  };
  const me = await request("https://client-api.8slp.net/v1/users/me", { headers });
  const userId = token.userId || me.user?.userId;
  if (!userId) throw new Error("eight_user_missing");
  const url = "https://app-api.8slp.net/v1/users/" + encodeURIComponent(userId) +
    "/temperature/pod";
  const read = () => request("https://app-api.8slp.net/v1/users/" +
    encodeURIComponent(userId) + "/temperature", { headers });
  return { headers, url, read };
}
function target(baseline: Record<string, number>, score: number) {
  const offset = score >= 67 ? 0 : score >= 34 ? -5 : -10;
  const result: Record<string, number> = {};
  for (const stage of levels) {
    const original = baseline[stage];
    if (!Number.isInteger(original) || original < -100 || original > 100)
      throw new Error("invalid_baseline");
    result[stage] = Math.max(-100, Math.min(100, original + offset));
  }
  return result;
}
async function run(state: State, dryRun: boolean) {
  if (!state.baseline) throw new Error("missing_baseline");
  const score = await recoveryScore(state);
  if (score === null) return { outcome: "unscored", applied: false };
  const expected = target(state.baseline, score);
  const eight = await pod();
  const before = await eight.read();
  const same = levels.every(stage => before.smart?.[stage] === expected[stage]);
  if (same) return { outcome: "already_at_target", applied: false, score };
  if (dryRun) return { outcome: "dry_run", applied: false, score, expected };
  const beforePower = before.currentState?.type;
  await request(eight.url + "?ignoreDeviceErrors=true", {
    method: "PUT", headers: eight.headers, body: JSON.stringify({ smart: expected }),
  });
  let after = await eight.read();
  if (beforePower && after.currentState?.type !== beforePower) {
    await request(eight.url + "?ignoreDeviceErrors=true", {
      method: "PUT", headers: eight.headers,
      body: JSON.stringify({ currentState: { type: beforePower } }),
    });
    after = await eight.read();
    if (after.currentState?.type !== beforePower) throw new Error("power_restore_failed");
  }
  if (!levels.every(stage => after.smart?.[stage] === expected[stage]))
    throw new Error("write_not_verified");
  return { outcome: "applied", applied: true, score };
}

Deno.serve(async (req) => {
  if (req.method !== "POST") return new Response("Method not allowed", { status: 405 });
  const [state] = await db<State[]>`select cron_key, whoop_refresh_token, baseline,
    enabled from podshift_private.state where id = 1`;
  if (!state || req.headers.get("X-Podshift-Cron") !== state.cron_key)
    return new Response("Unauthorized", { status: 401 });
  const dryRun = (await req.json().catch(() => ({}))).dry_run === true;
  if (!state.enabled && !dryRun) return Response.json({ outcome: "disabled" });
  const date = localDate();
  try {
    // Claim the date before doing I/O. No second Supabase worker may run this day.
    if (!dryRun) {
      const claimed = await db`insert into podshift_private.runs (local_date, outcome)
        values (${date}, 'running') on conflict do nothing returning local_date`;
      if (!claimed.length) return Response.json({ outcome: "already_checked" });
    }
    const result = await run(state, dryRun);
    if (!dryRun) await db`update podshift_private.runs set outcome = ${result.outcome},
      recovery = ${result.score ?? null} where local_date = ${date}`;
    return Response.json(result);
  } catch (error) {
    const reason = error instanceof Error ? error.message : "unknown_error";
    if (!dryRun) await db`update podshift_private.runs set outcome = 'error',
      error_code = ${reason.slice(0, 100)} where local_date = ${date}`;
    console.error("Podshift fallback:", reason);
    return Response.json({ outcome: "error", error_code: reason }, { status: 500 });
  }
});
