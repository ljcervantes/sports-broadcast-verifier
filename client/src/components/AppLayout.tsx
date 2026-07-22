import { useState } from "react";
import { Link, useLocation } from "wouter";
import { trpc } from "@/lib/trpc";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Separator } from "@/components/ui/separator";
import {
  LayoutDashboard, History, Settings,
  Plus, Tv, Search,
  Activity, Shield,
} from "lucide-react";
import AddLeagueDialog from "./AddLeagueDialog";

type Props = {
  children: React.ReactNode;
  selectedLeagues?: string[];
  onLeagueToggle?: (name: string) => void;
  enabledSources?: string[];
  onSourceToggle?: (src: string) => void;
};

const DATA_SOURCES = [
  { id: "mlb", label: "MLB Stats API", icon: Activity },
  { id: "nhl", label: "NHL API", icon: Activity },
  { id: "espn", label: "ESPN", icon: Tv },
  { id: "google", label: "Google Search", icon: Search },
];

export default function AppLayout({
  children,
  selectedLeagues = [],
  onLeagueToggle,
  enabledSources = ["google"],
  onSourceToggle,
}: Props) {
  const [location] = useLocation();
  const [showAddLeague, setShowAddLeague] = useState(false);
  const leaguesQuery = trpc.leagues.list.useQuery();
  const leagues = leaguesQuery.data ?? [];

  const navItems = [
    { href: "/", label: "Dashboard", icon: LayoutDashboard },
    { href: "/history", label: "Run History", icon: History },
    { href: "/settings", label: "Settings", icon: Settings },
  ];

  return (
    <div className="flex min-h-screen bg-background">
      {/* Sidebar */}
      <aside className="w-64 shrink-0 flex flex-col border-r border-border bg-sidebar">
        {/* Logo */}
        <div className="px-4 py-5 border-b border-sidebar-border">
          <div className="flex items-center gap-2">
            <div className="w-8 h-8 rounded-lg bg-primary flex items-center justify-center">
              <Shield className="w-4 h-4 text-primary-foreground" />
            </div>
            <div>
              <p className="text-sm font-bold text-sidebar-foreground leading-tight">Broadcast</p>
              <p className="text-xs text-muted-foreground leading-tight">Verifier</p>
            </div>
          </div>
        </div>

        {/* Navigation */}
        <nav className="px-2 py-3 space-y-0.5">
          {navItems.map((item) => {
            const Icon = item.icon;
            const active = location === item.href;
            return (
              <Link key={item.href} href={item.href}>
                <div
                  className={`flex items-center gap-2.5 px-3 py-2 rounded-md text-sm cursor-pointer transition-colors ${
                    active
                      ? "bg-sidebar-accent text-sidebar-foreground font-medium"
                      : "text-muted-foreground hover:text-sidebar-foreground hover:bg-sidebar-accent/50"
                  }`}
                >
                  <Icon className="w-4 h-4 shrink-0" />
                  {item.label}
                </div>
              </Link>
            );
          })}
        </nav>

        <Separator className="bg-sidebar-border" />

        {/* Data Sources */}
        {onSourceToggle && (
          <div className="px-4 py-3">
            <p className="text-xs font-semibold text-muted-foreground uppercase tracking-wider mb-2">
              Data Sources
            </p>
            <div className="space-y-1.5">
              {DATA_SOURCES.map((src) => {
                const Icon = src.icon;
                const active = enabledSources.includes(src.id);
                return (
                  <button
                    key={src.id}
                    onClick={() => onSourceToggle(src.id)}
                    className={`w-full flex items-center gap-2 px-2 py-1.5 rounded text-xs transition-colors ${
                      active
                        ? "bg-primary/20 text-primary border border-primary/30"
                        : "text-muted-foreground hover:text-foreground hover:bg-accent/50 border border-transparent"
                    }`}
                  >
                    <Icon className="w-3 h-3 shrink-0" />
                    <span className="truncate">{src.label}</span>
                    {active && (
                      <span className="ml-auto w-1.5 h-1.5 rounded-full bg-emerald-400 shrink-0" />
                    )}
                  </button>
                );
              })}
            </div>
          </div>
        )}

        <Separator className="bg-sidebar-border" />

        {/* Leagues */}
        {onLeagueToggle && (
          <div className="px-4 py-3 flex-1 overflow-y-auto">
            <div className="flex items-center justify-between mb-2">
              <p className="text-xs font-semibold text-muted-foreground uppercase tracking-wider">
                Leagues
              </p>
              <button
                onClick={() => setShowAddLeague(true)}
                className="text-muted-foreground hover:text-foreground transition-colors"
                title="Add league"
              >
                <Plus className="w-3.5 h-3.5" />
              </button>
            </div>
            <div className="space-y-0.5">
              {leagues.map((league) => {
                const selected = selectedLeagues.includes(league.name);
                return (
                  <button
                    key={league.id}
                    onClick={() => onLeagueToggle(league.name)}
                    className={`w-full flex items-center gap-2 px-2 py-1.5 rounded text-xs transition-colors text-left ${
                      selected
                        ? "bg-primary/20 text-primary"
                        : "text-muted-foreground hover:text-foreground hover:bg-accent/50"
                    }`}
                  >
                    <span className="truncate font-medium">{league.name}</span>
                    <Badge
                      variant="outline"
                      className={`ml-auto text-[9px] px-1 py-0 h-4 shrink-0 ${
                        league.sportType === "event"
                          ? "border-amber-600/50 text-amber-500"
                          : "border-blue-600/50 text-blue-400"
                      }`}
                    >
                      {league.sportType === "event" ? "EVT" : "MU"}
                    </Badge>
                  </button>
                );
              })}
            </div>
          </div>
        )}

        {/* User */}
        <div className="mt-auto px-4 py-3 border-t border-sidebar-border">
          <p className="text-[10px] text-muted-foreground text-center">Broadcast Verifier v1.0</p>
        </div>
      </aside>

      {/* Main content */}
      <main className="flex-1 overflow-auto">
        {children}
      </main>

      {showAddLeague && (
        <AddLeagueDialog
          open={showAddLeague}
          onClose={() => setShowAddLeague(false)}
          onAdded={() => leaguesQuery.refetch()}
        />
      )}
    </div>
  );
}
