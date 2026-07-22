import { eq, desc, and } from "drizzle-orm";
import { drizzle } from "drizzle-orm/mysql2";
import {
  InsertUser, users,
  leagues, InsertLeague, League,
  verificationRuns, InsertVerificationRun, VerificationRun,
  verificationResults, InsertVerificationResult, VerificationResult,
  appSettings,
} from "../drizzle/schema";
import { ENV } from "./_core/env";

let _db: ReturnType<typeof drizzle> | null = null;

export async function getDb() {
  if (!_db && process.env.DATABASE_URL) {
    try {
      _db = drizzle(process.env.DATABASE_URL);
    } catch (error) {
      console.warn("[Database] Failed to connect:", error);
      _db = null;
    }
  }
  return _db;
}

export async function upsertUser(user: InsertUser): Promise<void> {
  if (!user.openId) throw new Error("User openId is required for upsert");
  const db = await getDb();
  if (!db) return;
  const values: InsertUser = { openId: user.openId };
  const updateSet: Record<string, unknown> = {};
  const textFields = ["name", "email", "loginMethod"] as const;
  for (const field of textFields) {
    const value = user[field];
    if (value === undefined) continue;
    const normalized = value ?? null;
    values[field] = normalized;
    updateSet[field] = normalized;
  }
  if (user.lastSignedIn !== undefined) {
    values.lastSignedIn = user.lastSignedIn;
    updateSet.lastSignedIn = user.lastSignedIn;
  }
  if (user.role !== undefined) {
    values.role = user.role;
    updateSet.role = user.role;
  } else if (user.openId === ENV.ownerOpenId) {
    values.role = "admin";
    updateSet.role = "admin";
  }
  if (!values.lastSignedIn) values.lastSignedIn = new Date();
  if (Object.keys(updateSet).length === 0) updateSet.lastSignedIn = new Date();
  await db.insert(users).values(values).onDuplicateKeyUpdate({ set: updateSet });
}

export async function getUserByOpenId(openId: string) {
  const db = await getDb();
  if (!db) return undefined;
  const result = await db.select().from(users).where(eq(users.openId, openId)).limit(1);
  return result.length > 0 ? result[0] : undefined;
}

// ---- Leagues ----
export async function getLeagues(): Promise<League[]> {
  const db = await getDb();
  if (!db) return [];
  return db.select().from(leagues).orderBy(leagues.name);
}

export async function addLeague(data: InsertLeague): Promise<void> {
  const db = await getDb();
  if (!db) return;
  await db.insert(leagues).values(data);
}

export async function updateLeague(id: number, data: Partial<InsertLeague>): Promise<void> {
  const db = await getDb();
  if (!db) return;
  await db.update(leagues).set(data).where(eq(leagues.id, id));
}

export async function deleteLeague(id: number): Promise<void> {
  const db = await getDb();
  if (!db) return;
  await db.delete(leagues).where(eq(leagues.id, id));
}

// ---- Verification Runs ----
export async function createVerificationRun(data: InsertVerificationRun): Promise<number> {
  const db = await getDb();
  if (!db) throw new Error("DB not available");
  const result = await db.insert(verificationRuns).values(data);
  return (result[0] as any).insertId as number;
}

export async function getVerificationRuns(limit = 50): Promise<VerificationRun[]> {
  const db = await getDb();
  if (!db) return [];
  return db.select().from(verificationRuns).orderBy(desc(verificationRuns.createdAt)).limit(limit);
}

export async function getVerificationRun(id: number): Promise<VerificationRun | undefined> {
  const db = await getDb();
  if (!db) return undefined;
  const result = await db.select().from(verificationRuns).where(eq(verificationRuns.id, id)).limit(1);
  return result[0];
}

export async function updateRunTotal(id: number, total: number): Promise<void> {
  const db = await getDb();
  if (!db) return;
  await db.update(verificationRuns).set({ totalEvents: total }).where(eq(verificationRuns.id, id));
}

// ---- Verification Results ----
export async function saveVerificationResults(rows: InsertVerificationResult[]): Promise<void> {
  const db = await getDb();
  if (!db) return;
  if (rows.length === 0) return;
  for (const row of rows) {
    await db.insert(verificationResults).values(row);
  }
}

export async function getResultsByRun(runId: number): Promise<VerificationResult[]> {
  const db = await getDb();
  if (!db) return [];
  return db.select().from(verificationResults).where(eq(verificationResults.runId, runId));
}

// ---- Settings ----
// Retrieve the user-defined custom local station list (comma-separated call signs)
export async function getCustomStations(): Promise<string[]> {
  const raw = await getSetting("custom_stations");
  if (!raw) return [];
  return raw
    .split(",")
    .map((s) => s.trim().toUpperCase())
    .filter(Boolean);
}

export async function getSetting(key: string): Promise<string | null> {
  const db = await getDb();
  if (!db) return null;
  const result = await db.select().from(appSettings).where(eq(appSettings.key, key)).limit(1);
  return result[0]?.value ?? null;
}

export async function setSetting(key: string, value: string): Promise<void> {
  const db = await getDb();
  if (!db) return;
  await db.insert(appSettings).values({ key, value }).onDuplicateKeyUpdate({ set: { value } });
}

export async function getAllSettings(): Promise<Record<string, string>> {
  const db = await getDb();
  if (!db) return {};
  const rows = await db.select().from(appSettings);
  return Object.fromEntries(rows.map(r => [r.key, r.value ?? ""]));
}
