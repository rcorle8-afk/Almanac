// The endless table (M6): server/endless.py's /api/open.

import type { AvatarConfig } from "./types";

export interface BoardRow {
  place: number;
  name: string;
  public_id: string;
  avatar: AvatarConfig | null;
  points: number;
  rounds: number;
}

export interface Board {
  top: BoardRow[];
  you: BoardRow | null;
  players: number;
}

export interface OpenOverview {
  code: string;
  people: number; // people at the table right now
  bots: number;
  house_traders: number;
  running: boolean;
  round_no: number;
  signed_in: boolean;
  today: Board;
  week: Board;
}

export async function fetchOpen(): Promise<OpenOverview> {
  const response = await fetch("/api/open", { credentials: "same-origin" });
  if (!response.ok) throw new Error("The open table couldn't be loaded.");
  return response.json();
}
