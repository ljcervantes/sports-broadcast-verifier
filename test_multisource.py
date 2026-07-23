"""
Functional tests for multi-source verification engine.
Tests: espn_lookup, mlb_lookup, nhl_lookup, thesportsdb_lookup, multi_source_lookup,
       compute_verdict, _merge_lookup, video_duration field, sources_used field.
"""
import sys, os, types, importlib

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
# 1. _merge_lookup: fills empty fields, does not overwrite existing
# ─────────────────────────────────────────────────────────────────────────────
print("\n[1] _merge_lookup")
base = {"actual_start":"7:00 PM ET","actual_end":"","video_duration":"","national_channel":"ESPN","local_home":"","local_away":"","streaming":"","status_hint":"","sources_used":[]}
extra = {"actual_start":"8:00 PM ET","actual_end":"10:00 PM ET","video_duration":"2:45","national_channel":"FOX","local_home":"KCAL","local_away":"","streaming":"Peacock","status_hint":""}
app._merge_lookup(base, extra)
check("existing actual_start not overwritten", base["actual_start"] == "7:00 PM ET")
check("empty actual_end filled", base["actual_end"] == "10:00 PM ET")
check("empty video_duration filled", base["video_duration"] == "2:45")
check("existing national_channel not overwritten", base["national_channel"] == "ESPN")
check("empty local_home filled", base["local_home"] == "KCAL")
check("streaming appended", "Peacock" in base["streaming"])

# ─────────────────────────────────────────────────────────────────────────────
# 2. _merge_lookup: streaming deduplication
# ─────────────────────────────────────────────────────────────────────────────
print("\n[2] _merge_lookup streaming dedup")
base2 = {"actual_start":"","actual_end":"","video_duration":"","national_channel":"","local_home":"","local_away":"","streaming":"ESPN+","status_hint":"","sources_used":[]}
extra2 = {"streaming":"ESPN+, Peacock"}
app._merge_lookup(base2, extra2)
check("no duplicate ESPN+", base2["streaming"].count("ESPN+") == 1)
check("Peacock added", "Peacock" in base2["streaming"])

# ─────────────────────────────────────────────────────────────────────────────
# 3. multi_source_lookup: returns required keys
# ─────────────────────────────────────────────────────────────────────────────
print("\n[3] multi_source_lookup structure")
event = {"league":"NHRA","event_name":"NHRA Nationals","event_date":"2025-07-20","sched_start":"1:00 PM","sched_channel":"FOX"}
result = app.multi_source_lookup(event, api_key="", run_type="pre_event")
for key in ["actual_start","actual_end","video_duration","national_channel","local_home","local_away","streaming","status_hint","search_url","sources_used"]:
    check(f"key '{key}' present", key in result, f"missing key: {key}")
check("sources_used is list", isinstance(result["sources_used"], list))

# ─────────────────────────────────────────────────────────────────────────────
# 4. multi_source_lookup: niche sport (NHRA) returns no sources (no API covers it)
# ─────────────────────────────────────────────────────────────────────────────
print("\n[4] multi_source_lookup niche sport (NHRA)")
check("NHRA sources_used is a list", isinstance(result["sources_used"], list))
check("NHRA not matched by core structured APIs", not any(s in {"MLB API","NHL API","ESPN","TheSportsDB"} for s in result["sources_used"]))

# ─────────────────────────────────────────────────────────────────────────────
# 5. compute_verdict: UNVERIFIED for niche sport with no data
# ─────────────────────────────────────────────────────────────────────────────
print("\n[5] compute_verdict with empty lookup")
empty_lookup = {"actual_start":"","actual_end":"","video_duration":"","national_channel":"","local_home":"","local_away":"","streaming":"","status_hint":"","sources_used":[]}
# Use a truly unknown channel (not in known-local list) to get UNVERIFIED
v = app.compute_verdict({"league":"NHRA","sched_channel":"ZZZUNKNOWN"}, empty_lookup, "pre_event")
check("empty lookup + truly unknown channel = UNVERIFIED", v == "UNVERIFIED")

