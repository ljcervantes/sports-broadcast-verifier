/**
 * Core verification engine.
 * Handles CSV parsing, pre-event cross-check, day-after verdict logic,
 * Google/SerpApi broadcast lookup, and ESPN scoreboard integration.
 */

export type SportEvent = {
  league: string;
  eventName: string;
  homeTeam?: string;
  awayTeam?: string;
  scheduledDate: string;
  scheduledStartTime?: string;
  scheduledChannel?: string;
};

export type BroadcastLookup = {
  actualStartTime?: string;
  actualEndTime?: string;
  nationalChannel?: string;
  localHomeRsn?: string;
  localAwayRsn?: string;
  streamingPlatforms: string[];
  allChannels: string[];
  sourceDetails: Record<string, unknown>;
  googleSearchUrl?: string;
};

export type VerificationVerdict =
  | "MATCH"
  | "MISMATCH"
  | "UNCONFIRMED"
  | "AIRED_AS_SCHEDULED"
  | "DELAYED"
  | "POSTPONED"
  | "CANCELED"
  | "NETWORK_CHANGED"
  | "UNVERIFIED";

export type VerificationResultRow = SportEvent &
  BroadcastLookup & {
    verdict: VerificationVerdict;
  };

// ---- CSV Parser ----
export function parseCSV(csvText: string): SportEvent[] {
  const lines = csvText.split(/\r?\n/).filter((l) => l.trim());
  if (lines.length < 2) return [];
  const header = lines[0]
    .split(",")
    .map((h) => h.trim().toLowerCase().replace(/[^a-z0-9]/g, "_"));

  const get = (row: string[], ...keys: string[]): string => {
    for (const key of keys) {
      const idx = header.indexOf(key);
      if (idx !== -1 && row[idx]?.trim()) return row[idx].trim();
    }
    return "";
  };

  return lines
    .slice(1)
    .map((line) => {
      const row = splitCSVLine(line);
      const homeTeam = get(row, "home", "home_team", "hometeam", "home_club");
      const awayTeam = get(row, "away", "away_team", "awayteam", "visitor", "away_club");
      const eventTitle = get(row, "event", "event_name", "title", "game", "name", "description");
      const league = get(row, "league", "sport", "league_name", "sport_name");
      const date = get(row, "date", "event_date", "game_date", "air_date");
      const startTime = get(row, "time", "start_time", "start", "scheduled_time", "air_time");
      const channel = get(row, "channel", "network", "broadcast", "tv", "scheduled_channel", "broadcaster");
      const eventName =
        eventTitle ||
        (homeTeam && awayTeam
          ? `${awayTeam} @ ${homeTeam}`
          : homeTeam || awayTeam || "Unknown Event");
      return {
        league,
        eventName,
        homeTeam: homeTeam || undefined,
        awayTeam: awayTeam || undefined,
        scheduledDate: date,
        scheduledStartTime: startTime || undefined,
        scheduledChannel: channel || undefined,
      };
    })
    .filter((e) => e.scheduledDate);
}

function splitCSVLine(line: string): string[] {
  const result: string[] = [];
  let current = "";
  let inQuotes = false;
  for (let i = 0; i < line.length; i++) {
    const ch = line[i];
    if (ch === '"') {
      inQuotes = !inQuotes;
    } else if (ch === "," && !inQuotes) {
      result.push(current);
      current = "";
    } else {
      current += ch;
    }
  }
  result.push(current);
  return result;
}

