import streamlit as st
import pandas as pd
import sqlite3
import requests
import json
import re
import io
import os
from datetime import datetime, date
from urllib.parse import urlparse, parse_qs

# ─────────────────────────────────────────────
# PAGE CONFIG
# ─────────────────────────────────────────────
st.set_page_config(
    page_title="Broadcast Verifier",
    page_icon="📡",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ─────────────────────────────────────────────
# CUSTOM CSS — dark sports dashboard theme
# ─────────────────────────────────────────────
st.markdown("""
<style>
/* Dark background */
[data-testid="stAppViewContainer"] { background-color: #0f1117; }
[data-testid="stSidebar"] { background-color: #161b22; border-right: 1px solid #30363d; }

/* Verdict badge colors */
.verdict-green  { background:#1a4731; color:#4ade80; padding:3px 10px; border-radius:12px; font-weight:700; font-size:12px; }
.verdict-orange { background:#4a2c0a; color:#fb923c; padding:3px 10px; border-radius:12px; font-weight:700; font-size:12px; }
.verdict-red    { background:#4a1a1a; color:#f87171; padding:3px 10px; border-radius:12px; font-weight:700; font-size:12px; }
.verdict-yellow { background:#3d3000; color:#facc15; padding:3px 10px; border-radius:12px; font-weight:700; font-size:12px; }

/* Table row colors */
.row-red    { background-color: #2d1515 !important; }
.row-orange { background-color: #2d1e0a !important; }
.row-yellow { background-color: #2d2600 !important; }
.row-green  { background-color: #0d2618 !important; }

h1, h2, h3 { color: #e6edf3 !important; }
p, li, label { color: #8b949e !important; }

.stButton > button {
    background-color: #238636;
    color: white;
    border: none;
    border-radius: 6px;
    font-weight: 600;
}
.stButton > button:hover { background-color: #2ea043; }
</style>
""", unsafe_allow_html=True)

# ─────────────────────────────────────────────
# DATABASE SETUP (SQLite — persists in repo)
# ─────────────────────────────────────────────
DB_PATH = "broadcast_verifier.db"

def get_db():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db()
    c = conn.cursor()
    c.executescript("""
        CREATE TABLE IF NOT EXISTS leagues (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE,
            display_name TEXT NOT NULL,
            sport_type TEXT NOT NULL DEFAULT 'matchup',
            active INTEGER NOT NULL DEFAULT 1,
            created_at TEXT DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS verification_runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_name TEXT,
            run_type TEXT NOT NULL,
            event_count INTEGER DEFAULT 0,
            created_at TEXT DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS verification_results (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id INTEGER NOT NULL,
            league TEXT,
            event_name TEXT,
            event_date TEXT,
            sched_start TEXT,
            sched_channel TEXT,
            actual_start TEXT,
            actual_end TEXT,
            video_duration TEXT,
            national_channel TEXT,
            local_home TEXT,
            local_away TEXT,
            streaming TEXT,
            verdict TEXT,
            notes TEXT,
            search_url TEXT,
            sources_used TEXT,
            created_at TEXT DEFAULT (datetime('now')),
            FOREIGN KEY (run_id) REFERENCES verification_runs(id)
        );

        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT
        );
    """)

    # Seed default leagues
    default_leagues = [
        ("MLB", "MLB", "matchup"), ("NFL", "NFL", "matchup"),
        ("NHL", "NHL", "matchup"), ("NBA", "NBA", "matchup"),
        ("WNBA", "WNBA", "matchup"), ("MLS", "MLS", "matchup"),
        ("NCAAB", "NCAA Basketball", "matchup"), ("NCAAF", "NCAA Football", "matchup"),
        ("NASCAR", "NASCAR", "event"), ("NHRA", "NHRA", "event"),
        ("PGA", "PGA Tour", "event"), ("LPGA", "LPGA Tour", "event"),
        ("PLL", "PLL", "matchup"), ("PBR", "PBR", "event"),
        ("BOXING", "Boxing", "event"), ("UFC", "UFC", "event"),
        ("F1", "Formula 1", "event"), ("INDYCAR", "IndyCar", "event"),
        ("FISHING", "Bass Fishing", "event"), ("TENNIS", "Tennis", "event"),
    ]
    for name, display, stype in default_leagues:
        c.execute("INSERT OR IGNORE INTO leagues (name, display_name, sport_type) VALUES (?,?,?)",
                  (name, display, stype))
    conn.commit()
    conn.close()

init_db()

# ─────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────

# Known local OTA stations and RSNs
KNOWN_LOCAL_STATIONS = {
    # Las Vegas
    "KMCC","KSNV","KVVU","KLAS","KVBC",
    # Pacific Northwest
    "KUNS","KOMO","KING","KIRO","KPDX","KPTV",
    # New England
    "NESN","WHDH","WBZ","WCVB",
    # New York
    "YES","SNY","MSG","WPIX","WNBC","WABC","WCBS",
    # Mid-Atlantic
    "MASN","MASN2","NBCSWA","WBAL","WRC",
    # Chicago
    "NBCSCH","WGN","WBBM","WLS","WMAQ",
    # California
    "SPECSN","SPECSN","NBCSBA","NBCSCA","KCAL","KABC","KNBC","KTTV","KTLA",
    # Texas
    "BSSW","BALLY","BSSUN","KXAS","KTVT","KHOU","KPRC",
    # Southeast
    "BSSE","BSSO","BSSUN","WFTV","WESH","WSVN","WPLG",
    # Midwest
    "BSGL","BSOH","BSDET","BSIN","BSKC","BSMW",
    # Mountain/West
    "ATTRM","ATTSN","ROOT","ROOTSPORTS","KUSA","KDVR",
    # National (for completeness)
    "ESPN","ESPN2","ESPNU","ABC","NBC","CBS","FOX","FS1","FS2",
    "TNT","TBS","USA","NBCSN","CBSSN","PEACOCK","PARAMOUNT",
    "BALLY SPORTS","BALLY","NBCS","ATTSN","DIRECTV",
    # Generic RSN patterns
    "NBCSB","NBCSP","NBCSPH","NBCSNW","NBCSCH",
}

VERDICT_COLORS = {
    "AIRED_AS_SCHEDULED": "green",
    "MATCH": "green",
    "DELAYED": "orange",
    "NETWORK_CHANGED": "orange",
    "MISMATCH": "orange",
    "POSTPONED": "red",
    "CANCELED": "red",
    "UNCONFIRMED": "yellow",
    "UNVERIFIED": "yellow",
}

def normalize_channel(ch: str) -> str:
    if not ch:
        return ""
    return re.sub(r'[^A-Z0-9]', '', ch.upper().strip())

def is_known_local(channel: str) -> bool:
    norm = normalize_channel(channel)
    if norm in {normalize_channel(s) for s in KNOWN_LOCAL_STATIONS}:
        return True
    # Fuzzy: starts with known RSN prefix
    for prefix in ["BALLY","NBCS","ROOT","ATT","SPEC","NESN","MASN","YES","SNY","MSG"]:
        if norm.startswith(prefix):
            return True
    return False

def google_sheets_to_csv_url(url: str) -> str | None:
    """Convert a Google Sheets share URL to a direct CSV export URL."""
    patterns = [
        r"docs\.google\.com/spreadsheets/d/([a-zA-Z0-9_-]+)",
    ]
    for p in patterns:
        m = re.search(p, url)
        if m:
            sheet_id = m.group(1)
            # Check for specific tab (gid)
            gid_match = re.search(r"gid=(\d+)", url)
            gid = gid_match.group(1) if gid_match else "0"
            return f"https://docs.google.com/spreadsheets/d/{sheet_id}/export?format=csv&gid={gid}"
    return None

def fetch_google_sheet(url: str) -> pd.DataFrame | None:
    csv_url = google_sheets_to_csv_url(url)
    if not csv_url:
        return None
    try:
        resp = requests.get(csv_url, timeout=15)
        resp.raise_for_status()
        return pd.read_csv(io.StringIO(resp.text))
    except Exception as e:
        st.error(f"Could not fetch Google Sheet: {e}")
        return None

def detect_columns(df: pd.DataFrame) -> dict:
    """Auto-detect column names from common Zoomph/scraper export formats."""
    cols = {c.lower().strip(): c for c in df.columns}
    mapping = {}

    # League
    for k in ["league","sport","competition","league_name","sport_name","category"]:
        if k in cols: mapping["league"] = cols[k]; break

    # Date
    for k in ["date","game_date","event_date","air_date","gamedate","game date","event date","air date","airdate"]:
        if k in cols: mapping["date"] = cols[k]; break

    # Home team / event name
    for k in ["home","home_team","hometeam","event","event_name","title","program","name","game","matchup","description","teams","home team"]:
        if k in cols: mapping["home"] = cols[k]; break

    # Away team
    for k in ["away","away_team","awayteam","visitor","visiting_team","away team","visiting"]:
        if k in cols: mapping["away"] = cols[k]; break

    # Channel
    for k in ["channel","network","broadcast","broadcast_network","station","tv","air_channel","scheduled_channel","net","outlet","broadcaster","cable","air network","tv network","television"]:
        if k in cols: mapping["channel"] = cols[k]; break

    # Scheduled start time
    for k in ["time","start_time","scheduled_time","air_time","gametime","start","kickoff",
              "start time","air time","game time","scheduled start","tip off","tipoff","puck drop",
              "sched_start","sched start","scheduled start time","event start","event_start",
              "broadcast time","broadcast_time","airtime","on air","on_air","show time","showtime"]:
        if k in cols: mapping["time"] = cols[k]; break

    # Channel — extend with more Zoomph-style names
    if "channel" not in mapping:
        for k in ["sched_channel","sched channel","scheduled channel","scheduled_channel",
                  "air channel","air_channel","network name","network_name","tv channel",
                  "tv_channel","cable channel","cable_channel"]:
            if k in cols: mapping["channel"] = cols[k]; break

    return mapping

def _is_zoomph_format(df: pd.DataFrame) -> bool:
    """Return True if the dataframe looks like a Zoomph export."""
    cols_lower = {c.lower().strip() for c in df.columns}
    zoomph_markers = {"uploaded","cm feed start time (et)","network parent","home team","away team"}
    return len(zoomph_markers & cols_lower) >= 3

def parse_schedule_df(df: pd.DataFrame) -> list[dict]:
    """Normalize a raw dataframe into a list of event dicts."""
    mapping = detect_columns(df)

    # Debug: log detected mapping to help diagnose column issues
    unmapped = []
    if "time" not in mapping:
        unmapped.append("start time")
    if "channel" not in mapping:
        unmapped.append("channel/network")
    # Store on the df so the UI can surface a warning
    df.attrs["unmapped_cols"] = unmapped
    df.attrs["detected_mapping"] = mapping

    # If no home/event column detected, use the first text column as fallback
    if "home" not in mapping and len(df.columns) > 0:
        for col in df.columns:
            if df[col].dtype == object:
                mapping["home"] = col
                break

    events = []
    for _, row in df.iterrows():
        home = str(row.get(mapping.get("home",""), "")).strip()
        away = str(row.get(mapping.get("away",""), "")).strip()
        if away and away not in ("nan",""):
            event_name = f"{away} @ {home}"
        else:
            event_name = home

        sched_start = str(row.get(mapping.get("time",""), "")).strip()
        sched_channel = str(row.get(mapping.get("channel",""), "")).strip()
        # Replace literal "nan" (pandas NaN stringified) with empty string
        if sched_start == "nan": sched_start = ""
        if sched_channel == "nan": sched_channel = ""

        events.append({
            "league":        str(row.get(mapping.get("league",""), "")).strip(),
            "event_name":    event_name,
            "event_date":    str(row.get(mapping.get("date",""), "")).strip(),
            "sched_start":   sched_start,
            "sched_channel": sched_channel,
        })
    # Filter out empty/nan rows
    events = [e for e in events if e["event_name"] and e["event_name"] != "nan"]
    # Deduplicate: same league + event_name + event_date = same game
    seen = set()
    deduped = []
    for e in events:
        key = (e["league"].upper(), e["event_name"].lower().strip(), e["event_date"].strip())
        if key not in seen:
            seen.add(key)
            deduped.append(e)
    return deduped

def _parse_zoomph_df(df: pd.DataFrame) -> list[dict]:
    """
    Parse a Zoomph-format export where each game has multiple rows:
    - One row per network that aired (or is scheduled to air) the event
    - Uploaded='N' = scheduled/pre-broadcast entry
    - Uploaded='Y' = confirmed aired entry with actual times

    Strategy:
    - Group rows by (Date + Home Team + Away Team)
    - Scheduled start time = CM Feed Start Time (ET) from the Uploaded='N' row
      (or earliest time if no N row)
    - Scheduled channel = Network Parent from the Uploaded='N' row
    - Collect all confirmed (Y) Network Parent values as additional context
    """
    # Normalize column names for safe access
    col_map = {c.lower().strip(): c for c in df.columns}

    def gcol(key):
        return col_map.get(key, "")

    uploaded_col   = gcol("uploaded")
    date_col       = gcol("date")
    home_col       = gcol("home team")
    away_col       = gcol("away team")
    network_col    = gcol("network")
    net_parent_col = gcol("network parent")
    start_et_col   = gcol("cm feed start time (et)")
    end_et_col     = gcol("cm end time (et)")
    start_date_col = gcol("start date")
    league_col     = gcol("league") or gcol("sport")

    def safe(row, col):
        if not col: return ""
        v = str(row.get(col, "") or "").strip()
        return "" if v.lower() in ("nan","--","#n/a","n/a","none","") else v

    # Group rows by game key
    from collections import defaultdict
    groups = defaultdict(list)
    for _, row in df.iterrows():
        home = safe(row, home_col)
        away = safe(row, away_col)
        date = safe(row, date_col) or safe(row, start_date_col)
        if not home and not away:
            continue
        key = (date, home.lower(), away.lower())
        groups[key].append(row)

    events = []
    for (date, home_l, away_l), rows in groups.items():
        # Use the first row to get canonical names
        first = rows[0]
        home = safe(first, home_col)
        away = safe(first, away_col)
        event_name = f"{away} @ {home}" if away else home
        league = safe(first, league_col)

        # Scheduled entry: the N row with Network Parent = '--' (clean scheduled entry)
        # This row has the official scheduled time and no confirmed network yet
        clean_sched_rows = [r for r in rows
                            if str(r.get(uploaded_col,"")).strip().upper() == "N"
                            and str(r.get(net_parent_col,"")).strip() in ("--","","nan")]
        # Fallback: any N row
        any_n_rows = [r for r in rows if str(r.get(uploaded_col,"")).strip().upper() == "N"]
        sched_row = (clean_sched_rows or any_n_rows or [rows[0]])[0]

        sched_start = safe(sched_row, start_et_col)
        # Append ET suffix if not already present
        if sched_start and "et" not in sched_start.lower():
            if "pm" in sched_start.lower() or "am" in sched_start.lower():
                sched_start = sched_start + " ET"

        # Scheduled channel: use Network Parent from confirmed (Y) rows.
        # WCIUDT is Zoomph's internal streaming ID — skip it.
        # Collect all unique confirmed Network Parent values (excluding WCIUDT/blank).
        ZOOMPH_INTERNAL = {"WCIUDT","WCIUDT-90113",""}
        confirmed_nets = []
        for r in rows:
            if str(r.get(uploaded_col,"")).strip().upper() == "Y":
                net_parent = safe(r, net_parent_col)
                net_raw    = safe(r, network_col)
                # Prefer Network Parent; fall back to Network call sign
                ch = net_parent if net_parent and net_parent.upper() not in ZOOMPH_INTERNAL else net_raw
                if ch and ch.upper() not in ZOOMPH_INTERNAL and ch not in confirmed_nets:
                    confirmed_nets.append(ch)
        # Use the first confirmed network as the scheduled channel for comparison
        sched_channel = confirmed_nets[0] if confirmed_nets else ""

        events.append({
            "league":        league,
            "event_name":    event_name,
            "event_date":    date,
            "sched_start":   sched_start,
            "sched_channel": sched_channel,
        })

    # Filter blank events
    events = [e for e in events if e["event_name"] and e["event_name"] != "nan"]
    return events

# ─────────────────────────────────────────────
# SERPAPI GOOGLE SEARCH LOOKUP
# ─────────────────────────────────────────────

# ─────────────────────────────────────────────
# FREE MULTI-SOURCE LOOKUPS
# ─────────────────────────────────────────────

# ─────────────────────────────────────────────
# WEB SCRAPER SOURCES
# ─────────────────────────────────────────────

def _parse_506_page(html: str, event: dict) -> dict:
    """Parse a 506sports.com page and find a matching game entry.
    Pages are structured as: bold game name, time on next line, channel on next line.
    Times are already in ET — no conversion needed.
    """
    result = {"actual_start":"","actual_end":"","video_duration":"","national_channel":"",
              "local_home":"","local_away":"","streaming":"","status_hint":""}
    try:
        from html.parser import HTMLParser
        # Strip tags, preserve newlines at block elements
        clean = re.sub(r'<br\s*/?>', '\n', html, flags=re.IGNORECASE)
        clean = re.sub(r'<p[^>]*>', '\n', clean, flags=re.IGNORECASE)
        clean = re.sub(r'<li[^>]*>', '\n', clean, flags=re.IGNORECASE)
        clean = re.sub(r'<h[1-6][^>]*>', '\n', clean, flags=re.IGNORECASE)
        clean = re.sub(r'<[^>]+>', ' ', clean)
        clean = re.sub(r'&amp;', '&', clean)
        clean = re.sub(r'&nbsp;', ' ', clean)
        clean = re.sub(r'&#\d+;', '', clean)
        lines = [l.strip() for l in clean.splitlines() if l.strip()]
    except Exception:
        return result

    event_name = event.get("event_name","").lower()
    # Extract team names from event name (handles "Away @ Home" format)
    parts = re.split(r'\s+@\s+|\s+vs\.?\s+', event_name)
    teams = [p.strip().lower() for p in parts if len(p.strip()) > 2]

    # Also try short team names (last word of each part, e.g. "NY Yankees" -> "yankees")
    short_teams = []
    for t in teams:
        words = t.split()
        if len(words) >= 2:
            short_teams.append(words[-1])  # last word
            short_teams.append(words[0])   # first word
    all_terms = teams + short_teams

    # Slide a window: look for a line containing a team name, then grab time + channel from nearby lines
    time_pat = re.compile(r'\b(\d{1,2}:\d{2}\s*(?:AM|PM))\s*ET\b', re.IGNORECASE)
    for i, line in enumerate(lines):
        line_lower = line.lower()
        if not any(t in line_lower for t in all_terms):
            continue
        # Found a matching line — scan next 5 lines for time and channel
        window = lines[i:i+6]
        found_time = ""
        found_channel = ""
        for wline in window:
            if not found_time:
                m = time_pat.search(wline)
                if m:
                    found_time = m.group(0).strip().upper()
            if not found_channel and found_time:
                # Channel line: short, no digits, not a time, not a date header
                wl = wline.strip()
                if (wl and len(wl) < 50 and not time_pat.search(wl)
                        and not re.search(r'\b(MONDAY|TUESDAY|WEDNESDAY|THURSDAY|FRIDAY|SATURDAY|SUNDAY|JANUARY|FEBRUARY|MARCH|APRIL|MAY|JUNE|JULY|AUGUST|SEPTEMBER|OCTOBER|NOVEMBER|DECEMBER)\b', wl, re.IGNORECASE)
                        and not re.search(r'\b\d{4}\b', wl)
                        and wl != found_time):
                    found_channel = wl
        if found_time:
            result["actual_start"] = found_time
        if found_channel:
            # 506sports sometimes lists multiple channels separated by "/"
            for ch in re.split(r'\s*/\s*', found_channel):
                _classify_channel(ch.strip(), result)
        if result["actual_start"] or result["national_channel"]:
            break  # stop at first match
    return result

def fiveofsix_lookup(event: dict, run_type: str) -> dict:
    """Scrape 506sports.com for national broadcast listings. Times already in ET."""
    result = {"actual_start":"","actual_end":"","video_duration":"","national_channel":"",
              "local_home":"","local_away":"","streaming":"","status_hint":""}
    league = event.get("league","").upper()
    sport_map = {
        "MLB": "mlb", "NFL": "nfl", "NBA": "nba", "NHL": "nhl",
        "WNBA": "wnba", "NCAAF": "nfl",  # 506 uses nfl.php for CFB too during off-season; skip
    }
    # 506sports only covers major national broadcasts — skip unsupported leagues
    if league not in sport_map:
        return result
    slug = sport_map[league]
    url = f"https://506sports.com/{slug}.php"
    try:
        resp = requests.get(url, timeout=12, headers={"User-Agent": "Mozilla/5.0"})
        if resp.status_code != 200:
            return result
        return _parse_506_page(resp.text, event)
    except Exception:
        return result

def gameviewingguide_lookup(event: dict, run_type: str) -> dict:
    """Scrape gameviewingguide.com (CFB.guide) for college football and basketball listings."""
    result = {"actual_start":"","actual_end":"","video_duration":"","national_channel":"",
              "local_home":"","local_away":"","streaming":"","status_hint":""}
    league = event.get("league","").upper()
    path_map = {"NCAAF": "cfb", "NCAAB": "cbb"}
    if league not in path_map:
        return result
    url = f"https://gameviewingguide.com/{path_map[league]}"
    try:
        resp = requests.get(url, timeout=12, headers={"User-Agent": "Mozilla/5.0"})
        if resp.status_code != 200:
            return result
        html = resp.text
    except Exception:
        return result

    # The guide renders a grid table: each cell contains "Team A\n@\nTeam B\nTIME\nCHANNEL"
    # Extract all table cells and look for a match
    event_name = event.get("event_name","").lower()
    parts = re.split(r'\s+@\s+|\s+vs\.?\s+', event_name)
    teams = [p.strip().lower() for p in parts if len(p.strip()) > 2]

    # Find all <td> cell contents
    cells = re.findall(r'<td[^>]*>(.*?)</td>', html, re.DOTALL | re.IGNORECASE)
    time_pat = re.compile(r'\b(\d{1,2}:\d{2}\s*(?:AM|PM))\b', re.IGNORECASE)
    for cell in cells:
        # Strip HTML tags from cell
        cell_text = re.sub(r'<[^>]+>', ' ', cell)
        cell_text = re.sub(r'\s+', ' ', cell_text).strip().lower()
        if not any(t in cell_text for t in teams):
            continue
        # Found a match — extract time and channel
        m = time_pat.search(cell_text)
        if m:
            result["actual_start"] = m.group(0).strip().upper() + " ET"
        # Channel: look for known network names in the cell
        for token in cell_text.upper().split():
            token_clean = re.sub(r'[^A-Z0-9+]', '', token)
            if token_clean in {"ESPN","ESPN2","ESPNU","ABC","NBC","CBS","FOX","FS1","FS2",
                               "BTN","ACCN","SECN","CBSSN","PEACOCK","ESPN+","ESPNPLUS"}:
                _classify_channel(token_clean.replace("ESPNPLUS","ESPN+"), result)
        if result["actual_start"] or result["national_channel"]:
            break
    return result

def _merge_lookup(base: dict, extra: dict):
    """Merge extra source data into base, only filling empty fields."""
    for key in ["actual_start","actual_end","video_duration","national_channel","local_home","local_away","streaming","status_hint"]:
        if not base.get(key) and extra.get(key):
            base[key] = extra[key]
    # Streaming: always append new platforms
    if extra.get("streaming"):
        existing = base.get("streaming","")
        for platform in extra["streaming"].split(", "):
            if platform and platform not in existing:
                base["streaming"] = (existing + ", " + platform).strip(", ") if existing else platform
                existing = base["streaming"]

def _utc_to_et(dt_utc: "datetime") -> str:
    """Convert a naive UTC datetime to an ET time string.
    Uses EDT (UTC-4) from second Sunday of March through first Sunday of November,
    and EST (UTC-5) the rest of the year — matching US Eastern Time rules.
    Returns a string like '7:05 PM ET'.
    """
    from datetime import timedelta
    year = dt_utc.year
    # Second Sunday of March (EDT starts 2:00 AM local = 7:00 AM UTC)
    march_1 = datetime(year, 3, 1)
    days_to_sun = (6 - march_1.weekday()) % 7  # days until first Sunday
    edt_start = march_1 + timedelta(days=days_to_sun + 7, hours=7)  # 2 AM EST = 7 AM UTC
    # First Sunday of November (EST starts 2:00 AM local = 6:00 AM UTC)
    nov_1 = datetime(year, 11, 1)
    days_to_sun = (6 - nov_1.weekday()) % 7
    est_start = nov_1 + timedelta(days=days_to_sun, hours=6)  # 2 AM EDT = 6 AM UTC
    if edt_start <= dt_utc < est_start:
        offset = timedelta(hours=4)   # EDT = UTC-4
        tz_label = "ET"
    else:
        offset = timedelta(hours=5)   # EST = UTC-5
        tz_label = "ET"
    dt_et = dt_utc - offset
    return dt_et.strftime("%-I:%M %p") + " " + tz_label

def espn_lookup(event: dict, run_type: str) -> dict:
    """Query ESPN's public scoreboard API for game data. No key required."""
    result = {"actual_start":"","actual_end":"","video_duration":"","national_channel":"",
              "local_home":"","local_away":"","streaming":"","status_hint":""}
    league = event.get("league","").upper()
    date_str = event.get("event_date","")

    # Map league to ESPN API sport/league slug
    espn_map = {
        "MLB": ("baseball","mlb"), "NFL": ("football","nfl"),
        "NBA": ("basketball","nba"), "WNBA": ("basketball","wnba"),
        "NHL": ("hockey","nhl"), "MLS": ("soccer","usa.1"),
        "NCAAB": ("basketball","mens-college-basketball"),
        "NCAAF": ("football","college-football"),
        "PLL": ("lacrosse","pll"),
    }
    if league not in espn_map:
        return result

    sport, slug = espn_map[league]
    # Parse date to YYYYMMDD
    try:
        for fmt in ["%Y-%m-%d","%m/%d/%Y","%m/%d/%y","%B %d, %Y"]:
            try:
                dt = datetime.strptime(str(date_str).strip(), fmt)
                date_param = dt.strftime("%Y%m%d")
                break
            except ValueError:
                continue
        else:
            return result
    except Exception:
        return result

    try:
        url = f"https://site.api.espn.com/apis/site/v2/sports/{sport}/{slug}/scoreboard"
        resp = requests.get(url, params={"dates": date_param}, timeout=10)
        data = resp.json()
    except Exception:
        return result

    event_name = event.get("event_name","").lower()
    for game in data.get("events", []):
        name = game.get("name","").lower()
        short_name = game.get("shortName","").lower()
        # Fuzzy match: check if any team name from the event appears in ESPN game name
        parts = re.split(r'\s+@\s+|\s+vs\.?\s+', event_name)
        matched = any(p.strip().lower() in name or p.strip().lower() in short_name
                      for p in parts if len(p.strip()) > 2)
        if not matched:
            continue

        # Start time
        date_field = game.get("date","")
        if date_field:
            try:
                dt_utc = datetime.strptime(date_field[:19], "%Y-%m-%dT%H:%M:%S")
                result["actual_start"] = _utc_to_et(dt_utc)
            except Exception:
                pass

        # Status
        status = game.get("status",{}).get("type",{})
        desc = status.get("description","").lower()
        state = status.get("state","").lower()
        if "postpone" in desc:
            result["status_hint"] = "postponed"
        elif "cancel" in desc:
            result["status_hint"] = "canceled"
        elif "delay" in desc or "rain" in desc:
            result["status_hint"] = "delayed"

        # Broadcast / TV info
        for broadcast in game.get("broadcasts", []):
            for media in broadcast.get("media", []) if isinstance(broadcast.get("media"), list) else [broadcast]:
                ch_name = media.get("shortName","") or media.get("name","")
                if ch_name:
                    _classify_channel(ch_name, result)
        # Also check competitions
        for comp in game.get("competitions", []):
            for bc in comp.get("broadcasts", []):
                for media in bc.get("media", []) if isinstance(bc.get("media"), list) else [bc]:
                    ch_name = media.get("shortName","") or media.get("name","")
                    if ch_name:
                        _classify_channel(ch_name, result)
        break  # matched game found

    return result

def mlb_lookup(event: dict, run_type: str) -> dict:
    """Query MLB Stats API for game data. No key required."""
    result = {"actual_start":"","actual_end":"","video_duration":"","national_channel":"",
              "local_home":"","local_away":"","streaming":"","status_hint":""}
    if event.get("league","").upper() != "MLB":
        return result

    date_str = event.get("event_date","")
    try:
        for fmt in ["%Y-%m-%d","%m/%d/%Y","%m/%d/%y"]:
            try:
                dt = datetime.strptime(str(date_str).strip(), fmt)
                date_param = dt.strftime("%Y-%m-%d")
                break
            except ValueError:
                continue
        else:
            return result
    except Exception:
        return result

    try:
        url = "https://statsapi.mlb.com/api/v1/schedule"
        resp = requests.get(url, params={
            "sportId": 1, "date": date_param,
            "hydrate": "broadcasts(all),game(content(media(epg)))",
        }, timeout=10)
        data = resp.json()
    except Exception:
        return result

    event_name = event.get("event_name","").lower()
    for date_entry in data.get("dates", []):
        for game in date_entry.get("games", []):
            home = game.get("teams",{}).get("home",{}).get("team",{}).get("name","").lower()
            away = game.get("teams",{}).get("away",{}).get("team",{}).get("name","").lower()
            parts = re.split(r'\s+@\s+|\s+vs\.?\s+', event_name)
            matched = any(p.strip().lower() in home or p.strip().lower() in away
                          for p in parts if len(p.strip()) > 2)
            if not matched:
                continue

            # Start time
            game_time = game.get("gameDate","")
            if game_time:
                try:
                    dt_utc = datetime.strptime(game_time[:19], "%Y-%m-%dT%H:%M:%S")
                    result["actual_start"] = _utc_to_et(dt_utc)
                except Exception:
                    pass

            # Game duration (video duration equivalent)
            duration = game.get("gameDuration","")
            if duration:
                result["video_duration"] = str(duration)

            # Status
            status_code = game.get("status",{}).get("abstractGameState","")
            detail = game.get("status",{}).get("detailedState","").lower()
            if "postpone" in detail:
                result["status_hint"] = "postponed"
            elif "cancel" in detail:
                result["status_hint"] = "canceled"
            elif "delay" in detail or "rain" in detail:
                result["status_hint"] = "delayed"

            # Broadcasts
            for bc in game.get("broadcasts", []):
                ch_name = bc.get("name","")
                bc_type = bc.get("type","").lower()
                if ch_name:
                    if bc_type in ("national",""):
                        _classify_channel(ch_name, result)
                    else:
                        _classify_channel(ch_name, result)
            break

    return result

def nhl_lookup(event: dict, run_type: str) -> dict:
    """Query NHL API for game data. No key required."""
    result = {"actual_start":"","actual_end":"","video_duration":"","national_channel":"",
              "local_home":"","local_away":"","streaming":"","status_hint":""}
    if event.get("league","").upper() != "NHL":
        return result

    date_str = event.get("event_date","")
    try:
        for fmt in ["%Y-%m-%d","%m/%d/%Y","%m/%d/%y"]:
            try:
                dt = datetime.strptime(str(date_str).strip(), fmt)
                date_param = dt.strftime("%Y-%m-%d")
                break
            except ValueError:
                continue
        else:
            return result
    except Exception:
        return result

    try:
        url = f"https://api-web.nhle.com/v1/schedule/{date_param}"
        resp = requests.get(url, timeout=10)
        data = resp.json()
    except Exception:
        return result

    event_name = event.get("event_name","").lower()
    for week in data.get("gameWeek", []):
        for game in week.get("games", []):
            home = game.get("homeTeam",{}).get("placeName",{}).get("default","").lower()
            away = game.get("awayTeam",{}).get("placeName",{}).get("default","").lower()
            home_abbr = game.get("homeTeam",{}).get("abbrev","").lower()
            away_abbr = game.get("awayTeam",{}).get("abbrev","").lower()
            parts = re.split(r'\s+@\s+|\s+vs\.?\s+', event_name)
            matched = any(
                p.strip().lower() in home or p.strip().lower() in away or
                p.strip().lower() == home_abbr or p.strip().lower() == away_abbr
                for p in parts if len(p.strip()) > 1
            )
            if not matched:
                continue

            # Start time
            game_time = game.get("startTimeUTC","")
            if game_time:
                try:
                    dt_utc = datetime.strptime(game_time[:19], "%Y-%m-%dT%H:%M:%S")
                    result["actual_start"] = _utc_to_et(dt_utc)
                except Exception:
                    pass

            # Status
            game_state = game.get("gameState","").lower()
            if "postpone" in game_state or "ppd" in game_state:
                result["status_hint"] = "postponed"
            elif "cancel" in game_state:
                result["status_hint"] = "canceled"

            # TV/broadcast
            for bc in game.get("tvBroadcasts", []):
                ch_name = bc.get("network","")
                if ch_name:
                    _classify_channel(ch_name, result)
            break

    return result

def thesportsdb_lookup(event: dict, run_type: str) -> dict:
    """Query TheSportsDB free API for event data."""
    result = {"actual_start":"","actual_end":"","video_duration":"","national_channel":"",
              "local_home":"","local_away":"","streaming":"","status_hint":""}
    league = event.get("league","").upper()
    date_str = event.get("event_date","")

    # TheSportsDB league IDs for supported leagues
    league_ids = {
        "MLB": "4424", "NFL": "4391", "NBA": "4387", "NHL": "4380",
        "MLS": "4346", "WNBA": "4422", "PLL": "4966",
    }
    if league not in league_ids:
        return result

    try:
        for fmt in ["%Y-%m-%d","%m/%d/%Y","%m/%d/%y"]:
            try:
                dt = datetime.strptime(str(date_str).strip(), fmt)
                date_param = dt.strftime("%Y-%m-%d")
                break
            except ValueError:
                continue
        else:
            return result
    except Exception:
        return result

    try:
        url = f"https://www.thesportsdb.com/api/v1/json/3/eventsday.php"
        resp = requests.get(url, params={"d": date_param, "l": league_ids[league]}, timeout=10)
        data = resp.json()
    except Exception:
        return result

    event_name = event.get("event_name","").lower()
    for ev in (data.get("events") or []):
        name = (ev.get("strEvent","") or "").lower()
        home = (ev.get("strHomeTeam","") or "").lower()
        away = (ev.get("strAwayTeam","") or "").lower()
        parts = re.split(r'\s+@\s+|\s+vs\.?\s+', event_name)
        matched = any(p.strip().lower() in name or p.strip().lower() in home or p.strip().lower() in away
                      for p in parts if len(p.strip()) > 2)
        if not matched:
            continue

        # Start time
        time_val = ev.get("strTime","")
        if time_val:
            result["actual_start"] = time_val

        # Channel
        channel = ev.get("strChannel","") or ev.get("strTVStation","")
        if channel:
            _classify_channel(channel, result)

        # Status
        status = (ev.get("strStatus","") or "").lower()
        if "postpone" in status:
            result["status_hint"] = "postponed"
        elif "cancel" in status:
            result["status_hint"] = "canceled"
        break

    return result

def multi_source_lookup(event: dict, api_key: str, run_type: str) -> dict:
    """Run all available sources and merge results. SerpApi fills gaps left by free APIs."""
    # Start with empty base
    combined = {
        "actual_start":"","actual_end":"","video_duration":"",
        "national_channel":"","local_home":"","local_away":"",
        "streaming":"","status_hint":"",
        "search_url": build_fallback_url(event, run_type),
        "sources_used": [],
    }

    # 1. MLB Stats API (most detailed for MLB — includes game duration)
    mlb = mlb_lookup(event, run_type)
    if any(mlb.get(k) for k in ["actual_start","national_channel","status_hint","video_duration"]):
        _merge_lookup(combined, mlb)
        combined["sources_used"].append("MLB API")

    # 2. NHL API
    nhl = nhl_lookup(event, run_type)
    if any(nhl.get(k) for k in ["actual_start","national_channel","status_hint"]):
        _merge_lookup(combined, nhl)
        combined["sources_used"].append("NHL API")

    # 3. ESPN (covers MLB, NFL, NBA, WNBA, MLS, NCAAB, NCAAF, PLL)
    espn = espn_lookup(event, run_type)
    if any(espn.get(k) for k in ["actual_start","national_channel","status_hint"]):
        _merge_lookup(combined, espn)
        combined["sources_used"].append("ESPN")

    # 4. TheSportsDB (fallback for leagues ESPN/MLB/NHL don't cover)
    tsdb = thesportsdb_lookup(event, run_type)
    if any(tsdb.get(k) for k in ["actual_start","national_channel","status_hint"]):
        _merge_lookup(combined, tsdb)
        combined["sources_used"].append("TheSportsDB")

    # 5. ESPN.com schedule page (better channel data than ESPN API for many leagues)
    espn_web = espn_schedule_scrape(event, run_type)
    if any(espn_web.get(k) for k in ["actual_start","national_channel","streaming"]):
        _merge_lookup(combined, espn_web)
        combined["sources_used"].append("ESPN.com")

    # 6. 506sports.com (national broadcast listings, current week)
    fos = fiveofsix_lookup(event, run_type)
    if any(fos.get(k) for k in ["actual_start","national_channel"]):
        _merge_lookup(combined, fos)
        combined["sources_used"].append("506sports")

    # 7. Sports Media Watch (covers ALL sports including niche: NHRA, NASCAR, fishing, PBR)
    smw = sportsmediawatch_lookup(event, run_type)
    if any(smw.get(k) for k in ["actual_start","national_channel","streaming"]):
        _merge_lookup(combined, smw)
        combined["sources_used"].append("SportsMW")

    # 8. SerpApi Google Search (fills any remaining gaps, best for niche sports)
    if api_key:
        serp = serpapi_lookup(event, api_key, run_type)
        _merge_lookup(combined, serp)
        if serp.get("search_url"):
            combined["search_url"] = serp["search_url"]
        combined["sources_used"].append("Google Search")

    return combined

def build_search_query(event: dict, run_type: str) -> str:
    name = event.get("event_name","")
    league = event.get("league","")
    date_str = event.get("event_date","")
    if run_type == "day_after":
        return f"{league} {name} {date_str} what channel aired broadcast"
    else:
        return f"{league} {name} {date_str} where to watch channel broadcast"

def build_fallback_url(event: dict, run_type: str) -> str:
    q = build_search_query(event, run_type)
    return "https://www.google.com/search?q=" + requests.utils.quote(q)

def serpapi_lookup(event: dict, api_key: str, run_type: str) -> dict:
    """Query SerpApi Google Search and extract broadcast details."""
    result = {
        "actual_start": "", "actual_end": "",
        "national_channel": "", "local_home": "",
        "local_away": "", "streaming": "",
        "search_url": build_fallback_url(event, run_type),
    }
    if not api_key:
        return result

    query = build_search_query(event, run_type)
    try:
        resp = requests.get("https://serpapi.com/search", params={
            "q": query,
            "api_key": api_key,
            "engine": "google",
            "num": 5,
        }, timeout=15)
        data = resp.json()
    except Exception:
        return result

    # --- Extract from sports_results widget (most reliable source) ---
    sr = data.get("sports_results", {})
    if sr:
        # Channels from sports widget — these are the most reliable
        for ch_field in ["channels", "broadcast", "network"]:
            channels = sr.get(ch_field, [])
            if isinstance(channels, list):
                for ch in channels:
                    ch_name = ch.get("name","") if isinstance(ch, dict) else str(ch)
                    _classify_channel(ch_name, result)
            elif isinstance(channels, str):
                _classify_channel(channels, result)

        # Game time from sports widget spotlight
        spotlight = sr.get("game_spotlight", {})
        if isinstance(spotlight, dict):
            time_val = spotlight.get("match_time") or spotlight.get("time","")
            if time_val and not result["actual_start"]:
                clean = _parse_game_time(time_val)
                if clean:
                    result["actual_start"] = clean

        # Status for delay/postpone/cancel
        status = (sr.get("status","") or "").lower()
        if "delay" in status or "rain" in status:
            result["status_hint"] = "delayed"
        elif "postpone" in status:
            result["status_hint"] = "postponed"
        elif "cancel" in status:
            result["status_hint"] = "canceled"

    # --- Extract from organic results snippets (less reliable, use carefully) ---
    for organic in data.get("organic_results", []):
        snippet  = organic.get("snippet","") or ""
        title    = organic.get("title","") or ""
        full_text = snippet + " " + title
        full_lower = full_text.lower()

        # Only extract start time from snippets if sports widget did not provide one
        if not result["actual_start"]:
            # Strict: must have AM/PM and timezone to count as a real game time
            strict_times = re.findall(
                r'\b(\d{1,2}:\d{2}\s*(?:AM|PM|a\.m\.|p\.m\.)\s*(?:ET|CT|MT|PT|EST|CST|MST|PST|EDT|CDT|MDT|PDT))\b',
                full_text, re.IGNORECASE
            )
            if strict_times:
                result["actual_start"] = strict_times[0].strip().upper()

        # End time: only from phrases like "ended at X" or "final at X" or "game ended X"
        if not result["actual_end"]:
            end_patterns = [
                r'(?:ended?|final|concluded?|finished?|wrapped?)\s+(?:at\s+)?(\d{1,2}:\d{2}\s*(?:AM|PM)\s*(?:ET|CT|MT|PT|EST|CST|MST|PST|EDT|CDT|MDT|PDT)?)',
                r'(\d{1,2}:\d{2}\s*(?:AM|PM)\s*(?:ET|CT|MT|PT|EST|CST|MST|PST|EDT|CDT|MDT|PDT))\s*(?:ET|CT|MT|PT)?\s*(?:final|end)',
            ]
            for pat in end_patterns:
                m = re.search(pat, full_text, re.IGNORECASE)
                if m:
                    result["actual_end"] = m.group(1).strip().upper()
                    break

        # Channel names — only from known network patterns, never generic words
        channel_patterns = [
            r'\b(ESPN2?U?|FS[12]|TNT|TBS|TruTV|ABC|NBC|CBS|FOX|NBCSN|CBSSN|USA Network|USA)\b',
            r'\b(BALLY\s*SPORTS?(?:\s*[A-Z]+)?|ROOT\s*SPORTS?(?:\s*[A-Z]+)?)\b',
            r'\b(NESN|YES\s*Network|SNY|MSG(?:\+)?|MASN2?|NBCS[A-Z]*|ATTSN[A-Z]*)\b',
            r'\b(Peacock|Paramount\+|ESPN\+|Apple\s*TV\+|Amazon\s*Prime\s*Video|YouTube\s*TV|FuboTV|Fubo|Sling|DirecTV\s*Stream|DAZN|Max)\b',
        ]
        for pat in channel_patterns:
            found = re.findall(pat, full_text, re.IGNORECASE)
            for ch in found:
                _classify_channel(ch.strip(), result)

        # Streaming — explicit platform mentions only
        streaming_map = {
            "peacock": "PEACOCK", "paramount+": "PARAMOUNT+", "paramount plus": "PARAMOUNT+",
            "espn+": "ESPN+", "fubo": "FUBO", "fubotv": "FUBO",
            "sling": "SLING", "directv stream": "DIRECTV STREAM",
            "max": "MAX", "apple tv+": "APPLE TV+", "amazon prime video": "AMAZON PRIME",
            "youtube tv": "YOUTUBE TV", "dazn": "DAZN",
        }
        for platform, label in streaming_map.items():
            if platform in full_lower and label not in result["streaming"]:
                existing = result["streaming"]
                result["streaming"] = (existing + ", " + label).strip(", ") if existing else label

        # Status detection
        if "status_hint" not in result:
            if any(w in full_lower for w in ["rain delay","weather delay","game delayed"]):
                result["status_hint"] = "delayed"
            elif any(w in full_lower for w in ["postponed","game postponed"]):
                result["status_hint"] = "postponed"
            elif any(w in full_lower for w in ["canceled","cancelled","called off","game called"]):
                result["status_hint"] = "canceled"

    return result

def _parse_game_time(raw: str) -> str:
    """Clean and validate a time string from the sports widget. Returns empty string if it looks wrong."""
    if not raw:
        return ""
    raw = raw.strip()
    # Must contain AM or PM to be a valid game time (filters out durations like "2:26")
    if not re.search(r'\b(AM|PM|a\.m\.|p\.m\.)\b', raw, re.IGNORECASE):
        return ""
    # Remove any extra whitespace
    return re.sub(r'\s+', ' ', raw).upper()


# ─────────────────────────────────────────────
# ESPN.COM SCHEDULE SCRAPER
# ─────────────────────────────────────────────

def espn_schedule_scrape(event: dict, run_type: str) -> dict:
    """Scrape ESPN.com schedule page for game time and TV channel.
    URL: espn.com/{sport}/schedule/_/date/{YYYYMMDD}
    Times are already in ET. Covers MLB, NFL, NBA, NHL, WNBA, NCAAF, NCAAB, MLS.
    This is separate from the ESPN scoreboard API and often has better channel data.
    """
    result = {"actual_start":"","actual_end":"","video_duration":"","national_channel":"",
              "local_home":"","local_away":"","streaming":"","status_hint":""}
    league = event.get("league","").upper()
    date_str = event.get("event_date","")

    espn_path_map = {
        "MLB":   "mlb/schedule",
        "NFL":   "nfl/schedule",
        "NBA":   "nba/schedule",
        "NHL":   "nhl/schedule",
        "WNBA":  "wnba/schedule",
        "NCAAF": "college-football/schedule",
        "NCAAB": "mens-college-basketball/schedule",
        "MLS":   "soccer/schedule/_/league/usa.1",
    }
    if league not in espn_path_map:
        return result

    try:
        for fmt in ["%Y-%m-%d","%m/%d/%Y","%m/%d/%y"]:
            try:
                dt = datetime.strptime(str(date_str).strip(), fmt)
                date_param = dt.strftime("%Y%m%d")
                break
            except ValueError:
                continue
        else:
            return result
    except Exception:
        return result

    path = espn_path_map[league]
    if "league" in path:
        url = f"https://www.espn.com/{path}/date/{date_param}"
    else:
        url = f"https://www.espn.com/{path}/_/date/{date_param}"

    try:
        resp = requests.get(url, timeout=15, headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Accept": "text/html,application/xhtml+xml",
        })
        if resp.status_code != 200:
            return result
        html = resp.text
    except Exception:
        return result

    event_name = event.get("event_name","").lower()
    parts = re.split(r'\s+@\s+|\s+vs\.?\s+', event_name)
    teams = [p.strip().lower() for p in parts if len(p.strip()) > 2]
    short_teams = []
    for t in teams:
        words = t.split()
        if words:
            short_teams.append(words[-1])
            if len(words) >= 2:
                short_teams.append(words[0])
    all_terms = list(set(teams + short_teams))

    time_pat = re.compile(r'\b(\d{1,2}:\d{2}\s*(?:AM|PM))\b', re.IGNORECASE)
    channel_norm = {
        "ESPN UNLMTD": "ESPN+", "ESPN UNLIMITED": "ESPN+",
        "ESPN UNLTD": "ESPN+", "ESPN+": "ESPN+",
        "APPLE TV+": "Apple TV+", "PEACOCK": "Peacock",
        "PARAMOUNT+": "Paramount+", "AMAZON PRIME": "Amazon Prime",
        "MAX": "Max", "FUBO": "FuboTV",
        "MLB.TV": "MLB.TV", "NBA TV": "NBA TV",
        "NHL NETWORK": "NHL Network", "NFL NETWORK": "NFL Network",
    }

    rows = re.findall(r'<tr[^>]*>(.*?)</tr>', html, re.DOTALL | re.IGNORECASE)
    for row in rows:
        cells = re.findall(r'<td[^>]*>(.*?)</td>', row, re.DOTALL | re.IGNORECASE)
        if len(cells) < 2:
            continue
        cell_texts = []
        for c in cells:
            txt = re.sub(r'<[^>]+>', ' ', c)
            txt = re.sub(r'&amp;', '&', txt)
            txt = re.sub(r'&nbsp;', ' ', txt)
            txt = re.sub(r'\s+', ' ', txt).strip()
            cell_texts.append(txt)

        row_text = " ".join(cell_texts).lower()
        if not any(t in row_text for t in all_terms):
            continue

        for ct in cell_texts:
            m = time_pat.search(ct)
            if m and not result["actual_start"]:
                result["actual_start"] = m.group(0).strip().upper() + " ET"

        for ct in cell_texts:
            ct_upper = ct.upper().strip()
            for abbr, canonical in channel_norm.items():
                if abbr in ct_upper:
                    _classify_channel(canonical, result)
            for token in re.split(r'[\s,/]+', ct_upper):
                token_clean = re.sub(r'[^A-Z0-9+]', '', token)
                if token_clean in {"ESPN","ESPN2","ESPNU","ABC","NBC","CBS","FOX","FS1","FS2",
                                   "BTN","ACCN","SECN","CBSSN","TBS","TNT","USA","NBCSN",
                                   "MLBN","NBATV","NHLN","NFLN","PEACOCK"}:
                    _classify_channel(token_clean, result)

        if result["actual_start"] or result["national_channel"] or result["streaming"]:
            break

    return result


