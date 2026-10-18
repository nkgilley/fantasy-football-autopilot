export interface LeagueSummary {
  league_key: string;
  name: string;
  season: number;
  current_week: number;
  scoring_type: string;
  scoring_label: string;
  num_teams: number;
  team_key: string;
  team_name: string;
  team_record: string;
  team_standing: number;
  points_for: number;
  points_against: number;
  faab_balance: number;
  execution_mode: "advisory" | "auto_lineup";
  is_demo: boolean;
  last_synced_at: string | null;
  current_proj: number;
  optimal_proj: number;
  net_gain: number;
  pending_swaps_count: number;
  injury_alerts_count: number;
  fa_upgrades_count: number;
  starter_fa_upgrades_count: number;
  matchup: {
    week: number;
    opponent_team_name: string;
    opponent_record: string;
    opponent_projected_points: number;
    win_probability: number;
  };
}

export interface RosterPlayer {
  player_key: string;
  name: string;
  team: string;
  position: string;
  eligible_positions: string[];
  current_slot: string;
  optimal_slot: string;
  status: string;
  injury_note: string;
  bye_week: number;
  opponent: string;
  game_time: string;
  is_locked?: boolean;
  yahoo_proj: number;
  fp_ecr: number;
  fp_pos_rank: string;
  fp_proj: number;
  fp_tier: number;
  ros_ecr: number;
  ros_pos_rank: string;
  is_starter_current: boolean;
  is_starter_optimal: boolean;
  action_needed: "keep" | "promote_to_starter" | "bench_player";
  swap_reason: string;
}

export interface LineupSwap {
  slot: string;
  player_in: RosterPlayer;
  player_out: RosterPlayer;
  points_delta: number;
  reason: string;
}

export interface FreeAgentCandidate {
  player_key: string;
  name: string;
  team: string;
  position: string;
  eligible_positions: string[];
  availability_type: string;
  percent_owned: number;
  status: string;
  bye_week: number;
  opponent: string;
  yahoo_proj: number;
  fp_ecr: number;
  fp_pos_rank: string;
  fp_proj: number;
  fp_tier: number;
  ros_ecr: number;
  ros_pos_rank: string;
  recommended_drop_player_key: string;
  recommended_drop_player_name: string;
  recommended_drop_player_proj: number;
  recommended_drop_player_ros_rank: string;
  recommended_target_slot: string;
  net_starter_gain: number;
  net_bench_gain: number;
  recommendation_type: "starter_upgrade" | "bench_upgrade";
  rationale: string;
}

export interface ScheduleWeek {
  week: number;
  opponent_name: string;
  my_points: number;
  my_projected: number;
  opponent_points: number;
  opponent_projected: number;
  status: string;
}

export interface LeagueDetailResponse {
  league: LeagueSummary & { roster_slots: string[] };
  roster: RosterPlayer[];
  swaps: LineupSwap[];
  free_agents: FreeAgentCandidate[];
  matchup: {
    week: number;
    my_projected_points: number;
    my_optimal_projected_points: number;
    opponent_team_name: string;
    opponent_manager: string;
    opponent_record: string;
    opponent_projected_points: number;
    win_probability: number;
    schedule: ScheduleWeek[];
  };
  yahoo_xml_preview: string;
}

export interface ScheduledJobInfo {
  id: string;
  type: "daily" | "pre_kickoff";
  label: string;
  time_str: string;
  kickoff_time: string | null;
  teams: string[];
  next_run_time: string;
}

export interface OverviewResponse {
  leagues: LeagueSummary[];
  oauth: {
    configured: boolean;
    connected: boolean;
    token_expired: boolean;
    yahoo_guid: string;
    redirect_uri: string;
  };
  scheduler: {
    running: boolean;
    next_run_time: string | null;
    daily_sync_time: string;
    daily_times?: string[];
    pre_game_sync_enabled?: boolean;
    pre_game_minutes_before?: number;
    scheduled_jobs?: ScheduledJobInfo[];
    timezone: string;
    dry_run: boolean;
  };
  smtp_configured: boolean;
  latest_run: {
    id: number;
    created_at: string;
    trigger_source: string;
    data_source: string;
    leagues_processed: number;
    total_swaps_recommended: number;
    total_fa_upgrades: number;
    lineup_changes_applied: number;
    email_sent: boolean;
    email_subject: string;
  } | null;
}

export interface AppSettings {
  yahoo_client_id: string;
  yahoo_client_secret: string;
  yahoo_redirect_uri: string;
  smtp_host: string;
  smtp_port: number;
  smtp_username: string;
  smtp_app_password: string;
  email_from: string;
  email_to: string;
  daily_sync_time: string;
  pre_game_sync_enabled?: boolean;
  pre_game_minutes_before?: number;
  timezone: string;
  default_execution_mode: "advisory" | "auto_lineup";
  dry_run: boolean;
  has_yahoo_secret?: boolean;
  has_smtp_password?: boolean;
}

export interface LeagueTeamScout {
  team_key: string;
  team_name: string;
  manager_name: string;
  is_my_team: boolean;
  is_current_opponent: boolean;
  rank: number;
  record: string;
  streak: string;
  points_for: number;
  points_against: number;
  waiver_priority: number;
  number_of_moves: number;
  faab_balance: number;
  current_proj: number;
  optimal_proj: number;
  points_left_on_bench: number;
  inactive_starters_count: number;
  questionable_starters_count: number;
  top100_ros_count: number;
  status_severity: "optimal" | "warning" | "alert";
  status_summary: string;
  swaps_count: number;
  swaps: LineupSwap[];
  roster: RosterPlayer[];
}

export interface LeagueTeamsResponse {
  league_key: string;
  league_name: string;
  current_week: number;
  teams: LeagueTeamScout[];
}