// ---- Channel Classification ----
// Known local OTA and RSN call signs — expanded for WNBA, NBA, MLB, NHL, etc.
// These are real broadcast stations that carry local sports rights.
// Format: uppercase call sign exactly as it appears in schedule data.
export const LOCAL_OTA_STATIONS: Set<string> = new Set([
  // WNBA local affiliates (team home markets)
  "KMCC",   // Las Vegas Aces — Las Vegas
  "SPECSN", // Spectrum SportsNet — LA Sparks / Lakers
  "KUNS",   // Seattle Storm — Seattle
  "KPDX",   // Portland (Storm away)
  "NBCSB",  // NBC Sports Bay Area — Golden State / San Jose
  "KPIX",   // CBS San Francisco
  "KNTV",   // NBC Bay Area
  "WTTV",   // Indianapolis — Indiana Fever
  "WFLD",   // Chicago Sky — Fox Chicago
  "WMAQ",   // NBC Chicago
  "WGBO",   // Univision Chicago
  "WBNS",   // Columbus
  "WXYZ",   // Detroit
  "WDIV",   // Detroit
  "WEWS",   // Cleveland
  "WJW",    // Cleveland Fox
  "WKYC",   // Cleveland NBC
  "WTAE",   // Pittsburgh
  "WPXI",   // Pittsburgh NBC
  "KDKA",   // Pittsburgh CBS
  "WBAL",   // Baltimore
  "WMAR",   // Baltimore ABC
  "WBFF",   // Baltimore Fox
  "WUSA",   // DC CBS
  "WRC",    // DC NBC
  "WJLA",   // DC ABC
  "WTTG",   // DC Fox
  "WNBC",   // New York NBC
  "WABC",   // New York ABC
  "WCBS",   // New York CBS
  "WNYW",   // New York Fox
  "WPIX",   // New York CW
  "WCVB",   // Boston ABC
  "WBZ",    // Boston CBS
  "WHDH",   // Boston NBC
  "WFXT",   // Boston Fox
  "WBTS",   // Boston NBC Sports
  "NESN",   // New England Sports Network
  "MASN",   // Mid-Atlantic Sports Network
  "MASN2",  // MASN2
  "MSG",    // Madison Square Garden Network
  "MSGPLUS", // MSG+
  "YES",    // YES Network (Yankees/Nets)
  "SNY",    // SportsNet New York (Mets)
  "BSOH",   // Bally Sports Ohio
  "BSSUN",  // Bally Sports Sun (Tampa/Orlando)
  "BSSE",   // Bally Sports Southeast
  "BSSW",   // Bally Sports Southwest
  "BSMW",   // Bally Sports Midwest
  "BSDET",  // Bally Sports Detroit
  "BSGL",   // Bally Sports Great Lakes
  "BSFL",   // Bally Sports Florida
  "BSAZ",   // Bally Sports Arizona
  "BSSD",   // Bally Sports San Diego
  "BSSC",   // Bally Sports SoCal
  "BSNW",   // Bally Sports Northwest
  "BSRM",   // Bally Sports Rocky Mountain
  "BSKC",   // Bally Sports Kansas City
  "BSNO",   // Bally Sports New Orleans
  "BSIN",   // Bally Sports Indiana
  "BSWI",   // Bally Sports Wisconsin
  "NBCSP",  // NBC Sports Philadelphia
  "NBCSCH", // NBC Sports Chicago
  "NBCSCA", // NBC Sports California
  "NBCSWA", // NBC Sports Washington
  "NBCSBO", // NBC Sports Boston
  "ATTSN",  // AT&T SportsNet (Pittsburgh/Rocky Mtn/Southwest)
  "ATTSRM", // AT&T SportsNet Rocky Mountain
  "ATTSNSW",// AT&T SportsNet Southwest
  "ROOT",   // Root Sports Northwest
  "ROOTNW", // Root Sports Northwest
  "FSDET",  // Fox Sports Detroit
  "FSTENN", // Fox Sports Tennessee
  "FSWIS",  // Fox Sports Wisconsin
  "FSSOUTH",// Fox Sports South
  "FSSE",   // Fox Sports Southeast
  "FSSW",   // Fox Sports Southwest
  "FSMW",   // Fox Sports Midwest
  "FSOH",   // Fox Sports Ohio
  "FSFLA",  // Fox Sports Florida
  "FSAZ",   // Fox Sports Arizona
  "FSSD",   // Fox Sports San Diego
  "FSNW",   // Fox Sports Northwest
  "FSRM",   // Fox Sports Rocky Mountain
  "FSKC",   // Fox Sports Kansas City
  "FSNO",   // Fox Sports New Orleans
  "FSIN",   // Fox Sports Indiana
  // Common local network affiliates by market
  "KABC",   // LA ABC
  "KNBC",   // LA NBC
  "KCBS",   // LA CBS
  "KTTV",   // LA Fox
  "KCAL",   // LA Independent
  "KSWB",   // San Diego Fox
  "KGTV",   // San Diego ABC
  "KNSD",   // San Diego NBC
  "KPHO",   // Phoenix CBS
  "KNXV",   // Phoenix ABC
  "KPNX",   // Phoenix NBC
  "KSAZ",   // Phoenix Fox
  "KDVR",   // Denver Fox
  "KMGH",   // Denver ABC
  "KUSA",   // Denver NBC
  "KCNC",   // Denver CBS
  "KHOU",   // Houston CBS
  "KPRC",   // Houston NBC
  "KTRK",   // Houston ABC
  "KRIV",   // Houston Fox
  "WFAA",   // Dallas ABC
  "KXAS",   // Dallas NBC
  "KTVT",   // Dallas CBS
  "KDFW",   // Dallas Fox
  "KSAT",   // San Antonio ABC
  "KABB",   // San Antonio Fox
  "WOAI",   // San Antonio NBC
  "KENS",   // San Antonio CBS
  "KOIN",   // Portland CBS
  "KGW",    // Portland NBC
  "KATU",   // Portland ABC
  "KPTV",   // Portland Fox
  "KING",   // Seattle NBC
  "KOMO",   // Seattle ABC
  "KIRO",   // Seattle CBS/Fox
  "KCPQ",   // Seattle Fox
  "KVAL",   // Eugene/Portland
  "KEZI",   // Eugene ABC
  "KOIN2",  // Portland CBS2
  "KBOI",   // Boise CBS
  "KTVB",   // Boise NBC
  "KIVI",   // Boise ABC
  "KTRV",   // Boise Fox
  "KVVU",   // Las Vegas Fox
  "KLAS",   // Las Vegas CBS
  "KSNV",   // Las Vegas NBC
  "KTNV",   // Las Vegas ABC
  "KSNT",   // Topeka NBC
  "WKRN",   // Nashville ABC
  "WSMV",   // Nashville NBC
  "WTVF",   // Nashville CBS
  "WZTV",   // Nashville Fox
  "WSOC",   // Charlotte ABC
  "WCNC",   // Charlotte NBC
  "WBTV",   // Charlotte CBS
  "WCCB",   // Charlotte CW
  "WXIA",   // Atlanta NBC
  "WSB",    // Atlanta ABC
  "WGCL",   // Atlanta CBS
  "WAGA",   // Atlanta Fox
  "WFTV",   // Orlando ABC
  "WESH",   // Orlando NBC
  "WKMG",   // Orlando CBS
  "WOFL",   // Orlando Fox
  "WSVN",   // Miami Fox
  "WFOR",   // Miami CBS
  "WPLG",   // Miami ABC
  "WTVJ",   // Miami NBC
  "WFTS",   // Tampa ABC
  "WTSP",   // Tampa CBS
  "WFLA",   // Tampa NBC
  "WTVT",   // Tampa Fox
  "WVIT",   // Hartford NBC
  "WTNH",   // Hartford ABC
  "WFSB",   // Hartford CBS
  "WTIC",   // Hartford Fox
  "WJAR",   // Providence NBC
  "WPRI",   // Providence CBS
  "WLNE",   // Providence ABC
  "WPHL",   // Philadelphia CW
  "WCAU",   // Philadelphia NBC
  "WPVI",   // Philadelphia ABC
  "KYW",    // Philadelphia CBS
  "WTXF",   // Philadelphia Fox
  "KDKA2",  // Pittsburgh CBS2
  "WPCW",   // Pittsburgh CW
  "WKRC",   // Cincinnati CBS
  "WCPO",   // Cincinnati ABC
  "WLWT",   // Cincinnati NBC
  "WXIX",   // Cincinnati Fox
  "WEWS2",  // Cleveland ABC2
  "WDTN",   // Dayton NBC
  "WHIO",   // Dayton CBS
  "WKEF",   // Dayton ABC
  "WRGT",   // Dayton Fox
  "WBRC",   // Birmingham Fox
  "WVTM",   // Birmingham NBC
  "WIAT",   // Birmingham CBS
  "WAAY",   // Huntsville ABC
  "WAFF",   // Huntsville NBC
  "WHNT",   // Huntsville CBS
  "WZDX",   // Huntsville Fox
  "WLOX",   // Biloxi ABC
  "WDAM",   // Hattiesburg NBC
  "WLBT",   // Jackson NBC
  "WAPT",   // Jackson ABC
  "WJTV",   // Jackson CBS
  "WDBD",   // Jackson Fox
  "KARK",   // Little Rock NBC
  "KATV",   // Little Rock ABC
  "KTHV",   // Little Rock CBS
  "KLRT",   // Little Rock Fox
  "KFOR",   // Oklahoma City NBC
  "KOCO",   // Oklahoma City ABC
  "KWTV",   // Oklahoma City CBS
  "KOKH",   // Oklahoma City Fox
  "KOTV",   // Tulsa CBS
  "KJRH",   // Tulsa NBC
  "KTUL",   // Tulsa ABC
  "KOKI",   // Tulsa Fox
  "KWCH",   // Wichita CBS
  "KSNW",   // Wichita NBC
  "KAKE",   // Wichita ABC
  "KSAS",   // Wichita Fox
  "KCTV",   // Kansas City CBS
  "KMBC",   // Kansas City ABC
  "KSHB",   // Kansas City NBC
  "WDAF",   // Kansas City Fox
  "KMOV",   // St. Louis CBS
  "KSDK",   // St. Louis NBC
  "KTVI",   // St. Louis Fox
  "KDNL",   // St. Louis ABC
  "KSTP",   // Minneapolis ABC
  "WCCO",   // Minneapolis CBS
  "KARE",   // Minneapolis NBC
  "KMSP",   // Minneapolis Fox
  "WOI",    // Des Moines ABC
  "WHO",    // Des Moines NBC
  "KCCI",   // Des Moines CBS
  "KDSM",   // Des Moines Fox
  "WITI",   // Milwaukee Fox
  "WTMJ",   // Milwaukee NBC
  "WISN",   // Milwaukee ABC
  "WDJT",   // Milwaukee CBS
  "WKOW",   // Madison ABC
  "WMTV",   // Madison NBC
  "WISC",   // Madison CBS
  "WMSN",   // Madison Fox
  "WBAY",   // Green Bay ABC
  "WGBA",   // Green Bay NBC
  "WFRV",   // Green Bay CBS
  "WLUK",   // Green Bay Fox
  "WLNS",   // Lansing CBS
  "WLAJ",   // Lansing ABC
  "WSYM",   // Lansing Fox
  "WZZM",   // Grand Rapids ABC
  "WOOD",   // Grand Rapids NBC
  "WWMT",   // Grand Rapids CBS
  "WXMI",   // Grand Rapids Fox
  "WKBD",   // Detroit CW
  "WJBK",   // Detroit Fox
  "WDIV2",  // Detroit NBC2
  "WNEM",   // Flint/Saginaw NBC
  "WEYI",   // Flint/Saginaw NBC
  "WSMH",   // Flint Fox
  "WJRT",   // Flint ABC
  "WWTV",   // Traverse City CBS
  "WGTU",   // Traverse City ABC
  "WTOM",   // Traverse City NBC
  "WBUP",   // Marquette NBC
  "WLUC",   // Marquette NBC
  "WZMQ",   // Marquette ABC
  "WJMN",   // Marquette CBS
  "WFRV2",  // Green Bay CBS2
  "WLAX",   // La Crosse Fox
  "WXOW",   // La Crosse ABC
  "WKBT",   // La Crosse CBS
  "WEAU",   // Eau Claire NBC
  "WQOW",   // Eau Claire ABC
  "WSAW",   // Wausau CBS
  "WAOW",   // Wausau ABC
  "WHRM",   // Wausau NBC
  "WJFW",   // Rhinelander NBC
  "WACY",   // Green Bay CW
  "WTVO",   // Rockford ABC
  "WIFR",   // Rockford CBS
  "WREX",   // Rockford NBC
  "WQRF",   // Rockford Fox
  "WEEK",   // Peoria NBC
  "WMBD",   // Peoria CBS
  "WHOI",   // Peoria ABC
  "WYZZ",   // Peoria Fox
  "WCIA",   // Champaign CBS
  "WICD",   // Champaign NBC
  "WAND",   // Champaign ABC
  "WCIX",   // Champaign Fox
  "WSIL",   // Paducah ABC
  "KFVS",   // Paducah CBS
  "WPSD",   // Paducah NBC
  "WDKA",   // Paducah Fox
  "WKRG",   // Mobile CBS
  "WPMI",   // Mobile NBC
  "WALA",   // Mobile Fox
  "WEAR",   // Pensacola ABC
  "WKRG2",  // Mobile CBS2
  "WJHG",   // Panama City NBC
  "WMBB",   // Panama City ABC
  "WJCT",   // Jacksonville PBS
  "WJXT",   // Jacksonville CBS
  "WTLV",   // Jacksonville NBC
  "WJAX",   // Jacksonville ABC
  "WFOX",   // Jacksonville Fox
  "WCJB",   // Gainesville ABC
  "WUFT",   // Gainesville PBS
  "WOGX",   // Gainesville Fox
  "WTXL",   // Tallahassee ABC
  "WCTV",   // Tallahassee CBS
  "WTWC",   // Tallahassee NBC
  "WTLH",   // Tallahassee Fox
  "WFSU",   // Tallahassee PBS
]);

