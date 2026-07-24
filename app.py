import streamlit as st
import pandas as pd
import sqlite3
import requests
import json
import re
import io
import os
import html
import time
from datetime import datetime, date, timedelta
from collections import defaultdict

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
            broadcast_channels TEXT,
            verdict TEXT,
            notes TEXT,
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

    # Safe migration: add columns introduced after the table was first created
    existing = {r[1] for r in c.execute("PRAGMA table_info(verification_results)")}
    for col, coltype in [("video_duration", "TEXT"), ("sources_used", "TEXT"),
                         ("notes", "TEXT"), ("details", "TEXT"), ("broadcast_channels", "TEXT")]:
        if col not in existing:
            c.execute(f"ALTER TABLE verification_results ADD COLUMN {col} {coltype}")

    conn.commit()
    conn.close()

@st.cache_resource
def _init_db_once():
    """Run schema setup once per server process, not on every Streamlit rerun."""
    init_db()
    return True

_init_db_once()

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
    "SPECSN","NBCSBA","NBCSCA","KCAL","KABC","KNBC","KTTV","KTLA",
    # Texas
    "BSSW","BALLY","BSSUN","KXAS","KTVT","KHOU","KPRC",
    # Southeast
    "BSSE","BSSO","BSSUN","WFTV","WESH","WSVN","WPLG",
    # Midwest
    "BSGL","BSOH","BSDET","BSIN","BSKC","BSMW",
    # Mountain/West
    "ATTRM","ATTSN","ROOT","ROOTSPORTS","KUSA","KDVR",
    # Generic RSN patterns (national networks are NOT local stations)
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

def channel_tokens(raw: str) -> set[str]:
    """Split a possibly multi-channel string ('ESPN; ABC', 'ESPN, ABC') into
    normalized tokens. Normalizing the joined string as one blob ('ESPNABC')
    would make membership tests always fail."""
    tokens = set()
    for part in re.split(r'[;,/]+|\band\b', raw or "", flags=re.IGNORECASE):
        norm = normalize_channel(part)
        if norm:
            tokens.add(norm)
    return tokens

def channels_match(sched: str, found: set[str]) -> bool:
    """Lenient match: exact token, or one contains the other (>=3 chars) so
    'FOX' matches 'FOXSPORTS' and 'BALLYSPORTS' matches 'BALLY'."""
    if not sched:
        return False
    for f in found:
        if sched == f:
            return True
        if len(sched) >= 3 and len(f) >= 3 and (sched in f or f in sched):
            return True
    return False

_KNOWN_LOCAL_NORM = {normalize_channel(s) for s in KNOWN_LOCAL_STATIONS}

def is_known_local(channel: str) -> bool:
    """True if any channel token in the (possibly multi-channel) string is a
    known local/RSN station."""
    for norm in channel_tokens(channel):
        if norm in _KNOWN_LOCAL_NORM:
            return True
        # Fuzzy: starts with known RSN prefix
        for prefix in ("BALLY","NBCS","ROOT","ATT","SPEC","NESN","MASN","YES","SNY","MSG"):
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
            "home_team":     home,
            "away_team":     away,
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
    start_date_col = gcol("start date")
    league_col     = gcol("league") or gcol("sport")

    def safe(row, col):
        if not col: return ""
        v = str(row.get(col, "") or "").strip()
        return "" if v.lower() in ("nan","--","#n/a","n/a","none","") else v

    # Group rows by game key
    groups = defaultdict(list)
    for _, row in df.iterrows():
        home = safe(row, home_col)
        away = safe(row, away_col)
        row_date = safe(row, date_col) or safe(row, start_date_col)
        if not home and not away:
            continue
        key = (row_date, home.lower(), away.lower())
        groups[key].append(row)

    events = []
    for (row_date, home_l, away_l), rows in groups.items():
        # Use the first row to get canonical names
        first = rows[0]
        home = safe(first, home_col)
        away = safe(first, away_col)
        # If Home Team == Away Team it's a show/event (not a game) — use just the name
        is_show = (home and away and home.lower().strip() == away.lower().strip())
        if is_show:
            event_name = home
        elif away:
            event_name = f"{away} @ {home}"
        else:
            event_name = home
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
        # Collect ALL unique Network values from all rows (excluding Zoomph internal IDs)
        all_nets = []
        for r in rows:
            net_raw    = safe(r, network_col)
            net_parent = safe(r, net_parent_col)
            # Use Network call sign first, then Network Parent as fallback
            ch = net_raw if net_raw and net_raw.upper() not in ZOOMPH_INTERNAL else net_parent
            if ch and ch.upper() not in ZOOMPH_INTERNAL and ch not in all_nets:
                all_nets.append(ch)
        sched_channel = ", ".join(all_nets) if all_nets else ""

        events.append({
            "league":        league,
            "event_name":    event_name,
            "home_team":     home,
            "away_team":     away,
            "event_date":    row_date,
            "sched_start":   sched_start,
            "sched_channel": sched_channel,
        })

    # Filter blank events
    events = [e for e in events if e["event_name"] and e["event_name"] != "nan"]
    return events

# ─────────────────────────────────────────────
# PERPLEXITY LOOKUP  (single source for everything)
#
# Extraction strategy (in order):
#   1. STRUCTURED — request a JSON-schema response from sonar-pro and map
#      fields directly into columns. No regex guessing. This is the primary
#      path and covers the vast majority of lookups.
#   2. TEXT FALLBACK — if the structured call fails or returns unparseable
#      output, fall back to a labeled-lines prompt and the regex extractors.
# Each row's Details value is tagged [structured] or [text fallback] so you
# can audit exactly how every column was filled.
# ─────────────────────────────────────────────

PPLX_URL = "https://api.perplexity.ai/chat/completions"
PPLX_MODEL = "sonar-pro"

# JSON schema for structured broadcast verification results.
# Every field is required; unknowns are empty strings / empty arrays so the
# model can't silently omit columns.
BROADCAST_SCHEMA = {
    "type": "object",
    "properties": {
        "data_found": {
            "type": "boolean",
            "description": "true only if sources confirmed this specific event's broadcast details",
        },
        "status": {
            "type": "string",
            "enum": ["aired", "delayed", "postponed", "canceled", "suspended", "unknown"],
        },
        "actual_start_et": {
            "type": "string",
            "description": "Actual broadcast start time in Eastern Time, e.g. '8:08 PM ET'. Empty string if unknown.",
        },
        "actual_end_et": {
            "type": "string",
            "description": "Actual broadcast end time in Eastern Time, e.g. '11:15 PM ET'. Empty string if unknown.",
        },
        "duration": {
            "type": "string",
            "description": "Total broadcast/video duration, e.g. '3 hours 7 minutes' or '2:01:53'. Empty string if unknown.",
        },
        "national_channels": {"type": "array", "items": {"type": "string"}},
        "local_home_channels": {
            "type": "array", "items": {"type": "string"},
            "description": "Local/RSN channel(s) for the HOME team's market",
        },
        "local_away_channels": {
            "type": "array", "items": {"type": "string"},
            "description": "Local/RSN channel(s) for the AWAY team's market",
        },
        "streaming_platforms": {"type": "array", "items": {"type": "string"}},
        "notes": {
            "type": "string",
            "description": "Only real events: 'Overtime', 'Rain delay', 'Postponed', 'Canceled', 'Extra innings', 'Suspended'. Empty string if none occurred.",
        },
        "summary": {
            "type": "string",
            "description": "1-2 sentence plain-text narrative of what the sources say",
        },
        "confidence": {"type": "string", "enum": ["high", "medium", "low"]},
    },
    "required": ["data_found", "status", "actual_start_et", "actual_end_et", "duration",
                 "national_channels", "local_home_channels", "local_away_channels",
                 "streaming_platforms", "notes", "summary", "confidence"],
    "additionalProperties": False,
}

