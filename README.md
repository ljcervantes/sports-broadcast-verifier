# 📡 Broadcast Verifier

A Streamlit app that verifies whether sports broadcasts actually aired as scheduled, using **Perplexity AI as the sole data source**.

## How It Works

1. Upload a CSV schedule file (Zoomph format or similar)
2. For each event, the app sends a single query to **Perplexity sonar-pro**
3. Perplexity returns: actual start/end times (ET), broadcast channels, video duration, and any notes (overtime, delays, postponements)
4. The app compares actual data against scheduled data and assigns a **VERDICT**

## Output Columns

| Column | Description |
|---|---|
| League | Sport/league code |
| Event | Game or event name |
| Date | Event date |
| Sched Start | Scheduled start time from CSV |
| Sched Channel | Scheduled channel from CSV |
| Act. Start | Actual start time in ET (from Perplexity) |
| Act. End | Actual end time in ET (from Perplexity, or calculated from start + duration) |
| Video Duration | Total broadcast duration (from Perplexity) |
| National | National broadcast network(s) |
| Local Home | Local/RSN channel for home market |
| Local Away | Local/RSN channel for away market |
| Streaming | Streaming platform(s) |
| Notes | Real events only: Overtime, Rain delay, Postponed, Canceled, Extra innings (blank if none) |
| Details | Full cleaned Perplexity response (Start/End/Duration/Broadcast/Notes + narrative) |
| Verdict | AIRED_AS_SCHEDULED / MISMATCH / UNVERIFIED / UNCONFIRMED / POSTPONED / CANCELED / DELAYED |
| Sources | Clickable citation links [1][2][3] from Perplexity |

## Verdict Logic

- **AIRED_AS_SCHEDULED** — time match OR channel match
- **MISMATCH** — neither time nor channel matched
- **UNVERIFIED** — no data returned by Perplexity
- **UNCONFIRMED** — known local/RSN station but no data found
- **POSTPONED / CANCELED / DELAYED** — Perplexity reported a status event

## Setup

### Requirements
```
streamlit
pandas
requests
```

Install: `pip install -r requirements.txt`

### API Key
The Perplexity API key is stored in `broadcast_verifier.db`. Enter it once in the sidebar and it persists.

Get a key at: https://www.perplexity.ai/settings/api

### Run
```bash
streamlit run app.py
```

## Input CSV Format

The app accepts **Zoomph export format** with columns:
- `Date` — event date/time
- `Home Team` / `Away Team` — team names
- `Network` / `Network ID` — scheduled broadcast channel
- `Uploaded` — (optional) upload timestamp

Generic CSVs with `event`, `date`, `channel` columns are also supported.

## Data Source

**Perplexity AI (sonar-pro model)** is the only data source. No ESPN API, MLB API, NHL API, SerpApi, or web scraping is used. Perplexity searches the web in real time and returns structured results with citations.
