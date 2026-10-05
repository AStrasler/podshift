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

type State = {
  cron_key: string; whoop_refresh_token: string | null;
  baseline: Record<string, number> | null; enabled: boolean;
};
type Observation = {
  score?: number;
  offset?: number;
  matched_before?: boolean;
  expected?: Record<string, number>;
  before_levels?: Record<string, number | null>;
};
type NightResult = Observation & { outcome: string; applied: boolean };

class RunError extends Error {
  detail: Observation;
  constructor(message: string, detail: Observation = {}) {
    super(message);
    this.detail = detail;
  }
}

const env = (name: string) => {
  const value = Deno.env.get(name);
  if (!value) throw new Error("missing_" + name);
  return value;
};
async function request(url: string, init: RequestInit, label: string) {
  const response = await fetch(url, { ...init, signal: AbortSignal.timeout(30000) });
  if (!response.ok) {
    if (label === "eight_login") {
      const body = await response.json().catch(() => ({}));
      const code = body?.error;
      if (typeof code === "string" && /^[a-zA-Z0-9_-]{1,40}$/.test(code))
        throw new Error(label + "_http_" + response.status + "_" + code);
    }
    throw new Error(label + "_http_" + response.status);
  }
  const body = await response.text();
  if (!body) return {};
  try {
    return JSON.parse(body);
  } catch {
    // A successful write may return plain text. Never skip the follow-up Pod
    // read (and potential power restoration) because of its response format.
    if (label === "eight_write" || label === "eight_power_restore") return {};
    throw new Error(label + "_non_json_response");
  }
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
  }, "whoop_refresh");
  // Refresh tokens rotate; commit the replacement before making any other API call.
  if (!session.refresh_token) throw new Error("whoop_refresh_token_missing");
  await db`update podshift_private.state set whoop_refresh_token = ${session.refresh_token},
    updated_at = now() where id = 1`;
  const headers = { Authorization: "Bearer " + session.access_token };
  const base = "https://api.prod.whoop.com/developer/v2";
  const cycles = await request(base + "/cycle?limit=1", { headers }, "whoop_cycle");
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
      client_id: env("EIGHT_SLEEP_CLIENT_ID"), client_secret: env("EIGHT_SLEEP_CLIENT_SECRET"),
    }),
  }, "eight_login");
  const headers = {
    Authorization: "Bearer " + token.access_token,
    "Content-Type": "application/json", Accept: "application/json",
    "User-Agent": "okhttp/4.9.3",
  };
  let userId = token.userId;
  if (!userId) {
    const me = await request("https://client-api.8slp.net/v1/users/me", { headers }, "eight_user");
    userId = me.user?.userId;
  }
  if (!userId) throw new Error("eight_user_missing");
  const url = "https://app-api.8slp.net/v1/users/" + encodeURIComponent(userId) +
    "/temperature/pod";
  const read = () => request("https://app-api.8slp.net/v1/users/" +
    encodeURIComponent(userId) + "/temperature", { headers }, "eight_temperature");
  return { headers, url, read };
}
function offsetFor(score: number) {
  // Same bands as podshift/apply.py. Do not add felt-temperature rules here.
  return score >= 67 ? 0 : score >= 34 ? -5 : -10;
}
function target(baseline: Record<string, number>, score: number) {
  const offset = offsetFor(score);
  const expected: Record<string, number> = {};
  for (const stage of levels) {
    const original = baseline[stage];
    if (!Number.isInteger(original) || original < -100 || original > 100)
      throw new RunError("invalid_baseline", { score, offset });
    expected[stage] = Math.max(-100, Math.min(100, original + offset));
  }
  return { expected, offset };
}
function smartSnapshot(body: { smart?: Record<string, unknown> }) {
  const smart = body.smart ?? {};
  const snapshot: Record<string, number | null> = {};
  for (const stage of levels) {
    const value = smart[stage];
    snapshot[stage] = typeof value === "number" ? value : null;
  }
  return snapshot;
}
function asJson(value: Record<string, number | null> | undefined) {
  if (value === undefined) return null;
  return db.json(value);
}
function isUndefinedColumn(error: unknown) {
  if (typeof error !== "object" || error === null) return false;
  const candidate = error as { code?: string; message?: string };
  return candidate.code === "42703" ||
    (typeof candidate.message === "string" && /column .* does not exist/i.test(candidate.message));
}
async function finish(date: string, outcome: string, detail: Observation, errorCode?: string) {
  // Columns from supabase/migrations/podshift_runs_observability.sql.
  // If that migration is not applied yet, keep the original row update so the
  // night is still recorded. The HTTP body still carries the new fields.
  const base = async () => {
    await db`update podshift_private.runs set outcome = ${outcome},
      recovery = ${detail.score ?? null},
      error_code = ${errorCode ?? null}
      where local_date = ${date}`;
  };
  try {
    await db`update podshift_private.runs set outcome = ${outcome},
      recovery = ${detail.score ?? null},
      error_code = ${errorCode ?? null},
      offset = ${detail.offset ?? null},
      matched_before = ${detail.matched_before ?? null},
      expected = ${asJson(detail.expected)},
      before_levels = ${asJson(detail.before_levels)}
      where local_date = ${date}`;
  } catch (error) {
    if (!isUndefinedColumn(error)) throw error;
    console.error("Podshift runs_observability_columns_missing");
    await base();
  }
}
async function run(state: State, dryRun: boolean): Promise<NightResult> {
  if (!state.baseline) throw new Error("missing_baseline");
  const score = await recoveryScore(state);
  if (score === null) return { outcome: "unscored", applied: false };
  const { expected, offset } = target(state.baseline, score);
  const observed: Observation = { score, offset, expected };
  try {
    const eight = await pod();
    const before = await eight.read();
    const beforeLevels = smartSnapshot(before);
    observed.matched_before = levels.every(stage => beforeLevels[stage] === expected[stage]);
    observed.before_levels = beforeLevels;
    if (dryRun) return { outcome: "dry_run", applied: false, ...observed };
    // Claimed scored nights always PUT, including when the Pod already matches.
    // Matching levels are recorded on the run row; they are not a skip.
    const beforePower = before.currentState?.type;
    await request(eight.url + "?ignoreDeviceErrors=true", {
      method: "PUT", headers: eight.headers, body: JSON.stringify({ smart: expected }),
    }, "eight_write");
    let after = await eight.read();
    if (beforePower && after.currentState?.type !== beforePower) {
      await request(eight.url + "?ignoreDeviceErrors=true", {
        method: "PUT", headers: eight.headers,
        body: JSON.stringify({ currentState: { type: beforePower } }),
      }, "eight_power_restore");
      after = await eight.read();
      if (after.currentState?.type !== beforePower) throw new RunError("power_restore_failed", observed);
    }
    if (!levels.every(stage => after.smart?.[stage] === expected[stage]))
      throw new RunError("write_not_verified", observed);
    return { outcome: "applied", applied: true, ...observed };
  } catch (error) {
    if (error instanceof RunError) throw error;
    const reason = error instanceof Error ? error.message : "unknown_error";
    throw new RunError(reason, observed);
  }
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
    if (!dryRun) await finish(date, result.outcome, result);
    return Response.json(result);
  } catch (error) {
    const reason = error instanceof Error ? error.message : "unknown_error";
    const detail = error instanceof RunError ? error.detail : {};
    if (!dryRun) {
      try {
        await finish(date, "error", detail, reason.slice(0, 100));
      } catch (writeError) {
        const code = typeof writeError === "object" && writeError !== null &&
          "code" in writeError ? String((writeError as { code?: string }).code) : "unknown_error";
        console.error("Podshift run row update failed:", code);
      }
    }
    console.error("Podshift nightly:", reason);
    return Response.json({ outcome: "error", error_code: reason, ...detail }, { status: 500 });
  }
});
