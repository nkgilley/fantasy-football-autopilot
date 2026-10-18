import { AppSettings, LeagueDetailResponse, LeagueTeamsResponse, OverviewResponse } from "./types";

export async function fetchOverview(): Promise<OverviewResponse> {
  const res = await fetch("/api/overview");
  if (!res.ok) throw new Error(`Failed fetching overview: ${res.statusText}`);
  return res.json();
}

export async function fetchLeagueDetail(leagueKey: string): Promise<LeagueDetailResponse> {
  const res = await fetch(`/api/leagues/${encodeURIComponent(leagueKey)}`);
  if (!res.ok) throw new Error(`Failed fetching league detail: ${res.statusText}`);
  return res.json();
}

export async function fetchLeagueTeams(leagueKey: string): Promise<LeagueTeamsResponse> {
  const res = await fetch(`/api/leagues/${encodeURIComponent(leagueKey)}/teams`);
  if (!res.ok) throw new Error(`Failed fetching league teams: ${res.statusText}`);
  return res.json();
}

export async function triggerSync(sendEmail = false): Promise<any> {
  const res = await fetch("/api/sync", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ send_email: sendEmail, attempt_live_fp: true }),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || `Sync failed: ${res.statusText}`);
  }
  return res.json();
}

export async function updateLeagueExecutionMode(
  leagueKey: string,
  mode: "advisory" | "auto_lineup"
): Promise<any> {
  const res = await fetch(`/api/leagues/${encodeURIComponent(leagueKey)}/execution-mode`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ execution_mode: mode }),
  });
  if (!res.ok) throw new Error(`Failed updating execution mode`);
  return res.json();
}

export async function applyLeagueOptimalLineup(leagueKey: string): Promise<any> {
  const res = await fetch(`/api/leagues/${encodeURIComponent(leagueKey)}/apply-lineup`, {
    method: "POST",
  });
  if (!res.ok) throw new Error(`Failed applying lineup`);
  return res.json();
}

export async function fetchSettings(): Promise<AppSettings> {
  const res = await fetch("/api/settings");
  if (!res.ok) throw new Error(`Failed fetching settings`);
  return res.json();
}

export async function saveSettings(payload: Partial<AppSettings>): Promise<AppSettings> {
  const res = await fetch("/api/settings", {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!res.ok) throw new Error(`Failed saving settings`);
  return res.json();
}

export async function sendDigestEmailNow(recipient?: string): Promise<any> {
  const res = await fetch("/api/notifications/send-email", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ recipient: recipient || null }),
  });
  if (!res.ok) throw new Error(`Failed sending email`);
  return res.json();
}

export async function getYahooAuthorizeUrl(): Promise<string> {
  const res = await fetch("/api/auth/yahoo/login");
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || "Failed building Yahoo OAuth URL");
  }
  const data = await res.json();
  return data.authorize_url;
}

export async function exchangeYahooCode(code: string): Promise<any> {
  const res = await fetch("/api/auth/yahoo/code", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ code }),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || "Failed exchanging Yahoo authorization code");
  }
  return res.json();
}

export async function connectYahooCookie(cookieOrCurl: string): Promise<any> {
  const res = await fetch("/api/auth/yahoo/cookie", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ cookie_or_curl: cookieOrCurl }),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || "Failed connecting Yahoo session cookie");
  }
  return res.json();
}
