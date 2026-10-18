import React, { useEffect, useState } from "react";
import {
  Activity,
  AlertTriangle,
  ArrowRightLeft,
  Calendar,
  CheckCircle2,
  Clock,
  Code2,
  ExternalLink,
  Mail,
  Play,
  RefreshCw,
  Send,
  Settings,
  ShieldCheck,
  Sparkles,
  Trophy,
  UserPlus,
  Users,
  Zap,
} from "lucide-react";
import {
  applyLeagueOptimalLineup,
  connectYahooCookie,
  exchangeYahooCode,
  fetchLeagueDetail,
  fetchLeagueTeams,
  fetchOverview,
  fetchSettings,
  getYahooAuthorizeUrl,
  saveSettings,
  sendDigestEmailNow,
  triggerSync,
  updateLeagueExecutionMode,
} from "./api";
import {
  AppSettings,
  LeagueDetailResponse,
  LeagueTeamsResponse,
  OverviewResponse,
  RosterPlayer,
} from "./types";

type ActiveTab = "lineup" | "waivers" | "teams" | "schedule" | "email" | "settings";

export default function App() {
  const [overview, setOverview] = useState<OverviewResponse | null>(null);
  const [selectedLeagueKey, setSelectedLeagueKey] = useState<string>("");
  const [leagueDetail, setLeagueDetail] = useState<LeagueDetailResponse | null>(null);
  const [leagueTeams, setLeagueTeams] = useState<LeagueTeamsResponse | null>(null);
  const [loadingTeams, setLoadingTeams] = useState<boolean>(false);
  const [selectedScoutTeamKey, setSelectedScoutTeamKey] = useState<string>("");
  const [activeTab, setActiveTab] = useState<ActiveTab>("lineup");
  const [posFilter, setPosFilter] = useState<string>("ALL");
  const [showXmlPreview, setShowXmlPreview] = useState<boolean>(false);

  const [loading, setLoading] = useState<boolean>(true);
  const [syncing, setSyncing] = useState<boolean>(false);
  const [applyingLineup, setApplyingLineup] = useState<boolean>(false);
  const [sendingEmail, setSendingEmail] = useState<boolean>(false);
  const [bannerMsg, setBannerMsg] = useState<{ type: "success" | "info" | "error"; text: string } | null>(null);

  const [settingsForm, setSettingsForm] = useState<AppSettings | null>(null);
  const [yahooAuthCode, setYahooAuthCode] = useState<string>("");
  const [yahooCookieInput, setYahooCookieInput] = useState<string>("");
  const [connectingCookie, setConnectingCookie] = useState<boolean>(false);
  const [emailPreviewKey, setEmailPreviewKey] = useState<number>(Date.now());

  async function loadLeagueTeams(leagueKey: string) {
    if (!leagueKey) return;
    try {
      setLoadingTeams(true);
      const data = await fetchLeagueTeams(leagueKey);
      setLeagueTeams(data);
      const opp = data.teams.find((t) => t.is_current_opponent);
      const firstOther = data.teams.find((t) => !t.is_my_team);
      const defaultTeam = opp || firstOther || data.teams[0];
      if (defaultTeam) {
        setSelectedScoutTeamKey(defaultTeam.team_key);
      }
    } catch (err: any) {
      setBannerMsg({ type: "error", text: err.message || "Failed loading league teams" });
    } finally {
      setLoadingTeams(false);
    }
  }

  async function loadAll(preferredKey?: string) {
    try {
      setLoading(true);
      const ov = await fetchOverview();
      setOverview(ov);
      const targetKey =
        preferredKey ||
        selectedLeagueKey ||
        (ov.leagues.length > 0 ? ov.leagues[0].league_key : "");
      if (targetKey) {
        setSelectedLeagueKey(targetKey);
        const detail = await fetchLeagueDetail(targetKey);
        setLeagueDetail(detail);
        if (activeTab === "teams") {
          await loadLeagueTeams(targetKey);
        } else {
          setLeagueTeams(null);
        }
      }
      const st = await fetchSettings();
      setSettingsForm(st);
      setEmailPreviewKey(Date.now());
    } catch (err: any) {
      setBannerMsg({ type: "error", text: err.message || "Failed loading dashboard" });
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    loadAll();
  }, []);

  async function handleSelectLeague(leagueKey: string) {
    setSelectedLeagueKey(leagueKey);
    try {
      const detail = await fetchLeagueDetail(leagueKey);
      setLeagueDetail(detail);
      if (activeTab === "teams") {
        await loadLeagueTeams(leagueKey);
      } else {
        setLeagueTeams(null);
      }
    } catch (err: any) {
      setBannerMsg({ type: "error", text: err.message });
    }
  }

  async function handleSyncNow(sendEmail = false) {
    try {
      setSyncing(true);
      setBannerMsg(null);
      const res = await triggerSync(sendEmail);
      await loadAll(selectedLeagueKey);
      setBannerMsg({
        type: "success",
        text: `Synced ${res.leagues_processed} leagues against FantasyPros Weekly ECR: ${res.total_swaps_recommended} lineup swap(s) & ${res.total_fa_upgrades} waiver upgrade(s) found.`,
      });
    } catch (err: any) {
      setBannerMsg({ type: "error", text: err.message || "Sync failed" });
    } finally {
      setSyncing(false);
    }
  }

  async function handleToggleExecutionMode(leagueKey: string, currentMode: "advisory" | "auto_lineup") {
    const nextMode = currentMode === "advisory" ? "auto_lineup" : "advisory";
    try {
      await updateLeagueExecutionMode(leagueKey, nextMode);
      await loadAll(leagueKey);
      setBannerMsg({
        type: "info",
        text: `Updated league mode to ${nextMode === "auto_lineup" ? "Auto-Lineup (Automatically sets optimal starters)" : "Advisory Only (Email + Web recommendations)"}.`,
      });
    } catch (err: any) {
      setBannerMsg({ type: "error", text: err.message });
    }
  }

  async function handleApplyOptimalLineup() {
    if (!selectedLeagueKey) return;
    try {
      setApplyingLineup(true);
      const res = await applyLeagueOptimalLineup(selectedLeagueKey);
      await loadAll(selectedLeagueKey);
      const simNote = res.yahoo_response?.simulated
        ? `(Simulated in ${res.yahoo_response.reason === "demo_league" ? "Demo Mode" : "Dry-Run Mode"} — Yahoo XML payload verified)`
        : "(Executed live on Yahoo Fantasy API!)";
      setBannerMsg({
        type: "success",
        text: `Applied ${res.swaps_applied} optimal lineup swap(s) for ${res.league_name} ${simNote}`,
      });
    } catch (err: any) {
      setBannerMsg({ type: "error", text: err.message });
    } finally {
      setApplyingLineup(false);
    }
  }

  async function handleSendEmailNow() {
    try {
      setSendingEmail(true);
      const res = await sendDigestEmailNow();
      if (res.sent) {
        setBannerMsg({ type: "success", text: res.message });
      } else {
        setBannerMsg({ type: "info", text: res.message });
      }
    } catch (err: any) {
      setBannerMsg({ type: "error", text: err.message });
    } finally {
      setSendingEmail(false);
    }
  }

  async function handleSaveSettings(e: React.FormEvent) {
    e.preventDefault();
    if (!settingsForm) return;
    try {
      const updated = await saveSettings(settingsForm);
      setSettingsForm(updated);
      await loadAll(selectedLeagueKey);
      setBannerMsg({ type: "success", text: "Settings saved and daily scheduler updated." });
    } catch (err: any) {
      setBannerMsg({ type: "error", text: err.message });
    }
  }

  async function handleStartYahooOAuth() {
    try {
      if (!settingsForm?.yahoo_client_id?.trim()) {
        setBannerMsg({
          type: "error",
          text: "Yahoo Client ID is missing! First create a free app at developer.yahoo.com/apps, paste your Client ID & Client Secret in Section 1 below, and click '1. Save & Authorize with Yahoo'.",
        });
        return;
      }
      // Auto-save current form values (Client ID, Secret, Redirect URI) before generating OAuth URL
      const updated = await saveSettings(settingsForm);
      setSettingsForm(updated);

      const url = await getYahooAuthorizeUrl();
      window.open(url, "_blank", "noopener,noreferrer");
      setBannerMsg({
        type: "info",
        text: "Opened Yahoo login in a new tab. After approving, copy either the verification code OR the entire redirected URL (https://localhost:8000/?code=...) from that tab's address bar and paste it in Step 2.",
      });
    } catch (err: any) {
      setBannerMsg({ type: "error", text: err.message });
    }
  }

  async function handleExchangeYahooCode() {
    if (!yahooAuthCode.trim()) return;
    try {
      if (settingsForm) {
        await saveSettings(settingsForm);
      }
      await exchangeYahooCode(yahooAuthCode.trim());
      setYahooAuthCode("");
      await loadAll();
      setBannerMsg({ type: "success", text: "Yahoo OAuth connected! Synced live Yahoo leagues." });
    } catch (err: any) {
      setBannerMsg({ type: "error", text: err.message });
    }
  }

  async function handleConnectYahooCookie() {
    if (!yahooCookieInput.trim()) return;
    try {
      setConnectingCookie(true);
      setBannerMsg(null);
      const res = await connectYahooCookie(yahooCookieInput.trim());
      setYahooCookieInput("");
      await loadAll();
      setBannerMsg({
        type: "success",
        text: `Connected Yahoo Session & synced ${res.sync_result?.leagues_processed ?? 0} real Yahoo league(s)!`,
      });
      setActiveTab("lineup");
    } catch (err: any) {
      setBannerMsg({ type: "error", text: err.message });
    } finally {
      setConnectingCookie(false);
    }
  }

  function renderStatusBadge(status: string) {
    const s = (status || "Healthy").toUpperCase();
    if (s === "HEALTHY") {
      return (
        <span className="inline-flex items-center px-2 py-0.5 rounded text-xs font-medium bg-emerald-950/80 text-emerald-300 border border-emerald-800/60">
          Healthy
        </span>
      );
    }
    if (s === "BYE") {
      return (
        <span className="inline-flex items-center px-2 py-0.5 rounded text-xs font-bold bg-amber-950/90 text-amber-300 border border-amber-700/70">
          BYE WEEK
        </span>
      );
    }
    if (s === "O" || s === "OUT" || s === "IR") {
      return (
        <span className="inline-flex items-center px-2 py-0.5 rounded text-xs font-bold bg-rose-950/90 text-rose-300 border border-rose-700/70">
          {s}
        </span>
      );
    }
    return (
      <span className="inline-flex items-center px-2 py-0.5 rounded text-xs font-bold bg-yellow-950/90 text-yellow-300 border border-yellow-700/70">
        {s}
      </span>
    );
  }

  if (loading && !overview) {
    return (
      <div className="min-h-screen bg-slate-950 flex items-center justify-center text-slate-300">
        <div className="flex items-center gap-3">
          <RefreshCw className="w-6 h-6 animate-spin text-indigo-400" />
          <span className="text-lg font-medium">Loading Yahoo Fantasy Football Autopilot...</span>
        </div>
      </div>
    );
  }

  const totalSwapsAllLeagues =
    overview?.leagues.reduce((acc, lg) => acc + lg.pending_swaps_count, 0) ?? 0;
  const totalFaUpgradesAllLeagues =
    overview?.leagues.reduce((acc, lg) => acc + lg.fa_upgrades_count, 0) ?? 0;

  const filteredFreeAgents =
    leagueDetail?.free_agents.filter((fa) => posFilter === "ALL" || fa.position === posFilter) ?? [];

  return (
    <div className="min-h-screen bg-slate-950 text-slate-100 pb-16">
      {/* Top Navigation Bar */}
      <header className="sticky top-0 z-30 border-b border-slate-800/80 bg-slate-950/90 backdrop-blur-md">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 py-3.5 flex flex-wrap items-center justify-between gap-4">
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 rounded-xl bg-gradient-to-br from-indigo-500 to-violet-600 flex items-center justify-center shadow-lg shadow-indigo-500/20">
              <Zap className="w-5 h-5 text-white" />
            </div>
            <div>
              <div className="flex items-center gap-2">
                <h1 className="text-lg font-bold tracking-tight text-white">
                  Fantasy Football Autopilot
                </h1>
                <span className="text-xs px-2.5 py-0.5 rounded-full font-semibold bg-indigo-950 text-indigo-300 border border-indigo-800/60">
                  Yahoo + FantasyPros ECR
                </span>
                {overview?.oauth.connected ? (
                  <span className="text-xs px-2.5 py-0.5 rounded-full font-semibold bg-emerald-950 text-emerald-300 border border-emerald-800/60">
                    Yahoo Live Connected
                  </span>
                ) : (
                  <span className="text-xs px-2.5 py-0.5 rounded-full font-semibold bg-amber-950/80 text-amber-300 border border-amber-800/60">
                    Multi-League Demo Active
                  </span>
                )}
              </div>
              <p className="text-xs text-slate-400 flex flex-wrap items-center gap-3 mt-0.5">
                <span className="inline-flex items-center gap-1">
                  <Clock className="w-3.5 h-3.5 text-slate-500" />
                  Daily: {overview?.scheduler.daily_sync_time}
                  {overview?.scheduler.pre_game_sync_enabled !== false && (
                    <span className="text-indigo-400 font-medium">
                      + {overview?.scheduler.pre_game_minutes_before ?? 5}m Pre-Kickoff
                    </span>
                  )}{" "}
                  ({overview?.scheduler.timezone})
                </span>
                {overview?.scheduler.scheduled_jobs && overview.scheduler.scheduled_jobs.length > 0 && (
                  <>
                    <span>•</span>
                    <span className="text-slate-300">
                      Next Check:{" "}
                      <strong className="text-indigo-300">
                        {overview.scheduler.scheduled_jobs[0].label}
                      </strong>
                    </span>
                  </>
                )}
                <span>•</span>
                <span className="inline-flex items-center gap-1">
                  <ShieldCheck className="w-3.5 h-3.5 text-emerald-400" />
                  {overview?.scheduler.dry_run
                    ? "Safety Mode: Dry-Run Enabled"
                    : "Live Yahoo Write Enabled"}
                </span>
              </p>
            </div>
          </div>

          <div className="flex items-center gap-2.5">
            <button
              onClick={() => handleSyncNow(false)}
              disabled={syncing}
              className="inline-flex items-center gap-2 px-3.5 py-2 rounded-lg text-sm font-semibold bg-indigo-600 hover:bg-indigo-500 disabled:opacity-50 text-white shadow-sm transition cursor-pointer"
            >
              <RefreshCw className={`w-4 h-4 ${syncing ? "animate-spin" : ""}`} />
              {syncing ? "Syncing Rankings..." : "Run Daily Check Now"}
            </button>

            <button
              onClick={() => setActiveTab("email")}
              className={`inline-flex items-center gap-1.5 px-3 py-2 rounded-lg text-sm font-medium border transition cursor-pointer ${
                activeTab === "email"
                  ? "bg-slate-800 text-white border-indigo-500"
                  : "bg-slate-900/90 hover:bg-slate-800 text-slate-200 border-slate-800"
              }`}
            >
              <Mail className="w-4 h-4 text-indigo-400" />
              Daily Email Preview
            </button>

            <button
              onClick={() => setActiveTab("settings")}
              className={`inline-flex items-center gap-1.5 px-3 py-2 rounded-lg text-sm font-medium border transition cursor-pointer ${
                activeTab === "settings"
                  ? "bg-slate-800 text-white border-indigo-500"
                  : "bg-slate-900/90 hover:bg-slate-800 text-slate-200 border-slate-800"
              }`}
            >
              <Settings className="w-4 h-4 text-slate-400" />
              Settings &amp; OAuth
            </button>
          </div>
        </div>
      </header>

      <main className="max-w-7xl mx-auto px-4 sm:px-6 pt-6 space-y-6">
        {/* Status Banner */}
        {bannerMsg && (
          <div
            className={`p-4 rounded-xl border flex items-center justify-between gap-4 ${
              bannerMsg.type === "success"
                ? "bg-emerald-950/60 border-emerald-800 text-emerald-200"
                : bannerMsg.type === "error"
                ? "bg-rose-950/60 border-rose-800 text-rose-200"
                : "bg-indigo-950/60 border-indigo-800 text-indigo-200"
            }`}
          >
            <div className="flex items-center gap-2.5 text-sm font-medium">
              <Sparkles className="w-4 h-4 shrink-0" />
              <span>{bannerMsg.text}</span>
            </div>
            <button
              onClick={() => setBannerMsg(null)}
              className="text-xs opacity-75 hover:opacity-100 underline cursor-pointer"
            >
              Dismiss
            </button>
          </div>
        )}

        {/* Multi-League Selector Cards */}
        <div>
          <div className="flex items-center justify-between mb-3">
            <h2 className="text-xs font-bold uppercase tracking-wider text-slate-400">
              Your Yahoo Fantasy Leagues ({overview?.leagues.length ?? 0}) —{" "}
              <span className="text-emerald-400">{totalSwapsAllLeagues} Lineup Swaps</span> &amp;{" "}
              <span className="text-amber-400">{totalFaUpgradesAllLeagues} Waiver Upgrades</span> Available
            </h2>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
            {overview?.leagues.map((lg) => {
              const isSelected = lg.league_key === selectedLeagueKey;
              return (
                <div
                  key={lg.league_key}
                  onClick={() => {
                    handleSelectLeague(lg.league_key);
                    if (activeTab === "settings" || activeTab === "email") {
                      setActiveTab("lineup");
                    }
                  }}
                  className={`rounded-2xl p-4 border transition cursor-pointer relative overflow-hidden ${
                    isSelected
                      ? "bg-slate-900 border-indigo-500 shadow-lg shadow-indigo-950/50 ring-1 ring-indigo-500/50"
                      : "bg-slate-900/50 border-slate-800/90 hover:border-slate-700 hover:bg-slate-900/80"
                  }`}
                >
                  <div className="flex items-center justify-between gap-2 mb-2">
                    <span className="text-[11px] font-bold uppercase tracking-wide px-2 py-0.5 rounded bg-indigo-950/90 text-indigo-300 border border-indigo-800/60">
                      {lg.scoring_label} • Wk {lg.current_week}
                    </span>

                    <button
                      onClick={(e) => {
                        e.stopPropagation();
                        handleToggleExecutionMode(lg.league_key, lg.execution_mode);
                      }}
                      title="Click to toggle between Advisory Only and Auto-Lineup mode"
                      className={`text-[11px] font-semibold px-2 py-0.5 rounded border transition cursor-pointer ${
                        lg.execution_mode === "auto_lineup"
                          ? "bg-emerald-950 text-emerald-300 border-emerald-700"
                          : "bg-slate-800 text-slate-300 border-slate-700 hover:border-slate-500"
                      }`}
                    >
                      {lg.execution_mode === "auto_lineup" ? "⚡ Auto-Lineup" : "📩 Advisory Mode"}
                    </button>
                  </div>

                  <h3 className="font-bold text-base text-white truncate">{lg.name}</h3>
                  <div className="flex items-center justify-between text-xs text-slate-400 mt-1">
                    <span>
                      <strong className="text-slate-200">{lg.team_name}</strong> ({lg.team_record})
                    </span>
                    <span>
                      Rank #{lg.team_standing} of {lg.num_teams}
                    </span>
                  </div>

                  {/* Projections Comparison Bar */}
                  <div className="mt-3 pt-3 border-t border-slate-800/80 flex items-center justify-between text-xs">
                    <div>
                      <span className="text-slate-400">Proj: </span>
                      <span className="font-semibold text-slate-200">{lg.current_proj.toFixed(1)}</span>
                      <span className="mx-1 text-slate-500">&rarr;</span>
                      <span className="font-bold text-emerald-400">{lg.optimal_proj.toFixed(1)} pts</span>
                    </div>
                    {lg.net_gain > 0 ? (
                      <span className="px-2 py-0.5 rounded-full font-bold bg-emerald-950 text-emerald-300 border border-emerald-800/70">
                        +{lg.net_gain.toFixed(1)} pts
                      </span>
                    ) : (
                      <span className="px-2 py-0.5 rounded-full font-semibold bg-slate-800 text-emerald-400">
                        ✓ Optimal
                      </span>
                    )}
                  </div>

                  {/* Action Badges */}
                  <div className="mt-2.5 flex items-center gap-2 flex-wrap">
                    {lg.pending_swaps_count > 0 && (
                      <span className="inline-flex items-center gap-1 text-[11px] font-semibold px-2 py-0.5 rounded bg-indigo-950/90 text-indigo-300">
                        <ArrowRightLeft className="w-3 h-3" />
                        {lg.pending_swaps_count} Swap{lg.pending_swaps_count > 1 ? "s" : ""}
                      </span>
                    )}
                    {lg.injury_alerts_count > 0 && (
                      <span className="inline-flex items-center gap-1 text-[11px] font-semibold px-2 py-0.5 rounded bg-rose-950/90 text-rose-300">
                        <AlertTriangle className="w-3 h-3" />
                        {lg.injury_alerts_count} Starter Alert{lg.injury_alerts_count > 1 ? "s" : ""}
                      </span>
                    )}
                    {lg.fa_upgrades_count > 0 && (
                      <span className="inline-flex items-center gap-1 text-[11px] font-semibold px-2 py-0.5 rounded bg-amber-950/90 text-amber-300">
                        <UserPlus className="w-3 h-3" />
                        {lg.fa_upgrades_count} FA Upgrade{lg.fa_upgrades_count > 1 ? "s" : ""}
                      </span>
                    )}
                  </div>
                </div>
              );
            })}
          </div>
        </div>

        {/* Navigation Tabs */}
        <div className="border-b border-slate-800 flex items-center justify-between flex-wrap gap-3">
          <div className="flex items-center gap-1">
            <button
              onClick={() => setActiveTab("lineup")}
              className={`px-4 py-2.5 text-sm font-semibold border-b-2 transition flex items-center gap-2 cursor-pointer ${
                activeTab === "lineup"
                  ? "border-indigo-500 text-white"
                  : "border-transparent text-slate-400 hover:text-slate-200"
              }`}
            >
              <ArrowRightLeft className="w-4 h-4" />
              Lineup Optimizer
              {leagueDetail && leagueDetail.swaps.length > 0 && (
                <span className="px-1.5 py-0.2 rounded-full text-xs bg-indigo-600 text-white">
                  {leagueDetail.swaps.length}
                </span>
              )}
            </button>

            <button
              onClick={() => setActiveTab("waivers")}
              className={`px-4 py-2.5 text-sm font-semibold border-b-2 transition flex items-center gap-2 cursor-pointer ${
                activeTab === "waivers"
                  ? "border-indigo-500 text-white"
                  : "border-transparent text-slate-400 hover:text-slate-200"
              }`}
            >
              <UserPlus className="w-4 h-4" />
              Free Agent Upgrades
              {leagueDetail && leagueDetail.free_agents.length > 0 && (
                <span className="px-1.5 py-0.2 rounded-full text-xs bg-amber-600 text-white">
                  {leagueDetail.free_agents.length}
                </span>
              )}
            </button>

            <button
              onClick={() => {
                setActiveTab("teams");
                if (
                  selectedLeagueKey &&
                  (!leagueTeams || leagueTeams.league_key !== selectedLeagueKey)
                ) {
                  loadLeagueTeams(selectedLeagueKey);
                }
              }}
              className={`px-4 py-2.5 text-sm font-semibold border-b-2 transition flex items-center gap-2 cursor-pointer ${
                activeTab === "teams"
                  ? "border-indigo-500 text-white"
                  : "border-transparent text-slate-400 hover:text-slate-200"
              }`}
            >
              <Users className="w-4 h-4" />
              League Teams &amp; Scouting
            </button>

            <button
              onClick={() => setActiveTab("schedule")}
              className={`px-4 py-2.5 text-sm font-semibold border-b-2 transition flex items-center gap-2 cursor-pointer ${
                activeTab === "schedule"
                  ? "border-indigo-500 text-white"
                  : "border-transparent text-slate-400 hover:text-slate-200"
              }`}
            >
              <Calendar className="w-4 h-4" />
              Matchup &amp; Schedule
            </button>

            <button
              onClick={() => setActiveTab("email")}
              className={`px-4 py-2.5 text-sm font-semibold border-b-2 transition flex items-center gap-2 cursor-pointer ${
                activeTab === "email"
                  ? "border-indigo-500 text-white"
                  : "border-transparent text-slate-400 hover:text-slate-200"
              }`}
            >
              <Mail className="w-4 h-4" />
              Daily Email Digest
            </button>

            <button
              onClick={() => setActiveTab("settings")}
              className={`px-4 py-2.5 text-sm font-semibold border-b-2 transition flex items-center gap-2 cursor-pointer ${
                activeTab === "settings"
                  ? "border-indigo-500 text-white"
                  : "border-transparent text-slate-400 hover:text-slate-200"
              }`}
            >
              <Settings className="w-4 h-4" />
              Settings &amp; OAuth
            </button>
          </div>
        </div>

        {/* TAB 1: LINEUP OPTIMIZER */}
        {activeTab === "lineup" && leagueDetail && (
          <div className="space-y-6">
            {/* Recommended Swaps Action Card */}
            <div className="rounded-2xl bg-slate-900 border border-slate-800 p-5">
              <div className="flex flex-wrap items-center justify-between gap-4 mb-4">
                <div>
                  <h3 className="text-base font-bold text-white flex items-center gap-2">
                    <Sparkles className="w-5 h-5 text-indigo-400" />
                    Recommended Starting Lineup Swaps — {leagueDetail.league.name}
                  </h3>
                  <p className="text-xs text-slate-400 mt-0.5">
                    Optimized for {leagueDetail.league.scoring_label} using FantasyPros Weekly Expert Consensus Rankings (ECR)
                  </p>
                </div>

                <div className="flex items-center gap-2.5">
                  <button
                    onClick={() => setShowXmlPreview(!showXmlPreview)}
                    className="inline-flex items-center gap-1.5 px-3 py-2 rounded-lg text-xs font-semibold bg-slate-800 hover:bg-slate-700 text-slate-200 border border-slate-700 transition cursor-pointer"
                  >
                    <Code2 className="w-4 h-4 text-indigo-400" />
                    {showXmlPreview ? "Hide Yahoo API XML" : "Inspect Yahoo PUT XML"}
                  </button>

                  {leagueDetail.swaps.length > 0 && (
                    <button
                      onClick={handleApplyOptimalLineup}
                      disabled={applyingLineup}
                      className="inline-flex items-center gap-2 px-4 py-2 rounded-lg text-xs font-bold bg-emerald-600 hover:bg-emerald-500 disabled:opacity-50 text-white shadow-sm transition cursor-pointer"
                    >
                      <Play className="w-4 h-4" />
                      {applyingLineup
                        ? "Applying to Yahoo..."
                        : `Apply ${leagueDetail.swaps.length} Swap(s) (+${leagueDetail.league.net_gain.toFixed(1)} pts)`}
                    </button>
                  )}
                </div>
              </div>

              {showXmlPreview && (
                <div className="mb-4 p-3.5 rounded-xl bg-slate-950 border border-slate-800 text-xs font-mono text-indigo-300 overflow-x-auto">
                  <div className="text-slate-400 mb-1.5 font-sans">
                    Official Yahoo Fantasy v2 API Payload (<code>PUT /fantasy/v2/team/{leagueDetail.league.team_key}/roster</code>):
                  </div>
                  <pre>{leagueDetail.yahoo_xml_preview}</pre>
                </div>
              )}

              {leagueDetail.swaps.length > 0 ? (
                <div className="grid grid-cols-1 md:grid-cols-2 gap-3.5">
                  {leagueDetail.swaps.map((sw, idx) => (
                    <div
                      key={idx}
                      className="rounded-xl bg-slate-950/90 border border-slate-800 p-4 flex flex-col justify-between gap-3"
                    >
                      <div className="flex items-center justify-between">
                        <span className="px-2.5 py-0.5 rounded text-xs font-bold bg-indigo-950 text-indigo-300 border border-indigo-800">
                          Target Slot: {sw.slot}
                        </span>
                        <span className="text-sm font-bold text-emerald-400">
                          +{sw.points_delta.toFixed(1)} Proj Pts
                        </span>
                      </div>

                      <div className="grid grid-cols-2 gap-3 pt-1">
                        {/* Player OUT */}
                        <div className="p-2.5 rounded-lg bg-rose-950/25 border border-rose-900/50">
                          <div className="text-[10px] font-bold uppercase tracking-wider text-rose-400">
                            Move to Bench
                          </div>
                          <div className="font-bold text-sm text-white mt-0.5">
                            {sw.player_out.name}
                          </div>
                          <div className="text-xs text-slate-400 mt-0.5 flex items-center gap-1.5 flex-wrap">
                            <span>{sw.player_out.team} • {sw.player_out.position}</span>
                            {renderStatusBadge(sw.player_out.status)}
                          </div>
                          <div className="mt-1.5 text-xs font-semibold text-rose-300">
                            {sw.player_out.fp_proj.toFixed(1)} pts ({sw.player_out.fp_pos_rank})
                          </div>
                        </div>

                        {/* Player IN */}
                        <div className="p-2.5 rounded-lg bg-emerald-950/25 border border-emerald-900/50">
                          <div className="text-[10px] font-bold uppercase tracking-wider text-emerald-400">
                            Switch into {sw.slot}
                          </div>
                          <div className="font-bold text-sm text-white mt-0.5">
                            {sw.player_in.name}
                          </div>
                          <div className="text-xs text-slate-400 mt-0.5 flex items-center gap-1.5 flex-wrap">
                            <span>{sw.player_in.team} • {sw.player_in.position}</span>
                            {renderStatusBadge(sw.player_in.status)}
                          </div>
                          <div className="mt-1.5 text-xs font-semibold text-emerald-300">
                            {sw.player_in.fp_proj.toFixed(1)} pts ({sw.player_in.fp_pos_rank})
                          </div>
                        </div>
                      </div>

                      <p className="text-xs text-slate-300 bg-slate-900/90 px-3 py-2 rounded-lg border border-slate-800/80">
                        {sw.reason}
                      </p>
                    </div>
                  ))}
                </div>
              ) : (
                <div className="p-4 rounded-xl bg-emerald-950/30 border border-emerald-800/60 flex items-center gap-3 text-emerald-200 text-sm">
                  <CheckCircle2 className="w-5 h-5 text-emerald-400 shrink-0" />
                  <span>
                    Your current Yahoo starting lineup is already 100% optimal according to FantasyPros Weekly ECR!
                  </span>
                </div>
              )}

              {/* Starter Injury / Questionable Alerts Callout */}
              {(() => {
                const flaggedStarters = leagueDetail.roster.filter(
                  (p) =>
                    p.is_starter_current &&
                    ["O", "OUT", "IR", "D", "Q", "BYE"].includes((p.status || "").toUpperCase())
                );
                if (flaggedStarters.length === 0) return null;
                return (
                  <div className="mt-3 p-3.5 rounded-xl bg-amber-950/30 border border-amber-800/60 flex items-start gap-3 text-amber-200 text-xs">
                    <AlertTriangle className="w-4 h-4 text-amber-400 shrink-0 mt-0.5" />
                    <div className="space-y-1">
                      <div className="font-bold text-amber-300">
                        {flaggedStarters.length} Starter Status Alert{flaggedStarters.length > 1 ? "s" : ""} (Monitor Pre-Game Inactives):
                      </div>
                      <div className="text-slate-300 flex flex-wrap gap-2">
                        {flaggedStarters.map((st) => (
                          <span
                            key={st.player_key}
                            className="inline-flex items-center gap-1.5 px-2 py-0.5 rounded bg-slate-950/80 border border-amber-800/50"
                          >
                            <strong className="text-white">{st.name}</strong>
                            <span className="text-slate-400">({st.current_slot})</span>
                            {renderStatusBadge(st.status)}
                            <span className="text-emerald-400 font-semibold">{st.fp_proj.toFixed(1)} pts</span>
                            {st.game_time ? <span className="text-slate-400">• {st.game_time}</span> : null}
                          </span>
                        ))}
                      </div>
                      <div className="text-[11px] text-slate-400">
                        Questionable starters with strong FantasyPros projections remain in your optimal lineup unless downgraded to Out before kickoff.
                      </div>
                    </div>
                  </div>
                );
              })()}
            </div>

            {/* Full Team Roster Table */}
            <div className="rounded-2xl bg-slate-900 border border-slate-800 overflow-hidden">
              <div className="px-5 py-4 border-b border-slate-800 flex items-center justify-between">
                <h3 className="text-sm font-bold uppercase tracking-wider text-slate-300">
                  Full Team Roster &amp; FantasyPros Weekly Projections
                </h3>
                <div className="text-xs text-slate-400">
                  Current Total: <strong className="text-slate-200">{leagueDetail.league.current_proj.toFixed(1)} pts</strong>
                  {" • "}
                  Optimal Total: <strong className="text-emerald-400">{leagueDetail.league.optimal_proj.toFixed(1)} pts</strong>
                </div>
              </div>

              <div className="overflow-x-auto">
                <table className="w-full text-left border-collapse text-sm">
                  <thead>
                    <tr className="bg-slate-950/80 text-slate-400 text-xs uppercase border-b border-slate-800">
                      <th className="py-3 px-4">Current Slot</th>
                      <th className="py-3 px-4">Optimal Slot</th>
                      <th className="py-3 px-4">Player</th>
                      <th className="py-3 px-4">Status</th>
                      <th className="py-3 px-4">Matchup</th>
                      <th className="py-3 px-4">Weekly / ROS ECR</th>
                      <th className="py-3 px-4 text-right">FP Proj</th>
                      <th className="py-3 px-4 text-right">Action</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-800/70">
                    {leagueDetail.roster.map((p: RosterPlayer) => {
                      const isPromote = p.action_needed === "promote_to_starter";
                      const isBench = p.action_needed === "bench_player";
                      return (
                        <tr
                          key={p.player_key}
                          className={
                            isPromote
                              ? "bg-emerald-950/20 hover:bg-emerald-950/30"
                              : isBench
                              ? "bg-rose-950/20 hover:bg-rose-950/30"
                              : "hover:bg-slate-800/40"
                          }
                        >
                          <td className="py-3 px-4 font-bold text-xs">
                            <span
                              className={`px-2 py-0.5 rounded ${
                                p.current_slot === "BN" || p.current_slot === "IR"
                                  ? "bg-slate-800 text-slate-400"
                                  : "bg-indigo-950 text-indigo-300 border border-indigo-800/60"
                              }`}
                            >
                              {p.current_slot}
                            </span>
                          </td>
                          <td className="py-3 px-4 font-bold text-xs">
                            <span
                              className={`px-2 py-0.5 rounded ${
                                p.optimal_slot === "BN" || p.optimal_slot === "IR"
                                  ? "bg-slate-800 text-slate-400"
                                  : "bg-emerald-950 text-emerald-300 border border-emerald-800/60"
                              }`}
                            >
                              {p.optimal_slot}
                            </span>
                          </td>
                          <td className="py-3 px-4">
                            <div className="font-semibold text-white">{p.name}</div>
                            <div className="text-xs text-slate-400">
                              {p.team} • {p.position}
                              {p.injury_note ? ` • ${p.injury_note}` : ""}
                            </div>
                          </td>
                          <td className="py-3 px-4">{renderStatusBadge(p.status)}</td>
                          <td className="py-3 px-4 text-xs text-slate-300">
                            <div>{p.opponent || "—"}</div>
                            {p.is_locked || (p.game_time && p.game_time.includes("Locked")) ? (
                              <div className="inline-flex items-center gap-1 mt-0.5 px-1.5 py-0.5 rounded text-[10px] font-bold bg-amber-950/80 text-amber-300 border border-amber-800/70">
                                🔒 {p.game_time || "Played (Locked)"}
                              </div>
                            ) : (
                              <div className="text-slate-500">{p.game_time}</div>
                            )}
                          </td>
                          <td className="py-3 px-4 text-xs">
                            <div>
                              <span className="font-semibold text-slate-200">{p.fp_pos_rank}</span>
                              <span className="ml-1 text-slate-400">Wk</span>
                            </div>
                            {p.ros_pos_rank && !p.ros_pos_rank.endsWith("--") && (
                              <div className="text-[11px] text-indigo-300 mt-0.5">
                                ROS: {p.ros_pos_rank}
                                {p.ros_ecr && p.ros_ecr < 400 ? ` (#${p.ros_ecr})` : ""}
                              </div>
                            )}
                          </td>
                          <td className="py-3 px-4 text-right font-bold text-emerald-400">
                            {p.fp_proj.toFixed(1)}
                          </td>
                          <td className="py-3 px-4 text-right text-xs">
                            {p.is_locked || (p.game_time && p.game_time.includes("Locked")) ? (
                              <span className="px-2.5 py-1 rounded-full font-semibold bg-slate-800 text-amber-300 border border-slate-700">
                                🔒 Locked ({p.current_slot})
                              </span>
                            ) : isPromote ? (
                              <span className="px-2.5 py-1 rounded-full font-bold bg-emerald-950 text-emerald-300 border border-emerald-700">
                                &uarr; Start at {p.optimal_slot}
                              </span>
                            ) : isBench ? (
                              <span className="px-2.5 py-1 rounded-full font-bold bg-rose-950 text-rose-300 border border-rose-700">
                                &darr; Move to Bench
                              </span>
                            ) : p.is_starter_current &&
                              ["O", "OUT", "IR", "D", "Q", "BYE"].includes((p.status || "").toUpperCase()) ? (
                              <span className="px-2.5 py-1 rounded-full font-semibold bg-amber-950/60 text-amber-300 border border-amber-800/70">
                                ⚠ Monitor {p.status} ({p.current_slot})
                              </span>
                            ) : (
                              <span className="text-slate-500">Keep ({p.current_slot})</span>
                            )}
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            </div>
          </div>
        )}

        {/* TAB 2: FREE AGENT & WAIVER UPGRADES */}
        {activeTab === "waivers" && leagueDetail && (
          <div className="rounded-2xl bg-slate-900 border border-slate-800 overflow-hidden">
            <div className="p-5 border-b border-slate-800 flex flex-wrap items-center justify-between gap-4">
              <div>
                <h3 className="text-base font-bold text-white flex items-center gap-2">
                  <UserPlus className="w-5 h-5 text-amber-400" />
                  Free Agent &amp; Waiver Wire Upgrades — {leagueDetail.league.name}
                </h3>
                <p className="text-xs text-slate-400 mt-0.5">
                  Weighs both FantasyPros Weekly Projections and Rest-of-Season (ROS) Rankings so injured/bye studs are protected (FAAB: ${leagueDetail.league.faab_balance})
                </p>
              </div>

              <div className="flex items-center gap-1.5">
                {["ALL", "QB", "RB", "WR", "TE", "K", "DEF"].map((pos) => (
                  <button
                    key={pos}
                    onClick={() => setPosFilter(pos)}
                    className={`px-2.5 py-1 rounded-lg text-xs font-semibold transition cursor-pointer ${
                      posFilter === pos
                        ? "bg-indigo-600 text-white"
                        : "bg-slate-800 text-slate-300 hover:bg-slate-700"
                    }`}
                  >
                    {pos}
                  </button>
                ))}
              </div>
            </div>

            {filteredFreeAgents.length > 0 ? (
              <div className="overflow-x-auto">
                <table className="w-full text-left border-collapse text-sm">
                  <thead>
                    <tr className="bg-slate-950/80 text-slate-400 text-xs uppercase border-b border-slate-800">
                      <th className="py-3 px-4">Available Player</th>
                      <th className="py-3 px-4">Availability</th>
                      <th className="py-3 px-4">Wk / ROS ECR</th>
                      <th className="py-3 px-4 text-right">FP Proj</th>
                      <th className="py-3 px-4">Suggested Drop</th>
                      <th className="py-3 px-4">Upgrade Type</th>
                      <th className="py-3 px-4">Recommendation Rationale</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-800/70">
                    {filteredFreeAgents.map((fa) => (
                      <tr key={fa.player_key} className="hover:bg-slate-800/40">
                        <td className="py-3.5 px-4">
                          <div className="font-bold text-white">{fa.name}</div>
                          <div className="text-xs text-slate-400">
                            {fa.team} • {fa.position} • {fa.opponent}
                          </div>
                        </td>
                        <td className="py-3.5 px-4 text-xs">
                          <span
                            className={`px-2 py-0.5 rounded font-bold ${
                              fa.availability_type === "FA"
                                ? "bg-emerald-950 text-emerald-300 border border-emerald-800"
                                : "bg-amber-950 text-amber-300 border border-amber-800"
                            }`}
                          >
                            {fa.availability_type}
                          </span>
                          <span className="ml-2 text-slate-400">{fa.percent_owned.toFixed(0)}% Owned</span>
                        </td>
                        <td className="py-3.5 px-4 text-xs">
                          <div>
                            <span className="font-semibold text-slate-200">{fa.fp_pos_rank}</span>
                            <span className="ml-1 text-slate-400">Wk</span>
                          </div>
                          {fa.ros_pos_rank && !fa.ros_pos_rank.endsWith("--") && (
                            <div className="text-[11px] text-indigo-300 mt-0.5">
                              ROS: {fa.ros_pos_rank}
                              {fa.ros_ecr && fa.ros_ecr < 400 ? ` (#${fa.ros_ecr})` : ""}
                            </div>
                          )}
                        </td>
                        <td className="py-3.5 px-4 text-right font-bold text-emerald-400">
                          {fa.fp_proj.toFixed(1)}
                        </td>
                        <td className="py-3.5 px-4 text-xs">
                          <div className="font-semibold text-rose-300">
                            - {fa.recommended_drop_player_name}
                          </div>
                          <div className="text-slate-500">
                            {fa.recommended_drop_player_ros_rank
                              ? `${fa.recommended_drop_player_ros_rank} ROS • `
                              : ""}
                            {fa.recommended_drop_player_proj.toFixed(1)} pts Wk
                          </div>
                        </td>
                        <td className="py-3.5 px-4 text-xs">
                          {fa.recommendation_type === "starter_upgrade" ? (
                            <span className="px-2.5 py-1 rounded-full font-bold bg-emerald-950 text-emerald-300 border border-emerald-700">
                              Starter +{fa.net_starter_gain.toFixed(1)} pts
                            </span>
                          ) : (
                            <span className="px-2.5 py-1 rounded-full font-semibold bg-indigo-950 text-indigo-300 border border-indigo-800">
                              Bench +{fa.net_bench_gain.toFixed(1)} pts
                            </span>
                          )}
                        </td>
                        <td className="py-3.5 px-4 text-xs text-slate-300 max-w-md">
                          {fa.rationale}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : (
              <div className="p-8 text-center text-slate-400 text-sm">
                No free agent upgrades found for position filter {posFilter}.
              </div>
            )}
          </div>
        )}

        {/* TAB: LEAGUE TEAMS & SCOUTING */}
        {activeTab === "teams" && leagueDetail && (
          <div className="space-y-6">
            <div className="rounded-2xl bg-slate-900 border border-slate-800 overflow-hidden">
              <div className="p-5 border-b border-slate-800 flex flex-wrap items-center justify-between gap-4">
                <div>
                  <h3 className="text-base font-bold text-white flex items-center gap-2">
                    <Users className="w-5 h-5 text-indigo-400" />
                    League Standings &amp; Lineup Health Check — {leagueDetail.league.name}
                  </h3>
                  <p className="text-xs text-slate-400 mt-0.5">
                    Click any team below to inspect their starting lineup, bench, FantasyPros Weekly &amp; ROS ECR, and unmade start/sit swaps
                  </p>
                </div>

                <button
                  onClick={() => loadLeagueTeams(selectedLeagueKey)}
                  disabled={loadingTeams}
                  className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-semibold bg-slate-800 hover:bg-slate-700 text-slate-200 border border-slate-700 transition cursor-pointer"
                >
                  <RefreshCw className={`w-3.5 h-3.5 ${loadingTeams ? "animate-spin" : ""}`} />
                  {loadingTeams ? "Checking Teams..." : "Refresh All Teams"}
                </button>
              </div>

              {loadingTeams && !leagueTeams ? (
                <div className="p-10 text-center text-slate-400 text-sm">
                  Fetching live rosters and lineup health for all {leagueDetail.league.num_teams} teams...
                </div>
              ) : leagueTeams && leagueTeams.teams.length > 0 ? (
                <div className="overflow-x-auto">
                  <table className="w-full text-left border-collapse text-sm">
                    <thead>
                      <tr className="bg-slate-950/80 text-slate-400 text-xs uppercase border-b border-slate-800">
                        <th className="py-3 px-4">Rank</th>
                        <th className="py-3 px-4">Team &amp; Manager</th>
                        <th className="py-3 px-4">Record</th>
                        <th className="py-3 px-4">PF / PA</th>
                        <th className="py-3 px-4">Wk {leagueTeams.current_week} Proj (Cur &rarr; Opt)</th>
                        <th className="py-3 px-4">Top-100 ROS</th>
                        <th className="py-3 px-4">Lineup Status</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-slate-800/70">
                      {leagueTeams.teams.map((tm) => {
                        const isInspected = tm.team_key === selectedScoutTeamKey;
                        return (
                          <tr
                            key={tm.team_key}
                            onClick={() => setSelectedScoutTeamKey(tm.team_key)}
                            className={`cursor-pointer transition ${
                              isInspected
                                ? "bg-indigo-950/40 ring-1 ring-inset ring-indigo-500/60"
                                : "hover:bg-slate-800/50"
                            }`}
                          >
                            <td className="py-3 px-4 font-bold text-slate-200">#{tm.rank}</td>
                            <td className="py-3 px-4">
                              <div className="flex items-center gap-2 flex-wrap">
                                <span className="font-bold text-white">{tm.team_name}</span>
                                {tm.is_my_team && (
                                  <span className="px-1.5 py-0.5 rounded text-[10px] font-bold bg-indigo-600 text-white">
                                    YOU
                                  </span>
                                )}
                                {tm.is_current_opponent && (
                                  <span className="px-1.5 py-0.5 rounded text-[10px] font-bold bg-amber-600 text-white">
                                    WK {leagueTeams.current_week} OPPONENT
                                  </span>
                                )}
                              </div>
                              <div className="text-xs text-slate-400">
                                Mgr: {tm.manager_name} • {tm.number_of_moves} moves
                              </div>
                            </td>
                            <td className="py-3 px-4 text-xs">
                              <span className="font-semibold text-slate-200">{tm.record}</span>
                              {tm.streak && (
                                <span className="ml-1.5 text-slate-400">({tm.streak})</span>
                              )}
                            </td>
                            <td className="py-3 px-4 text-xs text-slate-300">
                              <span className="font-semibold text-slate-200">{tm.points_for.toFixed(1)}</span>
                              <span className="text-slate-500"> / {tm.points_against.toFixed(1)}</span>
                            </td>
                            <td className="py-3 px-4 text-xs">
                              <span className="font-semibold text-slate-200">{tm.current_proj.toFixed(1)}</span>
                              <span className="mx-1 text-slate-500">&rarr;</span>
                              <span className="font-bold text-emerald-400">{tm.optimal_proj.toFixed(1)}</span>
                              {tm.points_left_on_bench > 0.5 && (
                                <span className="ml-1.5 text-amber-300 font-semibold">
                                  (+{tm.points_left_on_bench.toFixed(1)} on BN)
                                </span>
                              )}
                            </td>
                            <td className="py-3 px-4 text-xs font-semibold text-indigo-300">
                              {tm.top100_ros_count} players
                            </td>
                            <td className="py-3 px-4 text-xs">
                              <span
                                className={`inline-flex items-center px-2.5 py-1 rounded-full font-semibold border ${
                                  tm.status_severity === "alert"
                                    ? "bg-rose-950/80 text-rose-200 border-rose-800"
                                    : tm.status_severity === "warning"
                                    ? "bg-amber-950/80 text-amber-200 border-amber-800"
                                    : "bg-emerald-950/70 text-emerald-300 border-emerald-800/70"
                                }`}
                              >
                                {tm.status_summary}
                              </span>
                            </td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </div>
              ) : null}
            </div>

            {/* Selected Team Roster & Lineup Inspector */}
            {leagueTeams &&
              (() => {
                const inspected = leagueTeams.teams.find((t) => t.team_key === selectedScoutTeamKey);
                if (!inspected) return null;
                return (
                  <div className="rounded-2xl bg-slate-900 border border-slate-800 overflow-hidden">
                    <div className="p-5 border-b border-slate-800 flex flex-wrap items-center justify-between gap-4">
                      <div>
                        <div className="flex items-center gap-2">
                          <h4 className="text-base font-bold text-white">
                            {inspected.team_name} — Full Roster &amp; Lineup Audit
                          </h4>
                          <span className="text-xs px-2 py-0.5 rounded bg-slate-800 text-slate-300">
                            Rank #{inspected.rank} ({inspected.record}) • Mgr: {inspected.manager_name}
                          </span>
                        </div>
                        <p className="text-xs text-slate-400 mt-1">
                          Current Lineup: <strong className="text-slate-200">{inspected.current_proj.toFixed(1)} pts</strong>
                          {" • "}
                          Optimal Lineup: <strong className="text-emerald-400">{inspected.optimal_proj.toFixed(1)} pts</strong>
                          {" • "}
                          {inspected.swaps.length > 0
                            ? `${inspected.swaps.length} unmade start/sit swap(s) (+${inspected.points_left_on_bench.toFixed(1)} pts left on bench)`
                            : "Starting lineup is currently optimal"}
                        </p>
                      </div>
                    </div>

                    {inspected.swaps.length > 0 && (
                      <div className="px-5 py-3 bg-amber-950/20 border-b border-slate-800 space-y-1.5">
                        <div className="text-xs font-bold uppercase tracking-wider text-amber-300">
                          Unmade Lineup Swaps on {inspected.team_name}:
                        </div>
                        {inspected.swaps.map((sw, idx) => (
                          <div key={idx} className="text-xs text-slate-300">
                            • <strong>{sw.slot}</strong>: Should start{" "}
                            <span className="text-emerald-300 font-semibold">
                              {sw.player_in.name} ({sw.player_in.fp_proj.toFixed(1)} pts)
                            </span>{" "}
                            over{" "}
                            <span className="text-rose-300 font-semibold">
                              {sw.player_out.name} ({sw.player_out.fp_proj.toFixed(1)} pts, {sw.player_out.status})
                            </span>{" "}
                            (+{sw.points_delta.toFixed(1)} pts)
                          </div>
                        ))}
                      </div>
                    )}

                    <div className="overflow-x-auto">
                      <table className="w-full text-left border-collapse text-sm">
                        <thead>
                          <tr className="bg-slate-950/80 text-slate-400 text-xs uppercase border-b border-slate-800">
                            <th className="py-2.5 px-4">Current Slot</th>
                            <th className="py-2.5 px-4">Optimal Slot</th>
                            <th className="py-2.5 px-4">Player</th>
                            <th className="py-2.5 px-4">Status</th>
                            <th className="py-2.5 px-4">Weekly / ROS ECR</th>
                            <th className="py-2.5 px-4 text-right">FP Proj</th>
                          </tr>
                        </thead>
                        <tbody className="divide-y divide-slate-800/70">
                          {inspected.roster.map((p) => (
                            <tr key={p.player_key} className="hover:bg-slate-800/40">
                              <td className="py-2.5 px-4 font-bold text-xs">
                                <span
                                  className={`px-2 py-0.5 rounded ${
                                    p.current_slot === "BN" || p.current_slot === "IR"
                                      ? "bg-slate-800 text-slate-400"
                                      : "bg-indigo-950 text-indigo-300 border border-indigo-800/60"
                                  }`}
                                >
                                  {p.current_slot}
                                </span>
                              </td>
                              <td className="py-2.5 px-4 font-bold text-xs">
                                <span
                                  className={`px-2 py-0.5 rounded ${
                                    p.optimal_slot === "BN" || p.optimal_slot === "IR"
                                      ? "bg-slate-800 text-slate-400"
                                      : "bg-emerald-950 text-emerald-300 border border-emerald-800/60"
                                  }`}
                                >
                                  {p.optimal_slot}
                                </span>
                              </td>
                              <td className="py-2.5 px-4">
                                <div className="font-semibold text-white flex items-center gap-2">
                                  <span>{p.name}</span>
                                  {(p.is_locked || (p.game_time && p.game_time.includes("Locked"))) && (
                                    <span className="px-1.5 py-0.5 rounded text-[10px] font-bold bg-amber-950/80 text-amber-300 border border-amber-800/70">
                                      🔒 {p.game_time || "Played (Locked)"}
                                    </span>
                                  )}
                                </div>
                                <div className="text-xs text-slate-400">
                                  {p.team} • {p.position}
                                  {p.opponent ? ` • ${p.opponent}` : ""}
                                  {!p.is_locked && p.game_time ? ` (${p.game_time})` : ""}
                                  {p.injury_note ? ` • ${p.injury_note}` : ""}
                                </div>
                              </td>
                              <td className="py-2.5 px-4">{renderStatusBadge(p.status)}</td>
                              <td className="py-2.5 px-4 text-xs">
                                <div>
                                  <span className="font-semibold text-slate-200">{p.fp_pos_rank}</span>
                                  <span className="ml-1 text-slate-400">Wk</span>
                                </div>
                                {p.ros_pos_rank && !p.ros_pos_rank.endsWith("--") && (
                                  <div className="text-[11px] text-indigo-300 mt-0.5">
                                    ROS: {p.ros_pos_rank}
                                    {p.ros_ecr && p.ros_ecr < 400 ? ` (#${p.ros_ecr})` : ""}
                                  </div>
                                )}
                              </td>
                              <td className="py-2.5 px-4 text-right font-bold text-emerald-400">
                                {p.fp_proj.toFixed(1)}
                              </td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  </div>
                );
              })()}
          </div>
        )}

        {/* TAB 3: MATCHUP & SCHEDULE */}
        {activeTab === "schedule" && leagueDetail && (
          <div className="space-y-6">
            <div className="rounded-2xl bg-slate-900 border border-slate-800 p-5">
              <h3 className="text-base font-bold text-white flex items-center gap-2 mb-4">
                <Trophy className="w-5 h-5 text-amber-400" />
                Week {leagueDetail.matchup.week} Head-to-Head Matchup Projection
              </h3>

              <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
                <div className="p-4 rounded-xl bg-slate-950 border border-slate-800">
                  <div className="text-xs text-slate-400 uppercase font-semibold">
                    {leagueDetail.league.team_name} (You)
                  </div>
                  <div className="mt-2 flex items-baseline gap-2">
                    <span className="text-2xl font-extrabold text-emerald-400">
                      {leagueDetail.matchup.my_optimal_projected_points.toFixed(1)}
                    </span>
                    <span className="text-xs text-slate-400">
                      optimal pts (current: {leagueDetail.matchup.my_projected_points.toFixed(1)})
                    </span>
                  </div>
                </div>

                <div className="p-4 rounded-xl bg-slate-950 border border-slate-800 flex flex-col justify-center items-center">
                  <div className="text-xs text-slate-400 uppercase font-semibold">
                    Optimal Win Probability
                  </div>
                  <div className="text-2xl font-extrabold text-indigo-400 mt-1">
                    {leagueDetail.matchup.win_probability.toFixed(0)}%
                  </div>
                  <div className="w-full bg-slate-800 h-2 rounded-full mt-2 overflow-hidden">
                    <div
                      className="bg-gradient-to-r from-indigo-500 to-emerald-400 h-full"
                      style={{ width: `${leagueDetail.matchup.win_probability}%` }}
                    />
                  </div>
                </div>

                <div className="p-4 rounded-xl bg-slate-950 border border-slate-800">
                  <div className="text-xs text-slate-400 uppercase font-semibold">
                    Opponent: {leagueDetail.matchup.opponent_team_name} ({leagueDetail.matchup.opponent_record})
                  </div>
                  <div className="mt-2 flex items-baseline gap-2">
                    <span className="text-2xl font-extrabold text-slate-200">
                      {leagueDetail.matchup.opponent_projected_points.toFixed(1)}
                    </span>
                    <span className="text-xs text-slate-400">projected pts</span>
                  </div>
                </div>
              </div>
            </div>

            <div className="rounded-2xl bg-slate-900 border border-slate-800 overflow-hidden">
              <div className="px-5 py-4 border-b border-slate-800">
                <h3 className="text-sm font-bold uppercase tracking-wider text-slate-300">
                  Season Schedule &amp; Weekly Results
                </h3>
              </div>
              <div className="overflow-x-auto">
                <table className="w-full text-left border-collapse text-sm">
                  <thead>
                    <tr className="bg-slate-950/80 text-slate-400 text-xs uppercase border-b border-slate-800">
                      <th className="py-3 px-4">Week</th>
                      <th className="py-3 px-4">Opponent</th>
                      <th className="py-3 px-4">Your Score / Proj</th>
                      <th className="py-3 px-4">Opponent Score / Proj</th>
                      <th className="py-3 px-4 text-right">Result / Status</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-800/70">
                    {leagueDetail.matchup.schedule.map((wk) => {
                      const isCurrent = wk.week === leagueDetail.league.current_week;
                      const isPast = wk.status === "postevent";
                      const won = isPast && wk.my_points > wk.opponent_points;
                      return (
                        <tr
                          key={wk.week}
                          className={isCurrent ? "bg-indigo-950/30 font-semibold" : "hover:bg-slate-800/40"}
                        >
                          <td className="py-3 px-4">
                            Week {wk.week}{" "}
                            {isCurrent && (
                              <span className="ml-1.5 px-2 py-0.5 rounded text-[10px] bg-indigo-600 text-white">
                                CURRENT
                              </span>
                            )}
                          </td>
                          <td className="py-3 px-4 text-white">{wk.opponent_name}</td>
                          <td className="py-3 px-4">
                            {isPast ? (
                              <span className="text-slate-200">{wk.my_points.toFixed(1)} pts</span>
                            ) : (
                              <span className="text-emerald-400">{wk.my_projected.toFixed(1)} proj</span>
                            )}
                          </td>
                          <td className="py-3 px-4">
                            {isPast ? (
                              <span className="text-slate-300">{wk.opponent_points.toFixed(1)} pts</span>
                            ) : (
                              <span className="text-slate-400">{wk.opponent_projected.toFixed(1)} proj</span>
                            )}
                          </td>
                          <td className="py-3 px-4 text-right">
                            {isPast ? (
                              <span
                                className={`px-2.5 py-0.5 rounded text-xs font-bold ${
                                  won
                                    ? "bg-emerald-950 text-emerald-300 border border-emerald-800"
                                    : "bg-rose-950 text-rose-300 border border-rose-800"
                                }`}
                              >
                                {won ? "WIN" : "LOSS"} ({(wk.my_points - wk.opponent_points > 0 ? "+" : "") + (wk.my_points - wk.opponent_points).toFixed(1)})
                              </span>
                            ) : (
                              <span className="text-xs text-indigo-300">
                                Proj Edge: {(wk.my_projected - wk.opponent_projected >= 0 ? "+" : "") + (wk.my_projected - wk.opponent_projected).toFixed(1)}
                              </span>
                            )}
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            </div>
          </div>
        )}

        {/* TAB 4: DAILY EMAIL DIGEST PREVIEW */}
        {activeTab === "email" && (
          <div className="space-y-4">
            <div className="rounded-2xl bg-slate-900 border border-slate-800 p-5 flex flex-wrap items-center justify-between gap-4">
              <div>
                <h3 className="text-base font-bold text-white flex items-center gap-2">
                  <Mail className="w-5 h-5 text-indigo-400" />
                  Daily Multi-League Email Briefing
                </h3>
                <p className="text-xs text-slate-400 mt-0.5">
                  Subject: <strong className="text-slate-200">{overview?.latest_run?.email_subject}</strong>
                </p>
              </div>

              <button
                onClick={handleSendEmailNow}
                disabled={sendingEmail}
                className="inline-flex items-center gap-2 px-4 py-2 rounded-lg text-xs font-bold bg-indigo-600 hover:bg-indigo-500 disabled:opacity-50 text-white shadow-sm transition cursor-pointer"
              >
                <Send className="w-4 h-4" />
                {sendingEmail ? "Sending via Gmail SMTP..." : "Send Email Digest Now"}
              </button>
            </div>

            <div className="rounded-2xl overflow-hidden border border-slate-800 bg-slate-900 h-[760px]">
              <iframe
                key={emailPreviewKey}
                src="/api/runs/latest/email-preview"
                title="Daily Email Digest Preview"
                className="w-full h-full border-0"
              />
            </div>
          </div>
        )}

        {/* TAB 5: SETTINGS & YAHOO OAUTH */}
        {activeTab === "settings" && settingsForm && (
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
            <form
              onSubmit={handleSaveSettings}
              className="rounded-2xl bg-slate-900 border border-slate-800 p-6 space-y-5"
            >
              <div>
                <h3 className="text-base font-bold text-white flex items-center gap-2">
                  <Settings className="w-5 h-5 text-indigo-400" />
                  Yahoo OAuth, Gmail SMTP &amp; Scheduler Configuration
                </h3>
                <p className="text-xs text-slate-400 mt-0.5">
                  Persisted in SQLite (<code>/data/autopilot.db</code>) so settings survive Docker/Unraid container updates.
                </p>
              </div>

              {/* Yahoo Section */}
              <div className="space-y-3 pt-2 border-t border-slate-800">
                <h4 className="text-xs font-bold uppercase tracking-wider text-indigo-400">
                  1. Yahoo Developer Application (OAuth 2.0)
                </h4>
                <div>
                  <label className="block text-xs text-slate-300 mb-1">Yahoo Client ID</label>
                  <input
                    type="text"
                    value={settingsForm.yahoo_client_id}
                    onChange={(e) =>
                      setSettingsForm({ ...settingsForm, yahoo_client_id: e.target.value })
                    }
                    placeholder="dj0yJmk9..."
                    className="w-full px-3 py-2 rounded-lg bg-slate-950 border border-slate-800 text-sm text-white"
                  />
                </div>
                <div>
                  <label className="block text-xs text-slate-300 mb-1">Yahoo Client Secret</label>
                  <input
                    type="password"
                    value={settingsForm.yahoo_client_secret}
                    onChange={(e) =>
                      setSettingsForm({ ...settingsForm, yahoo_client_secret: e.target.value })
                    }
                    placeholder="Enter Yahoo Client Secret"
                    className="w-full px-3 py-2 rounded-lg bg-slate-950 border border-slate-800 text-sm text-white"
                  />
                </div>
                <div>
                  <div className="flex items-center justify-between mb-1">
                    <label className="block text-xs text-slate-300">
                      Redirect URI (Must match your Yahoo App exactly)
                    </label>
                    <div className="flex items-center gap-1.5 text-[11px]">
                      <button
                        type="button"
                        onClick={() =>
                          setSettingsForm({
                            ...settingsForm,
                            yahoo_redirect_uri: "https://localhost:8000",
                          })
                        }
                        className="px-2 py-0.5 rounded bg-slate-800 hover:bg-slate-700 text-indigo-300 cursor-pointer"
                      >
                        Use https://localhost:8000
                      </button>
                      <button
                        type="button"
                        onClick={() =>
                          setSettingsForm({
                            ...settingsForm,
                            yahoo_redirect_uri: "oob",
                          })
                        }
                        className="px-2 py-0.5 rounded bg-slate-800 hover:bg-slate-700 text-indigo-300 cursor-pointer"
                      >
                        Use oob
                      </button>
                    </div>
                  </div>
                  <input
                    type="text"
                    value={settingsForm.yahoo_redirect_uri}
                    onChange={(e) =>
                      setSettingsForm({ ...settingsForm, yahoo_redirect_uri: e.target.value })
                    }
                    className="w-full px-3 py-2 rounded-lg bg-slate-950 border border-slate-800 text-sm text-white"
                  />
                  <p className="text-[11px] text-slate-400 mt-1">
                    Note: Yahoo Developer Console requires <code>https://</code> (e.g.{" "}
                    <code>https://localhost:8000</code>) when creating a web app.
                  </p>
                </div>
              </div>

              {/* Gmail SMTP Section */}
              <div className="space-y-3 pt-3 border-t border-slate-800">
                <h4 className="text-xs font-bold uppercase tracking-wider text-indigo-400">
                  2. Gmail SMTP (App Password)
                </h4>
                <div className="grid grid-cols-2 gap-3">
                  <div>
                    <label className="block text-xs text-slate-300 mb-1">SMTP Host</label>
                    <input
                      type="text"
                      value={settingsForm.smtp_host}
                      onChange={(e) =>
                        setSettingsForm({ ...settingsForm, smtp_host: e.target.value })
                      }
                      className="w-full px-3 py-2 rounded-lg bg-slate-950 border border-slate-800 text-sm text-white"
                    />
                  </div>
                  <div>
                    <label className="block text-xs text-slate-300 mb-1">SMTP Port</label>
                    <input
                      type="number"
                      value={settingsForm.smtp_port}
                      onChange={(e) =>
                        setSettingsForm({
                          ...settingsForm,
                          smtp_port: parseInt(e.target.value || "587", 10),
                        })
                      }
                      className="w-full px-3 py-2 rounded-lg bg-slate-950 border border-slate-800 text-sm text-white"
                    />
                  </div>
                </div>
                <div>
                  <label className="block text-xs text-slate-300 mb-1">Gmail Address (SMTP Username)</label>
                  <input
                    type="email"
                    value={settingsForm.smtp_username}
                    onChange={(e) =>
                      setSettingsForm({ ...settingsForm, smtp_username: e.target.value })
                    }
                    placeholder="you@gmail.com"
                    className="w-full px-3 py-2 rounded-lg bg-slate-950 border border-slate-800 text-sm text-white"
                  />
                </div>
                <div>
                  <label className="block text-xs text-slate-300 mb-1">
                    Gmail 16-Character App Password
                  </label>
                  <input
                    type="password"
                    value={settingsForm.smtp_app_password}
                    onChange={(e) =>
                      setSettingsForm({ ...settingsForm, smtp_app_password: e.target.value })
                    }
                    placeholder="xxxx xxxx xxxx xxxx"
                    className="w-full px-3 py-2 rounded-lg bg-slate-950 border border-slate-800 text-sm text-white"
                  />
                </div>
                <div>
                  <label className="block text-xs text-slate-300 mb-1">Recipient Email (To)</label>
                  <input
                    type="text"
                    value={settingsForm.email_to}
                    onChange={(e) =>
                      setSettingsForm({ ...settingsForm, email_to: e.target.value })
                    }
                    placeholder="you@gmail.com"
                    className="w-full px-3 py-2 rounded-lg bg-slate-950 border border-slate-800 text-sm text-white"
                  />
                </div>
              </div>

              {/* Scheduler & Safety Section */}
              <div className="space-y-3 pt-3 border-t border-slate-800">
                <h4 className="text-xs font-bold uppercase tracking-wider text-indigo-400">
                  3. Daily Schedule, Game-Day Pre-Kickoff Checks &amp; Safety
                </h4>
                <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                  <div>
                    <label className="block text-xs text-slate-300 mb-1">
                      Daily Check Time(s) <span className="text-slate-500">(24h, comma-separated)</span>
                    </label>
                    <input
                      type="text"
                      value={settingsForm.daily_sync_time}
                      onChange={(e) =>
                        setSettingsForm({ ...settingsForm, daily_sync_time: e.target.value })
                      }
                      placeholder="08:00, 12:00"
                      className="w-full px-3 py-2 rounded-lg bg-slate-950 border border-slate-800 text-sm text-white"
                    />
                    <div className="text-[11px] text-slate-500 mt-1">
                      Always runs once a day (or at each listed time, e.g. <code>08:00, 12:00</code>).
                    </div>
                  </div>
                  <div>
                    <label className="block text-xs text-slate-300 mb-1">Timezone</label>
                    <input
                      type="text"
                      value={settingsForm.timezone}
                      onChange={(e) =>
                        setSettingsForm({ ...settingsForm, timezone: e.target.value })
                      }
                      placeholder="America/New_York"
                      className="w-full px-3 py-2 rounded-lg bg-slate-950 border border-slate-800 text-sm text-white"
                    />
                  </div>
                </div>

                <div className="p-3.5 rounded-xl bg-slate-950 border border-slate-800 space-y-2.5">
                  <div className="flex flex-wrap items-center justify-between gap-3">
                    <label className="flex items-center gap-3 cursor-pointer">
                      <input
                        type="checkbox"
                        checked={settingsForm.pre_game_sync_enabled ?? true}
                        onChange={(e) =>
                          setSettingsForm({
                            ...settingsForm,
                            pre_game_sync_enabled: e.target.checked,
                          })
                        }
                        className="w-4 h-4 rounded accent-indigo-600"
                      />
                      <span className="text-xs text-slate-200 font-semibold">
                        ⚡ Game-Day Pre-Kickoff Checks (Check before every NFL kickoff window)
                      </span>
                    </label>

                    <div className="flex items-center gap-2 text-xs text-slate-300">
                      <span>Run</span>
                      <input
                        type="number"
                        min={1}
                        max={60}
                        value={settingsForm.pre_game_minutes_before ?? 5}
                        onChange={(e) =>
                          setSettingsForm({
                            ...settingsForm,
                            pre_game_minutes_before: Math.max(1, parseInt(e.target.value || "5", 10)),
                          })
                        }
                        className="w-16 px-2 py-1 rounded bg-slate-900 border border-slate-700 text-center text-white font-bold"
                      />
                      <span>min before kickoff</span>
                    </div>
                  </div>
                  <p className="text-[11px] text-slate-400">
                    Automatically detects every NFL game kickoff window each week (TNF, Sunday London/Early/Late/SNF, MNF, Saturday) and runs a fresh check right before kickoff to catch late inactive announcements.
                  </p>

                  {overview?.scheduler.scheduled_jobs && overview.scheduler.scheduled_jobs.length > 0 && (
                    <div className="pt-2 border-t border-slate-800/80">
                      <div className="text-[11px] font-bold uppercase tracking-wider text-slate-400 mb-1.5">
                        Upcoming Scheduled Checks ({overview.scheduler.scheduled_jobs.length})
                      </div>
                      <div className="flex flex-wrap gap-1.5">
                        {overview.scheduler.scheduled_jobs.map((job) => (
                          <span
                            key={job.id}
                            title={job.teams && job.teams.length > 0 ? `Teams: ${job.teams.join(", ")}` : job.label}
                            className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-lg text-[11px] font-medium border ${
                              job.type === "pre_kickoff"
                                ? "bg-indigo-950/60 text-indigo-200 border-indigo-800/60"
                                : "bg-emerald-950/50 text-emerald-200 border-emerald-800/60"
                            }`}
                          >
                            {job.type === "pre_kickoff" ? "🏈" : "⏰"} {job.label}
                            {job.teams && job.teams.length > 0 && (
                              <span className="text-slate-400">({job.teams.length} teams)</span>
                            )}
                          </span>
                        ))}
                      </div>
                    </div>
                  )}
                </div>

                <label className="flex items-center gap-3 pt-1 cursor-pointer">
                  <input
                    type="checkbox"
                    checked={settingsForm.dry_run}
                    onChange={(e) =>
                      setSettingsForm({ ...settingsForm, dry_run: e.target.checked })
                    }
                    className="w-4 h-4 rounded accent-indigo-600"
                  />
                  <span className="text-xs text-slate-300">
                    <strong>Dry-Run Safety Switch</strong> (When checked, Yahoo roster updates are simulated and logged without modifying your live Yahoo lineup)
                  </span>
                </label>
              </div>

              <button
                type="submit"
                className="w-full py-2.5 rounded-lg bg-indigo-600 hover:bg-indigo-500 text-white font-bold text-sm shadow transition cursor-pointer"
              >
                Save Configuration
              </button>
            </form>

            {/* Yahoo Connection Helper Cards */}
            <div className="space-y-6">
              {/* Instant Cookie / Copy-as-cURL Bypass Card */}
              <div className="rounded-2xl bg-slate-900 border border-emerald-700/70 p-6 space-y-4 shadow-lg shadow-emerald-950/30">
                <div className="flex items-center justify-between gap-2">
                  <h3 className="text-base font-bold text-white flex items-center gap-2">
                    <Zap className="w-5 h-5 text-emerald-400" />
                    Instant Yahoo Session Connect (Bypasses Yahoo's 403 App Gate)
                  </h3>
                  <span className="text-[11px] font-bold px-2.5 py-0.5 rounded-full bg-emerald-950 text-emerald-300 border border-emerald-700">
                    Recommended
                  </span>
                </div>

                <p className="text-xs text-slate-300 leading-relaxed">
                  Yahoo places a backend <code>403 ("This application is not authorized")</code> gate on newly created Developer App keys until Yahoo Support manually whitelists your Client ID. You can bypass that gate immediately using Yahoo's web API (<code>pub-api-ro.fantasysports.yahoo.com</code>):
                </p>

                <ol className="text-xs text-slate-300 space-y-2 list-decimal list-inside">
                  <li>
                    Open{" "}
                    <a
                      href="https://football.fantasysports.yahoo.com"
                      target="_blank"
                      rel="noreferrer"
                      className="text-emerald-400 underline font-semibold"
                    >
                      football.fantasysports.yahoo.com
                    </a>{" "}
                    in your browser while logged in.
                  </li>
                  <li>
                    Open <strong>Developer Tools</strong> (<code>Cmd+Option+I</code> or Right-Click &rarr; Inspect) and click the <strong>Network</strong> tab.
                  </li>
                  <li>
                    Refresh the page, right-click the first request to <code>football.fantasysports.yahoo.com</code>, and choose <strong>Copy &rarr; Copy as cURL</strong>.
                  </li>
                  <li>
                    Paste the copied <code>curl</code> command (or raw <code>Cookie</code> header) below and click <strong>Connect &amp; Sync My Leagues</strong>!
                  </li>
                </ol>

                <div className="space-y-2.5 pt-1">
                  <textarea
                    rows={3}
                    value={yahooCookieInput}
                    onChange={(e) => setYahooCookieInput(e.target.value)}
                    placeholder="Paste 'Copy as cURL' command (curl 'https://football.fantasysports.yahoo.com/...' -H 'cookie: ...') or Cookie string here..."
                    className="w-full px-3 py-2 rounded-lg bg-slate-950 border border-slate-800 text-xs font-mono text-white"
                  />
                  <button
                    type="button"
                    onClick={handleConnectYahooCookie}
                    disabled={connectingCookie}
                    className="w-full py-2.5 rounded-lg text-xs font-bold bg-emerald-600 hover:bg-emerald-500 disabled:opacity-50 text-white transition cursor-pointer shadow"
                  >
                    {connectingCookie
                      ? "Connecting & Syncing Your Yahoo Leagues..."
                      : "Connect Yahoo Session & Sync My Leagues"}
                  </button>
                </div>
              </div>

              {/* OAuth 2.0 Card */}
              <div className="rounded-2xl bg-slate-900 border border-slate-800 p-6 space-y-4">
                <h3 className="text-sm font-bold text-slate-200 flex items-center gap-2">
                  <Activity className="w-4 h-4 text-indigo-400" />
                  Alternative: Yahoo Developer OAuth 2.0 (Requires Yahoo App Whitelisting)
                </h3>
                <ol className="text-xs text-slate-400 space-y-2 list-decimal list-inside">
                  <li>
                    Create an app at{" "}
                    <a
                      href="https://developer.yahoo.com/apps/create/"
                      target="_blank"
                      rel="noreferrer"
                      className="text-indigo-400 underline"
                    >
                      developer.yahoo.com/apps/create
                    </a>{" "}
                    with Redirect URI <code>https://localhost:8000</code> and <strong>Fantasy Sports</strong> permission.
                  </li>
                  <li>
                    Click <strong>1. Save &amp; Authorize with Yahoo</strong>, approve access, and paste the redirected <code>https://localhost:8000/?code=...</code> URL into Step 2.
                  </li>
                </ol>

                <div className="pt-1 flex flex-wrap gap-3">
                  <button
                    type="button"
                    onClick={handleStartYahooOAuth}
                    className="inline-flex items-center gap-2 px-4 py-2 rounded-lg text-xs font-bold bg-violet-600 hover:bg-violet-500 text-white transition cursor-pointer"
                  >
                    <ExternalLink className="w-4 h-4" />
                    1. Save &amp; Authorize with Yahoo
                  </button>
                </div>

                <div className="pt-3 border-t border-slate-800 space-y-2">
                  <label className="block text-xs text-slate-300">
                    2. Paste Redirected URL (<code>https://localhost:8000/?code=...</code>) or Verification Code:
                  </label>
                  <div className="flex gap-2">
                    <input
                      type="text"
                      value={yahooAuthCode}
                      onChange={(e) => setYahooAuthCode(e.target.value)}
                      placeholder="Paste full URL (https://localhost:8000/?code=...) or code here"
                      className="flex-1 px-3 py-2 rounded-lg bg-slate-950 border border-slate-800 text-sm text-white"
                    />
                    <button
                      type="button"
                      onClick={handleExchangeYahooCode}
                      className="px-4 py-2 rounded-lg text-xs font-bold bg-indigo-600 hover:bg-indigo-500 text-white transition cursor-pointer"
                    >
                      Connect Token
                    </button>
                  </div>
                </div>
              </div>
            </div>
          </div>
        )}
      </main>
    </div>
  );
}
