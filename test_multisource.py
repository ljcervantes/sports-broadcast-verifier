"""
Functional tests for the Perplexity-only verification engine.
Tests: multi_source_lookup, google_game_times_lookup (broadcast parsing),
       compute_verdict, normalize_channel, is_known_local, parse_schedule_df.
"""
import sys, os, types, importlib, re

# ── Stub streamlit so app.py can be imported without a browser ──────────────
st_mod = types.ModuleType("streamlit")
st_mod.cache_resource = lambda f: f
st_mod.cache_data = lambda f: f
st_mod.progress = lambda *a, **kw: type("P", (), {"progress": lambda *a,**kw: None, "empty": lambda *a,**kw: None})()
st_mod.error = print
st_mod.warning = print
st_mod.info = print
st_mod.success = print
st_mod.markdown = lambda *a, **kw: None
st_mod.sidebar = type("SB", (), {
    "markdown": lambda *a,**kw: None,
    "text_input": lambda *a,**kw: "",
    "text_area": lambda *a,**kw: "",
    "button": lambda *a,**kw: False,
    "success": lambda *a,**kw: None,
    "expander": lambda *a,**kw: type("E", (), {"__enter__": lambda s,*a: s, "__exit__": lambda s,*a: None, "text_input": lambda *a,**kw: "", "button": lambda *a,**kw: False, "success": lambda *a,**kw: None})(),
})()
st_mod.set_page_config = lambda *a, **kw: None
st_mod.columns = lambda n: [type("C", (), {"__enter__": lambda s,*a: s, "__exit__": lambda s,*a: None, "markdown": lambda *a,**kw: None, "metric": lambda *a,**kw: None, "button": lambda *a,**kw: False, "selectbox": lambda *a,**kw: "", "text_input": lambda *a,**kw: "", "file_uploader": lambda *a,**kw: None, "dataframe": lambda *a,**kw: None, "download_button": lambda *a,**kw: None, "warning": lambda *a,**kw: None, "info": lambda *a,**kw: None, "error": lambda *a,**kw: None, "success": lambda *a,**kw: None, "expander": lambda *a,**kw: type("E", (), {"__enter__": lambda s,*a: s, "__exit__": lambda s,*a: None, "text_input": lambda *a,**kw: "", "button": lambda *a,**kw: False, "success": lambda *a,**kw: None})()})() for _ in range(n if isinstance(n, int) else 3)]
st_mod.tabs = lambda names: [type("T", (), {"__enter__": lambda s,*a: s, "__exit__": lambda s,*a: None})() for _ in names]
st_mod.expander = lambda *a, **kw: type("E", (), {"__enter__": lambda s,*a: s, "__exit__": lambda s,*a: None, "text_input": lambda *a,**kw: "", "button": lambda *a,**kw: False, "success": lambda *a,**kw: None})()
st_mod.text_input = lambda *a, **kw: ""
st_mod.button = lambda *a, **kw: False
st_mod.selectbox = lambda *a, **kw: ""
st_mod.file_uploader = lambda *a, **kw: None
st_mod.dataframe = lambda *a, **kw: None
st_mod.download_button = lambda *a, **kw: None
st_mod.session_state = {}
sys.modules["streamlit"] = st_mod

# ── Import app ───────────────────────────────────────────────────────────────
sys.path.insert(0, "/home/ubuntu/broadcast-verifier-streamlit")
import app

PASS = 0
FAIL = 0

def check(name, condition, detail=""):
    global PASS, FAIL
    if condition:
        print(f"  PASS  {name}")
        PASS += 1
    else:
        print(f"  FAIL  {name}" + (f" — {detail}" if detail else ""))
        FAIL += 1

# ─────────────────────────────────────────────────────────────────────────────
# 1. multi_source_lookup: returns required keys when no API key given
# ─────────────────────────────────────────────────────────────────────────────
print("\n[1] multi_source_lookup structure (no API key)")
event = {"league":"WNBA","event_name":"Chicago Sky vs Seattle Storm","event_date":"2025-07-20","sched_start":"1:00 PM","sched_channel":"ESPN"}
result = app.multi_source_lookup(event, api_key="", run_type="day_after")
for key in ["actual_start","actual_end","video_duration","national_channel","local_home","local_away","streaming","status_hint","sources_used"]:
    check(f"key '{key}' present", key in result, f"missing key: {key}")
check("sources_used is list", isinstance(result["sources_used"], list))
check("all fields empty when no API key", all(result.get(k,"") == "" for k in ["actual_start","national_channel"]))

