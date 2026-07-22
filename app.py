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
            national_channel TEXT,
            local_home TEXT,
            local_away TEXT,
            streaming TEXT,
            verdict TEXT,
            notes TEXT,
            search_url TEXT,
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
    for k in ["time","start_time","scheduled_time","air_time","gametime","start","kickoff","start time","air time","game time","scheduled start","tip off","tipoff","puck drop"]:
        if k in cols: mapping["time"] = cols[k]; break

    return mapping

def parse_schedule_df(df: pd.DataFrame) -> list[dict]:
    """Normalize a raw dataframe into a list of event dicts."""
    mapping = detect_columns(df)

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

        events.append({
            "league":        str(row.get(mapping.get("league",""), "")).strip(),
            "event_name":    event_name,
            "event_date":    str(row.get(mapping.get("date",""), "")).strip(),
            "sched_start":   str(row.get(mapping.get("time",""), "")).strip(),
            "sched_channel": str(row.get(mapping.get("channel",""), "")).strip(),
        })
    return [e for e in events if e["event_name"] and e["event_name"] != "nan"]

# ─────────────────────────────────────────────
# SERPAPI GOOGLE SEARCH LOOKUP
# ─────────────────────────────────────────────

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

    # --- Extract from sports_results widget ---
    sr = data.get("sports_results", {})
    if sr:
        # Broadcast channels from sports widget
        channels = sr.get("channels", [])
        if isinstance(channels, list):
            for ch in channels:
                name = ch.get("name","") if isinstance(ch, dict) else str(ch)
                _classify_channel(name, result)
        elif isinstance(channels, str):
            _classify_channel(channels, result)

        # Game time from sports widget
        game_date = sr.get("game_spotlight", {})
        if isinstance(game_date, dict):
            time_val = game_date.get("match_time") or game_date.get("time","")
            if time_val and not result["actual_start"]:
                result["actual_start"] = time_val

        # Venue/status for delay detection
        status = sr.get("status","").lower()
        if "delay" in status or "rain" in status:
            result["status_hint"] = "delayed"
        elif "postpone" in status:
            result["status_hint"] = "postponed"
        elif "cancel" in status:
            result["status_hint"] = "canceled"

    # --- Extract from organic results snippets ---
    for organic in data.get("organic_results", []):
        snippet = organic.get("snippet","").lower()
        title   = organic.get("title","").lower()
        full_text = snippet + " " + title

        # Look for time patterns like "7:30 PM ET" or "8:00 p.m."
        time_matches = re.findall(r'\b(\d{1,2}:\d{2}\s*(?:am|pm|a\.m\.|p\.m\.)?(?:\s*[a-z]{2,3}t?)?)\b', full_text, re.IGNORECASE)
        if time_matches and not result["actual_start"]:
            result["actual_start"] = time_matches[0].strip().upper()
        if len(time_matches) > 1 and not result["actual_end"]:
            result["actual_end"] = time_matches[-1].strip().upper()

        # Look for channel names in snippets
        channel_patterns = [
            r'\b(ESPN2?|FS[12]|TNT|TBS|ABC|NBC|CBS|FOX|NBCSN|CBSSN|USA|PEACOCK|PARAMOUNT\+?)\b',
            r'\b(BALLY\s*SPORTS?|ROOT\s*SPORTS?|NESN|YES\s*NETWORK|SNY|MSG|MASN|NBCS[A-Z]*)\b',
            r'\b(K[A-Z]{2,4}|W[A-Z]{2,4})\b',  # call signs
        ]
        for pat in channel_patterns:
            found = re.findall(pat, full_text, re.IGNORECASE)
            for ch in found:
                _classify_channel(ch.strip(), result)

        # Streaming platforms
        streaming_platforms = ["peacock","paramount+","paramount plus","espn+","hulu","fubo","sling","directv stream","max","apple tv","amazon prime","youtube tv"]
        for platform in streaming_platforms:
            if platform in full_text and platform.upper() not in result["streaming"]:
                existing = result["streaming"]
                result["streaming"] = (existing + ", " + platform.upper()).strip(", ") if existing else platform.upper()

        # Delay / postpone / cancel detection
        if any(w in full_text for w in ["rain delay","weather delay","delayed","postponed","called off","canceled","cancelled","rescheduled"]):
            if "delay" in full_text and "status_hint" not in result:
                result["status_hint"] = "delayed"
            elif "postpone" in full_text and "status_hint" not in result:
                result["status_hint"] = "postponed"
            elif any(w in full_text for w in ["cancel","called off"]) and "status_hint" not in result:
                result["status_hint"] = "canceled"

    return result

