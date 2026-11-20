// The nightly live game (M6): server/live.py's /api/live.

import type { AvatarConfig } from "./types";

export interface LiveRow {
  name: string;
  public_id: string | null;
  avatar: AvatarConfig | null;
  prestige: number | null;
}

export interface LiveOverview {
  on: boolean;
  zone: string; // "ET"
  hour: number; // 21
  rounds: number;
  lobby_minutes: number;
  next_start: number; // epoch ms
  room: {
    code: string;
    phase: string;
    round_no: number;
    rounds_total: number;
    players: number;
    starts_at: number | null;
    cancelled: boolean;
  } | null;
  signed_in: boolean;
  last: { ended_at: string; rounds: number; players: number; table: (LiveRow & { place: number; points: string })[] } | null;
  standings: (LiveRow & { games: number; wins: number; points: number })[];
}

export async function fetchLive(): Promise<LiveOverview> {
  const response = await fetch("/api/live", { credentials: "same-origin" });
  if (!response.ok) throw new Error("The live game couldn't be loaded.");
  return response.json();
}