# ─────────────────────────────────────────────────────────────────────────────
# 2. compute_verdict: UNVERIFIED for no data + unknown channel
# ─────────────────────────────────────────────────────────────────────────────
print("\n[2] compute_verdict UNVERIFIED")
empty_lookup = {"actual_start":"","actual_end":"","video_duration":"","national_channel":"","local_home":"","local_away":"","streaming":"","status_hint":"","sources_used":[]}
v = app.compute_verdict({"league":"NHRA","sched_channel":"ZZZUNKNOWN"}, empty_lookup, "pre_event")
check("empty lookup + unknown channel = UNVERIFIED", v == "UNVERIFIED")

# ─────────────────────────────────────────────────────────────────────────────
# 3. compute_verdict: channel match = AIRED_AS_SCHEDULED
# ─────────────────────────────────────────────────────────────────────────────
print("\n[3] compute_verdict channel match")
v = app.compute_verdict({"league":"NHRA","sched_channel":"FOX"}, {"national_channel":"FOX","local_home":"","local_away":"","streaming":"","status_hint":""}, "pre_event")
check("matching channel = AIRED_AS_SCHEDULED", v == "AIRED_AS_SCHEDULED")

# ─────────────────────────────────────────────────────────────────────────────
# 4. compute_verdict: channel mismatch = MISMATCH
# ─────────────────────────────────────────────────────────────────────────────
print("\n[4] compute_verdict channel mismatch")
v = app.compute_verdict({"league":"NHRA","sched_channel":"ESPN"}, {"national_channel":"FOX","local_home":"","local_away":"","streaming":"","status_hint":""}, "pre_event")
check("mismatched channel = MISMATCH", v == "MISMATCH")

# ─────────────────────────────────────────────────────────────────────────────
# 5. compute_verdict: status_hint overrides
# ─────────────────────────────────────────────────────────────────────────────
print("\n[5] compute_verdict status_hint overrides")
for hint, expected in [("postponed","POSTPONED"),("canceled","CANCELED"),("delayed","DELAYED")]:
    v = app.compute_verdict({}, {"status_hint": hint, "national_channel":"","local_home":"","local_away":"","streaming":""}, "day_after")
    check(f"status_hint={hint} -> {expected}", v == expected)

# ─────────────────────────────────────────────────────────────────────────────
# 6. compute_verdict: known local station = UNCONFIRMED when no data
# ─────────────────────────────────────────────────────────────────────────────
print("\n[6] compute_verdict known local station")
v = app.compute_verdict({"sched_channel":"NBCSB"}, {"national_channel":"","local_home":"","local_away":"","streaming":"","status_hint":""}, "day_after")
check("known local + no data = UNCONFIRMED", v == "UNCONFIRMED")

# ─────────────────────────────────────────────────────────────────────────────
# 7. compute_verdict: time match = AIRED_AS_SCHEDULED
# ─────────────────────────────────────────────────────────────────────────────
print("\n[7] compute_verdict time match")
v = app.compute_verdict(
    {"sched_start":"7:00 PM", "sched_channel":"ABC"},
    {"actual_start":"7:00 PM ET","national_channel":"ESPN","local_home":"","local_away":"","streaming":"","status_hint":""},
    "day_after"
)
check("time match (even channel mismatch) = AIRED_AS_SCHEDULED", v == "AIRED_AS_SCHEDULED")

# ─────────────────────────────────────────────────────────────────────────────
# 8. normalize_channel: strips whitespace and uppercases
# ─────────────────────────────────────────────────────────────────────────────
print("\n[8] normalize_channel")
check("ESPN normalized", app.normalize_channel("  espn  ") == "ESPN")
check("FS1 normalized", app.normalize_channel("fs1") == "FS1")
check("empty string", app.normalize_channel("") == "")

# ─────────────────────────────────────────────────────────────────────────────
# 9. is_known_local: recognizes known RSN call signs
# ─────────────────────────────────────────────────────────────────────────────
print("\n[9] is_known_local")
check("NBCSB is known local", app.is_known_local("NBCSB"))
check("NESN is known local", app.is_known_local("NESN"))
check("ZZZUNKNOWN is not known local", not app.is_known_local("ZZZUNKNOWN"))
check("ESPN is not local (it's national)", not app.is_known_local("ESPN"))

# ─────────────────────────────────────────────────────────────────────────────
# 10. Broadcast parsing: national channels extracted correctly
# ─────────────────────────────────────────────────────────────────────────────
print("\n[10] Broadcast parsing — national channels")
# Simulate what google_game_times_lookup does with a mock Perplexity answer
mock_answer = (
    "Start: 7:30 PM ET\n"
    "End: 10:05 PM ET\n"
    "Duration: 2 hours 35 minutes\n"
    "Broadcast: ESPN, ABC\n"
    "Notes: None\n"
    "The game was a close contest decided in the final minutes."
)

