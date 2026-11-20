// The players page (/admin/players): every signed-in account with its standing and record,
// for admins and the teammates they've given view access (server/players.py).

import type { AvatarConfig } from "./types";

export interface PlayerRow {
  public_id: string;
  name: string;
  handle: string | null;
  avatar: AvatarConfig | null;
  joined: string; // ISO time the account was made
  last_played: string | null; // the latest game or open-table round; null if never
  level: number;
  xp: number;
  prestige: number;
  coins: number;
  games: number; // hosted and live games; open-table rounds are counted apart
  wins: number;
  podiums: number;
  best_quotes: number;
  trades: number;
  points: number;
  live_games: number;
  open_rounds: number;
  coins_spent: number;
  items: number;
  badges: number;
  friends: number;
  groups: string[];
  // Admins only; a teammate's rows don't carry them.
  email?: string;
  flag?: "open" | "cleared" | "confirmed" | null;
}

export interface PlayersReport {
  viewer: { admin: boolean };
  as_of: string;
  recent_days: number; // what "this week" means in the totals
  summary: {
    accounts: number;
    new_recently: number;
    played_recently: number;
    played_ever: number;
    games: number;
    open_rounds: number;
    coins: number;
  };
  players: PlayerRow[];
}

export interface Teammate {
  email: string;
  added_at: string;
  added_by: string | null;
  account: string | null; // the account that email signs in to, once it has
}

export interface TeamList {
  team: Teammate[];
  admins?: string[];
  max?: number;
}

/** The same table as an Excel file; the browser downloads it. */
export const PLAYERS_FILE = "/api/admin/players.xlsx";

async function call<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, { credentials: "same-origin", cache: "no-store", ...init });
  if (!response.ok) {
    let message = "Something went wrong.";
    try {
      message = (await response.json()).detail ?? message;
    } catch {
      // not JSON; keep the generic message
    }
    throw new Error(message);
  }
  return response.json();
}

export const fetchPlayers = () => call<PlayersReport>("/api/admin/players");
export const fetchTeam = () => call<TeamList>("/api/admin/team");
export const addTeammate = (email: string) =>
  call<TeamList>("/api/admin/team", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email }),
  });
export const removeTeammate = (email: string) =>
  call<TeamList>(`/api/admin/team/${encodeURIComponent(email)}`, { method: "DELETE" });