_JSON_SYSTEM_PROMPT = (
    "You are verifying whether a sports broadcast aired as scheduled. "
    "Search for the specific event and return ONLY a JSON object matching the required schema. "
    "Rules: All times must be in Eastern Time in 'H:MM AM/PM ET' format. "
    "Use empty strings/arrays for anything you cannot verify from sources — never guess. "
    "Set data_found=false and confidence='low' if sources do not cover this specific event on this date. "
    "The notes field must contain ONLY real occurrences (Overtime, Rain delay, Postponed, Canceled, "
    "Extra innings, Suspended) — empty string if the game proceeded normally. "
    "Do not include citation markers or URLs inside the JSON."
)

_TEXT_SYSTEM_PROMPT = (
    "Begin your answer with these five labeled lines, one per line, "
    "using exactly these labels (write 'Not available' if unknown):\n"
    "Start: <start time in ET>\n"
    "End: <end time in ET>\n"
    "Duration: <total broadcast duration>\n"
    "Broadcast: <comma-separated channel(s)/platform(s)>\n"
    "Notes: <Overtime / Rain delay / Postponed / Canceled / Extra innings, or None>\n"
    "Then add 1-2 short plain-text narrative paragraphs. "
    "Do NOT use markdown headers, bullet lists, or bold text. "
    "Be concise and factual."
)

def _call_perplexity(api_key: str, payload: dict) -> tuple[str, list[str], str]:
    """POST to Perplexity with retry/backoff. Returns (answer, citation_urls, error).
    Retries transient errors (429/5xx, connection); returns immediately on 4xx
    so structured-output schema errors fall through to the text path fast.
    Timeout is 60s because the first request with a new JSON schema can take
    10-30s while Perplexity prepares the schema."""
    last_err = ""
    for attempt in range(3):
        try:
            resp = requests.post(
                PPLX_URL,
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                json=payload,
                timeout=60,
            )
            if resp.status_code in (429, 500, 502, 503, 504):
                last_err = f"HTTP {resp.status_code}"
                if attempt < 2:
                    time.sleep(2 ** attempt)
                    continue
                return "", [], last_err
            if resp.status_code >= 400:
                # Non-retryable client error (e.g. schema rejected) — bail now
                return "", [], f"HTTP {resp.status_code}: {resp.text[:200]}"
            data = resp.json()
            answer = (data.get("choices") or [{}])[0].get("message", {}).get("content", "").strip()
            # Newer responses use search_results (dicts); older use citations (URL strings)
            raw_cites = data.get("citations") or data.get("search_results") or []
            citations = [
                c if isinstance(c, str) else (c.get("url") or c.get("link") or "")
                for c in raw_cites
            ]
            return answer, [c for c in citations if c], ""
        except requests.RequestException as exc:
            last_err = str(exc)
            if attempt < 2:
                time.sleep(2 ** attempt)
    return "", [], last_err

def _norm_time_val(val: str) -> str:
    """Normalize a time string: a.m./p.m. -> AM/PM, Eastern/EST/EDT -> ET."""
    val = re.sub(r'a\.m\.?', 'AM', val, flags=re.IGNORECASE)
    val = re.sub(r'p\.m\.?', 'PM', val, flags=re.IGNORECASE)
    val = re.sub(r'Eastern(?:\s+(?:Standard|Daylight|Time))?', 'ET', val, flags=re.IGNORECASE)
    val = re.sub(r'\b(?:EST|EDT)\b', 'ET', val, flags=re.IGNORECASE)
    return val.strip()

_UNKNOWN_RE = re.compile(r'^\s*(?:not\s+available|unknown|n/?a|none|null|--|-)?\s*$', re.IGNORECASE)

def _clean_field(val) -> str:
    """Treat 'unknown'/'n/a'/etc. placeholder strings as empty."""
    s = str(val or "").strip()
    return "" if _UNKNOWN_RE.match(s) else s

def _try_parse_json(answer: str):
    """Parse a JSON object out of a model response. Handles ```json fences and
    leading/trailing prose. Returns dict or None."""
    if not answer:
        return None
    text = answer.strip()
    # Strip markdown code fences
    fence = re.match(r'^```(?:json)?\s*(.*?)\s*```\s*$', text, re.DOTALL)
    if fence:
        text = fence.group(1).strip()
    # If there's surrounding prose, isolate the outermost {...}
    if not text.startswith("{"):
        start, end = text.find("{"), text.rfind("}")
        if start == -1 or end <= start:
            return None
        text = text[start:end + 1]
    try:
        parsed = json.loads(text)
    except (json.JSONDecodeError, ValueError):
        return None
    return parsed if isinstance(parsed, dict) else None

def _fill_from_structured(parsed: dict, result: dict) -> None:
    """Map a validated structured-output object into the result columns."""
    def clean_list(key):
        vals = parsed.get(key) or []
        if not isinstance(vals, list):
            vals = [vals]
        return [c for c in (_clean_field(v) for v in vals) if c]

    start = _clean_field(parsed.get("actual_start_et"))
    end   = _clean_field(parsed.get("actual_end_et"))
    if start:
        start = _norm_time_val(start)
        if not re.search(r'\bET\b', start, re.IGNORECASE):
            start += " ET"
        result["actual_start"] = start
    if end:
        end = _norm_time_val(end)
        if not re.search(r'\bET\b', end, re.IGNORECASE):
            end += " ET"
        result["actual_end"] = end
    result["video_duration"] = _clean_field(parsed.get("duration"))

    nationals = clean_list("national_channels")
    loc_home  = clean_list("local_home_channels")
    loc_away  = clean_list("local_away_channels")
    streams   = clean_list("streaming_platforms")
    result["national_channel"] = "; ".join(nationals)
    result["local_home"]       = "; ".join(loc_home)
    result["local_away"]       = "; ".join(loc_away)
    result["streaming"]        = "; ".join(streams)
    all_ch = nationals + loc_home + loc_away + streams
    result["broadcast_channels"] = ", ".join(dict.fromkeys(all_ch))  # dedupe, keep order

    notes = _clean_field(parsed.get("notes"))
    status = str(parsed.get("status") or "unknown").lower().strip()
    if status == "postponed":
        result["status_hint"] = "postponed"
        notes = notes or "Postponed"
    elif status == "canceled":
        result["status_hint"] = "canceled"
        notes = notes or "Canceled"
    elif status in ("delayed", "suspended"):
        result["status_hint"] = "delayed"
        notes = notes or ("Suspended" if status == "suspended" else "Game delayed")
    result["notes"] = notes

    summary    = _clean_field(parsed.get("summary"))
    confidence = _clean_field(parsed.get("confidence")) or "low"
    data_found = bool(parsed.get("data_found"))
    tag = f"[structured | confidence: {confidence}]"
    if not data_found:
        # Model says sources didn't cover this event — blank the data columns so
        # the verdict correctly lands on UNVERIFIED/UNCONFIRMED instead of
        # trusting hallucinated values.
        for k in ("actual_start", "actual_end", "video_duration", "national_channel",
                  "local_home", "local_away", "streaming", "broadcast_channels"):
            result[k] = ""
        result["details"] = (summary or "No sources found covering this event.") + f"  {tag} [no data found]"
    else:
        result["details"] = (summary or "") + f"  {tag}"
    result["details"] = result["details"].strip()

# ─────────────────────────────────────────────

