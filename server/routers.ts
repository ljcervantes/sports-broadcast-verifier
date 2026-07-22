import { z } from "zod";
import { COOKIE_NAME } from "@shared/const";
import { getSessionCookieOptions } from "./_core/cookies";
import { systemRouter } from "./_core/systemRouter";
import { publicProcedure, router } from "./_core/trpc";
import {
  getLeagues, addLeague, updateLeague, deleteLeague,
  createVerificationRun, getVerificationRuns, getVerificationRun,
  saveVerificationResults, getResultsByRun, updateRunTotal,
  getSetting, setSetting, getAllSettings,
} from "./db";
import {
  parseCSV, preEventCrossCheck, dayAfterVerification, resultsToCSV,
  VerificationResultRow,
} from "./verificationEngine";

export const appRouter = router({
  system: systemRouter,

  auth: router({
    me: publicProcedure.query((opts) => opts.ctx.user),
    logout: publicProcedure.mutation(({ ctx }) => {
      const cookieOptions = getSessionCookieOptions(ctx.req);
      ctx.res.clearCookie(COOKIE_NAME, { ...cookieOptions, maxAge: -1 });
      return { success: true } as const;
    }),
  }),

  // ---- Leagues ----
  leagues: router({
    list: publicProcedure.query(async () => {
      return getLeagues();
    }),

    add: publicProcedure
      .input(
        z.object({
          name: z.string().min(1).max(64),
          displayName: z.string().min(1).max(128),
          sportType: z.enum(["matchup", "event"]),
        })
      )
      .mutation(async ({ input }) => {
        await addLeague({
          name: input.name.toUpperCase().replace(/\s+/g, "_"),
          displayName: input.displayName,
          sportType: input.sportType,
          enabled: true,
        });
        return { success: true };
      }),

    update: publicProcedure
      .input(
        z.object({
          id: z.number(),
          displayName: z.string().optional(),
          enabled: z.boolean().optional(),
        })
      )
      .mutation(async ({ input }) => {
        const { id, ...data } = input;
        await updateLeague(id, data);
        return { success: true };
      }),

    delete: publicProcedure
      .input(z.object({ id: z.number() }))
      .mutation(async ({ input }) => {
        await deleteLeague(input.id);
        return { success: true };
      }),
  }),

  // ---- Settings ----
  settings: router({
    getAll: publicProcedure.query(async () => {
      return getAllSettings();
    }),

    set: publicProcedure
      .input(z.object({ key: z.string(), value: z.string() }))
      .mutation(async ({ input }) => {
        await setSetting(input.key, input.value);
        return { success: true };
      }),
  }),

  // ---- Google Sheets Import ----
  sheets: router({
    // Fetch a public Google Sheet by shareable URL and return CSV text + parsed events
    import: publicProcedure
      .input(z.object({ url: z.string().url() }))
      .mutation(async ({ input }) => {
        // Convert any Google Sheets share URL to a CSV export URL
        const sheetUrl = input.url.trim();

        // Extract spreadsheet ID from various URL formats:
        // https://docs.google.com/spreadsheets/d/SHEET_ID/edit#gid=0
        // https://docs.google.com/spreadsheets/d/SHEET_ID/pub?...
        // https://docs.google.com/spreadsheets/d/SHEET_ID
        const idMatch = sheetUrl.match(/\/spreadsheets\/d\/([a-zA-Z0-9_-]+)/);
        if (!idMatch) {
          throw new Error(
            "Invalid Google Sheets URL. Please share the sheet and paste the link — it should contain '/spreadsheets/d/'"
          );
        }
        const sheetId = idMatch[1];

        // Extract optional gid (tab/sheet index)
        const gidMatch = sheetUrl.match(/[?&#]gid=(\d+)/);
        const gid = gidMatch ? gidMatch[1] : "0";

        // Build the CSV export URL
        const csvUrl = `https://docs.google.com/spreadsheets/d/${sheetId}/export?format=csv&gid=${gid}`;

        let csvText: string;
        try {
          const resp = await fetch(csvUrl, {
            headers: { "User-Agent": "Mozilla/5.0" },
            signal: AbortSignal.timeout(15000),
          });
          if (!resp.ok) {
            if (resp.status === 403 || resp.status === 401) {
              throw new Error(
                "Access denied. Make sure the sheet is shared as 'Anyone with the link can view', then try again."
              );
            }
            throw new Error(`Google Sheets returned HTTP ${resp.status}. Check the link and sharing settings.`);
          }
          csvText = await resp.text();
        } catch (err: unknown) {
          if (err instanceof Error) throw err;
          throw new Error("Failed to fetch the Google Sheet. Check your internet connection and try again.");
        }

        // Parse the CSV to get events
        const { parseCSV } = await import("./verificationEngine");
        const events = parseCSV(csvText);

        // Try to get the sheet title from the URL or default
        const sheetTitle = `Google Sheet (${events.length} rows)`;

        return {
          csvText,
          events,
          count: events.length,
          sheetTitle,
          sheetId,
          gid,
        };
      }),
  }),

  // ---- Verification ----
  verification: router({
    // Parse CSV and return events without running verification
    parseCSV: publicProcedure
      .input(z.object({ csvText: z.string(), fileName: z.string().optional() }))
      .mutation(async ({ input }) => {
        const events = parseCSV(input.csvText);
        return { events, count: events.length };
      }),

    // Run pre-event cross-check
    runPreEvent: publicProcedure
      .input(
        z.object({
          csvText: z.string(),
          fileName: z.string().optional(),
          enabledSources: z.array(z.string()),
          dateRangeStart: z.string().optional(),
          dateRangeEnd: z.string().optional(),
        })
      )
      .mutation(async ({ ctx, input }) => {
        const serpApiKey = (await getSetting("serpapi_key")) ?? "";
        const events = parseCSV(input.csvText);
        const results = await preEventCrossCheck(events, input.enabledSources, serpApiKey);

        const runId = await createVerificationRun({
          userId: 1,
          runType: "pre_event",
          sourceFile: input.fileName,
          dateRangeStart: input.dateRangeStart,
          dateRangeEnd: input.dateRangeEnd,
          enabledSources: input.enabledSources,
          totalEvents: results.length,
        });

        await saveVerificationResults(
          results.map((r) => ({
            runId,
            league: r.league,
            eventName: r.eventName,
            homeTeam: r.homeTeam,
            awayTeam: r.awayTeam,
            scheduledDate: r.scheduledDate,
            scheduledStartTime: r.scheduledStartTime,
            scheduledChannel: r.scheduledChannel,
            actualStartTime: r.actualStartTime,
            actualEndTime: r.actualEndTime,
            nationalChannel: r.nationalChannel,
            localHomeRsn: r.localHomeRsn,
            localAwayRsn: r.localAwayRsn,
            streamingPlatforms: r.streamingPlatforms,
            allChannels: r.allChannels,
            verdict: r.verdict,
            sourceDetails: r.sourceDetails,
            googleSearchUrl: r.googleSearchUrl,
          }))
        );

        return { runId, results, count: results.length };
      }),

    // Run day-after verification
    runDayAfter: publicProcedure
      .input(
        z.object({
          csvText: z.string(),
          fileName: z.string().optional(),
          enabledSources: z.array(z.string()),
          dateRangeStart: z.string().optional(),
          dateRangeEnd: z.string().optional(),
        })
      )
      .mutation(async ({ ctx, input }) => {
        const serpApiKey = (await getSetting("serpapi_key")) ?? "";
        const events = parseCSV(input.csvText);
        const results = await dayAfterVerification(events, input.enabledSources, serpApiKey);

        const runId = await createVerificationRun({
          userId: 1,
          runType: "day_after",
          sourceFile: input.fileName,
          dateRangeStart: input.dateRangeStart,
          dateRangeEnd: input.dateRangeEnd,
          enabledSources: input.enabledSources,
          totalEvents: results.length,
        });

        await saveVerificationResults(
          results.map((r) => ({
            runId,
            league: r.league,
            eventName: r.eventName,
            homeTeam: r.homeTeam,
            awayTeam: r.awayTeam,
            scheduledDate: r.scheduledDate,
            scheduledStartTime: r.scheduledStartTime,
            scheduledChannel: r.scheduledChannel,
            actualStartTime: r.actualStartTime,
            actualEndTime: r.actualEndTime,
            nationalChannel: r.nationalChannel,
            localHomeRsn: r.localHomeRsn,
            localAwayRsn: r.localAwayRsn,
            streamingPlatforms: r.streamingPlatforms,
            allChannels: r.allChannels,
            verdict: r.verdict,
            sourceDetails: r.sourceDetails,
            googleSearchUrl: r.googleSearchUrl,
          }))
        );

        return { runId, results, count: results.length };
      }),

    // Get past runs
    listRuns: publicProcedure.query(async () => {
      return getVerificationRuns(100);
    }),

    // Get results for a specific run
    getRunResults: publicProcedure
      .input(z.object({ runId: z.number() }))
      .query(async ({ input }) => {
        const run = await getVerificationRun(input.runId);
        const results = await getResultsByRun(input.runId);
        return { run, results };
      }),

    // Export results as CSV text
    exportCSV: publicProcedure
      .input(z.object({ runId: z.number() }))
      .query(async ({ input }) => {
        const results = await getResultsByRun(input.runId);
        const rows: VerificationResultRow[] = results.map((r) => ({
          league: r.league,
          eventName: r.eventName,
          homeTeam: r.homeTeam ?? undefined,
          awayTeam: r.awayTeam ?? undefined,
          scheduledDate: r.scheduledDate,
          scheduledStartTime: r.scheduledStartTime ?? undefined,
          scheduledChannel: r.scheduledChannel ?? undefined,
          actualStartTime: r.actualStartTime ?? undefined,
          actualEndTime: r.actualEndTime ?? undefined,
          nationalChannel: r.nationalChannel ?? undefined,
          localHomeRsn: r.localHomeRsn ?? undefined,
          localAwayRsn: r.localAwayRsn ?? undefined,
          streamingPlatforms: (r.streamingPlatforms as string[]) ?? [],
          allChannels: (r.allChannels as string[]) ?? [],
          verdict: r.verdict,
          sourceDetails: (r.sourceDetails as Record<string, unknown>) ?? {},
          googleSearchUrl: r.googleSearchUrl ?? undefined,
        }));
        return { csv: resultsToCSV(rows), fileName: `verification_run_${input.runId}.csv` };
      }),
  }),
});

export type AppRouter = typeof appRouter;