v2 = app.compute_verdict({"league":"NHRA","sched_channel":"FOX"}, {"national_channel":"FOX","local_home":"","local_away":"","streaming":"","status_hint":""}, "pre_event")
check("matching channel = AIRED_AS_SCHEDULED", v2 == "AIRED_AS_SCHEDULED")

v3 = app.compute_verdict({"league":"NHRA","sched_channel":"ESPN"}, {"national_channel":"FOX","local_home":"","local_away":"","streaming":"","status_hint":""}, "pre_event")
check("mismatched channel = MISMATCH", v3 == "MISMATCH")

# ─────────────────────────────────────────────────────────────────────────────
# 6. compute_verdict: status_hint overrides
# ─────────────────────────────────────────────────────────────────────────────
print("\n[6] compute_verdict status_hint overrides")
for hint, expected in [("postponed","POSTPONED"),("canceled","CANCELED"),("delayed","DELAYED")]:
    v = app.compute_verdict({}, {"status_hint": hint, "national_channel":"","local_home":"","local_away":"","streaming":""}, "day_after")
    check(f"status_hint={hint} -> {expected}", v == expected)

# ─────────────────────────────────────────────────────────────────────────────
# 7. compute_verdict: day_after with known local station
# ─────────────────────────────────────────────────────────────────────────────
print("\n[7] compute_verdict day_after known local station")
v = app.compute_verdict({"sched_channel":"NBCSB"}, {"national_channel":"","local_home":"","local_away":"","streaming":"","status_hint":""}, "day_after")
check("known local + no data + day_after = UNCONFIRMED", v == "UNCONFIRMED")

v = app.compute_verdict({"sched_channel":"NBCSB"}, {"national_channel":"","local_home":"","local_away":"","streaming":"","status_hint":""}, "pre_event")
check("known local + no data + pre_event = UNCONFIRMED", v == "UNCONFIRMED")

# ─────────────────────────────────────────────────────────────────────────────
# 8. espn_lookup: returns correct structure for unsupported league
# ─────────────────────────────────────────────────────────────────────────────
print("\n[8] espn_lookup unsupported league")
r = app.espn_lookup({"league":"NHRA","event_name":"Nationals","event_date":"2025-07-20"}, "pre_event")
check("unsupported league returns empty dict keys", r.get("national_channel","") == "")
check("unsupported league returns empty actual_start", r.get("actual_start","") == "")

# ─────────────────────────────────────────────────────────────────────────────
# 9. mlb_lookup: returns correct structure for non-MLB league
# ─────────────────────────────────────────────────────────────────────────────
print("\n[9] mlb_lookup non-MLB league")
r = app.mlb_lookup({"league":"NFL","event_name":"Chiefs vs Ravens","event_date":"2025-09-07"}, "pre_event")
check("non-MLB returns empty actual_start", r.get("actual_start","") == "")
check("non-MLB returns empty video_duration", r.get("video_duration","") == "")

# ─────────────────────────────────────────────────────────────────────────────
# 10. nhl_lookup: returns correct structure for non-NHL league
# ─────────────────────────────────────────────────────────────────────────────
print("\n[10] nhl_lookup non-NHL league")
r = app.nhl_lookup({"league":"NBA","event_name":"Lakers vs Celtics","event_date":"2025-06-15"}, "day_after")
check("non-NHL returns empty actual_start", r.get("actual_start","") == "")

# ─────────────────────────────────────────────────────────────────────────────
# 11. thesportsdb_lookup: returns correct structure for unsupported league
# ─────────────────────────────────────────────────────────────────────────────
print("\n[11] thesportsdb_lookup unsupported league")
r = app.thesportsdb_lookup({"league":"NHRA","event_name":"Nationals","event_date":"2025-07-20"}, "pre_event")
check("unsupported league returns empty actual_start", r.get("actual_start","") == "")

# ─────────────────────────────────────────────────────────────────────────────
# 12. build_fallback_url: returns a Google search URL
# ─────────────────────────────────────────────────────────────────────────────
print("\n[12] build_fallback_url")
url = app.build_fallback_url({"event_name":"Cubs vs Cardinals","event_date":"2025-07-20","league":"MLB"}, "day_after")
check("returns https URL", url.startswith("https://"))
check("contains google.com", "google.com" in url)

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
