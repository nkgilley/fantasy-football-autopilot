from typing import Any


SLOT_ELIGIBILITY: dict[str, set[str]] = {
    "QB": {"QB"},
    "RB": {"RB"},
    "WR": {"WR"},
    "TE": {"TE"},
    "W/R/T": {"WR", "RB", "TE"},
    "W/R": {"WR", "RB"},
    "W/T": {"WR", "TE"},
    "Q/W/R/T": {"QB", "WR", "RB", "TE"},
    "K": {"K"},
    "DEF": {"DEF"},
}

INACTIVE_STATUSES = {"O", "OUT", "IR", "BYE", "SUSP", "NA"}


def is_player_locked(player: dict[str, Any]) -> bool:
    return bool(
        player.get("is_locked")
        or player.get("is_editable") is False
        or "Locked" in str(player.get("game_time", ""))
    )


def is_player_eligible_for_slot(player: dict[str, Any], slot: str) -> bool:
    allowed = SLOT_ELIGIBILITY.get(slot, {slot})
    player_positions = set(player.get("eligible_positions") or [player.get("position", "")])
    return bool(player_positions & allowed)


def effective_starter_score(player: dict[str, Any], slot: str) -> float:
    """
    Calculates optimization score for placing `player` into starting `slot`.
    Players who are Out, IR, or on BYE receive a severe penalty so healthy players are always preferred.
    Includes a tiny tie-breaker (+0.001) if the player is already in `slot` to avoid pointless swaps.
    """
    status = str(player.get("status", "Healthy")).upper()
    proj = float(player.get("fp_proj", 0.0))
    ecr = int(player.get("fp_ecr", 999))

    if status in INACTIVE_STATUSES or proj <= 0.0:
        base = -50.0 + proj
    elif status in ("D", "DOUBTFUL"):
        base = proj * 0.25
    else:
        base = proj

    # Small ECR tie-breaker so higher-ranked players win ties
    ecr_bonus = max(0, (300 - ecr)) * 0.0001
    stability_bonus = 0.002 if player.get("current_slot") == slot else 0.0
    return base + ecr_bonus + stability_bonus


