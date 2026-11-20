// The cosmetics catalog from /api/catalog, fetched once and shared by every avatar on the page.

import { useEffect, useSyncExternalStore } from "react";

export type Rarity = "common" | "rare" | "epic" | "legendary" | "mythical";

export interface CatalogItem {
  id: string;
  slot: string;
  name: string;
  free: boolean;
  color: string | null;
  index: number;
  motion: number;
  rarity: Rarity;
  price: number;
  // Earned items are never for sale: they unlock in Academia, or are reserved for
  // tournament and live-game winners.
  earned: boolean;
  unlock: { kind: "level" | "prestige"; at: number } | null;
  source: "tournament" | "live" | "achievement" | null;
  scores: { coverage: number; attention: number; novelty: number };
}

/** How an earned item is won, for cards and the road. */
export function earnedLabel(item: CatalogItem): string {
  if (item.unlock) return item.unlock.kind === "level" ? `Level ${item.unlock.at}` : `${item.unlock.at} prestige`;
  if (item.source === "tournament") return "Tournament reward";
  if (item.source === "live") return "Live game reward";
  if (item.source === "achievement") return "Achievement reward";
  return "";
}

export interface CatalogSlot {
  id: string;
  label: string;
  optional: boolean;
}

export interface CatalogBundle {
  id: string;
  name: string;
  blurb: string;
  items: string[];
  full_price: number;
  price: number;
  rarity: Rarity;
}

export interface Catalog {
  slots: CatalogSlot[];
  items: CatalogItem[];
  bundles: CatalogBundle[];
  bundle_discount: number;
  rarity_colors: Record<Rarity, string>;
  welcome_coins: number;
  byId: Record<string, CatalogItem>;
}

/** Mirrors Bundle.price_for on the server: the discount applies to whatever you don't own. */
export function bundlePrice(bundle: CatalogBundle, catalog: Catalog, owned: Set<string>) {
  const missing = bundle.items.filter((id) => !owned.has(id));
  const sum = missing.reduce((total, id) => total + (catalog.byId[id]?.price ?? 0), 0);
  return Math.round((catalog.bundle_discount * sum) / 5) * 5;
}

let catalog: Catalog | null = null;
let loading: Promise<Catalog> | null = null;
const listeners = new Set<() => void>();

export function loadCatalog(): Promise<Catalog> {
  loading ??= fetch("/api/catalog")
    .then((response) => response.json())
    .then((raw: Omit<Catalog, "byId">) => {
      catalog = { ...raw, byId: Object.fromEntries(raw.items.map((item) => [item.id, item])) };
      listeners.forEach((listener) => listener());
      return catalog;
    })
    .catch((error) => {
      loading = null;
      throw error;
    });
  return loading;
}

function subscribe(listener: () => void) {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

export function useCatalog(): Catalog | null {
  useEffect(() => {
    loadCatalog().catch(() => undefined);
  }, []);
  return useSyncExternalStore(subscribe, () => catalog);
}