# ─────────────────────────────────────────────
# SPORTS MEDIA WATCH SCRAPER
# ─────────────────────────────────────────────

def sportsmediawatch_lookup(event: dict, run_type: str) -> dict:
    """Scrape Sports Media Watch 'Sports on TV Today' page.
    URL: sportsmediawatch.com/games-on-tv-today-sports-time-channel/
    Covers ALL sports including niche (NHRA, NASCAR, fishing, PBR, boxing, golf, tennis).
    Times are listed in ET (lowercase am/pm format).
    """
    result = {"actual_start":"","actual_end":"","video_duration":"","national_channel":"",
              "local_home":"","local_away":"","streaming":"","status_hint":""}
    try:
        resp = requests.get(
            "https://www.sportsmediawatch.com/games-on-tv-today-sports-time-channel/",
            timeout=15,
            headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"},
        )
        if resp.status_code != 200:
            return result
        html = resp.text
    except Exception:
        return result

    clean = re.sub(r'<br\s*/?>', '\n', html, flags=re.IGNORECASE)
    clean = re.sub(r'<li[^>]*>', '\n', clean, flags=re.IGNORECASE)
    clean = re.sub(r'<p[^>]*>', '\n', clean, flags=re.IGNORECASE)
    clean = re.sub(r'<div[^>]*>', '\n', clean, flags=re.IGNORECASE)
    clean = re.sub(r'<h[1-6][^>]*>', '\n', clean, flags=re.IGNORECASE)
    clean = re.sub(r'<[^>]+>', ' ', clean)
    clean = re.sub(r'&amp;', '&', clean)
    clean = re.sub(r'&nbsp;', ' ', clean)
    clean = re.sub(r'&#\d+;', '', clean)
    lines = [l.strip() for l in clean.splitlines() if l.strip()]

    event_name = event.get("event_name","").lower()
    parts = re.split(r'\s+@\s+|\s+vs\.?\s+', event_name)
    teams = [p.strip().lower() for p in parts if len(p.strip()) > 2]
    short_teams = []
    for t in teams:
        words = t.split()
        if words:
            short_teams.append(words[-1])
            if len(words) >= 2:
                short_teams.append(words[0])
    all_terms = list(set(teams + short_teams))

    time_pat = re.compile(r'\b(\d{1,2}:\d{2}\s*(?:am|pm))\b', re.IGNORECASE)

    for i, line in enumerate(lines):
        line_lower = line.lower()
        if not any(t in line_lower for t in all_terms):
            continue
        window = lines[max(0,i-2):i+5]
        found_time = ""
        found_channels = []
        for wline in window:
            m = time_pat.search(wline)
            if m and not found_time:
                raw = m.group(0).strip()
                found_time = raw.upper() + " ET"
            if found_time and wline != line:
                wl = wline.strip()
                # Split on commas and pipes; strip SMW local-station labels like "A KTVK" / "H SPECSN"
                for ch in re.split(r'[,|]+', wl):
                    ch = ch.strip()
                    # Skip home/away local station labels: "A KXXX" or "H KXXX"
                    if re.match(r'^[AH]\s+[A-Z]{2,6}(\s+[A-Z]{2,6})*$', ch):
                        continue
                    # Skip WNBA League Pass and similar league-pass entries
                    if 'league pass' in ch.lower() or 'league_pass' in ch.lower():
                        continue
                    if ch and len(ch) < 40 and not time_pat.search(ch):
                        found_channels.append(ch)
        if found_time:
            result["actual_start"] = found_time
        for ch in found_channels:
            _classify_channel(ch, result)
        if result["actual_start"] or result["national_channel"] or result["streaming"]:
            break

    return result