def solve_optimal_lineup(
    players: list[dict[str, Any]],
    roster_slots: list[str],
) -> dict[str, Any]:
    """
    Finds the highest-projected legal assignment of roster players to starting slots.
    Players whose games have already started/finished (`is_locked`) are pinned to their current
    starter or bench slot so they are never included in lineup swap recommendations.
    """
    starting_slots = [s for s in roster_slots if s not in ("BN", "IR")]
    # Order slots from most restrictive (QB, K, DEF, TE, RB, WR) to flex (W/R/T, Q/W/R/T)
    slot_Restrictiveness = {
        "QB": 1,
        "K": 1,
        "DEF": 1,
        "TE": 2,
        "RB": 3,
        "WR": 3,
        "W/T": 4,
        "W/R": 4,
        "W/R/T": 5,
        "Q/W/R/T": 6,
    }

    pinned_assignment: dict[int, str] = {}
    locked_player_indices: set[int] = set()

    for idx, p in enumerate(players):
        if is_player_locked(p):
            locked_player_indices.add(idx)
            cur_slot = p.get("current_slot", "BN")
            if cur_slot not in ("BN", "IR"):
                for s_idx, s_name in enumerate(starting_slots):
                    if s_idx not in pinned_assignment and s_name == cur_slot:
                        pinned_assignment[s_idx] = p["player_key"]
                        break

    indexed_slots = [
        (s_idx, s_name)
        for s_idx, s_name in enumerate(starting_slots)
        if s_idx not in pinned_assignment
    ]
    indexed_slots.sort(key=lambda pair: slot_Restrictiveness.get(pair[1], 4))

    best_score = float("-inf")
    best_assignment: dict[int, str] = dict(pinned_assignment)

    # Precompute eligible unlocked player indices for each remaining starting slot
    eligible_for_slot: list[list[int]] = []
    for _, slot_name in indexed_slots:
        elig_idxs = [
            idx
            for idx, p in enumerate(players)
            if idx not in locked_player_indices and is_player_eligible_for_slot(p, slot_name)
        ]
        # Sort candidates by effective score descending for fast branch pruning
        elig_idxs.sort(key=lambda idx: effective_starter_score(players[idx], slot_name), reverse=True)
        eligible_for_slot.append(elig_idxs)

    # Upper bound per step for branch-and-bound pruning
    max_possible_for_step = [
        max((effective_starter_score(players[i], indexed_slots[step][1]) for i in elig), default=0.0)
        for step, elig in enumerate(eligible_for_slot)
    ]

    used_players: set[int] = set(locked_player_indices)
    current_assignment: dict[int, str] = dict(pinned_assignment)

    def backtrack(step: int, running_score: float) -> None:
        nonlocal best_score, best_assignment
        if step == len(indexed_slots):
            if running_score > best_score:
                best_score = running_score
                best_assignment = dict(current_assignment)
            return

        remaining_optimistic = sum(max_possible_for_step[step:])
        if running_score + remaining_optimistic <= best_score:
            return

        orig_slot_idx, slot_name = indexed_slots[step]
        candidates = eligible_for_slot[step]
        assigned_any = False

        for p_idx in candidates:
            if p_idx in used_players:
                continue
            assigned_any = True
            used_players.add(p_idx)
            current_assignment[orig_slot_idx] = players[p_idx]["player_key"]
            backtrack(step + 1, running_score + effective_starter_score(players[p_idx], slot_name))
            del current_assignment[orig_slot_idx]
            used_players.remove(p_idx)

        if not assigned_any:
            backtrack(step + 1, running_score)

    backtrack(0, 0.0)

    # Map player_key -> assigned optimal starting slot
    optimal_slot_by_player: dict[str, str] = {}
    for slot_idx, pk in best_assignment.items():
        optimal_slot_by_player[pk] = starting_slots[slot_idx]

    current_starters: list[dict[str, Any]] = []
    optimal_starters: list[dict[str, Any]] = []
    promoted_players: list[dict[str, Any]] = []
    benched_players: list[dict[str, Any]] = []

    enriched_players: list[dict[str, Any]] = []
    for p in players:
        pk = p["player_key"]
        cur_slot = p.get("current_slot", "BN")
        locked = is_player_locked(p)
        is_cur_starter = cur_slot not in ("BN", "IR")
        opt_slot = cur_slot if locked else optimal_slot_by_player.get(pk, "IR" if cur_slot == "IR" else "BN")
        is_opt_starter = is_cur_starter if locked else (pk in optimal_slot_by_player)

        action = "keep"
        if not locked:
            if is_opt_starter and not is_cur_starter:
                action = "promote_to_starter"
            elif is_cur_starter and not is_opt_starter:
                action = "bench_player"

        p_copy = dict(p)
        p_copy["is_locked"] = locked
        p_copy["optimal_slot"] = opt_slot
        p_copy["is_starter_current"] = is_cur_starter
        p_copy["is_starter_optimal"] = is_opt_starter
        p_copy["action_needed"] = action
        p_copy["swap_reason"] = ""

        if is_cur_starter:
            current_starters.append(p_copy)
        if is_opt_starter:
            optimal_starters.append(p_copy)
        if action == "promote_to_starter":
            promoted_players.append(p_copy)
        elif action == "bench_player":
            benched_players.append(p_copy)

        enriched_players.append(p_copy)

    # Pair promoted bench players with benched starters to build clear swap instructions
    swaps: list[dict[str, Any]] = []
    promoted_sorted = sorted(promoted_players, key=lambda x: float(x.get("fp_proj", 0.0)), reverse=True)
    remaining_benched = sorted(benched_players, key=lambda x: float(x.get("fp_proj", 0.0)))

    for p_in in promoted_sorted:
        target_slot = p_in["optimal_slot"]
        p_out = next(
            (b for b in remaining_benched if b.get("current_slot") == target_slot),
            None,
        )
        if p_out is None and remaining_benched:
            p_out = remaining_benched[0]
        if p_out is not None:
            remaining_benched.remove(p_out)

        in_proj = float(p_in.get("fp_proj", 0.0))
        out_proj = float(p_out.get("fp_proj", 0.0)) if p_out else 0.0
        delta = round(in_proj - out_proj, 1)

        if p_out:
            out_status = str(p_out.get("status", "Healthy")).upper()
            if out_status == "BYE":
                reason = (
                    f"{p_out['name']} is on Week BYE (0.0 pts). "
                    f"Start {p_in['name']} ({p_in.get('fp_pos_rank', p_in['position'])}, {in_proj:.1f} pts) at {target_slot}."
                )
            elif out_status in ("O", "OUT", "IR", "D"):
                reason = (
                    f"{p_out['name']} is marked {out_status}. "
                    f"Swap in healthy {p_in['name']} ({p_in.get('fp_pos_rank', p_in['position'])}, {in_proj:.1f} pts) at {target_slot}."
                )
            else:
                reason = (
                    f"{p_in['name']} ({p_in.get('fp_pos_rank', p_in['position'])}, {in_proj:.1f} pts) "
                    f"outprojects {p_out['name']} ({p_out.get('fp_pos_rank', p_out['position'])}, {out_proj:.1f} pts) "
                    f"by +{delta:.1f} pts in FantasyPros Weekly ECR."
                )
            p_in["swap_reason"] = reason
            p_out["swap_reason"] = reason
            swaps.append(
                {
                    "slot": target_slot,
                    "player_in": p_in,
                    "player_out": p_out,
                    "points_delta": delta,
                    "reason": reason,
                }
            )

    current_total = round(sum(float(p.get("fp_proj", 0.0)) for p in current_starters), 1)
    optimal_total = round(sum(float(p.get("fp_proj", 0.0)) for p in optimal_starters), 1)

    return {
        "players": enriched_players,
        "swaps": swaps,
        "current_projected_total": current_total,
        "optimal_projected_total": optimal_total,
        "net_gain": round(optimal_total - current_total, 1),
    }