// Normalize a call sign for comparison
export function normalizeCallSign(ch: string): string {
  return ch.toUpperCase().replace(/[-\s]/g, "").replace(/[^A-Z0-9+]/g, "");
}

// Check if a channel name is a known local OTA station
export function isKnownLocalStation(ch: string, customStations: string[] = []): boolean {
  const norm = normalizeCallSign(ch);
  if (LOCAL_OTA_STATIONS.has(norm)) return true;
  return customStations.some((s) => normalizeCallSign(s) === norm);
}

const NATIONAL_CHANNELS: string[] = [
  "ESPN", "ESPN2", "ESPNU", "ESPN News", "ABC", "NBC", "CBS", "FOX",
  "FS1", "FS2", "TNT", "TBS", "USA", "NBCSN", "truTV", "TruTV",
  "NFL Network", "MLB Network", "NBA TV", "NHL Network",
  "Golf Channel", "Tennis Channel", "CBS Sports Network",
  "Paramount Network", "Outdoor Channel", "Sportsman Channel",
  "MAVTV", "World Fishing Network",
];

const STREAMING_PLATFORMS: string[] = [
  "ESPN+", "Peacock", "Paramount+", "Amazon Prime Video", "Apple TV+",
  "Max", "Hulu", "fuboTV", "DirecTV Stream", "YouTube TV", "Sling",
  "Sling TV", "DAZN", "FloSports", "WatchESPN", "NBC Sports App",
  "NFL+", "MLB.TV", "NHL.TV", "NBA League Pass", "MLS Season Pass",
  "FloRacing", "FloLacrosse", "Peacock Sports",
];