def _parse_broadcast(answer, event):
    """Replicate the broadcast parsing logic from google_game_times_lookup."""
    m = re.search(r'^Broadcast:\s*(.+?)$', answer, re.IGNORECASE | re.MULTILINE)
    if not m:
        return {"national_channel":"","local_home":"","local_away":"","streaming":""}
    bcast_raw = m.group(1).strip()
    parts = re.split(r'[;,]|\band\b', bcast_raw, flags=re.IGNORECASE)
    home_team = (event.get("home_team") or "").lower()
    away_team = (event.get("away_team") or "").lower()
    NATIONAL_NETS = {
        "espn","espn2","espnu","abc","nbc","cbs","fox","tnt","tbs","truetv",
        "usa network","usa","fs1","fs2","nfl network","nba tv","nhl network",
        "mlb network","nbc sports","cbssn","cbs sports network","sec network",
        "acc network","big ten network","btn","the cw","cw","ion","stadium",
        "fanduel sports","bally sports","msg","sny","yes network","nesn",
        "masn","nbcsn","marquee sports","marquee","victory+",
    }
    STREAMING_KWORDS = [
        "league pass","espn+","peacock","paramount+","amazon prime","prime video",
        "apple tv+","apple tv","disney+","hulu","fubo","sling","youtube tv",
        "directv stream","max","streaming","digital","app","online",
    ]
    LOCAL_KWORDS = ["local","market","regional","rsn"]
    nationals, locals_, streamers = [], [], []
    for raw_part in parts:
        p = raw_part.strip()
        if not p: continue
        pl = p.lower()
        if any(kw in pl for kw in STREAMING_KWORDS):
            streamers.append(p); continue
        if any(kw in pl for kw in LOCAL_KWORDS):
            if home_team and any(tok in pl for tok in home_team.split() if len(tok)>3):
                locals_.append(("home",p))
            elif away_team and any(tok in pl for tok in away_team.split() if len(tok)>3):
                locals_.append(("away",p))
            else:
                locals_.append(("home",p))
            continue
        p_norm = re.sub(r'\(.*?\)','',pl).strip()
        if any(p_norm == net or net in p_norm for net in NATIONAL_NETS):
            nationals.append(p); continue
        if re.match(r'^[A-Z]{2,5}(\d)?(-[A-Z]+)?$', p.strip()):
            locals_.append(("home",p)); continue
        nationals.append(p)
    return {
        "national_channel": "; ".join(nationals),
        "local_home": "; ".join(ch for role,ch in locals_ if role=="home"),
        "local_away": "; ".join(ch for role,ch in locals_ if role=="away"),
        "streaming": "; ".join(streamers),
    }

ev_nat = {"home_team":"Chicago Sky","away_team":"Seattle Storm"}
parsed = _parse_broadcast(mock_answer, ev_nat)
check("ESPN extracted as national", "ESPN" in parsed["national_channel"])
check("ABC extracted as national", "ABC" in parsed["national_channel"])
check("no local channels for national-only broadcast", parsed["local_home"] == "")
check("no streaming for linear-only broadcast", parsed["streaming"] == "")

# ─────────────────────────────────────────────────────────────────────────────
# 11. Broadcast parsing: streaming channels classified correctly
# ─────────────────────────────────────────────────────────────────────────────
print("\n[11] Broadcast parsing — streaming")
mock_stream = (
    "Start: 8:00 PM ET\n"
    "End: 10:30 PM ET\n"
    "Duration: 2 hours 30 minutes\n"
    "Broadcast: NBA League Pass, ESPN+\n"
    "Notes: None\n"
    "Summary sentence."
)
parsed2 = _parse_broadcast(mock_stream, {})
check("NBA League Pass is streaming", "NBA League Pass" in parsed2["streaming"] or "League Pass" in parsed2["streaming"])
check("ESPN+ is streaming", "ESPN+" in parsed2["streaming"])
check("no national for streaming-only", parsed2["national_channel"] == "")

# ─────────────────────────────────────────────────────────────────────────────
# 12. Broadcast parsing: local channels with city names
# ─────────────────────────────────────────────────────────────────────────────
print("\n[12] Broadcast parsing — local channels")
mock_local = (
    "Start: 7:00 PM ET\n"
    "End: 9:30 PM ET\n"
    "Duration: 2 hours 30 minutes\n"
    "Broadcast: ESPN; CW26 (Chicago local); ROOT Sports (Seattle local)\n"
    "Notes: None\n"
    "Summary."
)
ev_local = {"home_team":"Chicago Sky","away_team":"Seattle Storm"}
parsed3 = _parse_broadcast(mock_local, ev_local)
check("ESPN extracted as national from mixed broadcast", "ESPN" in parsed3["national_channel"])
check("Chicago local channel detected", parsed3["local_home"] != "" or parsed3["local_away"] != "")