def _classify_channel(name: str, result: dict):
    """Put a channel name into the right bucket: national, local_home, local_away, or streaming."""
    if not name:
        return
    n = name.upper().strip()
    national = {"ESPN","ESPN2","ESPNU","ABC","NBC","CBS","FOX","FS1","FS2","TNT","TBS","USA","NBCSN","CBSSN","PEACOCK","PARAMOUNT","PARAMOUNT+","TBS","TRUETV","GOLF CHANNEL","TENNIS CHANNEL","OUTDOOR CHANNEL","SPORTSMAN CHANNEL"}
    streaming = {"PEACOCK","PARAMOUNT+","ESPN+","HULU","FUBO","SLING","DIRECTV STREAM","MAX","APPLE TV+","AMAZON PRIME","YOUTUBE TV","DAZN"}

    if n in streaming:
        existing = result.get("streaming","")
        if n not in existing:
            result["streaming"] = (existing + ", " + n).strip(", ") if existing else n
    elif n in national or any(n.startswith(p) for p in ["ESPN","FS","NBC","CBS","FOX","TNT","TBS"]):
        if not result["national_channel"]:
            result["national_channel"] = n
    else:
        # Local RSN — put first in home, second in away
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
    all_found = {c for c in [nat_ch, home_ch, away_ch] if c}

    if run_type == "pre_event":
        if not all_found:
            # If scheduled on a known local station, mark UNCONFIRMED (not UNVERIFIED)
            if sched_ch and is_known_local(event.get("sched_channel","")):
                return "UNCONFIRMED"
            return "UNVERIFIED"
        if sched_ch in all_found:
            return "MATCH"
        return "MISMATCH"
    else:
        # Day-after
        if not all_found:
            # Known local station — assume aired as scheduled
            if sched_ch and is_known_local(event.get("sched_channel","")):
                return "AIRED_AS_SCHEDULED"
            return "UNVERIFIED"
        if sched_ch in all_found:
            return "AIRED_AS_SCHEDULED"
        # Channel found but different
        return "NETWORK_CHANGED"

# ─────────────────────────────────────────────
# RUN VERIFICATION
# ─────────────────────────────────────────────

