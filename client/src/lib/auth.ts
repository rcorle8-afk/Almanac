// Accounts: /api/me, /api/config, /api/profile, sign-in and sign-out, and the Google button.

import type { HeldBadge } from "./achievements";
import { disablePush } from "./push";
import type { AvatarConfig } from "./types";

export interface Account {
  id: number;
  name: string;
  email: string;
  picture: string;
  coins: number;
  avatar: AvatarConfig;
  xp: number;
  prestige: number;
  level: number;
  next_level_xp: number;
  bio: string;
  bio_hidden: boolean; // reported, hidden from others until it's reviewed (M5)
  public_id: string; // the link id others see; never the database id
  handle: string | null; // searchable, shown with an @
  friend_code: string;
  admin?: boolean; // only from /api/me: opens the report review page
  team?: boolean; // only from /api/me: may open the players page (admins, and teammates they add)
}

export interface AuthConfig {
  google_client_id: string;
  dev_login: boolean;
}

export interface RecentGame {
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
}

export interface Profile {
  user: Account;
  games: number;
  wins: number;
  best_quotes: number;
  trades: number;
  total_points: string;
  recent: RecentGame[];
  badges: HeldBadge[]; // achievement tiers held, hardest first
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

function post<T>(path: string, body: unknown): Promise<T> {
  return call<T>(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

export const fetchConfig = () => call<AuthConfig>("/api/config");
export const fetchMe = async () => (await call<{ user: Account | null }>("/api/me")).user;
export const fetchProfile = () => call<Profile>("/api/profile");
export const saveBio = async (bio: string) =>
  (
    await call<{ user: Account }>("/api/profile/bio", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ bio }),
    })
  ).user;
// A phone that signs out stops getting this account's notifications before the session ends.
export const signOut = async () => {
  await disablePush().catch(() => undefined);
  return post<{ user: null }>("/api/auth/logout", {});
};
export const signInWithGoogle = async (credential: string) =>
  (await post<{ user: Account }>("/api/auth/google", { credential })).user;
export const devSignIn = async (name: string) =>
  (await post<{ user: Account }>("/api/auth/dev", { name })).user;

interface GoogleIdentity {
  initialize(config: { client_id: string; callback: (response: { credential: string }) => void }): void;
  renderButton(element: HTMLElement, options: Record<string, string | number>): void;
}

declare global {
  interface Window {
    google?: { accounts: { id: GoogleIdentity } };
  }
}

const GOOGLE_SCRIPT = "https://accounts.google.com/gsi/client";
let googleLoading: Promise<GoogleIdentity> | null = null;

/** Loads Google's sign-in script once and resolves with its API. */
export function loadGoogle(): Promise<GoogleIdentity> {
  if (window.google) return Promise.resolve(window.google.accounts.id);
  googleLoading ??= new Promise((resolve, reject) => {
    const script = document.createElement("script");
    script.src = GOOGLE_SCRIPT;
    script.async = true;
    script.onload = () => resolve(window.google!.accounts.id);
    script.onerror = () => {
      googleLoading = null;
      reject(new Error("Google sign-in didn't load. Check your connection and try again."));
    };
    document.head.append(script);
  });
  return googleLoading;
}
