// Locker and marketplace calls. The catalog itself lives in catalog.ts.

import type { EarnedAchievement } from "./achievements";
import type { Account } from "./auth";
import type { CatalogItem } from "./catalog";
import type { AvatarConfig } from "./types";

export interface Locker {
  user: Account;
  owned: string[]; // bought
  unlocked: string[]; // earned in Academia at this level and prestige
}

export interface Milestone {
  at: number;
  item: CatalogItem;
  unlocked: boolean;
}

export interface Road {
  user: Account;
  levels: Milestone[];
  prestige: Milestone[];
  reserved: CatalogItem[];
}

async function call<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, { credentials: "same-origin", ...init });
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

const json = (method: string, body: unknown): RequestInit => ({
  method,
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify(body),
});

export const fetchLocker = () => call<Locker>("/api/locker");
export const fetchRoad = () => call<Road>("/api/academia");
/** A purchase: the locker afterwards, and any spending or collecting achievement it earned. */
export type Purchase = Locker & { achievements: EarnedAchievement[] };

export const buyItem = (item_id: string) => call<Purchase>("/api/shop/buy", json("POST", { item_id }));
export const buyBundle = (bundle_id: string) =>
  call<Purchase>("/api/shop/buy-bundle", json("POST", { bundle_id }));
export const saveAvatar = (avatar: AvatarConfig) =>
  call<{ user: Account }>("/api/avatar", json("PUT", { avatar }));