def _classify_channel(name: str, result: dict):
    """Put a channel name into the right bucket: national, local_home, local_away, or streaming."""
    if not name:
        return
    n = name.upper().strip()

    # If the name contains a pipe or slash separator, split and classify each part separately
    if "|" in n or " / " in n:
        for part in re.split(r'\||\s*/\s*', n):
            part = part.strip()
            if part:
                _classify_channel(part, result)
        return

    # Hard blocklist — words that appear in "where to watch" UI but are NOT channels
    blocklist = {"WATCH","WITH","ON","AT","THE","AND","OR","LIVE","STREAM","GAME","SPORTS","NETWORK",
                 "TV","TELEVISION","CHANNEL","BROADCAST","APP","PLUS","FREE","ONLINE","NOW","HERE",
                 "SUBSCRIBE","SIGN","UP","IN","OF","FOR","TO","A","AN","IS","ARE","WAS","BE"}
    if n in blocklist or len(n) < 2:
        return

    national = {"ESPN","ESPN2","ESPNU","ABC","NBC","CBS","FOX","FS1","FS2","TNT","TBS","USA",
                "USA NETWORK","NBCSN","CBSSN","TRUETV","GOLF CHANNEL","TENNIS CHANNEL",
                "OUTDOOR CHANNEL","SPORTSMAN CHANNEL","NFL NETWORK","NBA TV","MLB NETWORK",
                "NHL NETWORK","OLYMPIC CHANNEL","ACCN","SECN","BIGTEN","PAC12","LONGHORN"}
    # Comprehensive streaming-only services — these populate STREAMING column only
    # and are NEVER used to drive NETWORK_CHANGED verdicts
    streaming = {
        "PEACOCK","PARAMOUNT+","PARAMOUNTPLUS","PARAMOUNT PLUS",
        "ESPN+","ESPNPLUS","ESPN PLUS","ESPN UNLIMITED","ESPN SELECT",
        "HULU","HULU LIVE","HULU + LIVE TV",
        "FUBO","FUBOTV","FUBO TV",
        "SLING","SLING TV","SLING BLUE","SLING ORANGE",
        "DIRECTV STREAM","DIRECTVSTREAM","DIRECTV NOW",
        "MAX","HBO MAX",
        "APPLE TV+","APPLETV+","APPLE TV PLUS",
        "AMAZON PRIME","AMAZON PRIME VIDEO","PRIME VIDEO",
        "YOUTUBE TV","YOUTUBETV",
        "DAZN",
        "VICTORY+","VICTORY PLUS","VICTORYPLUS",
        "WNBA LEAGUE PASS","WNBA LEAGUEPASS",
        "NBA LEAGUE PASS","NBA LEAGUEPASS","NBA TV CANADA","NBA CANADA",
        "MLB.TV","MLBTV","MLB TV","MLB EXTRA INNINGS",
        "NHL.TV","NHLTV","NHL TV","NHL CENTER ICE",
        "NFLPLUS","NFL+","NFL PLUS","NFL SUNDAY TICKET",
        "TUBI","PLUTO","PLUTO TV","CRACKLE","PEACOCKTV",
        "DISCOVERY+","DISCOVERY PLUS","DISCOVERYPLUS",
        "ESPNEWS","ESPN NEWS",  # streaming-only in most markets
        "TSN+","TVAS+","SN+","RDS+",  # Canadian streaming tiers
        "GOTD","PEACOCK GOTD",  # Peacock Game of the Day label
        "MLBN ALT.","MLBN ALT",  # MLB Network alternate stream
    }

    if n in streaming:
        existing = result.get("streaming","")
        if n not in existing:
            result["streaming"] = (existing + ", " + n).strip(", ") if existing else n
    elif n in national or any(n.startswith(p) for p in ["ESPN","FS1","FS2","NBC","CBS","FOX","TNT","TBS","NFL","NBA","MLB","NHL","ACC","SEC","BIG"]):
        # Extra guard: ESPN+ and ESPN Unlimited are streaming even though they start with ESPN
        if any(x in n for x in ["ESPN+","ESPNPLUS","ESPN PLUS","ESPN UNLIMITED","ESPN SELECT","ESPNNEWS","ESPN NEWS"]):
            existing = result.get("streaming","")
            if n not in existing:
                result["streaming"] = (existing + ", " + n).strip(", ") if existing else n
            return
        # Guard: MLB.TV, NHL.TV, NBA League Pass etc. start with league prefixes but are streaming
        if any(x in n for x in [".TV","LEAGUEPASS","LEAGUE PASS"," EXTRA INNINGS"," CENTER ICE"," SUNDAY TICKET","NFL+","NFLPLUS"]):
            existing = result.get("streaming","")
            if n not in existing:
                result["streaming"] = (existing + ", " + n).strip(", ") if existing else n
            return
        if not result["national_channel"]:
            result["national_channel"] = n
    elif re.match(r'^(K[A-Z]{2,4}|W[A-Z]{2,4}|BALLY|ROOT|NESN|YES|SNY|MSG|MASN|NBCS|ATTSN|SPEC|ROOTSPORTS)', n):
        # Local RSN or OTA call sign — put first in home, second in away
        if not result["local_home"]:
            result["local_home"] = n
        elif not result["local_away"] and n != result["local_home"]:
            result["local_away"] = n

