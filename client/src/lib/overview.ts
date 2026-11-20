// The overview page (/admin/overview): how Almanac is put together, what it runs on and what is
// planned, for admins and the teammates they've added (server/overview.py).

export type GoalStatus = "done" | "in_progress" | "ongoing" | "planned" | "not_started" | "untracked";
export type PageAccess = "everyone" | "signed_in" | "team" | "admin";

export interface Part {
  name: string;
  about: string;
  where: string;
}

/** One band of the structure chart; `link` is what joins it to the band under it. */
export interface Layer {
  id: string;
  name: string;
  about: string;
  parts: Part[];
  link: string;
}

export interface Goal {
  section: string;
  goal: string;
  depth: number; // 2 is a goal under another
  parent: string | null;
  order: number;
  status: GoalStatus;
  note: string;
  milestone: string;
  since: string;
}

export interface Milestone {
  id: string;
  name: string;
  status: "done" | "in_progress" | "planned" | "not_started";
  shipped: string;
  summary: string;
  open: string; // what is still to do in it
}

export interface Service {
  service: string;
  category: string;
  role: string;
  setup: string;
  since: string;
  pricing: string;
  link: string;
}

export interface Switch {
  name: string;
  on: boolean;
  expected: boolean; // how the live site should be set
  about: string;
}

export interface Person {
  name: string | null; // null: that email hasn't signed in yet
  email?: string; // admins only
}

export interface Overview {
  viewer: { admin: boolean };
  status: {
    started_at: string;
    uptime_seconds: number;
    build: string | null;
    rooms: number;
    rooms_in_play: number;
    people_at_tables: number;
    accounts: number;
    games: number;
    questions_playable: number;
    questions_in_bank: number;
    database_bytes: number | null;
    admins: number;
    teammates: number;
    switches: Switch[];
  };
  layers: Layer[];
  pages: { path: string; name: string; about: string; access: PageAccess }[];
  modules: { name: string; about: string; lines: number | null }[];
  client: { name: string; about: string }[];
  tables: { name: string; about: string; rows: number }[];
  team: { admins: Person[]; teammates: Person[]; admin_count: number; teammate_count: number };
  plans_as_of: string | null; // when the plans, services and versions below were last written
  principles: string[];
  milestones: Milestone[];
  goals: Goal[];
  timeline: { date: string; title: string; detail: string }[];
  services: Service[];
  costs: { item: string; service: string; basis: string; monthly_max_usd: number }[];
  cost_summary: { monthly_max_usd: number; fly_waiver_usd: number; revenue_usd: number; prices_checked: string } | null;
  stack: { layer: string; tool: string; version: string; role: string }[];
  project: { date: string; goals_done: number; goals_total: number; tests: number; code_files: number; code_lines: number } | null;
}

export async function fetchOverview(): Promise<Overview> {
  const response = await fetch("/api/admin/overview", { credentials: "same-origin", cache: "no-store" });
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
