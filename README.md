# Sports Broadcast Verifier

A full-stack web application for sports broadcast operations teams to cross-check scheduled sports events against actual broadcast outcomes. Built for professionals who need to verify that games aired on the correct network, at the correct time, and flag any delays, postponements, cancellations, or network changes — including niche leagues like NHRA, PLL, fishing tournaments, PBR, and LPGA that are not covered by major sports APIs.

---

## What It Does

Upload your Zoomph schedule export (CSV or Google Sheets link), run a verification, and get a color-coded report showing exactly what happened to every event:

| Verdict | Meaning | Row Color |
|---|---|---|
| `AIRED_AS_SCHEDULED` | Event aired on the correct channel at the scheduled time | Green |
| `MATCH` | Pre-event sources agree on channel and time | Green |
| `DELAYED` | Event started late due to rain delay or other reason | Orange |
| `NETWORK_CHANGED` | Event moved to a different channel than scheduled | Orange |
| `MISMATCH` | Sources disagree on channel or time | Orange |
| `POSTPONED` | Event was pushed to a future date | Red |
| `CANCELED` | Event was called off entirely | Red |
| `UNCONFIRMED` | Pre-event data found but sources do not fully agree | Yellow |
| `UNVERIFIED` | No automated source could confirm the broadcast | Yellow |

---

## Features

- **Google Sheets import** — paste a shareable Google Sheets link and the app fetches your Zoomph schedule automatically, no CSV download needed
- **CSV upload** — drag-and-drop support for any schedule CSV export with auto-detected column mapping
- **Pre-event cross-check** — run before game day to confirm scheduled channels match live data sources
- **Day-after verification** — run the morning after to confirm what actually aired, including rain delays and network changes
- **Google Search broadcast lookup** — powered by SerpApi, automatically queries Google to find actual start time, end time, national channel, local home RSN, local away RSN, and streaming platforms
- **200+ local station call signs** — built-in library of OTA affiliates and regional sports networks (KMCC, SPECSN, KUNS, Bally Sports, YES, NESN, SNY, MASN, and more) so local broadcasts are recognized correctly
- **ESPN live data** — free, no API key required
- **Run history** — every verification run is saved to the database and reviewable at any time
- **CSV export** — download full results as a paper-trail CSV from any run
- **Dynamic league management** — add any sport or league directly from the UI sidebar with zero code changes; supports both matchup-style (home vs. away) and event-style (NHRA, golf, fishing) leagues
- **Custom local stations** — add any call sign not in the built-in library directly from the Settings page
- **No login required** — open the URL and start working immediately

**Pre-loaded sports:** MLB, NFL, NHL, NBA, WNBA, MLS, NCAAB, NCAAF, NASCAR, NHRA, PGA, LPGA, PLL, PBR, Boxing, F1, IndyCar, Fishing, MLS, and more.

---

## Tech Stack

| Layer | Technology |
|---|---|
| Frontend | React 19, Tailwind CSS 4, shadcn/ui |
| Backend | Node.js, Express, tRPC |
| Database | MySQL (via Drizzle ORM) |
| Build | Vite, TypeScript, pnpm |
| Deployment | Railway (recommended) |

---

## Deployment on Railway

See the full step-by-step guide in [`RAILWAY_DEPLOYMENT_GUIDE.md`](./RAILWAY_DEPLOYMENT_GUIDE.md).

**Quick summary:**
1. Fork or clone this repo
2. Create a new project on [railway.app](https://railway.app) and connect this repo
3. Add a MySQL database plugin in Railway
4. Set the required environment variables (see below)
5. Deploy — Railway builds and starts the app automatically

---

## Environment Variables

See `env.example` for the full list. The required variables are:

| Variable | Description |
|---|---|
| `DATABASE_URL` | MySQL connection string (provided by Railway MySQL plugin) |
| `JWT_SECRET` | Any long random string for session security |
| `VITE_APP_ID` | Short app identifier, e.g. `broadcast-verifier` |
| `NODE_ENV` | Set to `production` on Railway |
| `SERPAPI_KEY` | Optional — enables Google Search broadcast lookups ([get one free at serpapi.com](https://serpapi.com)) |

---

## Local Development

```bash
# Install dependencies
pnpm install

# Set up environment variables
cp env.example .env
# Edit .env and fill in DATABASE_URL and JWT_SECRET

# Run database migrations
pnpm db:push

# Start the development server
pnpm dev
```

The app will be available at `http://localhost:3000`.

---

## Running Tests

```bash
pnpm test
```

The test suite covers CSV parsing, Google Sheets URL conversion, broadcast verdict logic, and the authentication flow (10 tests total).

---

## Adding a New Sport or League

No code changes needed. In the app:
1. Click the **+** button next to **LEAGUES** in the sidebar
2. Enter the league name (e.g. `USFL`) and display name
3. Choose **Matchup** (home vs. away teams) or **Event** (single named event like a race or tournament)
4. Click **Add League**

The new league appears in the sidebar immediately and is available for all future verification runs.

---

## Project Structure

```
client/          React frontend (pages, components, UI)
server/          Express backend (tRPC routers, verification engine, DB helpers)
drizzle/         Database schema and migration files
shared/          Types and constants shared between frontend and backend
railway.json     Railway deployment configuration
nixpacks.toml    Railway build configuration
env.example      Template for required environment variables
```

---

## License

Private — all rights reserved.