def multi_source_lookup(event: dict, api_key: str, run_type: str) -> dict:
    """Single Perplexity query returns all data: times, channels, duration, notes."""
    combined = {
        "actual_start": "", "actual_end": "", "video_duration": "",
        "details": "",
        "national_channel": "", "local_home": "", "local_away": "",
        "streaming": "", "broadcast_channels": "", "status_hint": "", "notes": "",
        "sources_used": [],
    }
    if api_key:
        ggt = perplexity_lookup(event, api_key)
        combined["actual_start"]       = ggt.get("actual_start", "")
        combined["actual_end"]         = ggt.get("actual_end", "")
        combined["video_duration"]     = ggt.get("video_duration", "")
        combined["notes"]              = ggt.get("notes", "")
        combined["details"]            = ggt.get("details", "")
        combined["national_channel"]   = ggt.get("national_channel", "")
        combined["local_home"]         = ggt.get("local_home", "")
        combined["local_away"]         = ggt.get("local_away", "")
        combined["streaming"]          = ggt.get("streaming", "")
        combined["broadcast_channels"] = ggt.get("broadcast_channels", "")
        combined["status_hint"]        = ggt.get("status_hint", "")
        plex_srcs = ggt.get("perplexity_sources", [])
        combined["sources_used"] = plex_srcs if plex_srcs else ["Perplexity"]
    return combined