def analyze_free_agent_upgrades(
    optimized_roster: list[dict[str, Any]],
    free_agents: list[dict[str, Any]],
    roster_slots: list[str],
) -> list[dict[str, Any]]:
    """
    Compares available Free Agents / Waivers against the user's optimal starters and bench players.
    Identifies both immediate Week Starter Upgrades and Bench/Depth Upgrades.
    """
    optimal_starters = [p for p in optimized_roster if p.get("is_starter_optimal")]
    bench_players = [
        p
        for p in optimized_roster
        if not p.get("is_starter_optimal") and p.get("current_slot") != "IR"
    ]

    recommendations: list[dict[str, Any]] = []

    is_superflex = "Q/W/R/T" in roster_slots

    def _is_protected_bench_player(b: dict[str, Any]) -> bool:
        # Bench players who have already played (e.g., Thursday Night Football) are locked on Yahoo until waivers run
        if is_player_locked(b):
            return True
        ros_ecr = int(b.get("ros_ecr", 999))
        wk_ecr = int(b.get("fp_ecr", 999))
        pos = str(b.get("position", ""))
        status = str(b.get("status", "Healthy")).upper()
        # Protect players inside top 115 ROS overall (e.g., RB26 Kyle Monangai #79 ROS, WR30/WR41, QB16)
        if pos not in ("K", "DEF") and ros_ecr <= 115:
            return True
        # Also protect top positional players temporarily Out/IR/BYE
        if status in (INACTIVE_STATUSES | {"D", "DOUBTFUL"}) and wk_ecr <= 36:
            return True
        return False

    droppable_bench = [b for b in bench_players if not _is_protected_bench_player(b)]

    def _drop_priority(p: dict[str, Any]) -> tuple[int, float]:
        # Lower tuple = more droppable. Prioritize dropping worst Rest-of-Season (highest ros_ecr) players first,
        # breaking ties by lowest weekly projection.
        ros_ecr = int(p.get("ros_ecr", 999))
        proj = float(p.get("fp_proj", 0.0))
        return (-ros_ecr, proj)

    for fa in free_agents:
        fa_status = str(fa.get("status", "Healthy")).upper()
        # Never recommend IR/Out/Suspended free agents, or free agents whose game already played this week
        if fa_status in ("O", "OUT", "IR", "SUSP", "NA") or is_player_locked(fa):
            continue

        fa_proj = float(fa.get("fp_proj", 0.0))
        fa_ecr = int(fa.get("fp_ecr", 999))
        fa_ros_ecr = int(fa.get("ros_ecr", 999))
        fa_pos = fa.get("position", "")
        fa_ros_label = str(fa.get("ros_pos_rank") or f"#{fa_ros_ecr}")

        # 1. Check if this FA beats any current unlocked Optimal Starter in a slot the FA can play
        best_starter_gain = 0.0
        target_starter: dict[str, Any] | None = None
        target_slot = "BN"

        if fa_status not in INACTIVE_STATUSES:
            for starter in optimal_starters:
                if is_player_locked(starter):
                    continue
                slot = starter.get("optimal_slot", starter.get("current_slot", "BN"))
                if is_player_eligible_for_slot(fa, slot):
                    gain = round(fa_proj - float(starter.get("fp_proj", 0.0)), 1)
                    if gain > best_starter_gain:
                        best_starter_gain = gain
                        target_starter = starter
                        target_slot = slot

        # Kickers and Defenses should only be recommended as direct starter upgrades (never bench stashes)
        if fa_pos in ("K", "DEF") and best_starter_gain < 0.8:
            continue

        # 2. Find the best drop candidate on the bench using ROS + Weekly priority
        drop_candidate: dict[str, Any] | None = None
        if fa_pos in ("K", "DEF"):
            same_pos_bench = [b for b in droppable_bench if b.get("position") == fa_pos]
            drop_candidate = min(same_pos_bench, key=_drop_priority) if same_pos_bench else target_starter
        elif fa_pos == "QB" and not is_superflex and best_starter_gain < 0.8:
            # In 1-QB leagues, only suggest a bench QB upgrade if replacing an existing droppable bench QB
            same_pos_bench = [
                b for b in droppable_bench if b.get("position") == "QB" and str(b.get("status", "")).upper() != "BYE"
            ]
            if same_pos_bench:
                drop_candidate = min(same_pos_bench, key=_drop_priority)
        elif fa_pos == "TE" and best_starter_gain < 0.8:
            # In 1-TE leagues, only suggest a bench TE stash if replacing an existing droppable bench TE
            same_pos_bench = [
                b for b in droppable_bench if b.get("position") == "TE" and str(b.get("status", "")).upper() != "BYE"
            ]
            if same_pos_bench:
                drop_candidate = min(same_pos_bench, key=_drop_priority)
        else:
            same_pos_bench = [
                b for b in droppable_bench if b.get("position") == fa_pos and str(b.get("status", "")).upper() != "BYE"
            ]
            non_bye_bench = [
                b
                for b in droppable_bench
                if str(b.get("status", "")).upper() != "BYE" and b.get("position") not in ("K", "DEF", "QB")
            ]
            # Pick the worst ROS player between same-position bench and overall droppable skill bench
            drop_pool = non_bye_bench or same_pos_bench or droppable_bench
            if drop_pool:
                drop_candidate = min(drop_pool, key=_drop_priority)

        if not drop_candidate:
            continue

        drop_proj = float(drop_candidate.get("fp_proj", 0.0))
        drop_ros_ecr = int(drop_candidate.get("ros_ecr", 999))
        drop_ros_label = str(drop_candidate.get("ros_pos_rank") or f"#{drop_ros_ecr}")
        net_bench_gain = round(fa_proj - drop_proj, 1)

        # Starter upgrade: requires meaningful weekly gain AND (for skill players) not sacrificing a much higher ROS asset
        starter_emergency = target_starter is not None and float(target_starter.get("fp_proj", 0.0)) <= 5.0
        if best_starter_gain >= 0.8 and (
            fa_pos in ("K", "DEF") or starter_emergency or fa_ros_ecr <= drop_ros_ecr + 30
        ):
            rec_type = "starter_upgrade"
            rationale = (
                f"Immediate {target_slot} starter upgrade (+{best_starter_gain:.1f} pts this week over "
                f"{target_starter['name']}; {fa_ros_label} ROS). "
                f"Drop {drop_candidate['name']} ({drop_ros_label} ROS, {drop_proj:.1f} pts)."
            )
        elif fa_pos not in ("K", "DEF") and (
            (fa_ros_ecr <= drop_ros_ecr - 15 and fa_ros_ecr <= 165)
            or (fa_status != "BYE" and fa_ros_ecr <= drop_ros_ecr + 10 and net_bench_gain >= 1.2)
        ):
            rec_type = "bench_upgrade"
            wk_note = "BYE WkStash" if fa_status == "BYE" else f"{fa.get('fp_pos_rank', fa_pos)} Wk, {fa_proj:.1f} pts"
            rationale = (
                f"Stronger ROS & weekly value ({fa_ros_label} ROS #{fa_ros_ecr} · {wk_note}) "
                f"over {drop_candidate['name']} ({drop_ros_label} ROS #{drop_ros_ecr}, {drop_proj:.1f} pts)."
            )
        else:
            continue

        fa_copy = dict(fa)
        fa_copy["recommended_drop_player_key"] = drop_candidate["player_key"] if drop_candidate else ""
        fa_copy["recommended_drop_player_name"] = drop_candidate["name"] if drop_candidate else ""
        fa_copy["recommended_drop_player_proj"] = drop_proj
        fa_copy["recommended_drop_player_ros_rank"] = drop_ros_label
        fa_copy["recommended_target_slot"] = target_slot if rec_type == "starter_upgrade" else "BN"
        fa_copy["net_starter_gain"] = best_starter_gain
        fa_copy["net_bench_gain"] = net_bench_gain
        fa_copy["recommendation_type"] = rec_type
        fa_copy["rationale"] = rationale
        recommendations.append(fa_copy)

    # Sort starter upgrades first, then by highest point gain & projected points
    recommendations.sort(
        key=lambda r: (
            1 if r["recommendation_type"] == "starter_upgrade" else 0,
            r["net_starter_gain"],
            r["fp_proj"],
        ),
        reverse=True,
    )
    return recommendations[:12]