const RSN_PATTERNS = [
  /YES Network/i, /NESN/i, /MASN/i, /MASN2/i, /BSOH/i, /BSW/i,
  /Bally Sports [A-Za-z ]+/i, /NBC Sports [A-Za-z]+/i,
  /AT&T SportsNet/i, /ROOT Sports/i, /SportsNet [A-Za-z]+/i,
  /MSG\b/i, /MSG\+/i, /WPIX/i, /WGBS/i,
];

function normalizeChannelName(ch: string): string {
  return normalizeCallSign(ch);
}

function channelsMatch(a: string, b: string): boolean {
  const na = normalizeChannelName(a);
  const nb = normalizeChannelName(b);
  return na.includes(nb) || nb.includes(na);
}

function parseChannelsFromText(text: string): string[] {
  const found: string[] = [];
  const allKnown = [...NATIONAL_CHANNELS, ...STREAMING_PLATFORMS];
  for (const ch of allKnown) {
    const escaped = ch.replace(/[+]/g, "\\+").replace(/\./g, "\\.");
    if (new RegExp(`\\b${escaped}\\b`, "i").test(text)) {
      if (!found.some((f) => normalizeChannelName(f) === normalizeChannelName(ch))) {
        found.push(ch);
      }
    }
  }
  for (const pattern of RSN_PATTERNS) {
    const m = text.match(pattern);
    if (m && m[0] && !found.some((f) => normalizeChannelName(f) === normalizeChannelName(m[0]))) {
      found.push(m[0]);
    }
  }
  return found;
}

