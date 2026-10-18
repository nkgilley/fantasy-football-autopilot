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
  - Supports **1-Click "Apply Swaps in Yahoo"** in the Web UI and per-league **Auto-Lineup** execution via Yahoo's `PUT /fantasy/v2/team/{team_key}/roster` XML API.

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
3. All Yahoo OAuth tokens, Gmail SMTP settings, and league configurations can be edited directly in the **Settings & OAuth** tab of the Web UI and are persisted in `/data/autopilot.db`.

