type Verdict =
  | "MATCH" | "MISMATCH" | "UNCONFIRMED"
  | "AIRED_AS_SCHEDULED" | "DELAYED" | "POSTPONED"
  | "CANCELED" | "NETWORK_CHANGED" | "UNVERIFIED";

const VERDICT_CONFIG: Record<Verdict, { label: string; className: string }> = {
  MATCH:              { label: "MATCH",              className: "bg-emerald-500/20 text-emerald-400 border-emerald-500/40" },
  MISMATCH:           { label: "MISMATCH",           className: "bg-red-500/20 text-red-400 border-red-500/40" },
  UNCONFIRMED:        { label: "UNCONFIRMED",        className: "bg-yellow-500/20 text-yellow-400 border-yellow-500/40" },
  AIRED_AS_SCHEDULED: { label: "AIRED_AS_SCHEDULED", className: "bg-emerald-500/20 text-emerald-400 border-emerald-500/40" },
  DELAYED:            { label: "DELAYED",            className: "bg-orange-500/20 text-orange-400 border-orange-500/40" },
  POSTPONED:          { label: "POSTPONED",          className: "bg-red-600/20 text-red-400 border-red-600/40" },
  CANCELED:           { label: "CANCELED",           className: "bg-red-700/30 text-red-300 border-red-700/50" },
  NETWORK_CHANGED:    { label: "NETWORK_CHANGED",    className: "bg-orange-500/20 text-orange-300 border-orange-500/40" },
  UNVERIFIED:         { label: "UNVERIFIED",         className: "bg-yellow-600/20 text-yellow-500 border-yellow-600/40" },
};

export function VerdictBadge({ verdict }: { verdict: string }) {
  const config = VERDICT_CONFIG[verdict as Verdict] ?? {
    label: verdict,
    className: "bg-muted text-muted-foreground border-border",
  };
  return (
    <span
      className={`inline-flex items-center px-2 py-0.5 rounded text-[10px] font-bold tracking-wide border font-mono ${config.className}`}
    >
      {config.label}
    </span>
  );
}

export function getRowClass(verdict: string): string {
  const map: Record<string, string> = {
    MATCH:              "border-l-2 border-emerald-500",
    MISMATCH:           "border-l-2 border-red-500 bg-red-950/20",
    UNCONFIRMED:        "border-l-2 border-yellow-500 bg-yellow-950/20",
    AIRED_AS_SCHEDULED: "border-l-2 border-emerald-500",
    DELAYED:            "border-l-2 border-orange-500 bg-orange-950/20",
    POSTPONED:          "border-l-2 border-red-600 bg-red-950/30",
    CANCELED:           "border-l-2 border-red-700 bg-red-950/40",
    NETWORK_CHANGED:    "border-l-2 border-orange-400 bg-orange-950/20",
    UNVERIFIED:         "border-l-2 border-yellow-600 bg-yellow-950/20",
  };
  return map[verdict] ?? "";
}
