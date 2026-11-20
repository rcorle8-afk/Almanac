import { useEffect, useRef, useState } from "react";
import { Avatar } from "../avatar/Avatar";
import { NameCard } from "../components/NameCard";
import { BookLoader } from "../components/BookLoader";
import { Brand } from "../components/TopBar";
import { Badge } from "../components/Badge";
import { Bell } from "../components/Bell";
import { HandlePanel, PushPanel } from "../components/ProfileSettings";
import { TIER_LABEL, type HeldBadge } from "../lib/achievements";
import { fetchProfile, saveBio, signOut, type Profile as ProfileData } from "../lib/auth";
import { pointsClass, signedPoints } from "../lib/format";
import styles from "../styles.module.css";

function day(iso: string) {
  return new Date(iso).toLocaleDateString(undefined, { month: "short", day: "numeric" });
}

const BADGES_SHOWN = 12;
const BIO_LIMIT = 160;
const BUBBLE_WIDTH = 210;
const BUBBLE_SECONDS = 2.4;

interface Bubble {
  key: string;
  badge: HeldBadge;
  left: number; // within the shelf, kept inside its edges
  top: number; // the tapped badge's top edge, within the shelf
  caret: number; // where the pointer sits along the bubble
}

/** Earned badges, hardest first. Tapping one shows a small bubble with what it's for, which
 *  fades on its own after a moment (or on the next tap anywhere). */
export function BadgeShelf({ badges }: { badges: HeldBadge[] }) {
  const shelf = useRef<HTMLDivElement>(null);
  const [bubble, setBubble] = useState<Bubble | null>(null);

  useEffect(() => {
    if (!bubble) return;
    const timer = window.setTimeout(() => setBubble(null), BUBBLE_SECONDS * 1000);
    const away = (event: PointerEvent) => {
      if (!(event.target as Element).closest?.("[data-badge]")) setBubble(null);
    };
    document.addEventListener("pointerdown", away);
    return () => {
      window.clearTimeout(timer);
      document.removeEventListener("pointerdown", away);
    };
  }, [bubble]);

  function show(badge: HeldBadge, key: string, button: HTMLButtonElement) {
    if (bubble?.key === key) return setBubble(null);
    const box = shelf.current!.getBoundingClientRect();
    const spot = button.getBoundingClientRect();
    const width = Math.min(BUBBLE_WIDTH, box.width);
    const centre = spot.left + spot.width / 2 - box.left;
    const left = Math.min(Math.max(centre - width / 2, 0), box.width - width);
    setBubble({ key, badge, left, top: spot.top - box.top, caret: centre - left });
  }

  return (
    <div ref={shelf} className={styles.badgeShelf}>
      {badges.slice(0, BADGES_SHOWN).map((badge) => {
        const key = `${badge.id}-${badge.tier}`;
        return (
          <button
            key={key}
            type="button"
            data-badge
            className={styles.badgeButton}
            aria-expanded={bubble?.key === key}
            onClick={(event) => show(badge, key, event.currentTarget)}
          >
            <Badge icon={badge.icon} tier={badge.tier} size={40} label={`${badge.name}, ${TIER_LABEL[badge.tier]}`} />
          </button>
        );
      })}
      {badges.length > BADGES_SHOWN && <span className={styles.rowMuted}>+{badges.length - BADGES_SHOWN}</span>}
      {bubble && (
        <span
          key={bubble.key}
          role="tooltip"
          className={styles.badgeBubble}
          style={{
            left: bubble.left,
            top: bubble.top,
            width: Math.min(BUBBLE_WIDTH, shelf.current?.clientWidth ?? BUBBLE_WIDTH),
            animationDuration: `${BUBBLE_SECONDS}s`,
            ["--caret" as string]: `${bubble.caret}px`,
          }}
        >
          <strong>{bubble.badge.name}</strong>
          <span className={`${styles.tierTag} ${styles[`tier_${bubble.badge.tier}`]}`}>
            {TIER_LABEL[bubble.badge.tier]}
          </span>
          <span className={styles.badgeBubbleText}>{bubble.badge.requirement}</span>
        </span>
      )}
    </div>
  );
}

