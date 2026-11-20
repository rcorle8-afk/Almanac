// The game log: every past game (GET /api/games, paged) and one past game from your side
// (GET /api/games/:id, server Database.game_detail).

import type { Relation } from "./social";
import type { Side } from "./types";

export interface LoggedPlayer {
  name: string;
  rank: number;
  points: string;
  bot: boolean;
  signed_in: boolean;
  you: boolean;
  public_id: string | null; // signed-in players: their profile link
  relation: Relation | null; // how you stand with them, for the Add friend button
}

export interface LoggedFill {
  side: Side;
  price: string;
  size: number;
  counterparty: string;
  points: string; // from your side
}

export interface LoggedRound {
  round_no: number;
  question: string;
  unit: string;
  answer: string;
  fills: LoggedFill[]; // yours only
}

export interface GameDetail {
  game: {
    id: number;
    room_code: string;
    ended_at: string;
    rounds: number;
    player_count: number;
    points: string;
    rank: number;
    coins: number;
    xp: number;
    prestige: number;
  };
  detailed: boolean; // false for games saved before the log kept the table and trades
  players: LoggedPlayer[];
  rounds: LoggedRound[];
}

/** One row of the full history (GET /api/games, server Database.history). */
export interface PastGame {
  game_id: number;
  room_code: string;
  ended_at: string;
  rounds: number;
  player_count: number;
  points: string;
  rank: number;
  coins: number;
  xp: number;
  prestige: number;
  best_quotes: number;
  trades: number;
  winners: string; // "" for games saved before the log kept the table
}

export interface HistoryPage {
  games: PastGame[];
  total: number;
  next: number | null; // pass back as `before` for the next page
}

export function fetchGame(id: string): Promise<GameDetail> {
  return get(`/api/games/${encodeURIComponent(id)}`);
}

export function fetchHistory(before?: number | null): Promise<HistoryPage> {
  return get(before ? `/api/games?before=${before}` : "/api/games");
}

async function get<T>(path: string): Promise<T> {
  const response = await fetch(path, { credentials: "same-origin" });
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
