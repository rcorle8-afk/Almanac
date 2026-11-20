// Achievements (server/achievements.py): types and the /api/achievements call.

import type { Account } from "./auth";

export type Tier = "bronze" | "silver" | "gold" | "platinum" | "mystery";

export const TIER_ORDER: Tier[] = ["bronze", "silver", "gold", "platinum", "mystery"];
export const TIER_LABEL: Record<Tier, string> = {
  bronze: "Bronze",
  silver: "Silver",
  gold: "Gold",
  platinum: "Platinum",
  mystery: "Mystery",
};

/** A tier just earned: on the game-end screen and after a purchase. */
export interface EarnedAchievement {
  id: string;
  name: string;
  icon: string;
  tier: Tier;
  requirement: string;
  reward: string;
}

/** A badge already held, for the profile's showcase. */
export interface HeldBadge {
  id: string;
  name: string;
  icon: string;
  tier: Tier;
  requirement: string;
  earned_at: string;
}

export interface AchievementTier {
  tier: Tier;
  requirement: string; // "???" for a mystery tier not yet earned
  reward: string;
  goal: number | null;
  earned_at: string | null;
}

export interface Achievement {
  id: string;
  name: string;
  icon: string;
  blurb: string;
  progress: number | null; // lifetime stats count toward their goals; per-game ones don't
  tiers: AchievementTier[];
}

export interface AchievementList {
  user: Account;
  new: EarnedAchievement[]; // tiers credited just now, on opening the page
  achievements: Achievement[];
  earned: number;
  total: number;
}

export async function fetchAchievements(): Promise<AchievementList> {
  const response = await fetch("/api/achievements", { credentials: "same-origin" });
  if (!response.ok) throw new Error(response.status === 401 ? "Sign in to see your achievements." : "Something went wrong.");
  return response.json();
}

/** Easiest first, so a list of new tiers builds to the best one. */
export const byTier = <T extends { tier: Tier }>(list: T[]) =>
  [...list].sort((a, b) => TIER_ORDER.indexOf(a.tier) - TIER_ORDER.indexOf(b.tier));

/** "Champion · Silver", for a notice line. */
export const earnedLine = (list: EarnedAchievement[]) =>
  list.map((a) => `${a.name} · ${TIER_LABEL[a.tier]} (${a.reward})`).join("; ");