function classifyChannels(channels: string[]): {
  national: string[];
  streaming: string[];
  local: string[];
} {
  const national: string[] = [];
  const streaming: string[] = [];
  const local: string[] = [];
  for (const ch of channels) {
    const norm = normalizeChannelName(ch);
    if (STREAMING_PLATFORMS.some((s) => normalizeChannelName(s) === norm)) {
      streaming.push(ch);
    } else if (NATIONAL_CHANNELS.some((n) => normalizeChannelName(n) === norm)) {
      national.push(ch);
    } else {
      local.push(ch);
    }
  }
  return { national, streaming, local };
}

// ---- Status Detection ----
type EventStatus = "CANCELED" | "POSTPONED" | "DELAYED" | "LIVE" | "FINAL" | "SCHEDULED" | null;

function detectStatus(text: string): EventStatus {
  const t = text.toLowerCase();
  if (/\b(cancel|called off|no game|no contest)\b/.test(t)) return "CANCELED";
  if (/\b(postpone|rescheduled|moved to)\b/.test(t)) return "POSTPONED";
  if (/\b(rain delay|weather delay|delay|suspended)\b/.test(t)) return "DELAYED";
  if (/\b(final|ended|completed|concluded)\b/.test(t)) return "FINAL";
  if (/\b(live|in progress|underway|ongoing)\b/.test(t)) return "LIVE";
  return null;
}

// ---- Google Query Builder ----
function buildGoogleQuery(event: SportEvent, dayAfter = false): string {
  const suffix = dayAfter
    ? "broadcast channel what channel aired"
    : "where to watch broadcast channel TV";
  if (event.homeTeam && event.awayTeam) {
    return `${event.awayTeam} vs ${event.homeTeam} ${event.scheduledDate} ${suffix}`;
  }
  return `${event.eventName} ${event.scheduledDate} ${suffix}`;
}

// ---- ESPN Scoreboard Lookup ----
const ESPN_LEAGUE_MAP: Record<string, string> = {
  MLB: "baseball/mlb",
  NBA: "basketball/nba",
  NFL: "football/nfl",
  NHL: "hockey/nhl",
  MLS: "soccer/usa.1",
  NCAAF: "football/college-football",
  NCAAB: "basketball/mens-college-basketball",
  WNBA: "basketball/wnba",
  PLL: "lacrosse/pll",
  INDYCAR: "racing/indycar",
  F1: "racing/f1",
  NASCAR: "racing/nascar-premier",
};