/** A short line about yourself: shown here, edited in place. The server trims it and refuses a
 *  few words (server/moderation.py). */
function BioPanel({ bio, hidden, onSaved }: { bio: string; hidden: boolean; onSaved: (bio: string) => void }) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(bio);
  const [problem, setProblem] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  async function save() {
    setSaving(true);
    setProblem(null);
    try {
      const user = await saveBio(draft);
      onSaved(user.bio);
      setEditing(false);
    } catch (caught) {
      setProblem(caught instanceof Error ? caught.message : "Couldn't save that.");
    } finally {
      setSaving(false);
    }
  }

  if (!editing) {
    return (
      <section className={styles.panel} aria-label="Bio">
        <div className={styles.roadHead}>
          <h2 className={styles.panelTitle}>Bio</h2>
          <button
            type="button"
            className={styles.linkButton}
            onClick={() => {
              setDraft(bio);
              setEditing(true);
            }}
          >
            {bio ? "Edit" : "Add a bio"}
          </button>
        </div>
        <p className={bio ? styles.bioText : styles.empty}>{bio || "A line about you and how you trade."}</p>
        {hidden && <p className={styles.notice}>Someone reported your bio, so others can't see it until it's reviewed.</p>}
      </section>
    );
  }
  return (
    <section className={styles.panel} aria-label="Bio">
      <h2 className={styles.panelTitle}>Bio</h2>
      <textarea
        className={styles.bioInput}
        value={draft}
        maxLength={BIO_LIMIT}
        rows={3}
        autoFocus
        onChange={(event) => setDraft(event.target.value)}
      />
      <div className={styles.bioFoot}>
        <span className={styles.rowMuted}>
          {draft.length} / {BIO_LIMIT}
        </span>
        <div className={styles.buttonRow}>
          <button type="button" className={styles.button} onClick={() => setEditing(false)}>
            Cancel
          </button>
          <button
            type="button"
            className={`${styles.button} ${styles.primary}`}
            disabled={saving}
            onClick={save}
          >
            Save
          </button>
        </div>
      </div>
      {problem && <p className={styles.notice}>{problem}</p>}
    </section>
  );
}