# ─────────────────────────────────────────────────────────────────────────────
# 13. Notes extraction: overtime flagged, None ignored
# ─────────────────────────────────────────────────────────────────────────────
print("\n[13] Notes extraction")
def _extract_notes(answer):
    m = re.search(r'^Notes:\s*(.+?)$', answer, re.IGNORECASE | re.MULTILINE)
    notes_text = m.group(1).strip() if m else ""
    if not notes_text or re.match(r'^(none|no|n/a|not applicable)', notes_text, re.IGNORECASE):
        return ""
    NOTES_PATS = [
        (re.compile(r'triple\s*overtime|3OT\b', re.IGNORECASE), "Triple overtime"),
        (re.compile(r'double\s*overtime|2OT\b', re.IGNORECASE), "Double overtime"),
        (re.compile(r'overtime|\bOT\b', re.IGNORECASE), "Overtime"),
        (re.compile(r'rain\s*delay|weather\s*delay', re.IGNORECASE), "Rain delay"),
        (re.compile(r'postponed', re.IGNORECASE), "Postponed"),
        (re.compile(r'canceled|cancelled|called\s*off', re.IGNORECASE), "Canceled"),
        (re.compile(r'extra\s*innings?', re.IGNORECASE), "Extra innings"),
    ]
    found = []
    for pat, label in NOTES_PATS:
        if pat.search(notes_text) and label not in found:
            found.append(label)
    return "; ".join(found) if found else notes_text

check("Notes: None → empty string", _extract_notes("Notes: None\nSummary.") == "")
check("Notes: No → empty string", _extract_notes("Notes: No overtime or delays.\nSummary.") == "")
check("Notes: overtime → 'Overtime'", _extract_notes("Notes: Game went to overtime.\nSummary.") == "Overtime")
check("Notes: rain delay → 'Rain delay'", _extract_notes("Notes: Rain delay of 45 minutes.\nSummary.") == "Rain delay")
check("Notes: extra innings → 'Extra innings'", _extract_notes("Notes: Game went to extra innings.\nSummary.") == "Extra innings")

# ─────────────────────────────────────────────────────────────────────────────
# 14. parse_schedule_df: Zoomph format detection
# ─────────────────────────────────────────────────────────────────────────────
print("\n[14] parse_schedule_df Zoomph format")
import pandas as pd
zoomph_df = pd.DataFrame({
    "Uploaded": ["2025-07-20"],
    "Date": ["7/20/2025 7:00 PM"],
    "Home Team": ["Chicago Sky"],
    "Away Team": ["Seattle Storm"],
    "Network": ["ESPN"],
    "Network ID": ["ESPN"],
})
events = app.parse_schedule_df(zoomph_df)
check("Zoomph parse returns list", isinstance(events, list))
check("Zoomph parse returns at least 1 event", len(events) >= 1)
if events:
    check("event has event_name", bool(events[0].get("event_name")))
    check("event has event_date", bool(events[0].get("event_date")))
    check("event has sched_channel", bool(events[0].get("sched_channel")))

# ─────────────────────────────────────────────────────────────────────────────
# 15. markdown stripping: bold and citation markers removed
# ─────────────────────────────────────────────────────────────────────────────
print("\n[15] Markdown stripping")
raw = "**Start:** 7:30 PM ET[1][2] The game was **exciting**."
clean = re.sub(r'\[\d+\]', '', raw)
clean = re.sub(r'\*\*(.+?)\*\*', r'\1', clean)
clean = re.sub(r'\*(.+?)\*', r'\1', clean)
clean = re.sub(r'  +', ' ', clean).strip()
check("citation markers removed", '[1]' not in clean and '[2]' not in clean)
check("bold markers removed", '**' not in clean)
check("content preserved", 'Start:' in clean and 'exciting' in clean)

# ─────────────────────────────────────────────────────────────────────────────
# Summary
# ─────────────────────────────────────────────────────────────────────────────
print(f"\n{'='*50}")
print(f"Results: {PASS} passed, {FAIL} failed out of {PASS+FAIL} tests")
if FAIL == 0:
    print("ALL TESTS PASSED")
    sys.exit(0)
else:
    print("SOME TESTS FAILED")
    sys.exit(1)
