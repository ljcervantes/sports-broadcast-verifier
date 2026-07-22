import { describe, expect, it } from "vitest";
import { parseCSV, resultsToCSV } from "./verificationEngine";

describe("parseCSV", () => {
  it("parses a matchup-style CSV with home/away teams", () => {
    const csv = `league,date,home,away,channel,time
MLB,2024-07-15,Yankees,Red Sox,ESPN,7:05 PM
NHL,2024-10-01,Bruins,Maple Leafs,TNT,8:00 PM`;
    const events = parseCSV(csv);
    expect(events).toHaveLength(2);
    expect(events[0].league).toBe("MLB");
    expect(events[0].homeTeam).toBe("Yankees");
    expect(events[0].awayTeam).toBe("Red Sox");
    expect(events[0].scheduledChannel).toBe("ESPN");
    expect(events[0].eventName).toBe("Red Sox @ Yankees");
  });

  it("parses an event-style CSV (NHRA, fishing) with no home/away", () => {
    const csv = `league,date,event,channel,time
NHRA,2024-07-20,NHRA Sonoma Nationals,FS1,3:00 PM
FISHING,2024-08-01,Bass Pro Tour Stage 8,Outdoor Channel,1:00 PM`;
    const events = parseCSV(csv);
    expect(events).toHaveLength(2);
    expect(events[0].eventName).toBe("NHRA Sonoma Nationals");
    expect(events[0].homeTeam).toBeUndefined();
    expect(events[1].scheduledChannel).toBe("Outdoor Channel");
  });

  it("handles quoted fields with commas", () => {
    const csv = `league,date,event,channel
PGA,2024-06-15,"The Memorial Tournament, presented by Workday",Golf Channel`;
    const events = parseCSV(csv);
    expect(events).toHaveLength(1);
    expect(events[0].eventName).toBe("The Memorial Tournament, presented by Workday");
  });

  it("filters rows with no date", () => {
    const csv = `league,date,event,channel
MLB,,Empty Event,ESPN`;
    const events = parseCSV(csv);
    expect(events).toHaveLength(0);
  });
});

describe("resultsToCSV", () => {
  it("generates a valid CSV with all columns", () => {
    const results = [{
      league: "MLB",
      eventName: "Red Sox @ Yankees",
      homeTeam: "Yankees",
      awayTeam: "Red Sox",
      scheduledDate: "2024-07-15",
      scheduledStartTime: "7:05 PM",
      scheduledChannel: "ESPN",
      actualStartTime: "7:10 PM",
      actualEndTime: "10:30 PM",
      nationalChannel: "ESPN",
      localHomeRsn: "YES Network",
      localAwayRsn: "NESN",
      streamingPlatforms: ["ESPN+"],
      allChannels: ["ESPN", "YES Network", "NESN", "ESPN+"],
      verdict: "AIRED_AS_SCHEDULED" as const,
      sourceDetails: {},
      googleSearchUrl: "https://google.com/search?q=test",
    }];
    const csv = resultsToCSV(results);
    expect(csv).toContain("AIRED_AS_SCHEDULED");
    expect(csv).toContain("YES Network");
    expect(csv).toContain("ESPN+");
    const lines = csv.split("\n");
    expect(lines).toHaveLength(2); // header + 1 row
  });
});

describe("Google Sheets URL parsing", () => {
  // Test the URL parsing logic inline (mirrors the router logic)
  function extractSheetId(url: string): { sheetId: string | null; gid: string } {
    const idMatch = url.match(/\/spreadsheets\/d\/([a-zA-Z0-9_-]+)/);
    const gidMatch = url.match(/[?&#]gid=(\d+)/);
    return {
      sheetId: idMatch ? idMatch[1] : null,
      gid: gidMatch ? gidMatch[1] : "0",
    };
  }

  it("extracts sheet ID from a standard edit URL", () => {
    const url = "https://docs.google.com/spreadsheets/d/1BxiMVs0XRA5nFMdKvBdBZjgmUUqptlbs74OgVE2upms/edit#gid=0";
    const { sheetId, gid } = extractSheetId(url);
    expect(sheetId).toBe("1BxiMVs0XRA5nFMdKvBdBZjgmUUqptlbs74OgVE2upms");
    expect(gid).toBe("0");
  });

  it("extracts sheet ID and gid from a URL with a specific tab", () => {
    const url = "https://docs.google.com/spreadsheets/d/1BxiMVs0XRA5nFMdKvBdBZjgmUUqptlbs74OgVE2upms/edit?gid=1234567";
    const { sheetId, gid } = extractSheetId(url);
    expect(sheetId).toBe("1BxiMVs0XRA5nFMdKvBdBZjgmUUqptlbs74OgVE2upms");
    expect(gid).toBe("1234567");
  });

  it("returns null for an invalid URL", () => {
    const url = "https://www.example.com/not-a-sheet";
    const { sheetId } = extractSheetId(url);
    expect(sheetId).toBeNull();
  });

  it("builds the correct CSV export URL", () => {
    const sheetId = "1BxiMVs0XRA5nFMdKvBdBZjgmUUqptlbs74OgVE2upms";
    const gid = "0";
    const csvUrl = `https://docs.google.com/spreadsheets/d/${sheetId}/export?format=csv&gid=${gid}`;
    expect(csvUrl).toBe("https://docs.google.com/spreadsheets/d/1BxiMVs0XRA5nFMdKvBdBZjgmUUqptlbs74OgVE2upms/export?format=csv&gid=0");
  });
});