# ─────────────────────────────────────────────
# VERDICT ENGINE
# ─────────────────────────────────────────────

def compute_verdict(event: dict, lookup: dict, run_type: str) -> str:
    sched_ch = normalize_channel(event.get("sched_channel",""))
    status_hint = lookup.get("status_hint","")

    # Hard status overrides
    if status_hint == "postponed":
        return "POSTPONED"
    if status_hint == "canceled":
        return "CANCELED"
    if status_hint == "delayed":
        return "DELAYED"

    nat_ch   = normalize_channel(lookup.get("national_channel",""))
    home_ch  = normalize_channel(lookup.get("local_home",""))
    away_ch  = normalize_channel(lookup.get("local_away",""))
    stream_ch = normalize_channel(lookup.get("streaming",""))
    # Include all found channels — national, local, and streaming — in the match set.
    # Split comma-separated streaming entries so each service is checked individually.
    all_found = {c for c in [nat_ch, home_ch, away_ch] if c}
    for s in re.split(r'[,;]+', lookup.get("streaming","")):
        sc = normalize_channel(s.strip())
        if sc:
            all_found.add(sc)

    if run_type == "pre_event":
        if not all_found:
            # If scheduled on a known local station, mark UNCONFIRMED (not UNVERIFIED)
            if sched_ch and is_known_local(event.get("sched_channel","")):
                return "UNCONFIRMED"
            # Streaming services found but no linear TV — still unverified for linear purposes
            if _has_streaming_only(lookup):
                return "UNVERIFIED"
            return "UNVERIFIED"
        # Any single channel match anywhere = confirmed
        if not sched_ch or sched_ch in all_found:
            return "MATCH"
        # Linear channel found but doesn't match scheduled — real mismatch
        return "MISMATCH"
    else:
        # Day-after
        if not all_found:
            # Known local station — assume aired as scheduled
            if sched_ch and is_known_local(event.get("sched_channel","")):
                return "AIRED_AS_SCHEDULED"
            # Streaming services found but no linear TV — unverified for linear purposes
            if _has_streaming_only(lookup):
                return "UNVERIFIED"
            return "UNVERIFIED"
        # Any single channel match anywhere = confirmed
        if not sched_ch or sched_ch in all_found:
            return "AIRED_AS_SCHEDULED"
        # Linear channel found but different from scheduled — real network change
        return "NETWORK_CHANGED"

