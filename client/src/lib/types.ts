// Mirrors server/protocol.py by hand; keep in sync. Prices and points are strings because the
// server keeps them as Decimals.

import type { EarnedAchievement } from "./achievements";

/** An end-of-game superlative: who did the most of something this game. Ties share it. */
export interface GameAward {
  id: string; // best_quotes, biggest_round, most_trades
  title: string;
  detail: string;
  winners: string[]; // seat ids
  names: string[];
}

export type Side = "BUY" | "SELL";

export type Phase =
  | "LOBBY"
  | "QUESTION"
  | "QUOTING"
  | "TRADING"
  | "REVEAL"
  | "SCORES"
  | "GAME_OVER";

export interface Level {
  price: string;
  size: number;
}

export interface Book {
  bids: Level[];
  asks: Level[];
}

export interface Order {
  id: string;
  player_id: string;
  side: Side;
  price: string;
  size: number;
  remaining: number;
  seq: number;
}

export interface Quote {
  player_id: string;
  bid: string;
  ask: string;
  submitted_at: number;
}

export interface Question {
  text: string;
  unit: string;
  tick: string;
  kind: "standard" | "case";
  context: string | null; // a case question's setup, shown above the question
  multiplier: string; // the round's points multiplier: "1" for standard, 1.5 to 2.5 for a case
  answer: string | null;
  source_url: string | null;
  source_note: string | null;
}

export interface TapeEntry {
  seq: number;
  price: string;
  size: number;
  buyer: string;
  seller: string;
}

/** One of your own fills this round, from your side of the trade. */
export interface YourFill {
  seq: number;
  side: Side;
  price: string;
  size: number;
  counterparty: string;
}

export interface You {
  player_id: string;
  position: number;
  resting_orders: Order[];
  quote: Quote | null;
  round_points: string | null;
  total_points: string;
  coins_awarded: number | null;
  xp_awarded: number | null;
  prestige_awarded: number | null;
  level_up: number | null; // the new level, when this game crossed one
  achievements: EarnedAchievement[]; // tiers this game earned, set at GAME_OVER
  fills: YourFill[];
  sitting_out: boolean; // joined mid-round; plays from the next question
  group_invites: TableInvite[]; // the host's group invites of this table you haven't answered
}

/** A card that pops up on your phone: the host invited this table to one of their groups. */
export interface TableInvite {
  group: string; // the group's public id
  name: string;
  host: string; // the inviting host's name
  sign_in_first: boolean; // a guest signs in, then accepts
  // The group as a stranger sees it, so the card shows what's on offer.
  icon: { glyph: string; color: string; image: string | null } | null;
  member_count: number;
  prestige: number;
}

/** The account signed in on the host screen. It hosts as itself and takes no seat, so the same
 *  account can also sit down and play from a phone. */
export interface HostView {
  name: string;
  avatar: AvatarConfig | null;
  level: number | null;
  prestige: number | null;
  public_id: string | null;
}

/** Slot id -> item id. Optional slots hold null. Guests have no avatar at all. */
export type AvatarConfig = Record<string, string | null>;

export interface Player {
  id: string;
  name: string;
  connected: boolean;
  quoted: boolean;
  signed_in: boolean;
  avatar: AvatarConfig | null;
  total_points: string;
  round_points: string | null;
  drinks: number | null; // drinks mode: this round's drinks once settled
  drinks_total: number;
  bot: boolean;
  level: number | null; // the account's standing; null for guests and bots
  prestige: number | null;
  public_id: string | null; // the account's link id: its profile and Add friend (M5)
}

export interface GameState {
  type: "state";
  room_code: string;
  phase: Phase;
  // Everyone seated. On a phone, `players` holds only the top ten plus you; the host gets all.
  player_count: number;
  round_no: number;
  rounds_total: number;
  timer_ends_at: number | null;
  phase_seconds: number | null; // this phase's full length; a case question's run longer
  hint_at: number | null; // epoch ms the hint is due, only while one is still to come
  server_now: number;
  question: Question | null;
  // A range that holds the answer, or for a case question a sentence with a related figure.
  hint: { low: string | null; high: string | null; text: string | null } | null;
  book: Book;
  tape: TapeEntry[];
  you: You | null;
  players: Player[];
  best_quote: { name: string; bid: string; ask: string } | null;
  awards: GameAward[]; // end-of-game superlatives, only at GAME_OVER
  group: { public_id: string; name: string } | null; // a members-only room's group
  host: HostView | null; // who is hosting, when the host screen is signed in
  invites:{ group: string; name: string; invited: number; joined: number }[]; // table invites so far
  live: { starts_at: number | null; cancelled: boolean } | null; // only on the nightly live room (M6)
  endless: boolean; // the endless table (M6): no last round (rounds_total is 0), paid every round
  config: {
    rounds: number;
    position_limit: number;
    scoring: "log" | "linear";
    timers: {
      question: number;
      quoting: number;
      trading: number;
      reveal: number;
      scores: number;
      case_question: number; // a case question's QUESTION and TRADING phases run on these
      case_trading: number;
    };
    hint_seconds_left: number;
    recall_on_start: boolean;
    drinks: boolean;
    drink_strength: number;
    max_players: number;
    categories: string[] | null;
    case_mode: "extra" | "default" | "off"; // any round, the last three, or none
  };
}

export type ServerMessage =
  | GameState
  | { type: "hosted"; room_code: string; token: string }
  | { type: "joined"; room_code: string; player_id: string; token: string }
  | { type: "error"; code: string; message: string }
  | { type: "notice"; message: string };

export type ClientMessage =
  | { type: "host_create"; config?: Record<string, never>; group?: string }
  | { type: "host_group_invite"; group: string }
  | { type: "answer_group_invite"; group: string; accept: boolean }
  | { type: "host_resume"; room_code: string; token: string }
  | {
      type: "host_configure";
      recall_on_start?: boolean;
      drinks?: boolean;
      drink_strength?: number;
      max_players?: number;
      categories?: string[] | null;
      rounds?: number;
      timers?: Partial<GameState["config"]["timers"]>;
      hint_seconds_left?: number;
      position_limit?: number;
      case_mode?: GameState["config"]["case_mode"];
    }
  | { type: "host_bots"; count: number; level: number }
  | { type: "host_demo" }
  | { type: "host_restart" }
  | { type: "host_start" }
  | { type: "host_advance" }
  | { type: "host_end" }
  | { type: "host_skip_round" }
  | { type: "join"; room_code: string; name: string; token: string | null }
  | { type: "submit_quote"; bid: string; ask: string }
  | { type: "place_order"; side: Side; price: string; size: number }
  | { type: "cancel_order"; order_id: string };
