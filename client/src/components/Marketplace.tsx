import { useEffect, useState } from "react";
import { Avatar } from "../avatar/Avatar";
import { bundlePrice, earnedLabel, useCatalog, type CatalogBundle, type CatalogItem } from "../lib/catalog";
import { earnedLine, type EarnedAchievement } from "../lib/achievements";
import { buyBundle, buyItem, fetchLocker, saveAvatar, type Locker } from "../lib/shop";
import styles from "../styles.module.css";
import { BookLoader } from "./BookLoader";
import { BundleCard, Coins, ItemCard } from "./ItemTile";

const RARITY_ORDER = { common: 0, rare: 1, epic: 2, legendary: 3, mythical: 4 };

/** A purchase notice, plus any spending or collecting achievement it just earned. */
const withAchievements = (notice: string, earned: EarnedAchievement[] = []) =>
  earned.length ? `${notice} Achievement unlocked: ${earnedLine(earned)}.` : notice;
const BUNDLES_TAB = "bundles";

interface MarketplaceProps {
  /** Smaller header, for the phone's in-game view. */
  compact?: boolean;
  /** Called after an equip is saved, so a game screen can refresh the seat's look. */
  onAvatarSaved?: () => void;
}

/** The marketplace body: slot tabs, bundles, and cards to buy or equip. */
export function Marketplace({ compact = false, onAvatarSaved }: MarketplaceProps) {
  const catalog = useCatalog();
  const [locker, setLocker] = useState<Locker | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [tab, setTab] = useState("all");
  const [busy, setBusy] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  useEffect(() => {
    fetchLocker()
      .then(setLocker)
      .catch((caught: Error) => setError(caught.message));
  }, []);

  if (error) {
    return (
      <>
        <p className={styles.empty}>{error} The marketplace needs a signed-in account.</p>
        <a className={styles.quietLink} href="/">
          Go to the main menu
        </a>
      </>
    );
  }
  if (!catalog || !locker) return <BookLoader label="Opening the marketplace" />;

  const owned = new Set(locker.owned);
  const unlocked = new Set(locker.unlocked);
  const avatar = locker.user.avatar;
  const balance = locker.user.coins;
  const forSale = catalog.slots.filter((entry) =>
    catalog.items.some((item) => item.slot === entry.id && !item.free),
  );
  // Banners lead the slot tabs, right after Bundles.
  const slots = [
    ...forSale.filter((entry) => entry.id === "banner"),
    ...forSale.filter((entry) => entry.id !== "banner"),
  ];
  const items = catalog.items
    .filter((item) => !item.free && (tab === "all" || item.slot === tab))
    // What's for sale first; the earned banners close the list as a reminder of Academia.
    .sort(
      (a, b) =>
        Number(a.earned) - Number(b.earned) ||
        RARITY_ORDER[a.rarity] - RARITY_ORDER[b.rarity] ||
        a.price - b.price,
    );

  async function attempt(key: string, action: () => Promise<string>) {
    setBusy(key);
    try {
      setNotice(await action());
    } catch (caught) {
      setNotice(caught instanceof Error ? caught.message : "That didn't go through.");
    } finally {
      setBusy(null);
    }
  }

  const buy = (item: CatalogItem) =>
    attempt(item.id, async () => {
      const result = await buyItem(item.id);
      setLocker(result);
      return withAchievements(`${item.name} is yours.`, result.achievements);
    });

  const equip = (item: CatalogItem) =>
    attempt(item.id, async () => {
      const { user } = await saveAvatar({ ...avatar, [item.slot]: item.id });
      setLocker((current) => (current ? { ...current, user } : current));
      onAvatarSaved?.();
      return `Wearing ${item.name}.`;
    });

  const buyWholeBundle = (bundle: CatalogBundle) =>
    attempt(bundle.id, async () => {
      const result = await buyBundle(bundle.id);
      setLocker(result);
      return withAchievements(
        `The ${bundle.name} bundle is yours. Equip it in the locker room.`,
        result.achievements,
      );
    });

  const needMore = (price: number) => `Need ${price - balance} more`;

  return (
    <>
      <section className={`${styles.panel} ${styles.shopHead}`}>
        <Avatar avatar={avatar} size={compact ? 48 : 64} label="Your avatar" />
        <div>
          {compact ? (
            <h2 className={styles.panelTitle}>Marketplace</h2>
          ) : (
            <h1 className={styles.heading}>Marketplace</h1>
          )}
          <p className={styles.empty}>
            You have <Coins amount={balance} />. Coins come from playing; the best banners are
            earned in{" "}
            <a className={styles.inlineLink} href="/academia">
              Academia
            </a>
            .
          </p>
        </div>
      </section>

      <div className={styles.slotTabs} role="tablist">
        {[{ id: "all", label: "All" }, { id: BUNDLES_TAB, label: "Bundles" }, ...slots].map((entry) => (
          <button
            key={entry.id}
            type="button"
            role="tab"
            aria-selected={tab === entry.id}
            className={`${styles.slotTab} ${tab === entry.id ? styles.slotTabActive : ""}`}
            onClick={() => setTab(entry.id)}
          >
            {entry.label}
          </button>
        ))}
      </div>

      {notice && (
        <p className={styles.notice} role="status">
          {notice}
        </p>
      )}

      {tab === BUNDLES_TAB ? (
        <div className={styles.itemGrid}>
          {catalog.bundles.map((bundle) => {
            const price = bundlePrice(bundle, catalog, owned);
            const complete = bundle.items.every((id) => owned.has(id));
            return (
              <BundleCard key={bundle.id} bundle={bundle} catalog={catalog} base={avatar} price={price}>
                {complete ? (
                  <span className={styles.cardState}>Owned</span>
                ) : (
                  <button
                    type="button"
                    className={`${styles.button} ${styles.primary} ${styles.cardButton}`}
                    disabled={busy === bundle.id || balance < price}
                    onClick={() => buyWholeBundle(bundle)}
                  >
                    {balance >= price ? "Buy bundle" : needMore(price)}
                  </button>
                )}
              </BundleCard>
            );
          })}
        </div>
      ) : (
        <div className={styles.itemGrid}>
          {items.map((item) => {
            const isOwned = owned.has(item.id) || unlocked.has(item.id);
            const worn = avatar[item.slot] === item.id;
            return (
              <ItemCard
                key={item.id}
                item={item}
                base={avatar}
                name={locker.user.name}
                prestige={locker.user.prestige}
              >
                {worn ? (
                  <span className={styles.cardState}>Wearing it</span>
                ) : item.earned && !isOwned ? (
                  <span className={styles.cardState}>
                    {item.unlock
                      ? `Unlocks at ${earnedLabel(item).toLowerCase()}`
                      : item.source === "achievement"
                        ? "Won with an achievement"
                        : "Not yet winnable"}
                  </span>
                ) : isOwned ? (
                  <button
                    type="button"
                    className={`${styles.button} ${styles.cardButton}`}
                    disabled={busy === item.id}
                    onClick={() => equip(item)}
                  >
                    Equip
                  </button>
                ) : (
                  <button
                    type="button"
                    className={`${styles.button} ${styles.primary} ${styles.cardButton}`}
                    disabled={busy === item.id || balance < item.price}
                    onClick={() => buy(item)}
                  >
                    {balance >= item.price ? "Buy" : needMore(item.price)}
                  </button>
                )}
              </ItemCard>
            );
          })}
        </div>
      )}
    </>
  );
}