def _has_streaming_only(lookup: dict) -> bool:
    """Return True if the lookup found streaming services but no linear TV channel."""
    has_linear = any(lookup.get(k,"") for k in ("national_channel","local_home","local_away"))
    has_streaming = bool(lookup.get("streaming",""))
    return has_streaming and not has_linear

# ─────────────────────────────────────────────
# RUN VERIFICATION
# ─────────────────────────────────────────────

def run_verification(events: list[dict], run_type: str, api_key: str, run_name: str) -> pd.DataFrame:
    conn = get_db()
    c = conn.cursor()
    # Add new columns if they don't exist yet (safe migration)
    for col_def in [("video_duration","TEXT"), ("sources_used","TEXT")]:
        try:
            c.execute(f"ALTER TABLE verification_results ADD COLUMN {col_def[0]} {col_def[1]}")
            conn.commit()
        except Exception:
            pass  # Column already exists

    c.execute("INSERT INTO verification_runs (run_name, run_type, event_count) VALUES (?,?,?)",
              (run_name, run_type, len(events)))
    run_id = c.lastrowid
    conn.commit()

    results = []
    progress = st.progress(0, text="Running verification...")
    total = len(events)

    for i, event in enumerate(events):
        league = event.get("league","")
        progress.progress((i + 1) / total, text=f"[{i+1}/{total}] {league} — {event.get('event_name','')[:40]}")

        # Run all available sources
        lookup = multi_source_lookup(event, api_key, run_type)
        verdict = compute_verdict(event, lookup, run_type)

        # If still no data found, fall back to known-local logic
        if verdict == "UNVERIFIED" and is_known_local(event.get("sched_channel","")):
            verdict = "AIRED_AS_SCHEDULED" if run_type == "day_after" else "UNCONFIRMED"

        row = {
            "run_id":          run_id,
            "league":          event.get("league",""),
            "event_name":      event.get("event_name",""),
            "event_date":      event.get("event_date",""),
            "sched_start":     event.get("sched_start",""),
            "sched_channel":   event.get("sched_channel",""),
            "actual_start":    lookup.get("actual_start",""),
            "actual_end":      lookup.get("actual_end",""),
            "video_duration":  lookup.get("video_duration",""),
            "national_channel":lookup.get("national_channel",""),
            "local_home":      lookup.get("local_home",""),
            "local_away":      lookup.get("local_away",""),
            "streaming":       lookup.get("streaming",""),
            "verdict":         verdict,
            "search_url":      lookup.get("search_url",""),
            "sources_used":    ", ".join(lookup.get("sources_used",[])),
        }
        results.append(row)
        c.execute("""INSERT INTO verification_results
            (run_id,league,event_name,event_date,sched_start,sched_channel,
             actual_start,actual_end,video_duration,national_channel,local_home,local_away,
             streaming,verdict,search_url,sources_used)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (row["run_id"],row["league"],row["event_name"],row["event_date"],
             row["sched_start"],row["sched_channel"],row["actual_start"],row["actual_end"],
             row["video_duration"],row["national_channel"],row["local_home"],row["local_away"],
             row["streaming"],row["verdict"],row["search_url"],row["sources_used"]))
        conn.commit()

    progress.empty()
    conn.close()
    return pd.DataFrame(results)

# ─────────────────────────────────────────────
# RESULTS TABLE RENDERER
# ─────────────────────────────────────────────

def verdict_html(verdict: str) -> str:
    color = VERDICT_COLORS.get(verdict, "yellow")
    css = f"verdict-{color}"
    return f'<span class="{css}">{verdict}</span>'

def render_results_table(df: pd.DataFrame):
    if df.empty:
        st.info("No results to display.")
        return

    # Build HTML table
    rows_html = ""
    for _, row in df.iterrows():
        verdict = str(row.get("verdict","UNVERIFIED"))
        color = VERDICT_COLORS.get(verdict, "yellow")
        bg = {"green":"#0d2618","orange":"#2d1e0a","red":"#2d1515","yellow":"#2d2600"}.get(color,"#161b22")

        search_url = row.get("search_url","")
        search_link = f'<a href="{search_url}" target="_blank" style="color:#58a6ff;font-size:11px;">🔍 Google</a>' if search_url else ""

        actual_start = str(row.get("actual_start","") or "—")
        actual_end   = str(row.get("actual_end","") or "—")
        video_dur    = str(row.get("video_duration","") or "—")
        nat_ch       = str(row.get("national_channel","") or "—")
        local_home   = str(row.get("local_home","") or "—")
        local_away   = str(row.get("local_away","") or "—")
        streaming    = str(row.get("streaming","") or "—")
        sources      = str(row.get("sources_used","") or "—")

        rows_html += f"""
        <tr style="background:{bg}; border-bottom:1px solid #30363d;">
            <td style="padding:6px 10px; color:#8b949e; font-size:12px;">{row.get('league','')}</td>
            <td style="padding:6px 10px; color:#e6edf3; font-size:12px; max-width:200px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap;" title="{row.get('event_name','')}">{row.get('event_name','')}</td>
            <td style="padding:6px 10px; color:#8b949e; font-size:12px;">{row.get('event_date','')}</td>
            <td style="padding:6px 10px; color:#8b949e; font-size:12px;">{row.get('sched_start','') or '—'}</td>
            <td style="padding:6px 10px; color:#58a6ff; font-size:12px; font-weight:600;">{actual_start}</td>
            <td style="padding:6px 10px; color:#58a6ff; font-size:12px; font-weight:600;">{actual_end}</td>
            <td style="padding:6px 10px; color:#a5d6ff; font-size:12px;">{video_dur}</td>
            <td style="padding:6px 10px; color:#8b949e; font-size:12px;">{row.get('sched_channel','') or '—'}</td>
            <td style="padding:6px 10px; color:#e6edf3; font-size:12px;">{nat_ch}</td>
            <td style="padding:6px 10px; color:#e6edf3; font-size:12px;">{local_home}</td>
            <td style="padding:6px 10px; color:#e6edf3; font-size:12px;">{local_away}</td>
            <td style="padding:6px 10px; color:#a5d6ff; font-size:12px;">{streaming}</td>
            <td style="padding:6px 10px;">{verdict_html(verdict)}</td>
            <td style="padding:6px 10px; color:#6e7681; font-size:10px;">{sources}</td>
            <td style="padding:6px 10px;">{search_link}</td>
        </tr>"""

    table_html = f"""
    <div style="overflow-x:auto; border-radius:8px; border:1px solid #30363d;">
    <table style="width:100%; border-collapse:collapse; background:#0f1117;">
        <thead>
            <tr style="background:#161b22; border-bottom:2px solid #30363d;">
                <th style="padding:8px 10px; color:#8b949e; font-size:11px; text-align:left; white-space:nowrap;">LEAGUE</th>
                <th style="padding:8px 10px; color:#8b949e; font-size:11px; text-align:left; white-space:nowrap;">EVENT</th>
                <th style="padding:8px 10px; color:#8b949e; font-size:11px; text-align:left; white-space:nowrap;">DATE</th>
                <th style="padding:8px 10px; color:#8b949e; font-size:11px; text-align:left; white-space:nowrap;">SCHED START</th>
                <th style="padding:8px 10px; color:#58a6ff; font-size:11px; text-align:left; white-space:nowrap;">ACT. START</th>
                <th style="padding:8px 10px; color:#58a6ff; font-size:11px; text-align:left; white-space:nowrap;">ACT. END</th>
                <th style="padding:8px 10px; color:#a5d6ff; font-size:11px; text-align:left; white-space:nowrap;">VIDEO DUR.</th>
                <th style="padding:8px 10px; color:#8b949e; font-size:11px; text-align:left; white-space:nowrap;">SCHED CH</th>
                <th style="padding:8px 10px; color:#8b949e; font-size:11px; text-align:left; white-space:nowrap;">NATIONAL</th>
                <th style="padding:8px 10px; color:#8b949e; font-size:11px; text-align:left; white-space:nowrap;">LOCAL HOME</th>
                <th style="padding:8px 10px; color:#8b949e; font-size:11px; text-align:left; white-space:nowrap;">LOCAL AWAY</th>
                <th style="padding:8px 10px; color:#8b949e; font-size:11px; text-align:left; white-space:nowrap;">STREAMING</th>
                <th style="padding:8px 10px; color:#8b949e; font-size:11px; text-align:left; white-space:nowrap;">VERDICT</th>
                <th style="padding:8px 10px; color:#6e7681; font-size:11px; text-align:left; white-space:nowrap;">SOURCES</th>
                <th style="padding:8px 10px; color:#8b949e; font-size:11px; text-align:left; white-space:nowrap;">SEARCH</th>
            </tr>
        </thead>
        <tbody>{rows_html}</tbody>
    </table>
    </div>"""
    st.markdown(table_html, unsafe_allow_html=True)

# ─────────────────────────────────────────────
# SIDEBAR
# ─────────────────────────────────────────────

def render_sidebar():
    st.sidebar.markdown("## 📡 Broadcast Verifier")
    st.sidebar.markdown("---")

    # Settings
    st.sidebar.markdown("### ⚙️ Settings")
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT value FROM settings WHERE key='serpapi_key'")
    row = c.fetchone()
    saved_key = row["value"] if row else ""
    conn.close()

    api_key = st.sidebar.text_input("SerpApi Key", value=saved_key, type="password",
                                     help="Get a free key at serpapi.com (100 searches/month free)")
    if api_key != saved_key:
        conn = get_db()
        conn.execute("INSERT OR REPLACE INTO settings (key,value) VALUES ('serpapi_key',?)", (api_key,))
        conn.commit()
        conn.close()
        st.sidebar.success("Key saved!")

    st.sidebar.markdown("---")

    # Leagues
    st.sidebar.markdown("### 🏆 Leagues")
    conn = get_db()
    leagues = [dict(r) for r in conn.execute("SELECT * FROM leagues WHERE active=1 ORDER BY name").fetchall()]
    conn.close()

    for lg in leagues:
        badge = "🔵" if lg["sport_type"] == "matchup" else "🟠"
        st.sidebar.markdown(f"{badge} **{lg['display_name']}** `{lg['name']}`")

    # Add new league
    with st.sidebar.expander("➕ Add New Sport / League"):
        new_name    = st.text_input("Short code (e.g. USFL)", key="new_league_name").upper()
        new_display = st.text_input("Display name (e.g. USFL Football)", key="new_league_display")
        new_type    = st.selectbox("Type", ["matchup","event"],
                                   help="Matchup = home vs away (MLB, NFL). Event = single event (NHRA, golf, fishing).",
                                   key="new_league_type")
        if st.button("Add League"):
            if new_name and new_display:
                conn = get_db()
                try:
                    conn.execute("INSERT INTO leagues (name, display_name, sport_type) VALUES (?,?,?)",
                                 (new_name, new_display, new_type))
                    conn.commit()
                    st.success(f"Added {new_display}!")
                    st.rerun()
                except sqlite3.IntegrityError:
                    st.error("A league with that code already exists.")
                finally:
                    conn.close()
            else:
                st.warning("Please fill in both fields.")

    st.sidebar.markdown("---")
    st.sidebar.markdown("🔵 Matchup (home vs away)  \n🟠 Event (race, tournament, etc.)")

    return api_key

# ─────────────────────────────────────────────
# MAIN APP
# ─────────────────────────────────────────────

def main():
    api_key = render_sidebar()

    tab_dash, tab_history = st.tabs(["📊 Dashboard", "🕐 Run History"])

    # ── DASHBOARD TAB ──────────────────────────
    with tab_dash:
        st.title("Broadcast Verification Dashboard")
        st.caption("Upload your Zoomph schedule, run a cross-check, and verify actual broadcast outcomes.")

        # ── Import section ─────────────────────
        col1, col2 = st.columns([3, 1])
        with col1:
            st.markdown("#### 📋 Import Schedule")

        import_method = st.radio("Import method", ["Google Sheets link", "Upload CSV file"], horizontal=True)

        events = []
        if import_method == "Google Sheets link":
            sheets_url = st.text_input("Paste shareable Google Sheets link",
                                        placeholder="https://docs.google.com/spreadsheets/d/...")
            if sheets_url and st.button("Import from Google Sheets"):
                with st.spinner("Fetching sheet..."):
                    df = fetch_google_sheet(sheets_url)
                if df is not None:
                    st.session_state["schedule_df"] = df
                    st.success(f"Imported {len(df)} rows from Google Sheets")
        else:
            uploaded = st.file_uploader("Drop your CSV file here", type=["csv"])
            if uploaded:
                df = pd.read_csv(uploaded)
                st.session_state["schedule_df"] = df
                st.success(f"Loaded {len(df)} rows from CSV")

        # ── Schedule preview ───────────────────
        if "schedule_df" in st.session_state:
            raw_df = st.session_state["schedule_df"]
            if _is_zoomph_format(raw_df):
                events = _parse_zoomph_df(raw_df)
            else:
                events = parse_schedule_df(raw_df)

            st.markdown(f"#### 📅 Schedule — {len(events)} events loaded")

            if len(events) == 0:
                # Show raw columns to help user understand what was detected
                st.warning("⚠️ Could not auto-detect columns in your file. Your sheet has these column names:")
                st.code(", ".join(raw_df.columns.tolist()))
                st.info("👇 Use the column mapping below to tell the app which column is which.")

                # Manual column mapping UI
                with st.expander("🗂️ Map your columns manually", expanded=True):
                    all_cols = ["(none)"] + raw_df.columns.tolist()
                    col1, col2, col3 = st.columns(3)
                    with col1:
                        map_event  = st.selectbox("Event / Team name column", all_cols, key="map_event")
                        map_league = st.selectbox("League column", all_cols, key="map_league")
                    with col2:
                        map_date   = st.selectbox("Date column", all_cols, key="map_date")
                        map_time   = st.selectbox("Start time column", all_cols, key="map_time")
                    with col3:
                        map_channel = st.selectbox("Channel / Network column", all_cols, key="map_channel")
                        map_away    = st.selectbox("Away team column (optional)", all_cols, key="map_away")

                    if st.button("Apply Column Mapping"):
                        # Rebuild events using manual mapping
                        manual_events = []
                        for _, row in raw_df.iterrows():
                            home_val = str(row.get(map_event if map_event != "(none)" else "", "")).strip()
                            away_val = str(row.get(map_away  if map_away  != "(none)" else "", "")).strip()
                            if away_val and away_val not in ("nan",""):
                                event_name = f"{away_val} @ {home_val}"
                            else:
                                event_name = home_val
                            manual_events.append({
                                "league":        str(row.get(map_league  if map_league  != "(none)" else "", "")).strip(),
                                "event_name":    event_name,
                                "event_date":    str(row.get(map_date    if map_date    != "(none)" else "", "")).strip(),
                                "sched_start":   str(row.get(map_time    if map_time    != "(none)" else "", "")).strip(),
                                "sched_channel": str(row.get(map_channel if map_channel != "(none)" else "", "")).strip(),
                            })
                        manual_events = [e for e in manual_events if e["event_name"] and e["event_name"] != "nan"]
                        if manual_events:
                            st.session_state["events_override"] = manual_events
                            st.success(f"Mapped {len(manual_events)} events! Scroll down to run verification.")
                            st.rerun()
                        else:
                            st.error("Still no events found. Check that the Event column contains data.")
            else:
                # Safe preview — only show columns that exist
                preview_data = pd.DataFrame(events)
                show_cols = [c for c in ["league","event_name","event_date","sched_start","sched_channel"] if c in preview_data.columns]
                preview_df = preview_data[show_cols].copy()
                preview_df.columns = [{"league":"League","event_name":"Event","event_date":"Date","sched_start":"Sched. Start","sched_channel":"Sched. Channel"}.get(c,c) for c in show_cols]
                st.dataframe(preview_df, use_container_width=True, height=250)

            # Use manual override if set
            if "events_override" in st.session_state:
                events = st.session_state["events_override"]

            # ── Run buttons ────────────────────
            st.markdown("---")
            col_pre, col_day, col_name = st.columns([1, 1, 2])
            with col_name:
                run_name = st.text_input("Run name (optional)", placeholder=f"Verification {date.today()}")
            with col_pre:
                run_pre = st.button("▶ Run Pre-Event Check", use_container_width=True)
            with col_day:
                run_day = st.button("📅 Run Day-After Verification", use_container_width=True, type="primary")

            if not api_key:
                st.warning("⚠️ No SerpApi key set — verification will use local station matching only. Add your key in the sidebar for full Google Search lookups.")

            # ── Run pre-event ──────────────────
            if run_pre:
                name = run_name or f"Pre-Event {date.today()}"
                with st.spinner("Running pre-event cross-check..."):
                    results_df = run_verification(events, "pre_event", api_key, name)
                st.session_state["results_df"] = results_df
                st.session_state["results_type"] = "Pre-Event"
                st.success(f"Pre-event check complete — {len(results_df)} events processed")

            # ── Run day-after ──────────────────
            if run_day:
                name = run_name or f"Day-After {date.today()}"
                with st.spinner("Running day-after verification..."):
                    results_df = run_verification(events, "day_after", api_key, name)
                st.session_state["results_df"] = results_df
                st.session_state["results_type"] = "Day-After"
                st.success(f"Day-after verification complete — {len(results_df)} events processed")

        # ── Results section ────────────────────
        if "results_df" in st.session_state:
            results_df = st.session_state["results_df"]
            rtype = st.session_state.get("results_type","")

            st.markdown(f"---")
            st.markdown(f"#### 🎯 {rtype} Results")

            # Summary stats
            verdicts = results_df["verdict"].value_counts()
            cols = st.columns(min(len(verdicts), 5))
            for i, (v, cnt) in enumerate(verdicts.items()):
                color = VERDICT_COLORS.get(v,"yellow")
                emoji = {"green":"✅","orange":"⚠️","red":"🔴","yellow":"🟡"}.get(color,"⚪")
                if i < len(cols):
                    cols[i].metric(f"{emoji} {v}", cnt)

            # Filter
            filter_verdict = st.multiselect("Filter by verdict", options=list(VERDICT_COLORS.keys()),
                                             default=[], key="verdict_filter")
            display_df = results_df[results_df["verdict"].isin(filter_verdict)] if filter_verdict else results_df

            # Render table
            render_results_table(display_df)

            # CSV export
            st.markdown("---")
            export_cols = ["league","event_name","event_date","sched_start","sched_channel",
                           "actual_start","actual_end","video_duration","national_channel",
                           "local_home","local_away","streaming","verdict","sources_used"]
            export_df = results_df[[c for c in export_cols if c in results_df.columns]].copy()
            col_labels = {
                "league":"League","event_name":"Event","event_date":"Date",
                "sched_start":"Sched Start","sched_channel":"Sched Channel",
                "actual_start":"Actual Start","actual_end":"Actual End",
                "video_duration":"Video Duration","national_channel":"National Channel",
                "local_home":"Local Home","local_away":"Local Away",
                "streaming":"Streaming","verdict":"Verdict","sources_used":"Sources Used",
            }
            export_df.columns = [col_labels.get(c,c) for c in export_df.columns]
            csv_bytes = export_df.to_csv(index=False).encode("utf-8")
            st.download_button(
                label="⬇️ Download Results as CSV",
                data=csv_bytes,
                file_name=f"broadcast_verification_{date.today()}.csv",
                mime="text/csv",
            )

    # ── RUN HISTORY TAB ────────────────────────
    with tab_history:
        st.title("Run History")
        st.caption("All past verification runs saved to the database.")

        conn = get_db()
        runs = [dict(r) for r in conn.execute(
            "SELECT * FROM verification_runs ORDER BY created_at DESC LIMIT 50"
        ).fetchall()]
        conn.close()

        if not runs:
            st.info("No verification runs yet. Go to the Dashboard tab and run a verification.")
        else:
            for run in runs:
                with st.expander(f"{'▶' if run['run_type']=='pre_event' else '📅'} {run['run_name'] or run['run_type']} — {run['created_at'][:16]} ({run['event_count']} events)"):
                    conn = get_db()
                    res = [dict(r) for r in conn.execute(
                        "SELECT * FROM verification_results WHERE run_id=?", (run["id"],)
                    ).fetchall()]
                    conn.close()

                    if res:
                        hist_df = pd.DataFrame(res)
                        render_results_table(hist_df)

                        export_cols = ["league","event_name","event_date","sched_start","sched_channel",
                                       "actual_start","actual_end","national_channel","local_home","local_away","streaming","verdict"]
                        available = [c for c in export_cols if c in hist_df.columns]
                        csv_bytes = hist_df[available].to_csv(index=False).encode("utf-8")
                        st.download_button(
                            label="⬇️ Download this run as CSV",
                            data=csv_bytes,
                            file_name=f"run_{run['id']}_{date.today()}.csv",
                            mime="text/csv",
                            key=f"dl_{run['id']}",
                        )

if __name__ == "__main__":
    main()
