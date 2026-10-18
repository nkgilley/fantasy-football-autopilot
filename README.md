# 🏈 Yahoo Fantasy Football Autopilot

> **Built with Gemini / Antigravity Autopilot** — This full-stack application (Python FastAPI backend, React + Tailwind CSS frontend, SQLite persistence, and multi-arch Docker deployment for Unraid) was architected and written autonomously by **Google Gemini / Antigravity**.

A multi-league Yahoo Fantasy Football helper and automation tool that checks your teams, starting lineups, available free agents, opponent rosters, and weekly matchups every day against **FantasyPros Weekly & Rest-of-Season (ROS) Expert Consensus Rankings (ECR)**.

## Key Features
- **Multi-League Support**: Automatically discovers all of your active Yahoo NFL leagues (`Standard`, `Half-PPR`, `Full PPR`, `Superflex`) and respects each league's exact starting slot constraints.
- **Lineup Optimizer & Locked-Game Detection**: Solves the optimal starting lineup using FantasyPros Weekly ECR & projections, automatically flagging starters on `BYE` or marked `Out`/`IR`/`Doubtful`/`Questionable`, while pinning and excluding players whose games have already kicked off (e.g., Thursday Night Football `🔒 Played (Locked)`).
- **Free Agent & Waiver Wire Analyzer with ROS Protection**: Compares available free agents & waiver targets against both your starters (`Starter Upgrade`) and bench (`Bench Upgrade`), while checking **FantasyPros Rest-of-Season (ROS) ECR** so high-value injured or bye-week stashes are never recommended as drops.
- **League Teams & Scouting**: Inspect every team in your league—standings, points for/against, weekly projected starter points, lineup readiness, and full rosters with Weekly & ROS rankings.
- **Daily HTML Email Digest (Gmail SMTP)**: Sends a consolidated morning briefing via Gmail App Password (`smtp.gmail.com:587`) summarizing matchup projections, lineup swaps, and waiver targets across all your leagues.
- **Advisory Mode vs. Auto-Lineup Mode**:
  - Defaults to **Advisory Mode** + **Dry-Run Safety Switch** so it only emails and displays recommendations.
  - Supports **1-Click "Apply Swaps in Yahoo"** in the Web UI and per-league **Auto-Lineup** execution using your Yahoo Browser Session Cookie (or OAuth 2.0 token).

---

## How It Works

### 1. Yahoo Fantasy Integration (Read & Live Lineup Writes)
Yahoo recently restricted newly created self-serve Developer Portal applications (`developer.yahoo.com/apps`) to **Read-Only (`fspt-r`)** scope, discontinuing the `Write (fspt-w)` checkbox for new OAuth apps and returning `401`/`403` on standard OAuth roster writes. To support both seamless data syncing and live lineup updates, Autopilot supports two authentication mechanisms in **Settings & OAuth**:
- **Yahoo Browser Session Cookie (Recommended — Full Read & Write)**:
  - **Reading League & Roster Data**: Queries Yahoo's internal read endpoint (`https://pub-api-ro.fantasysports.yahoo.com/fantasy/v2/...`) with your browser session cookie to fetch all active NFL leagues, league settings, standings, matchups, team rosters (with `is_editable` lock flags), and top available free agents.
  - **Applying Lineup Swaps Live**: When **Dry-Run** is disabled and you click **Apply Swap(s)** (or enable **Auto-Lineup** mode), [`writer.py`](backend/app/yahoo/writer.py) fetches your team's Yahoo Fantasy web page (`https://football.fantasysports.yahoo.com/f1/{league_id}/{team_id}?week={week}`), extracts Yahoo's dynamic anti-CSRF `crumb` and `#roster-edit-form` fields, updates each unlocked player's `<select>` slot assignment to their optimal slot, and `POST`s the form to `/f1/{league_id}/{team_id}/editroster`.
- **Yahoo OAuth 2.0 (`fspt-r` / `fspt-w`)**:
  - Supports standard OAuth 2.0 authorization code exchange and automatic token refresh against `https://api.login.yahoo.com/oauth2/get_token` and `https://fantasysports.yahooapis.com/fantasy/v2`.