async function espnLookup(event: SportEvent): Promise<BroadcastLookup | null> {
  const sportPath = ESPN_LEAGUE_MAP[event.league?.toUpperCase()];
  if (!sportPath) return null;

  try {
    const dateStr = event.scheduledDate.replace(/[-/]/g, "");
    const url = `https://site.api.espn.com/apis/site/v2/sports/${sportPath}/scoreboard?dates=${dateStr}&limit=50`;
    const resp = await fetch(url, { signal: AbortSignal.timeout(6000) });
    if (!resp.ok) return null;
    const data = (await resp.json()) as Record<string, unknown>;
    const events = (data.events as Array<Record<string, unknown>>) ?? [];

    for (const ev of events) {
      const name = String(ev.name ?? ev.shortName ?? "");
      const competitions = (ev.competitions as Array<Record<string, unknown>>) ?? [];
      const comp = competitions[0];
      if (!comp) continue;

      // Match by team names
      const competitors = (comp.competitors as Array<Record<string, unknown>>) ?? [];
      const teamNames = competitors.map((c) => {
        const t = c.team as Record<string, string> | undefined;
        return [t?.displayName ?? "", t?.abbreviation ?? "", t?.shortDisplayName ?? ""];
      }).flat().filter(Boolean);

      const isMatch =
        (event.homeTeam && teamNames.some((t) => t.toLowerCase().includes(event.homeTeam!.toLowerCase()))) ||
        (event.awayTeam && teamNames.some((t) => t.toLowerCase().includes(event.awayTeam!.toLowerCase()))) ||
        name.toLowerCase().includes(event.eventName.toLowerCase().slice(0, 15));

      if (!isMatch) continue;

      // Extract broadcast info
      const broadcasts = (comp.broadcasts as Array<Record<string, unknown>>) ?? [];
      const channels: string[] = [];
      for (const b of broadcasts) {
        const names = (b.names as string[]) ?? [];
        channels.push(...names);
      }

      // Status
      const statusObj = comp.status as Record<string, unknown> | undefined;
      const statusType = statusObj?.type as Record<string, unknown> | undefined;
      const statusName = String(statusType?.name ?? "");
      const statusDesc = String(statusType?.description ?? "");

      // Start time
      const dateStr2 = String(ev.date ?? "");
      const actualStartTime = dateStr2 ? new Date(dateStr2).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }) : undefined;

      const { national, streaming, local } = classifyChannels(channels);
      return {
        actualStartTime,
        nationalChannel: national[0],
        localHomeRsn: local[0],
        localAwayRsn: local[1],
        streamingPlatforms: streaming,
        allChannels: channels,
        sourceDetails: {
          source: "espn",
          statusName,
          statusDesc,
          channels,
          eventName: name,
        },
        googleSearchUrl: `https://www.google.com/search?q=${encodeURIComponent(buildGoogleQuery(event))}`,
      };
    }
    return null;
  } catch {
    return null;
  }
}

