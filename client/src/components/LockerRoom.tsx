import { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";
import { Avatar } from "../avatar/Avatar";
import { useCatalog, type CatalogSlot } from "../lib/catalog";
import { fetchLocker, saveAvatar, type Locker } from "../lib/shop";
import styles from "../styles.module.css";
import { BookLoader } from "./BookLoader";
import { Coins, ItemPreview, rarityStyle } from "./ItemTile";
import { NameCard } from "./NameCard";

// The preview card collapses as the page scrolls: it keeps its height in the page (so nothing
// below it moves or leaves a gap), its top slides under the edge of the screen, and the avatar
// and name glide into a slim row that stays pinned. These set that row.
const PINNED_HEIGHT = 76; // the strip still showing once it has collapsed
const PAD = 14; // the card's padding
const PINNED_AVATAR = 60;
const PINNED_NAME_SCALE = 0.9;

/** Moves a node from its place in the open card toward a target centre and scale, by p (0-1).
 *  offsetLeft/Top ignore transforms, so the open position is always known. */
function glide(node: HTMLElement | null, p: number, cx: number, cy: number, scale: number) {
  if (!node) return;
  const x = node.offsetLeft + node.offsetWidth / 2;
  const y = node.offsetTop + node.offsetHeight / 2;
  node.style.transform =
    p > 0 ? `translate(${(cx - x) * p}px, ${(cy - y) * p}px) scale(${1 + (scale - 1) * p})` : "";
}

interface LockerRoomProps {
  /** Smaller preview and no page title, for the phone's in-game view. */
  compact?: boolean;
  /** Called after a change is saved, so a game screen can refresh the seat's look. */
  onAvatarSaved?: () => void;
}

/** The locker room body: the player's avatar and every part they can wear, by slot. */
export function LockerRoom({ compact = false, onAvatarSaved }: LockerRoomProps) {
  const catalog = useCatalog();
  const [locker, setLocker] = useState<Locker | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [status, setStatus] = useState<string | null>(null);
  const card = useRef<HTMLElement>(null);
  const avatarBox = useRef<HTMLDivElement>(null);
  const nameRow = useRef<HTMLDivElement>(null);
  const note = useRef<HTMLParagraphElement>(null);
  const heading = useRef<HTMLHeadingElement>(null);
  const coins = useRef<HTMLParagraphElement>(null);
  // How far the card's top may slide off the screen: its height less the pinned strip.
  const [collapse, setCollapse] = useState(0);
  const ready = catalog !== null && locker !== null;

  useEffect(() => {
    fetchLocker()
      .then(setLocker)
      .catch((caught: Error) => setError(caught.message));
  }, []);

  // One frame of the collapse: how far it has gone (p), and everything placed to match.
  const frame = useCallback(() => {
    const el = card.current;
    if (!el) return;
    const height = el.offsetHeight;
    const p = Math.min(1, Math.max(0, -el.getBoundingClientRect().top / Math.max(1, height - PINNED_HEIGHT)));
    const cy = height - PINNED_HEIGHT / 2; // the middle of the strip that stays
    const avatarWidth = avatarBox.current?.offsetWidth || PINNED_AVATAR;
    glide(avatarBox.current, p, PAD + PINNED_AVATAR / 2, cy, PINNED_AVATAR / avatarWidth);
    const rowLeft = PAD + PINNED_AVATAR + 12;
    const rowWidth = (nameRow.current?.offsetWidth ?? 0) * PINNED_NAME_SCALE;
    glide(nameRow.current, p, rowLeft + rowWidth / 2, cy, PINNED_NAME_SCALE);
    const noteWidth = (note.current?.offsetWidth ?? 0) * 0.9;
    glide(note.current, p, rowLeft + rowWidth + 12 + noteWidth / 2, cy, 0.9);
    const fade = String(Math.max(0, 1 - p / 0.15)); // gone before the avatar passes over them
    if (heading.current) heading.current.style.opacity = fade;
    if (coins.current) coins.current.style.opacity = fade;
    el.classList.toggle(styles.lockerStuck, p >= 0.999);
  }, []);

  useEffect(() => {
    if (!ready) return;
    let queued = 0;
    const onScroll = () => {
      if (!queued)
        queued = requestAnimationFrame(() => {
          queued = 0;
          frame();
        });
    };
    window.addEventListener("scroll", onScroll, { passive: true });
    window.addEventListener("resize", onScroll);
    return () => {
      window.removeEventListener("scroll", onScroll);
      window.removeEventListener("resize", onScroll);
      cancelAnimationFrame(queued);
    };
  }, [ready, frame]);

  useLayoutEffect(() => {
    const el = card.current;
    if (!el) return;
    const next = Math.max(0, el.offsetHeight - PINNED_HEIGHT);
    if (next !== collapse) setCollapse(next);
    frame();
  });

  if (error) {
    return (
      <>
        <p className={styles.empty}>{error} The locker room needs a signed-in account.</p>
        <a className={styles.quietLink} href="/">
          Go to the main menu
        </a>
      </>
    );
  }
  if (!catalog || !locker) return <BookLoader label="Opening your locker" />;

  const owned = new Set([...locker.owned, ...locker.unlocked]); // bought, or earned in Academia
  const avatar = locker.user.avatar;

  async function wear(slot: string, itemId: string | null) {
    const next = { ...avatar, [slot]: itemId };
    setLocker((current) => (current ? { ...current, user: { ...current.user, avatar: next } } : current));
    try {
      const { user } = await saveAvatar(next);
      setLocker((current) => (current ? { ...current, user } : current));
      setStatus("Saved");
      onAvatarSaved?.();
    } catch (caught) {
      setStatus(caught instanceof Error ? caught.message : "Couldn't save that.");
      setLocker((current) => (current ? { ...current, user: { ...current.user, avatar } } : current));
    }
  }

  function options(slot: CatalogSlot) {
    return catalog!.items.filter((item) => item.slot === slot.id && (item.free || owned.has(item.id)));
  }

  return (
    <div className={styles.lockerBody}>
      <section ref={card} className={`${styles.panel} ${styles.lockerPreview}`} style={{ top: -collapse }}>
        <div ref={avatarBox} className={styles.lockerAvatar}>
          <Avatar avatar={avatar} size={compact ? 112 : 160} label="Your avatar" />
        </div>
        <div className={styles.lockerIdentity}>
          {!compact && (
            <h1 ref={heading} className={styles.heading}>
              Locker room
            </h1>
          )}
          {/* Exactly what other players see: the name on its banner, prestige beside it. */}
          <div ref={nameRow} className={styles.lockerNameRow}>
            <NameCard name={locker.user.name} banner={avatar.banner} prestige={locker.user.prestige} />
          </div>
          <p ref={coins} className={styles.empty}>
            <Coins amount={locker.user.coins} />
            {!compact && (
              <>
                {" · "}
                <a className={styles.inlineLink} href="/shop">
                  get more in the marketplace
                </a>
                {" · "}
                <a className={styles.inlineLink} href="/academia">
                  Academia
                </a>
              </>
            )}
          </p>
          {/* Always in the layout, so a "Saved" never changes the card's height. */}
          <p ref={note} className={styles.notice} role="status">
            {status}
          </p>
        </div>
      </section>

      {catalog.slots.map((slot) => (
        <section key={slot.id} className={styles.panel}>
          <h2 className={styles.panelTitle}>{slot.label}</h2>
          <div className={styles.optionRow}>
            {slot.optional && (
              <button
                type="button"
                className={`${styles.optionTile} ${avatar[slot.id] === null ? styles.optionTileActive : ""}`}
                onClick={() => wear(slot.id, null)}
              >
                <span className={styles.optionNone}>–</span>
                <span className={styles.optionLabel}>None</span>
              </button>
            )}
            {options(slot).map((item) => (
              <button
                key={item.id}
                type="button"
                className={`${styles.optionTile} ${avatar[slot.id] === item.id ? styles.optionTileActive : ""} ${item.rarity === "mythical" ? styles.mythicalCard : ""}`}
                style={rarityStyle(item.rarity, item.free)}
                aria-pressed={avatar[slot.id] === item.id}
                onClick={() => wear(slot.id, item.id)}
              >
                <ItemPreview item={item} base={avatar} size={48} name={locker.user.name} />
                <span className={styles.optionLabel}>{item.name}</span>
              </button>
            ))}
          </div>
        </section>
      ))}
    </div>
  );
}