export function Profile() {
  const [profile, setProfile] = useState<ProfileData | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetchProfile()
      .then(setProfile)
      .catch((caught: Error) => setError(caught.message));
  }, []);

  if (error) {
    return (
      <main className={styles.narrowPage}>
        <Brand home="social" />
        <p className={styles.empty}>{error}</p>
        <a className={styles.quietLink} href="/">
          Back to the main menu
        </a>
      </main>
    );
  }
  if (!profile) return <BookLoader label="Opening your almanac" />;

  const { user } = profile;
  const stats: [string, string | number][] = [
    ["Games", profile.games],
    ["Wins", profile.wins],
    ["Points", signedPoints(profile.total_points)],
    ["Best Quotes", profile.best_quotes],
    ["Trades", profile.trades],
    ["Prestige", user.prestige],
  ];
  // XP inside the current level, as a share of the way to the next one.
  const levelFloor = 100 * (user.level - 1) ** 2;
  const progress = Math.min(1, (user.xp - levelFloor) / Math.max(1, user.next_level_xp - levelFloor));

  return (
    <main className={styles.narrowPage}>
      <div className={styles.pageNav}>
        <Brand home="social" />
        <Bell />
      </div>
      <header className={styles.profileHead}>
        <Avatar avatar={user.avatar} size={72} label="Your avatar" />
        <div>
          <h1 className={styles.profileName}>
            <NameCard name={user.name} banner={user.avatar.banner} prestige={user.prestige} />
          </h1>
          <p className={styles.empty}>
            {user.handle ? `@${user.handle} · ` : ""}
            {user.email}
          </p>
          <p className={styles.pageLinks} style={{ margin: "6px 0 0" }}>
            <a href="/locker" style={{ marginLeft: 0 }}>
              Locker room
            </a>
            <a href="/shop">Marketplace</a>
            <a href="/academia">Academia</a>
          </p>
        </div>
      </header>

      {/* What other players see of you; your email and coins are never part of it. */}
      <a className={`${styles.button} ${styles.buttonLink}`} href={`/u/${user.public_id}`}>
        View your public profile
      </a>

      <BioPanel bio={user.bio} hidden={user.bio_hidden} onSaved={(bio) => setProfile({ ...profile, user: { ...user, bio } })} />
      <HandlePanel handle={user.handle} onSaved={(handle) => setProfile({ ...profile, user: { ...user, handle } })} />

      <section className={styles.panel} aria-label="Badges">
        <div className={styles.roadHead}>
          <h2 className={styles.panelTitle}>Badges</h2>
          <a className={styles.inlineLink} href="/profile/achievements">
            All achievements
          </a>
        </div>
        {profile.badges.length === 0 ? (
          <p className={styles.empty}>No badges yet. Win rounds, quote tight, and see what you can earn.</p>
        ) : (
          <BadgeShelf badges={profile.badges} />
        )}
      </section>

      <section className={styles.levelPanel} aria-label="Level">
        <div className={styles.levelHead}>
          <span className={styles.coinsLabel}>LEVEL {user.level}</span>
          <span className={styles.empty}>
            {user.xp} / {user.next_level_xp} XP
          </span>
        </div>
        <div className={styles.levelTrack}>
          <div className={styles.levelBar} style={{ width: `${progress * 100}%` }} />
        </div>
        <span className={styles.empty}>
          XP for every game played; prestige ({user.prestige}) for wins, podiums and Best Quotes.
          Both unlock banners in{" "}
          <a className={styles.inlineLink} href="/academia">
            Academia
          </a>
          .
        </span>
      </section>

      <section className={styles.coinsPanel}>
        <span className={styles.coinsLabel}>COINS</span>
        <span className={styles.coinsValue}>{user.coins}</span>
        <span className={styles.empty}>
          Earned by playing. Spend them in the{" "}
          <a className={styles.inlineLink} href="/shop">
            marketplace
          </a>
          .
        </span>
      </section>

      <section className={styles.statGrid} aria-label="Lifetime stats">
        {stats.map(([label, value]) => (
          <div key={label} className={styles.statTile}>
            <span className={styles.statValue}>{value}</span>
            <span className={styles.statLabel}>{label}</span>
          </div>
        ))}
      </section>

      <section className={styles.panel}>
        <div className={styles.roadHead}>
          <h2 className={styles.panelTitle}>Recent games · tap one for its log</h2>
          {profile.games > profile.recent.length && (
            <a className={styles.inlineLink} href="/profile/games">
              All {profile.games} games
            </a>
          )}
        </div>
        {profile.recent.length === 0 ? (
          <p className={styles.empty}>
            No games yet. Finish a game while signed in and it shows up here.
          </p>
        ) : (
          <div className={styles.rows}>
            <div className={`${styles.gameRow} ${styles.scoreHead}`}>
              <span>Date</span>
              <span>Room</span>
              <span>Place</span>
              <span>Points</span>
              <span>Coins</span>
            </div>
            {/* Each game opens its log: the table, the rounds and your trades. */}
            {profile.recent.map((game) => (
              <a
                key={game.game_id}
                href={`/profile/games/${game.game_id}`}
                className={`${styles.gameRow} ${styles.gameLink}`}
              >
                <span className={styles.rowMuted}>{day(game.ended_at)}</span>
                <span>{game.room_code}</span>
                <span>
                  {game.rank}
                  <span className={styles.rowMuted}>/{game.player_count}</span>
                </span>
                <span className={pointsClass(Number(game.points), styles)}>
                  {signedPoints(game.points)}
                </span>
                <span className={styles.gain}>+{game.coins}</span>
              </a>
            ))}
          </div>
        )}
      </section>

      <PushPanel />

      <div className={styles.actions}>
        <a className={`${styles.button} ${styles.primary} ${styles.buttonLink}`} href="/">
          Join a game
        </a>
        <button
          type="button"
          className={styles.button}
          onClick={() => signOut().then(() => location.assign("/"))}
        >
          Sign out
        </button>
      </div>
    </main>
  );
}