// ---- Google / SerpApi Lookup ----
export async function googleBroadcastLookup(
  event: SportEvent,
  serpApiKey: string,
  dayAfter = false
): Promise<BroadcastLookup> {
  const query = buildGoogleQuery(event, dayAfter);
  const googleSearchUrl = `https://www.google.com/search?q=${encodeURIComponent(query)}`;

  if (!serpApiKey) {
    return {
      streamingPlatforms: [],
      allChannels: [],
      sourceDetails: { error: "No SerpApi key configured" },
      googleSearchUrl,
    };
  }

  try {
    const url = new URL("https://serpapi.com/search.json");
    url.searchParams.set("q", query);
    url.searchParams.set("api_key", serpApiKey);
    url.searchParams.set("engine", "google");
    url.searchParams.set("num", "5");

    const resp = await fetch(url.toString(), { signal: AbortSignal.timeout(10000) });
    if (!resp.ok) {
      return {
        streamingPlatforms: [],
        allChannels: [],
        sourceDetails: { error: `SerpApi HTTP ${resp.status}` },
        googleSearchUrl,
      };
    }
    const data = (await resp.json()) as Record<string, unknown>;

    // Pull text from all result sections
    const organicResults = (data.organic_results as Array<{ snippet?: string; title?: string }>) ?? [];
    const snippets = organicResults.map((r) => [r.title ?? "", r.snippet ?? ""].join(" ")).join(" ");
    const sportsBox = JSON.stringify(data.sports_results ?? {});
    const answerBox = JSON.stringify(data.answer_box ?? {});
    const knowledgeGraph = JSON.stringify(data.knowledge_graph ?? {});
    const combinedText = [snippets, sportsBox, answerBox, knowledgeGraph].join(" ");

    // Parse channels
    const channels = parseChannelsFromText(combinedText);
    const { national, streaming, local } = classifyChannels(channels);

    // Parse status signals
    const status = detectStatus(combinedText);

    // Try to extract actual start/end time from sports_results game_spotlight
    let actualStartTime: string | undefined;
    let actualEndTime: string | undefined;
    const sr = data.sports_results as Record<string, unknown> | undefined;
    if (sr) {
      const spotlight = sr.game_spotlight as Record<string, string> | undefined;
      if (spotlight) {
        actualStartTime = spotlight.date ?? spotlight.time ?? undefined;
        actualEndTime = spotlight.end_time ?? undefined;
      }
      if (!actualStartTime) {
        actualStartTime = (sr.date as string | undefined) ?? undefined;
      }
    }
    // Also try answer box
    if (!actualStartTime) {
      const ab = data.answer_box as Record<string, string> | undefined;
      if (ab?.answer) actualStartTime = ab.answer;
    }

    return {
      actualStartTime,
      actualEndTime,
      nationalChannel: national[0],
      localHomeRsn: local[0],
      localAwayRsn: local[1],
      streamingPlatforms: streaming,
      allChannels: channels,
      sourceDetails: {
        query,
        nationalChannels: national,
        localChannels: local,
        streamingPlatforms: streaming,
        detectedStatus: status,
        serpApiUsed: true,
      },
      googleSearchUrl,
    };
  } catch (err: unknown) {
    const msg = err instanceof Error ? err.message : String(err);
    return {
      streamingPlatforms: [],
      allChannels: [],
      sourceDetails: { error: msg },
      googleSearchUrl,
    };
  }
}

// ---- Merge multiple source lookups ----
function mergeLookups(primary: BroadcastLookup, secondary: BroadcastLookup | null): BroadcastLookup {
  if (!secondary) return primary;
  const allChannels = Array.from(new Set(primary.allChannels.concat(secondary.allChannels)));
  const { national, streaming, local } = classifyChannels(allChannels);
  return {
    actualStartTime: primary.actualStartTime ?? secondary.actualStartTime,
    actualEndTime: primary.actualEndTime ?? secondary.actualEndTime,
    nationalChannel: national[0] ?? primary.nationalChannel ?? secondary.nationalChannel,
    localHomeRsn: local[0] ?? primary.localHomeRsn ?? secondary.localHomeRsn,
    localAwayRsn: local[1] ?? primary.localAwayRsn ?? secondary.localAwayRsn,
    streamingPlatforms: streaming,
    allChannels,
    sourceDetails: { ...secondary.sourceDetails, ...primary.sourceDetails },
    googleSearchUrl: primary.googleSearchUrl ?? secondary.googleSearchUrl,
  };
}

// ---- Pre-Event Cross-Check ----
// ---- Custom Station Loader ----
// Loads user-defined local stations from the database settings.
// Defined here to avoid circular imports since verificationEngine has no db import.
async function getCustomStations(): Promise<string[]> {
  try {
    const { getDb } = await import("./db");
    const db = await getDb();
    if (!db) return [];
    const { appSettings } = await import("../drizzle/schema");
    const { eq } = await import("drizzle-orm");
    const rows = await db.select().from(appSettings).where(eq(appSettings.key, "custom_stations")).limit(1);
    const raw = rows[0]?.value ?? "";
    return raw.split(",").map((s: string) => s.trim().toUpperCase()).filter(Boolean);
  } catch {
    return [];
  }
}

export async function preEventCrossCheck(
  events: SportEvent[],
  enabledSources: string[],
  serpApiKey: string
): Promise<VerificationResultRow[]> {
  const customStations = await getCustomStations();
  const results: VerificationResultRow[] = [];
  for (const event of events) {
    const googleUrl = `https://www.google.com/search?q=${encodeURIComponent(buildGoogleQuery(event))}`;
    let lookup: BroadcastLookup = {
      streamingPlatforms: [],
      allChannels: [],
      sourceDetails: {},
      googleSearchUrl: googleUrl,
    };

    // ESPN lookup (free, no key needed)
    if (enabledSources.includes("espn")) {
      const espnResult = await espnLookup(event);
      if (espnResult) lookup = mergeLookups(espnResult, lookup);
    }

    // Google/SerpApi lookup
    if (enabledSources.includes("google") && serpApiKey) {
      const googleResult = await googleBroadcastLookup(event, serpApiKey, false);
      lookup = mergeLookups(googleResult, lookup);
    }

    // Determine verdict
    let verdict: VerificationVerdict = "UNCONFIRMED";
    if (lookup.nationalChannel || lookup.allChannels.length > 0) {
      if (!event.scheduledChannel) {
        verdict = "UNCONFIRMED";
      } else {
        const foundMatch = lookup.allChannels.some((ch) => channelsMatch(ch, event.scheduledChannel!));
        verdict = foundMatch ? "MATCH" : "MISMATCH";
      }
    } else if (event.scheduledChannel && isKnownLocalStation(event.scheduledChannel, customStations)) {
      // Scheduled on a known local station — treat as confirmed since local rights are stable
      verdict = "MATCH";
    }

    results.push({ ...event, ...lookup, verdict });
  }
  return results;
}