### 2. FantasyPros Weekly & Rest-of-Season (ROS) Scraper
During each sync, [`scraper.py`](backend/app/fantasypros/scraper.py) fetches live **FantasyPros Expert Consensus Rankings (ECR)** tailored to each league's exact scoring format (`Standard`, `Half-PPR`, or `Full PPR`):
- **Weekly Positional Rankings & Projections**: Scrapes `ecrData` JSON embedded in FantasyPros' weekly `QB`, `RB`, `WR`, `TE`, `K`, and `DST` pages to extract projected points (`r2p_pts`), positional rank (`QB1`, `RB12`), tier, opponent matchup, kickoff timestamp (`player_game_kickoff_ts`), and live game status (`player_game_status`).
- **Rest-of-Season (ROS) Rankings**: Scrapes `ros-overall.php`, `ros-half-point-ppr-overall.php`, and `ros-ppr-overall.php` to attach each player's overall ROS ECR (`#1`–`#350+`) and ROS positional rank (`RB26`, `WR11`).
- **Fuzzy Player Name Normalization**: [`matcher.py`](backend/app/fantasypros/matcher.py) normalizes suffixes (`Jr.`, `III`, `II`), punctuation, and defense city/mascot aliases so Yahoo player records reliably match FantasyPros entries.

### 3. Lineup Optimizer & Locked-Game Protection
For every team, [`optimizer.py`](backend/app/engine/optimizer.py) solves the highest-projected starting lineup across exact league slots (`QB`, `RB`, `WR`, `TE`, `W/R/T`, `W/R`, `Q/W/R/T`, `K`, `DEF`):
- **Played / In-Progress Game Lock (`🔒 Played (Locked)`)**: Any player whose game has already kicked off or finished (e.g., Thursday Night Football, derived from `player_game_status` / kickoff timestamp or Yahoo's `is_editable=0` flag) is marked `is_locked = True`.
  - Locked starters are pinned to their current starting slot so the optimizer never recommends benching a starter who has already played.
  - Locked bench players are excluded from promotion into starting slots and cannot be recommended as waiver drops.
- **Injury, Bye & Questionable Handling**: Starters marked `BYE`, `OUT`, `IR`, or `Doubtful` are given `0.0` weekly projected points and automatically swapped out for the highest-projected eligible bench player. Starters marked `Questionable (Q)` who still hold optimal projections are kept in the lineup and surfaced in a **Starter Status Alert (Monitor Pre-Game Inactives)** banner.

### 4. Waiver Wire & Free Agent Analyzer with ROS Stash Protection
[`analyze_free_agent_upgrades`](backend/app/engine/optimizer.py) evaluates top unowned players at every position:
- **Starter Upgrades**: Recommends free agents who project higher this week than your optimal starter at that position (`+1.2 pts` threshold).
- **Bench Upgrades**: Recommends high-upside free agents who outperform your lowest-value droppable bench player (`+2.0 pts` threshold).
- **ROS Drop Protection**: Never recommends dropping a bench player who is a valuable Rest-of-Season hold (overall `ROS ECR <= 110` or top-32 RB / top-36 WR / top-12 QB/TE ROS), protecting injured or bye-week starters on your bench.

---

## Running Locally on macOS

### 1. Start the Backend (FastAPI + Built Frontend on Port 8000)
```bash
PYTHONPATH=backend .venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```
Open **http://localhost:8000** in your browser.
*(Note: Because `frontend/dist` is pre-built, port `8000` serves both the API and the Web UI! For frontend hot-reload during development, run `cd frontend && npm run dev` on port `5173`.)*

### 2. Run Unit & Integration Tests
```bash
PYTHONPATH=backend .venv/bin/pytest backend/tests -v
```

---

## Deploying with Docker / Unraid

Published on Docker Hub as `nkgilley/fantasy-football-autopilot:latest` (`linux/amd64` & `linux/arm64`).

1. Build or pull with Docker Compose:
   ```bash
   docker compose up -d
   ```
2. On **Unraid**, map the container's `/data` volume to `/mnt/user/appdata/fantasy-football-autopilot` and port `8000` to `8000`.
3. All Yahoo Session Cookies / OAuth tokens, Gmail SMTP settings, and league configurations can be edited directly in the **Settings & OAuth** tab of the Web UI and are persisted in `/data/autopilot.db`.


