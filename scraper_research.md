# Scraper Research Notes

## sportsmediawatch.com
- URL: https://www.sportsmediawatch.com/games-on-tv-today-sports-time-channel/
- Has a dedicated "Sports on TV Today" page with ALL sports for today
- Structure: sport name, team1 vs team2, time (lowercase "pm"), channel(s) comma-separated
- Times are in LOCAL time (lowercase am/pm), need to check if ET
- Covers: MLB, NFL, NBA, NHL, WNBA, MLS, NCAAF, NCAAB, NASCAR, PGA, tennis, boxing, etc.
- VERY valuable — covers niche sports too (canoe slalom, little league, darts, etc.)
- HTML structure: each event is a list item with sport, teams, time, channel
- No date parameter needed — just scrape the "today" page
- For historical verification, there may be archive pages

## espn.com/schedule
- URL pattern: https://www.espn.com/{sport}/schedule/_/date/{YYYYMMDD}
  - MLB: https://www.espn.com/mlb/schedule/_/date/20260722
  - NFL: https://www.espn.com/nfl/schedule/_/date/20260722
  - NBA: https://www.espn.com/nba/schedule/_/date/20260722
  - NHL: https://www.espn.com/nhl/schedule/_/date/20260722
  - WNBA: https://www.espn.com/wnba/schedule/_/date/20260722
  - NCAAF: https://www.espn.com/college-football/schedule/_/date/20260722
  - NCAAB: https://www.espn.com/mens-college-basketball/schedule/_/date/20260722
  - MLS: https://www.espn.com/soccer/schedule/_/league/usa.1/date/20260722
- Structure: Markdown table with MATCHUP | TIME | TV columns
- TV column has channel names like "ESPN", "MLB.TV", "ESPN Unlmtd", "Peacock"
- Times are in ET (already)
- Very clean table format — easy to parse
- Better than the ESPN API for getting channel info (API often returns empty broadcasts)

## 506sports.com
- URL pattern: https://506sports.com/{sport}.php
  - MLB: mlb.php, NFL: nfl.php, NBA: nba.php, NHL: nhl.php, WNBA: wnba.php
- Only covers NATIONAL broadcasts (not all games)
- Times already in ET
- Plain text structure: bold game name, time, channel on separate lines
- Covers current week only

## gameviewingguide.com
- URL: https://gameviewingguide.com/cfb (NCAAF), /cbb (NCAAB)
- JavaScript-rendered grid table — hard to scrape via requests
- Each cell: team @ team, time, channel
- Times in ET
- Only covers CFB and CBB

## streamingtvguides.com
- NOT useful for verification — it's a live TV channel grid (like a cable guide)
- Does not list specific game matchups or scheduled times
- SKIP this one

## Key insight: sportsmediawatch.com "Sports on TV Today" page
- This is the BEST single source for niche sports (NHRA, NASCAR, fishing, PBR, etc.)
- Covers everything in one page
- URL: https://www.sportsmediawatch.com/games-on-tv-today-sports-time-channel/
- Need to handle date: for day-after verification, need to find archive or use date-specific URL