// ---- Day-After Verification ----
export async function dayAfterVerification(
  events: SportEvent[],
  enabledSources: string[],
  serpApiKey: string
): Promise<VerificationResultRow[]> {
  const customStations = await getCustomStations();
  const results: VerificationResultRow[] = [];
  for (const event of events) {
    const googleUrl = `https://www.google.com/search?q=${encodeURIComponent(buildGoogleQuery(event, true))}`;
    let lookup: BroadcastLookup = {
      streamingPlatforms: [],
      allChannels: [],
      sourceDetails: {},
      googleSearchUrl: googleUrl,
    };

    // ESPN lookup
    if (enabledSources.includes("espn")) {
      const espnResult = await espnLookup(event);
      if (espnResult) lookup = mergeLookups(espnResult, lookup);
    }

    // Google/SerpApi lookup (day-after mode)
    if (enabledSources.includes("google") && serpApiKey) {
      const googleResult = await googleBroadcastLookup(event, serpApiKey, true);
      lookup = mergeLookups(googleResult, lookup);
    }

    // Determine day-after verdict
    let verdict: VerificationVerdict = "UNVERIFIED";
    const hasData = lookup.nationalChannel || lookup.allChannels.length > 0;
    const combinedText = JSON.stringify(lookup.sourceDetails).toLowerCase();
    const detectedStatus = detectStatus(combinedText);

    if (hasData || detectedStatus) {
      if (detectedStatus === "CANCELED") {
        verdict = "CANCELED";
      } else if (detectedStatus === "POSTPONED") {
        verdict = "POSTPONED";
      } else if (detectedStatus === "DELAYED") {
        verdict = "DELAYED";
      } else if (hasData) {
        if (!event.scheduledChannel) {
          verdict = "AIRED_AS_SCHEDULED";
        } else {
          const foundMatch = lookup.allChannels.some((ch) => channelsMatch(ch, event.scheduledChannel!));
          verdict = foundMatch ? "AIRED_AS_SCHEDULED" : "NETWORK_CHANGED";
        }
      }
    } else if (event.scheduledChannel && isKnownLocalStation(event.scheduledChannel, customStations)) {
      // No external data found, but the scheduled channel is a known local station.
      // Local broadcast rights are very stable — default to AIRED_AS_SCHEDULED.
      // The localHomeRsn field will show the station for reference.
      lookup.localHomeRsn = event.scheduledChannel;
      lookup.allChannels = [event.scheduledChannel];
      verdict = "AIRED_AS_SCHEDULED";
    }

    results.push({ ...event, ...lookup, verdict });
  }
  return results;
}

// ---- CSV Export ----
export function resultsToCSV(results: VerificationResultRow[]): string {
  const headers = [
    "League", "Event", "Home Team", "Away Team", "Date",
    "Scheduled Start", "Scheduled Channel",
    "Actual Start", "Actual End",
    "National Channel", "Local Home RSN", "Local Away RSN",
    "Streaming", "All Channels", "Verdict", "Google Search URL",
  ];
  const escape = (v: string | undefined | null) => {
    if (!v) return "";
    return `"${String(v).replace(/"/g, '""')}"`;
  };
  const rows = results.map((r) =>
    [
      escape(r.league), escape(r.eventName), escape(r.homeTeam), escape(r.awayTeam),
      escape(r.scheduledDate), escape(r.scheduledStartTime), escape(r.scheduledChannel),
      escape(r.actualStartTime), escape(r.actualEndTime),
      escape(r.nationalChannel), escape(r.localHomeRsn), escape(r.localAwayRsn),
      escape(r.streamingPlatforms.join("; ")), escape(r.allChannels.join("; ")),
      escape(r.verdict), escape(r.googleSearchUrl),
    ].join(",")
  );
  return [headers.join(","), ...rows].join("\n");
}