# ─────────────────────────────────────────────
def perplexity_lookup(event: dict, api_key: str) -> dict:
    """Single Perplexity sonar-pro query per game.
    Returns: actual_start, actual_end, video_duration, national_channel, local_home,
             local_away, streaming, notes, details (full cleaned response), perplexity_sources (citation URLs).
    """
    result = {
        "actual_start": "", "actual_end": "", "video_duration": "",
        "notes": "", "details": "", "perplexity_sources": [],
        "national_channel": "", "local_home": "", "local_away": "", "streaming": "",
        "broadcast_channels": "", "status_hint": "",
    }
    if not api_key:
        return result

    name     = event.get("event_name", "")
    date_str = event.get("event_date", "")

    # Build query using home/away team names when available, otherwise use event_name
    home = event.get("home_team", "")
    away = event.get("away_team", "")
    if home and away:
        # If home == away it's a show/event, not a game
        if home.lower().strip() == away.lower().strip():
            matchup = home
        else:
            # Use "Home vs Away" order — matches how users naturally query Perplexity
            matchup = f"{home} vs {away}"
    else:
        matchup = name

    q = (
        f"What time did '{matchup}' air on {date_str} in EST? "
        f"What broadcast channel(s) did it air on? "
        f"What was the total air/video duration? "
        f"Were there any delays, preemptions, or cancellations?"
        if (home and away and home.lower().strip() == away.lower().strip())
        else
        f"what time did {matchup} on {date_str} start and end in est time "
        f"and what broadcast channel/s did it air on? what was the video duration? "
        f"were there any weather/rain delays, postponements, or cancellations?"
    )

    # ── Attempt 1: structured JSON output ────────────────────────────────
    json_payload = {
        "model": PPLX_MODEL,
        "messages": [
            {"role": "system", "content": _JSON_SYSTEM_PROMPT},
            {"role": "user", "content": q},
        ],
        "max_tokens": 700,
        "temperature": 0.0,
        "response_format": {
            "type": "json_schema",
            "json_schema": {"name": "broadcast_verification", "schema": BROADCAST_SCHEMA},
        },
    }
    answer, citations, err = _call_perplexity(api_key, json_payload)
    parsed = _try_parse_json(answer)

    if parsed is not None:
        # Structured path: map fields directly into columns — no regex guessing.
        _fill_from_structured(parsed, result)
        result["perplexity_sources"] = citations
        clean_answer = ""  # downstream regex extractors become no-ops
    else:
        # ── Attempt 2: labeled-text fallback ─────────────────────────────
        # If the structured call returned non-JSON text, reuse it rather than
        # burning a second API call; only re-call if the request itself failed.
        if not answer:
            text_payload = {
                "model": PPLX_MODEL,
                "messages": [
                    {"role": "system", "content": _TEXT_SYSTEM_PROMPT},
                    {"role": "user", "content": q},
                ],
                "max_tokens": 500,
                "temperature": 0.0,
            }
            answer, citations, err = _call_perplexity(api_key, text_payload)
        if not answer:
            result["details"] = f"Perplexity error: {err or 'empty response'}"
            return result

        # Clean up markdown formatting from the response before extraction
        clean_answer = answer
        # Strip citation markers like [1][2][3] from the text
        clean_answer = re.sub(r'\[\d+\]', '', clean_answer)
        # Strip markdown bold (**text**) and italic (*text*)
        clean_answer = re.sub(r'\*\*(.+?)\*\*', r'\1', clean_answer)
        clean_answer = re.sub(r'\*(.+?)\*', r'\1', clean_answer)
        # Collapse multiple spaces
        clean_answer = re.sub(r'  +', ' ', clean_answer).strip()

        # Store the cleaned answer verbatim as Details, tagged so you can see
        # this row was filled by regex extraction rather than structured output.
        result["details"] = clean_answer + "  [text fallback]"
        result["perplexity_sources"] = citations

    # ── Extract Start time ───────────────────────────────────────────────────
    m_start = re.search(
        r'^Start:\s*(.+?)$',
        clean_answer, re.IGNORECASE | re.MULTILINE
    )
    if m_start:
        val = m_start.group(1).strip()
        if not re.search(r'not available|unknown|n/a', val, re.IGNORECASE):
            # Normalize time format
            val = re.sub(r'a\.m\.?', 'AM', val, flags=re.IGNORECASE)
            val = re.sub(r'p\.m\.?', 'PM', val, flags=re.IGNORECASE)
            val = re.sub(r'Eastern(?:\s+(?:Standard|Time))?', 'ET', val, flags=re.IGNORECASE)
            val = re.sub(r'\b(?:EST|EDT)\b', 'ET', val, flags=re.IGNORECASE)
            result["actual_start"] = val.strip()

    # Prose fallback for start: "started at 8:00 p.m. ET" / "tipped off at 7:30 PM ET"
    if not result["actual_start"]:
        m_start_prose = re.search(
            r'(?:started?|tipped?\s*off?|kicked?\s*off|began?|aired?'
            r'|scheduled\s+to\s+(?:start|tip|begin|kick\s*off)'
            r'|tip\s*off\s+(?:was|is|at)'
            r'|tip-off\s+(?:was|is|at)'
            r'|(?:the\s+)?game\s+(?:starts?|begins?|tips?)\s+at'
            r'|scheduled\s+(?:start|tip-?off)\s+(?:was|is)?)\s+at\s+'
            r'(\d{1,2}:\d{2}\s*(?:a\.?m\.?|p\.?m\.?)?(?:\s*[AaPp][Mm])?(?:\s*(?:ET|EST|EDT|Eastern))?)',
            clean_answer, re.IGNORECASE
        )
        # Also match "scheduled for X PM ET" / "listed at X PM ET"
        if not m_start_prose:
            m_start_prose = re.search(
                r'(?:scheduled\s+for|listed\s+(?:at|for)|tip-?off\s+at|start\s+time\s+(?:of|was|is)?:?\s*)'
                r'(\d{1,2}:\d{2}\s*(?:a\.?m\.?|p\.?m\.?)?(?:\s*[AaPp][Mm])?(?:\s*(?:ET|EST|EDT|Eastern))?)',
                clean_answer, re.IGNORECASE
            )
        if m_start_prose:
            val = m_start_prose.group(1).strip()
            val = re.sub(r'a\.m\.?', 'AM', val, flags=re.IGNORECASE)
            val = re.sub(r'p\.m\.?', 'PM', val, flags=re.IGNORECASE)
            val = re.sub(r'Eastern(?:\s+(?:Standard|Time))?', 'ET', val, flags=re.IGNORECASE)
            val = re.sub(r'\b(?:EST|EDT)\b', 'ET', val, flags=re.IGNORECASE)
            if not re.search(r'ET', val, re.IGNORECASE):
                val = val.strip() + " ET"
            result["actual_start"] = val.strip()

    # ── Extract End time ─────────────────────────────────────────────────────
    m_end = re.search(
        r'^End:\s*(.+?)$',
        clean_answer, re.IGNORECASE | re.MULTILINE
    )
    if m_end:
        val = m_end.group(1).strip()
        # Strip any trailing parenthetical like "(approximate)" or "(calc.)"
        val = re.sub(r'\s*\(.*?\)\s*$', '', val).strip()
        if not re.search(r'not available|unknown|n/a', val, re.IGNORECASE):
            val = re.sub(r'a\.m\.?', 'AM', val, flags=re.IGNORECASE)
            val = re.sub(r'p\.m\.?', 'PM', val, flags=re.IGNORECASE)
            val = re.sub(r'Eastern(?:\s+(?:Standard|Time))?', 'ET', val, flags=re.IGNORECASE)
            val = re.sub(r'\b(?:EST|EDT)\b', 'ET', val, flags=re.IGNORECASE)
            result["actual_end"] = val.strip()

    # Prose fallback for end: "ended at 10:36 p.m. ET" / "concluded at 10:30 PM ET"
    if not result["actual_end"]:
        m_end_prose = re.search(
            r'(?:ended?|concluded?|finished?|wrapped?\s*up|final\s+(?:score\s+)?(?:was\s+)?(?:posted\s+)?at|game\s+(?:ended?|concluded?|finished?))\s+at\s+'
            r'(\d{1,2}:\d{2}\s*(?:a\.?m\.?|p\.?m\.?)?(?:\s*[AaPp][Mm])?(?:\s*(?:ET|EST|EDT|Eastern))?)',
            clean_answer, re.IGNORECASE
        )
        # Also handle "ended at approximately/roughly/around 10:36 PM ET"
        if not m_end_prose:
            m_end_prose = re.search(
                r'(?:ended?|concluded?|finished?|wrapped?\s*up|game\s+(?:ended?|concluded?|finished?))\s+at\s+'
                r'(?:approximately|roughly|around|about|~)?\s*'
                r'(\d{1,2}:\d{2}\s*(?:a\.?m\.?|p\.?m\.?)?(?:\s*[AaPp][Mm])?(?:\s*(?:ET|EST|EDT|Eastern))?)',
                clean_answer, re.IGNORECASE
            )
        # Also handle "end time: 10:30 PM ET" / "end time was 10:30 PM ET"
        if not m_end_prose:
            m_end_prose = re.search(
                r'(?:end\s+time\s*(?:was|is|:)?|estimated\s+end\s*(?:time)?(?:\s*(?:was|is|:))?)\s*'
                r'(?:approximately|roughly|around|about|~)?\s*'
                r'(\d{1,2}:\d{2}\s*(?:a\.?m\.?|p\.?m\.?)?(?:\s*[AaPp][Mm])?(?:\s*(?:ET|EST|EDT|Eastern))?)',
                clean_answer, re.IGNORECASE
            )
        if m_end_prose:
            val = m_end_prose.group(1).strip()
            val = re.sub(r'a\.m\.?', 'AM', val, flags=re.IGNORECASE)
            val = re.sub(r'p\.m\.?', 'PM', val, flags=re.IGNORECASE)
            val = re.sub(r'Eastern(?:\s+(?:Standard|Time))?', 'ET', val, flags=re.IGNORECASE)
            val = re.sub(r'\b(?:EST|EDT)\b', 'ET', val, flags=re.IGNORECASE)
            if not re.search(r'ET', val, re.IGNORECASE):
                val = val.strip() + " ET"
            result["actual_end"] = val.strip()

    # ── Extract Duration ─────────────────────────────────────────────────────
    m_dur = re.search(
        r'^Duration:\s*(.+?)$',
        clean_answer, re.IGNORECASE | re.MULTILINE
    )
    if m_dur:
        val = m_dur.group(1).strip()
        if not re.search(r'not available|unknown|n/a', val, re.IGNORECASE):
            result["video_duration"] = val.strip()

    # Prose fallback for duration: "video duration of three hours" / "lasted 2 hours 36 minutes"
    if not result["video_duration"]:
        m_dur_prose = re.search(
            r'(?:video\s*duration\s*(?:of|was|is)|lasted?|ran?\s+(?:for|about)|total\s+(?:runtime|duration)\s+(?:of|was))\s+'
            r'((?:\d+|one|two|three|four|five|six|seven|eight|nine|ten)'
            r'(?:\s*(?:hours?|hrs?|h))?'
            r'(?:\s*(?:and\s*)?\d*\s*(?:minutes?|mins?|m))?)',
            clean_answer, re.IGNORECASE
        )
        if m_dur_prose:
            result["video_duration"] = m_dur_prose.group(1).strip()

    # Extended prose duration fallback — handles all formats Perplexity uses
    if not result["video_duration"]:
        # Pattern 1: H:MM:SS embedded in sentence — e.g. "runtime of 2:01:53"
        m_hms = re.search(r'\b(\d{1,2}:\d{2}:\d{2})\b', clean_answer)
        if m_hms:
            # Make sure it's not a clock time (exclude if preceded by "at" or "around")
            pre = clean_answer[max(0, m_hms.start()-10):m_hms.start()].lower()
            if not re.search(r'\bat\s*$|\baround\s*$|\bby\s*$', pre):
                result["video_duration"] = m_hms.group(1)

    if not result["video_duration"]:
        # Pattern 2: "about/~X hours Y minutes" / "approximately X hours" / "~2 hours"
        m_dur2 = re.search(
            r'(?:about|approximately|roughly|around|~|≈)?\s*'
            r'(\d+(?:\.\d+)?)\s*(?:hours?|hrs?|h)\s*'
            r'(?:(?:and\s*)?(\d+)\s*(?:–\d+\s*)?(?:minutes?|mins?|m))?',
            clean_answer, re.IGNORECASE
        )
        if m_dur2:
            hrs = m_dur2.group(1)
            mins = m_dur2.group(2)
            if mins:
                result["video_duration"] = f"{hrs} hours {mins} minutes"
            else:
                result["video_duration"] = f"{hrs} hours"

    if not result["video_duration"]:
        # Pattern 3: "X hour Y–Z minute" range — take the lower bound
        m_range = re.search(
            r'(\d+)\s*(?:hours?|hrs?)\s*(\d+)(?:–|-)\d+\s*(?:minutes?|mins?)',
            clean_answer, re.IGNORECASE
        )
        if m_range:
            result["video_duration"] = f"{m_range.group(1)} hours {m_range.group(2)} minutes"

    # ── Compute end time from start + duration if end not found ─────────────
    if result["actual_start"] and not result["actual_end"] and result["video_duration"]:
        try:
            # Parse start time: "10:00 PM ET", "9:05 PM ET"
            start_str = re.sub(r'\s*ET\s*$', '', result["actual_start"], flags=re.IGNORECASE).strip()
            start_dt = None
            for fmt in ("%I:%M %p", "%I:%M%p"):
                try:
                    start_dt = datetime.strptime(start_str.upper(), fmt)
                    break
                except ValueError:
                    pass
            if start_dt:
                # Parse duration: "2:01:53", "2 hours 16 minutes", "2h 7m", "1 hour 57 minutes"
                dur_str = result["video_duration"]
                total_secs = 0
                # HH:MM:SS format
                m_hms = re.match(r'^(\d+):(\d{2}):(\d{2})$', dur_str.strip())
                if m_hms:
                    total_secs = int(m_hms.group(1))*3600 + int(m_hms.group(2))*60 + int(m_hms.group(3))
                else:
                    # "X hours Y minutes" or "X hr Y min" or "Xh Ym"
                    m_h = re.search(r'(\d+)\s*(?:hour|hr|h)s?', dur_str, re.IGNORECASE)
                    m_m = re.search(r'(\d+)\s*(?:minute|min|m)s?', dur_str, re.IGNORECASE)
                    if m_h: total_secs += int(m_h.group(1)) * 3600
                    if m_m: total_secs += int(m_m.group(1)) * 60
                if total_secs > 0:
                    end_dt = start_dt + timedelta(seconds=total_secs)
                    # %-I is not portable (fails on Windows) — format manually
                    hour12 = end_dt.hour % 12 or 12
                    ampm = "AM" if end_dt.hour < 12 else "PM"
                    result["actual_end"] = f"{hour12}:{end_dt.minute:02d} {ampm} ET (calc.)"
        except Exception:
            pass  # calculation failure is non-fatal


    # ── Extract Broadcast channels ───────────────────────────────────────────
    bcast_raw = ""
    # Priority 1: Structured label "Broadcast: ESPN, ABC"
    m_bcast = re.search(r'^Broadcast:\s*(.+?)$', clean_answer, re.IGNORECASE | re.MULTILINE)
    if m_bcast:
        bcast_raw = m_bcast.group(1).strip()
    # Priority 2: Section header + bullet list (handles nested/labeled bullets)
    if not bcast_raw:
        m_sec = re.search(
            r'(?:^#+\s*)?(?:broadcast\s*(?:channel|coverage|info|detail|platform|listing|stream)?s?'
            r'|tv\s+coverage|television\s+coverage|stream(?:ing)?\s+(?:channel|listing|platform)s?'
            r'|broadcast\s*/\s*stream(?:ing)?\s+listings?)'
            r'(?:\s*\([^)]*\))?\s*[^:\n]*(?::\s*)?\n',
            clean_answer, re.IGNORECASE | re.MULTILINE
        )
        if m_sec:
            block_start = m_sec.end()
            block_end_m = re.search(r'\n(?:#{1,3}\s|\-{3,})', clean_answer[block_start:])
            block = clean_answer[block_start: block_start + (block_end_m.start() if block_end_m else 1500)]
            channels = []
            for line in block.split('\n'):
                bm = re.match(r'^\s*[-*•]\s*(.+)', line)
                if not bm:
                    continue
                item = bm.group(1).strip().rstrip('.')
                # Category header with channels in parens, ending with colon
                cat_m = re.match(r'^[^(]+\(([^)]+)\)\s*:\s*$', item)
                if cat_m:
                    ch = cat_m.group(1).strip()
                    if ch and ch not in channels:
                        channels.append(ch)
                    continue
                # Pure section label (ends with colon only, no channel content)
                if re.match(r'^[\w\s/()–-]+:\s*$', item):
                    continue
                # Source citation: 'Source: "Channel."' — only keep single-word quoted names
                src_m = re.match(r'^[\w\s]+:\s*["\u201c\u201d]([^""\u201c\u201d]+)["\u201c\u201d]\.?\s*$', item)
                if src_m:
                    quoted = src_m.group(1).strip().rstrip('.')
                    if quoted and not re.search(r'\s', quoted):
                        if quoted not in channels:
                            channels.append(quoted)
                    continue
                # Whole-line commentary (skip entirely)
                if re.search(r'\b(?:refer to|branded as|reflects|likely reflects|inferred from|these refer|all refer)\b', item, re.IGNORECASE):
                    continue
                if re.match(r'^(?:these|all|this|it|they|each)\b', item, re.IGNORECASE) and re.search(r'\b(?:refer to|branded as|reflects|listed as|appears as)\b', item, re.IGNORECASE):
                    continue
                # "Channel Name appears as a ..." — extract channel name before "appears as"
                appears_m = re.match(r'^(.+?)\s+appears as\b', item, re.IGNORECASE)
                if appears_m:
                    ch = appears_m.group(1).strip().rstrip('.,;–-').strip()
                    if ch and ch not in channels:
                        channels.append(ch)
                    continue
                # Strip label prefix: "National: ESPN" -> "ESPN"
                label_m = re.match(r'^(?:national|local|home|away|streaming|stream|regional|rsn|cable|ott|league)\s*(?:[\w/\s]+)?:\s*(.+)', item, re.IGNORECASE)
                if label_m:
                    item = label_m.group(1).strip().rstrip('.')
                # Strip trailing " – description" prose
                item = re.sub(r'\s+[–-]\s+(?:local|national|regional|team|league|streaming|home|away|primary|alternate|secondary|feed|channel)\b.*$', '', item, flags=re.IGNORECASE)
                item = re.sub(r'\s+[–-]\s+(?:listed as|also listed|appears as|known as|also known|listed under)\b.*$', '', item, flags=re.IGNORECASE)
                # Strip dangling trailing dash
                item = re.sub(r'\s+[–-]\s*$', '', item).strip()
                # Remove trailing adjective parens: "(national)", "(local)", etc.
                _pm = re.search(r'\s*\(([^)]+)\)\s*$', item)
                if _pm:
                    _c = _pm.group(1)
                    # Strip if it's a descriptor word or a city/location phrase
                    if re.match(r'^(?:national|local|home|away|primary|secondary|alternate|regional|streaming|cable|ott|league|chicago|portland|seattle|boston|new york|los angeles|san francisco|miami|dallas|houston|phoenix|denver|atlanta|washington|philadelphia|minneapolis|detroit|cleveland|orlando|sacramento|oklahoma city|salt lake|new orleans|memphis|milwaukee|charlotte|indiana|toronto|golden state|san antonio|brooklyn|los angeles clippers)\s*(?:local|regional|market|feed|area|based)?\s*$', _c, re.IGNORECASE):
                        item = item[:_pm.start()].strip()
                item = item.rstrip('.,;').strip()
                if item and len(item) > 1 and item not in channels:
                    channels.append(item)
            if channels:
                bcast_raw = ", ".join(channels)
    # Priority 3: Prose "aired on X, Y, and Z"
    if not bcast_raw:
        m_bcast_prose = re.search(
            r'(?:aired?\s+on|broadcast\s+on|televised\s+on|shown\s+on)\s+([^.;\n]+?)'
            r'(?:\.|;|\n|,\s*(?:did\s+not|had\s+(?:no|a\s+typical|an?\s+)|it\s+was|and\s+it\s+did'
            r'|with\s+no|which\s+did|there\s+was|no\s+overtime|no\s+weather|no\s+rain|no\s+delay'
            r'|a\s+typical|the\s+game\s+did|ran\s+for|lasted\s+about|lasting\s+about'
            r'|and\s+was\s+a|and\s+it\s+was))',
            clean_answer, re.IGNORECASE
        )
        bcast_raw = m_bcast_prose.group(1).strip() if m_bcast_prose else ""
    # Priority 4: "available on / listed on / airing on"
    if not bcast_raw:
        m_bcast_prose = re.search(
            r'(?:listed\s+on|available\s+on|can\s+be\s+seen\s+on|airing\s+on'
            r'|listed\s+as\s+airing\s+on)\s+([^.;\n]+?)(?:\.|;|\n)',
            clean_answer, re.IGNORECASE
        )
        bcast_raw = m_bcast_prose.group(1).strip() if m_bcast_prose else ""
    # Priority 5: colon + bullet list
    if not bcast_raw:
        m_bcast_prose = re.search(
            r'(?:aired?\s+on|broadcast\s+on|available\s+on|listed\s+on)[^:\n]*:\s*\n'
            r'((?:\s*[-*•]\s*[^\n]+\n?)+)',
            clean_answer, re.IGNORECASE
        )
        if m_bcast_prose:
            lines = re.findall(r'[-*•]\s*(.+)', m_bcast_prose.group(1))
            bcast_raw = ", ".join(l.strip() for l in lines if l.strip())
    # Priority 6: any prose line ending in colon followed by bullets (generic fallback)
    if not bcast_raw:
        m_bcast_prose = re.search(
            r'[^\n]*(?:channel|network|broadcast|air|stream)[^\n]*:\s*\n'
            r'((?:\s*[-*•]\s*[^\n]+\n?)+)',
            clean_answer, re.IGNORECASE
        )
        if m_bcast_prose:
            lines = re.findall(r'[-*•]\s*(.+)', m_bcast_prose.group(1))
            bcast_raw = ", ".join(l.strip() for l in lines if l.strip())
    if bcast_raw:
        # Split on semicolons, commas, or " and "
        parts = re.split(r'[;,]|\band\b', bcast_raw, flags=re.IGNORECASE)
        home_team  = (event.get("home_team") or "").lower()
        away_team  = (event.get("away_team") or "").lower()

        # Known national linear networks (lowercase for matching)
        NATIONAL_NETS = {
            "espn", "espn2", "espnu", "espnews", "abc", "nbc", "cbs", "fox",
            "tnt", "tbs", "truetv", "usa network", "usa", "fs1", "fs2",
            "nfl network", "nba tv", "nhl network", "mlb network",
            "nbc sports", "cbssn", "cbs sports network", "tennis channel",
            "golf channel", "olympic channel", "sec network", "acc network",
            "big ten network", "btn", "longhorn network", "pac-12 network",
            "espn+", "fox sports", "the cw", "cw", "ion", "ion television",
            "univision", "telemundo", "galavision", "tudn",
            "stadium", "fanduel sports", "bally sports",
            "msg", "sny", "yes network", "nesn", "masn", "masn2",
            "nbcsn", "nbc sports boston", "nbc sports bay area",
            "nbc sports chicago", "nbc sports philadelphia",
            "nbc sports washington", "nbc sports california",
            "nbc sports northwest", "nbc sports new york",
            "marquee sports", "marquee", "space city home network",
            "victory+", "directv sports", "syndication",
        }
        # Streaming-only keywords
        STREAMING_KWORDS = [
            "league pass", "nba league pass", "nhl.tv", "mlb.tv", "mls season pass",
            "espn+", "peacock", "paramount+", "amazon prime", "prime video",
            "apple tv+", "apple tv", "disney+", "hulu", "fubo", "sling",
            "youtube tv", "directv stream", "max",
            "streaming", "digital", "app", "online",
        ]
        # Local indicator keywords
        LOCAL_KWORDS = ["local", "market", "regional", "rsn"]

        nationals, locals_, streamers = [], [], []
        for raw_part in parts:
            p = raw_part.strip()
            if not p:
                continue
            pl = p.lower()

            # Streaming?
            if any(kw in pl for kw in STREAMING_KWORDS):
                streamers.append(p)
                continue

            # Explicit local marker?
            if any(kw in pl for kw in LOCAL_KWORDS):
                if home_team and any(tok in pl for tok in home_team.split() if len(tok) > 3):
                    locals_.append(("home", p))
                elif away_team and any(tok in pl for tok in away_team.split() if len(tok) > 3):
                    locals_.append(("away", p))
                else:
                    locals_.append(("home", p))
                continue

            # National network?
            p_norm = re.sub(r'\(.*?\)', '', pl).strip()
            if any(p_norm == net or net in p_norm for net in NATIONAL_NETS):
                nationals.append(p)
                continue

            # Looks like a call sign (all-caps 2-5 chars)?
            if re.match(r'^[A-Z]{2,5}(\d)?(-[A-Z]+)?$', p.strip()):
                locals_.append(("home", p))
                continue

            # Default: treat as national
            nationals.append(p)

        result["national_channel"] = "; ".join(nationals) if nationals else ""
        home_locals = [ch for role, ch in locals_ if role == "home"]
        away_locals = [ch for role, ch in locals_ if role == "away"]
        result["local_home"]       = "; ".join(home_locals) if home_locals else ""
        result["local_away"]       = "; ".join(away_locals) if away_locals else ""
        result["streaming"]        = "; ".join(streamers) if streamers else ""
        # Build a clean comma-separated channel list from the split parts
        all_channels = nationals + [ch for _, ch in locals_] + streamers
        if all_channels:
            result["broadcast_channels"] = ", ".join(all_channels)
        else:
            result["broadcast_channels"] = bcast_raw

    # ── Extract Notes (delays, postponements, cancellations) ────────────────
    m_notes = re.search(
        r'^Notes:\s*(.+?)$',
        clean_answer, re.IGNORECASE | re.MULTILINE
    )
    notes_text = m_notes.group(1).strip() if m_notes else ""
    # Prose fallback: if no Notes label, scan full response for event keywords
    scan_text = notes_text if notes_text else clean_answer
    from_label = bool(notes_text)  # structured label content is authoritative
    # Only flag real events — ignore "None", "No", "N/A" from structured label
    if notes_text and re.match(r'^(none|no|n/a|not applicable)', notes_text, re.IGNORECASE):
        scan_text = ""  # structured label explicitly said None — don't scan prose
    if scan_text:
        NOTES_PATS = [
            (re.compile(r'rain\s*delay|weather\s*delay', re.IGNORECASE), "Rain delay"),
            (re.compile(r'game\s*delayed|delayed\s*due', re.IGNORECASE), "Game delayed"),
            (re.compile(r'\bpostponed\b', re.IGNORECASE), "Postponed"),
            (re.compile(r'\bcanceled\b|\bcancelled\b|called\s*off', re.IGNORECASE), "Canceled"),
            (re.compile(r'\bsuspended\b', re.IGNORECASE), "Suspended"),
            (re.compile(r'extra\s*innings?', re.IGNORECASE), "Extra innings"),
        ]
        # Negation phrases — if the sentence containing the keyword has one of these,
        # the keyword is a negative mention (e.g. "did not go to overtime")
        NEGATION_RE = re.compile(
           r'\b(no|not|without|never|neither|nor|didn\'t|did not|does not|doesn\'t|'
           r'wasn\'t|was not|weren\'t|were not|no indication of|no evidence of|'
           r'no sign of|no reports? of|no overtime|no delay|no weather|'
           r'none of|no mention|not mentioned|not reported|not listed|'
           r'no indication|consistent with|confirms? no|showing no|'
           r'absence of|without any|no\s+(?:overtime|delay|weather|rain|postpone)|'
            r'non-overtime|non-ot\b|non.overtime|rather than|listed as final|'
            r'status.*final|final.*status|no evidence|no reports|no sources)\b',
           re.IGNORECASE
       )
        found = []
        for pat, label in NOTES_PATS:
            for m in pat.finditer(scan_text):
                # Get the line/sentence containing this match
                # Split on BOTH newlines and periods so bullet lines are checked individually
                line_start = scan_text.rfind('\n', 0, m.start())
                line_end   = scan_text.find('\n', m.end())
                line = scan_text[line_start+1 : line_end if line_end != -1 else len(scan_text)].strip()
                # Also get the period-bounded sentence within that line
                sent_start = line.rfind('.', 0, m.start() - line_start - 1)
                sent_end   = line.find('.', m.end() - line_start - 1)
                sentence = line[sent_start+1 : sent_end if sent_end != -1 else len(line)].strip()
                # Use whichever is shorter (more specific) — line or sentence
                check_text = line if len(line) <= len(sentence) else sentence
                # Prose-only heuristics: don't apply when scanning the structured
                # Notes: label — "Rain delay" there is an assertion, not a header.
                if not from_label:
                    # Skip markdown headers (### Overtime / Delays) — these are
                    # section labels, not assertions that overtime occurred
                    if re.match(r'^#+\s*', check_text):
                        continue
                    # Skip bullet-point section labels like "- Overtime" or "* Overtime"
                    if re.match(r'^[-*•]\s*\w[\w\s,/]+$', check_text) and len(check_text.split()) <= 6:
                        continue
                    # Skip sentences that are just listing topics (very short, no verb)
                    if len(check_text.split()) <= 4 and not re.search(r'\b(went|occurred|happened|resulted|required|took)\b', check_text, re.IGNORECASE):
                        continue
                # Only flag if the sentence does NOT contain a negation
                if not NEGATION_RE.search(check_text):
                    if label not in found:
                        found.append(label)
                    break
        if found:
            result["notes"] = "; ".join(found)
            # Derive status_hint so compute_verdict can return POSTPONED/CANCELED/DELAYED.
            # (Previously status_hint was never populated, so those verdicts never fired.)
            if "Postponed" in found:
                result["status_hint"] = "postponed"
            elif "Canceled" in found:
                result["status_hint"] = "canceled"
            elif "Rain delay" in found or "Game delayed" in found:
                result["status_hint"] = "delayed"
        # If no keywords found, leave notes blank — don't store the raw text

    # ── Compute video duration from actual start + end when not provided ────
    if not result["video_duration"] and result["actual_start"] and result["actual_end"]:
        try:
            from datetime import datetime as _dt, timedelta as _td
            import re as _re
            def _parse_t(s):
                s = _re.sub(r'\s*(ET|EST|EDT|CT|CST|CDT|MT|MST|MDT|PT|PST|PDT|Eastern|Central|Pacific|Mountain).*$', '', s, flags=_re.IGNORECASE).strip()
                s = _re.sub(r'\s*\(.*?\)\s*$', '', s).strip()
                for fmt in ("%I:%M %p", "%I:%M%p", "%H:%M"):
                    try:
                        return _dt.strptime(s.upper(), fmt)
                    except ValueError:
                        pass
                return None
            t_start = _parse_t(result["actual_start"])
            t_end   = _parse_t(result["actual_end"])
            if t_start and t_end:
                # Handle midnight crossover (e.g. start 10 PM, end 12:30 AM)
                if t_end < t_start:
                    t_end += _td(days=1)
                delta = t_end - t_start
                total_min = int(delta.total_seconds() // 60)
                hrs  = total_min // 60
                mins = total_min % 60
                if hrs > 0 and mins > 0:
                    result["video_duration"] = f"{hrs} hr {mins} min (calc.)"
                elif hrs > 0:
                    result["video_duration"] = f"{hrs} hr (calc.)"
                else:
                    result["video_duration"] = f"{mins} min (calc.)"
        except Exception:
            pass

    return result


def compute_verdict(event: dict, lookup: dict, run_type: str) -> str:
    sched_ch_tokens = channel_tokens(event.get("sched_channel", ""))
    sched_start = (event.get("sched_start") or "").strip().upper()
    actual_start = (lookup.get("actual_start") or "").strip().upper()
    status_hint  = lookup.get("status_hint", "")

    # ── Hard status overrides (always take priority) ──────────────────────
    if status_hint == "postponed":
        return "POSTPONED"
    if status_hint == "canceled":
        return "CANCELED"
    if status_hint == "delayed":
        return "DELAYED"

    # ── Build set of all found channels (split multi-channel strings first) ──
    all_found = set()
    for field in ("national_channel", "local_home", "local_away", "streaming", "broadcast_channels"):
        all_found |= channel_tokens(lookup.get(field, ""))

    # ── Two signals: time match and channel match ─────────────────────────
    # Time match: scheduled start == actual start (normalized, ignore timezone suffix)
    def _norm_time(t: str) -> str:
        """Strip timezone suffix and extra whitespace for loose comparison."""
        return re.sub(r'\s*(ET|CT|MT|PT|EST|CST|MST|PST|EDT|CDT|MDT|PDT|Eastern|Central|Pacific|Mountain).*$',
                      '', t, flags=re.IGNORECASE).strip()

    time_match = bool(
        sched_start and actual_start and
        _norm_time(sched_start) == _norm_time(actual_start)
    )

    # Loose time match: within ±5 minutes (handles "10:01 PM" sched vs "10:00 PM" actual)
    if not time_match and sched_start and actual_start:
        try:
            from datetime import datetime as _dt
            def _parse_t(s):
                s = _norm_time(s).strip().upper()
                for fmt in ("%I:%M %p", "%I:%M%p", "%H:%M"):
                    try: return _dt.strptime(s, fmt)
                    except ValueError: pass
                return None
            t1 = _parse_t(sched_start)
            t2 = _parse_t(actual_start)
            if t1 and t2:
                diff = abs((t1 - t2).total_seconds())
                # Wrap-around midnight: if diff > 12 hours, flip
                if diff > 43200: diff = 86400 - diff
                if diff <= 300:  # within 5 minutes
                    time_match = True
        except Exception:
            pass

    # Channel match: any scheduled channel token appears in any found channel field.
    # If no scheduled channel was provided, we can't contradict it — treat as neutral-pass.
    channel_match = (not sched_ch_tokens) or any(
        channels_match(t, all_found) for t in sched_ch_tokens
    )

    # ── Verdict logic ─────────────────────────────────────────────────────
    # If we have no data at all, can't verify
    if not all_found and not actual_start:
        if sched_ch_tokens and is_known_local(event.get("sched_channel", "")):
            return "UNCONFIRMED"
        return "UNVERIFIED"

    # At least one signal matched → AIRED AS SCHEDULED
    if time_match or channel_match:
        return "AIRED_AS_SCHEDULED"

    # Neither time nor channel matched → MISMATCH
    return "MISMATCH"

# ─────────────────────────────────────────────
# RUN VERIFICATION
# ─────────────────────────────────────────────

def run_verification(events: list[dict], run_type: str, api_key: str, run_name: str) -> pd.DataFrame:
    if not events:
        st.warning("No events to verify.")
        return pd.DataFrame()

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
        league = event.get("league","")
        progress.progress((i + 1) / total, text=f"[{i+1}/{total}] {league} — {event.get('event_name','')[:40]}")

        # Query Perplexity for actual broadcast data
        lookup = multi_source_lookup(event, api_key, run_type)
        verdict = compute_verdict(event, lookup, run_type)

        # No data but a known local/RSN channel → UNCONFIRMED (never claim
        # AIRED_AS_SCHEDULED with zero evidence)
        if verdict == "UNVERIFIED" and is_known_local(event.get("sched_channel","")):
            verdict = "UNCONFIRMED"

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
            "national_channel":   lookup.get("national_channel",""),
            "local_home":         lookup.get("local_home",""),
            "local_away":         lookup.get("local_away",""),
            "streaming":          lookup.get("streaming",""),
            "broadcast_channels": lookup.get("broadcast_channels",""),
            "verdict":            verdict,
            "sources_used":    ", ".join(lookup.get("sources_used",[])),
            "notes":           lookup.get("notes",""),
            "details":         lookup.get("details",""),
        }
        results.append(row)
        c.execute("""INSERT INTO verification_results
            (run_id,league,event_name,event_date,sched_start,sched_channel,
             actual_start,actual_end,video_duration,national_channel,local_home,local_away,
             streaming,broadcast_channels,verdict,notes,sources_used,details)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (row["run_id"],row["league"],row["event_name"],row["event_date"],
             row["sched_start"],row["sched_channel"],row["actual_start"],row["actual_end"],
             row["video_duration"],row["national_channel"],row["local_home"],row["local_away"],
             row["streaming"],row.get("broadcast_channels",""),row["verdict"],row.get("notes",""),
             row["sources_used"],row.get("details","")))
        conn.commit()

    progress.empty()
    conn.close()
    return pd.DataFrame(results)

# ─────────────────────────────────────────────
# RESULTS TABLE RENDERER
# ─────────────────────────────────────────────

def verdict_html(verdict: str) -> str:
    color = VERDICT_COLORS.get(verdict, "yellow")
    return f'<span class="verdict-{color}">{html.escape(str(verdict))}</span>'

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

        def esc(v, dash=True):
            s = str(v or "").strip()
            if not s and dash:
                return "—"
            return html.escape(s, quote=True)

        actual_start = esc(row.get("actual_start",""))
        actual_end   = esc(row.get("actual_end",""))
        video_dur    = esc(row.get("video_duration",""))

        # Build clickable source links from comma-separated URLs
        sources_raw = str(row.get("sources_used","") or "")
        url_list = [u.strip() for u in sources_raw.split(",") if u.strip().startswith("http")]
        if url_list:
            sources = " ".join(
                f'<a href="{html.escape(u, quote=True)}" target="_blank" rel="noopener noreferrer" style="color:#58a6ff;font-size:10px;">[{i+1}]</a>'
                for i, u in enumerate(url_list)
            )
        else:
            sources = esc(sources_raw)

        notes_disp    = esc(row.get("notes",""), dash=False)
        details_raw   = str(row.get("details","") or "")
        # Collapse newlines for display; show first 300 chars
        details_oneline = details_raw.replace('\n', ' ').replace('\r', ' ')
        details_disp  = esc((details_oneline[:300] + "…") if len(details_oneline) > 300 else details_oneline)
        details_title = html.escape(details_oneline, quote=True)
        broadcast_ch  = esc(row.get("broadcast_channels",""))
        event_name    = esc(row.get("event_name",""), dash=False)

        rows_html += f"""
        <tr style="background:{bg}; border-bottom:1px solid #30363d;">
            <td style="padding:6px 10px; color:#8b949e; font-size:12px;">{esc(row.get('league',''), dash=False)}</td>
            <td style="padding:6px 10px; color:#e6edf3; font-size:12px; max-width:200px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap;" title="{event_name}">{event_name}</td>
            <td style="padding:6px 10px; color:#8b949e; font-size:12px;">{esc(row.get('event_date',''), dash=False)}</td>
            <td style="padding:6px 10px; color:#8b949e; font-size:12px;">{esc(row.get('sched_start',''))}</td>
            <td style="padding:6px 10px; color:#58a6ff; font-size:12px; font-weight:600;">{actual_start}</td>
            <td style="padding:6px 10px; color:#58a6ff; font-size:12px; font-weight:600;">{actual_end}</td>
            <td style="padding:6px 10px; color:#a5d6ff; font-size:12px;">{video_dur}</td>
            <td style="padding:6px 10px; color:#8b949e; font-size:12px;">{esc(row.get('sched_channel',''))}</td>
            <td style="padding:6px 10px; color:#e6edf3; font-size:12px; max-width:260px; white-space:normal; word-wrap:break-word; line-height:1.4;">{broadcast_ch}</td>
            <td style="padding:6px 10px; color:#f0b429; font-size:11px; max-width:160px; white-space:normal; word-wrap:break-word;">{notes_disp}</td>
            <td style="padding:6px 10px; color:#c9d1d9; font-size:11px; max-width:420px; min-width:280px; white-space:normal; word-wrap:break-word; line-height:1.4;" title="{details_title}">{details_disp}</td>
            <td style="padding:6px 10px;">{verdict_html(verdict)}</td>
            <td style="padding:6px 10px; color:#6e7681; font-size:10px; white-space:nowrap;">{sources}</td>
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
                <th style="padding:8px 10px; color:#58a6ff; font-size:11px; text-align:left; white-space:nowrap;">BROADCAST CHANNELS</th>
                <th style="padding:8px 10px; color:#f0b429; font-size:11px; text-align:left; white-space:nowrap;">NOTES</th>
                <th style="padding:8px 10px; color:#8b949e; font-size:11px; text-align:left; white-space:nowrap;">DETAILS</th>
                <th style="padding:8px 10px; color:#8b949e; font-size:11px; text-align:left; white-space:nowrap;">VERDICT</th>
                <th style="padding:8px 10px; color:#6e7681; font-size:11px; text-align:left; white-space:nowrap;">SOURCES</th>
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

    # Prefer environment variable / secrets over plaintext DB storage
    env_key = os.environ.get("PERPLEXITY_API_KEY", "")
    if not env_key:
        try:
            env_key = st.secrets.get("PERPLEXITY_API_KEY", "")
        except Exception:
            env_key = ""

    if env_key:
        st.sidebar.success("Perplexity key loaded from environment/secrets.")
        api_key = env_key
    else:
        conn = get_db()
        c = conn.cursor()
        c.execute("SELECT value FROM settings WHERE key='perplexity_key'")
        row = c.fetchone()
        saved_key = row["value"] if row else ""
        conn.close()

        api_key = st.sidebar.text_input(
            "Perplexity API Key", value=saved_key, type="password",
            help="Get a key at perplexity.ai/settings/api. Stored unencrypted in the local "
                 "SQLite DB — keep broadcast_verifier.db out of version control, or set the "
                 "PERPLEXITY_API_KEY environment variable instead.",
        )
        if api_key != saved_key:
            conn = get_db()
            conn.execute("INSERT OR REPLACE INTO settings (key,value) VALUES ('perplexity_key',?)", (api_key,))
            conn.commit()
            conn.close()
            st.sidebar.success("Perplexity key saved!")

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
                    st.session_state.pop("events_override", None)  # clear stale manual mapping
                    st.success(f"Imported {len(df)} rows from Google Sheets")
        else:
            uploaded = st.file_uploader("Drop your CSV file here", type=["csv"])
            if uploaded:
                try:
                    df = pd.read_csv(uploaded)
                except Exception as e:
                    st.error(f"Could not parse CSV: {e}")
                    df = None
                if df is not None:
                    # Only reset manual mapping when a different file is loaded
                    if st.session_state.get("uploaded_name") != uploaded.name:
                        st.session_state.pop("events_override", None)
                        st.session_state["uploaded_name"] = uploaded.name
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
                st.warning("⚠️ No Perplexity API key set — actual game times (start/end) will not be looked up. Add your Perplexity key in the sidebar.")

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
        if "results_df" in st.session_state and not st.session_state["results_df"].empty:
            results_df = st.session_state["results_df"]
            rtype = st.session_state.get("results_type","")

            st.markdown("---")
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
                           "actual_start","actual_end","video_duration","broadcast_channels",
                           "notes","details","verdict","sources_used"]
            export_df = results_df[[c for c in export_cols if c in results_df.columns]].copy()
            col_labels = {
                "league":"League","event_name":"Event","event_date":"Date",
                "sched_start":"Sched Start","sched_channel":"Sched Channel",
                "actual_start":"Actual Start (ET)","actual_end":"Actual End (ET)",
                "video_duration":"Video Duration","broadcast_channels":"Broadcast Channels",
                "notes":"Notes","details":"Details","verdict":"Verdict","sources_used":"Sources Used",
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
                                       "actual_start","actual_end","video_duration","broadcast_channels",
                                       "notes","details","verdict","sources_used"]
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
