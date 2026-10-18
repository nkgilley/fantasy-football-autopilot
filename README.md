# Yahoo Fantasy Football Autopilot

A multi-league Yahoo Fantasy Football helper and automation tool that checks your teams, starting lineups, available free agents, and weekly matchups every day against **FantasyPros Weekly Expert Consensus Rankings (ECR) & Projections**.

## Key Features
- **Multi-League Support**: Automatically discovers all of your active Yahoo NFL leagues (`Standard`, `Half-PPR`, `Full PPR`, `Superflex`) and respects each league's exact starting slot constraints.
- **Lineup Optimizer**: Solves the optimal starting lineup using FantasyPros Weekly ECR & projections, automatically flagging starters on `BYE` or marked `Out`/`IR`/`Doubtful` and recommending bench-to-starter swaps.
- **Free Agent & Waiver Wire Analyzer**: Compares available free agents & waiver targets in each league against both your optimal starters (`Starter Upgrade`) and your lowest-projected bench players (`Bench Upgrade`), complete with suggested drop candidates.
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

## Deploying with Docker on Unraid

1. Build and start with Docker Compose:
   ```bash
   docker compose up -d --build
   ```
2. On **Unraid**, map the container's `/data` volume to `/mnt/user/appdata/fantasy-football-autopilot` and port `8000` to `8000`.
3. All Yahoo OAuth tokens, Gmail SMTP settings, and league configurations can be edited directly in the **Settings & OAuth** tab of the Web UI and are persisted in `/data/autopilot.db`.