def run_verification(events: list[dict], run_type: str, api_key: str, run_name: str) -> pd.DataFrame:
    conn = get_db()
    c = conn.cursor()
    c.execute("INSERT INTO verification_runs (run_name, run_type, event_count) VALUES (?,?,?)",
              (run_name, run_type, len(events)))
    run_id = c.lastrowid
    conn.commit()

    results = []
    progress = st.progress(0, text="Running verification...")
    total = len(events)

    for i, event in enumerate(events):
        progress.progress((i + 1) / total, text=f"Checking {i+1}/{total}: {event.get('event_name','')[:40]}")

        lookup = serpapi_lookup(event, api_key, run_type) if api_key else {
            "actual_start":"","actual_end":"","national_channel":"",
            "local_home":"","local_away":"","streaming":"",
            "search_url": build_fallback_url(event, run_type),
        }

        # If no SerpApi key, use known-local logic only
        if not api_key:
            if is_known_local(event.get("sched_channel","")):
                verdict = "AIRED_AS_SCHEDULED" if run_type == "day_after" else "UNCONFIRMED"
            else:
                verdict = "UNVERIFIED"
        else:
            verdict = compute_verdict(event, lookup, run_type)

        row = {
            "run_id":          run_id,
            "league":          event.get("league",""),
            "event_name":      event.get("event_name",""),
            "event_date":      event.get("event_date",""),
            "sched_start":     event.get("sched_start",""),
            "sched_channel":   event.get("sched_channel",""),
            "actual_start":    lookup.get("actual_start",""),
            "actual_end":      lookup.get("actual_end",""),
            "national_channel":lookup.get("national_channel",""),
            "local_home":      lookup.get("local_home",""),
            "local_away":      lookup.get("local_away",""),
            "streaming":       lookup.get("streaming",""),
            "verdict":         verdict,
            "search_url":      lookup.get("search_url",""),
        }
        results.append(row)
        c.execute("""INSERT INTO verification_results
            (run_id,league,event_name,event_date,sched_start,sched_channel,
             actual_start,actual_end,national_channel,local_home,local_away,streaming,verdict,search_url)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (row["run_id"],row["league"],row["event_name"],row["event_date"],
             row["sched_start"],row["sched_channel"],row["actual_start"],row["actual_end"],
             row["national_channel"],row["local_home"],row["local_away"],
             row["streaming"],row["verdict"],row["search_url"]))
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
        nat_ch       = str(row.get("national_channel","") or "—")
        local_home   = str(row.get("local_home","") or "—")
        local_away   = str(row.get("local_away","") or "—")
        streaming    = str(row.get("streaming","") or "—")

        rows_html += f"""
        <tr style="background:{bg}; border-bottom:1px solid #30363d;">
            <td style="padding:6px 10px; color:#8b949e; font-size:12px;">{row.get('league','')}</td>
            <td style="padding:6px 10px; color:#e6edf3; font-size:12px; max-width:200px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap;" title="{row.get('event_name','')}">{row.get('event_name','')}</td>
            <td style="padding:6px 10px; color:#8b949e; font-size:12px;">{row.get('event_date','')}</td>
            <td style="padding:6px 10px; color:#8b949e; font-size:12px;">{row.get('sched_start','') or '—'}</td>
            <td style="padding:6px 10px; color:#58a6ff; font-size:12px; font-weight:600;">{actual_start}</td>
            <td style="padding:6px 10px; color:#58a6ff; font-size:12px; font-weight:600;">{actual_end}</td>
            <td style="padding:6px 10px; color:#8b949e; font-size:12px;">{row.get('sched_channel','') or '—'}</td>
            <td style="padding:6px 10px; color:#e6edf3; font-size:12px;">{nat_ch}</td>
            <td style="padding:6px 10px; color:#e6edf3; font-size:12px;">{local_home}</td>
            <td style="padding:6px 10px; color:#e6edf3; font-size:12px;">{local_away}</td>
            <td style="padding:6px 10px; color:#a5d6ff; font-size:12px;">{streaming}</td>
            <td style="padding:6px 10px;">{verdict_html(verdict)}</td>
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
                <th style="padding:8px 10px; color:#8b949e; font-size:11px; text-align:left; white-space:nowrap;">SCHED CH</th>
                <th style="padding:8px 10px; color:#8b949e; font-size:11px; text-align:left; white-space:nowrap;">NATIONAL</th>
                <th style="padding:8px 10px; color:#8b949e; font-size:11px; text-align:left; white-space:nowrap;">LOCAL HOME</th>
                <th style="padding:8px 10px; color:#8b949e; font-size:11px; text-align:left; white-space:nowrap;">LOCAL AWAY</th>
                <th style="padding:8px 10px; color:#8b949e; font-size:11px; text-align:left; white-space:nowrap;">STREAMING</th>
                <th style="padding:8px 10px; color:#8b949e; font-size:11px; text-align:left; white-space:nowrap;">VERDICT</th>
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
                           "actual_start","actual_end","national_channel","local_home","local_away","streaming","verdict"]
            export_df = results_df[export_cols].copy()
            export_df.columns = ["League","Event","Date","Sched Start","Sched Channel",
                                  "Actual Start","Actual End","National Channel","Local Home","Local Away","Streaming","Verdict"]
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
