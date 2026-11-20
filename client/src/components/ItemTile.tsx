import type { CSSProperties, ReactNode } from "react";
import { Avatar } from "../avatar/Avatar";
import { earnedLabel, type Catalog, type CatalogBundle, type CatalogItem, type Rarity } from "../lib/catalog";
import type { AvatarConfig } from "../lib/types";
import styles from "../styles.module.css";
import { Banner } from "./Banner";
import { NameCard } from "./NameCard";

export const RARITY_COLORS: Record<Rarity, string> = {
  common: "#3d8bff",
  rare: "#ff8c1a",
  epic: "#a855f7",
  legendary: "#f5c242",
  mythical: "#8b5cf6",
};

const SWATCH_SLOTS = new Set(["skin", "hair_color", "eyes"]);

export function rarityStyle(rarity: Rarity, free = false): CSSProperties {
  return { "--rarity": free ? "var(--line-strong)" : RARITY_COLORS[rarity] } as CSSProperties;
}

/** What an item looks like: a swatch for colors, otherwise the item worn on the given avatar. */
export function ItemPreview({
  item,
  base,
  size,
  name = "Your name",
  prestige = null,
}: {
  item: CatalogItem;
  base: AvatarConfig;
  size: number;
  /** The name and prestige a banner preview carries: the player's own, as others will see them. */
  name?: string;
  prestige?: number | null;
}) {
  if (item.slot === "banner") {
    // A small locker tile shows a thumbnail of the art; everywhere else shows the real name card.
    if (size < 64) {
      return (
        <Banner id={item.id} className={styles.bannerTile}>
          {name}
        </Banner>
      );
    }
    return <NameCard name={name} banner={item.id} prestige={prestige} />;
  }
  if (item.color && SWATCH_SLOTS.has(item.slot)) {
    const background =
      item.color === "rainbow"
        ? "linear-gradient(135deg, #ef4444, #f59e0b, #22c55e, #3b82f6, #a855f7)"
        : item.color;
    return <span className={styles.swatch} style={{ width: size * 0.5, height: size * 0.5, background }} />;
  }
  return <Avatar avatar={{ ...base, [item.slot]: item.id }} size={size} label={item.name} />;
}

export function Coins({ amount }: { amount: number }) {
  return (
    <span className={styles.price}>
      <span className={styles.coin} aria-hidden="true" />
      {amount}
    </span>
  );
}

function cardClass(rarity: Rarity) {
  return `${styles.itemCard} ${rarity === "mythical" ? styles.mythicalCard : ""}`;
}

interface ItemCardProps {
  item: CatalogItem;
  base: AvatarConfig;
  /** The name and prestige a banner preview carries. */
  name?: string;
  prestige?: number | null;
  children?: ReactNode;
}

export function ItemCard({ item, base, name, prestige, children }: ItemCardProps) {
  return (
    <div className={cardClass(item.rarity)} style={rarityStyle(item.rarity, item.free)}>
      <div className={styles.itemPreview}>
        <ItemPreview item={item} base={base} size={88} name={name} prestige={prestige} />
      </div>
      <div className={styles.itemName}>{item.name}</div>
      <div className={styles.itemMeta}>
        <span className={styles.rarityTag}>{item.rarity}</span>
        {item.earned ? <span className={styles.earnedTag}>{earnedLabel(item)}</span> : <Coins amount={item.price} />}
      </div>
      {children}
    </div>
  );
}

/** Everything in the bundle worn at once on the player's own avatar. */
export function bundleLook(bundle: CatalogBundle, catalog: Catalog, base: AvatarConfig): AvatarConfig {
  const look = { ...base };
  for (const id of bundle.items) {
    const item = catalog.byId[id];
    if (item) look[item.slot] = id;
  }
  return look;
}

interface BundleCardProps {
  bundle: CatalogBundle;
  catalog: Catalog;
  base: AvatarConfig;
  price: number;
  children?: ReactNode;
}

export function BundleCard({ bundle, catalog, base, price, children }: BundleCardProps) {
  const names = bundle.items.map((id) => catalog.byId[id]?.name ?? id).join(", ");
  return (
    <div className={cardClass(bundle.rarity)} style={rarityStyle(bundle.rarity)}>
      <div className={styles.itemPreview}>
        <Avatar avatar={bundleLook(bundle, catalog, base)} size={88} label={bundle.name} />
      </div>
      <div className={styles.itemName}>{bundle.name} bundle</div>
      <p className={styles.bundleItems}>{names}</p>
      <div className={styles.itemMeta}>
        <span className={styles.rarityTag}>{bundle.rarity}</span>
        {price === 0 ? (
          <Coins amount={bundle.full_price} />
        ) : (
          <span className={styles.price}>
            {price < bundle.full_price && <span className={styles.wasPrice}>{bundle.full_price}</span>}
            <span className={styles.coin} aria-hidden="true" />
            {price}
          </span>
        )}
      </div>
      {children}
    </div>
  );
}
