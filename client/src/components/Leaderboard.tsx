import { useEffect, useState, type CSSProperties, type ReactNode, type RefObject } from "react";
import { Avatar } from "../avatar/Avatar";
import { usePager } from "../lib/pager";
import { fetchLeaderboard, onSocialChange, type Leaderboard, type LeaderboardGroup, type LeaderboardPlayer } from "../lib/social";
import styles from "../styles.module.css";
import { GroupIcon } from "./GroupIcon";
import { Chevron } from "./Icon";

/** The two boards, in swipe order. Groups is where it opens. */
export const BOARDS = ["groups", "players"] as const;
const LABELS = { groups: "Groups", players: "Players" };

/** A prestige count with its four-point star. Shown even at zero, so it's always in one place.
 *  The star and the number are all anyone sees: the social pages never spell the word out, so
 *  what the number is stays a little mysterious (Ryan, Nov 17, 2026). There is no tooltip for the
 *  same reason; the word is only there for a screen reader, which can't see the star. */
export function PrestigeCount({ value }: { value: number }) {
  return (
    <span className={styles.groupPrestige}>
      <svg viewBox="0 0 12 12" aria-hidden="true">
        <path d="M6 0C6.6 3.6 8.4 5.4 12 6C8.4 6.6 6.6 8.4 6 12C5.4 8.4 3.6 6.6 0 6C3.6 5.4 5.4 3.6 6 0Z" />
      </svg>
      {value.toLocaleString()}
      <span className={styles.srOnly}> prestige</span>
    </span>
  );
}

/** Loads the boards, and again whenever the bell changes something (a group joined, say). */
export function useLeaderboard() {
  const [board, setBoard] = useState<Leaderboard | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    const load = () => {
      fetchLeaderboard().then(setBoard, (caught: Error) => setError(caught.message));
    };
    load();
    return onSocialChange(load);
  }, []);
  return { board, error };
}

/** The switch between the two boards, its marker sliding with the swipe like every other tab bar. */
export function BoardTabs({ bar, active, go, small = false }: { bar: RefObject<HTMLElement>; active: number; go: (index: number) => void; small?: boolean }) {
  return (
    <nav
      className={`${styles.menuTabs} ${styles.subTabs} ${small ? styles.boardTabsSmall : ""}`}
      aria-label="Leaderboard"
      ref={bar}
      style={{ "--tabs": BOARDS.length } as CSSProperties}
    >
      <span className={styles.menuTabMarker} aria-hidden="true" />
      {BOARDS.map((id, index) => (
        <button
          key={id}
          type="button"
          className={`${styles.menuTab} ${styles.subTab} ${active === index ? styles.menuTabOn : ""}`}
          aria-current={active === index ? "true" : undefined}
          onClick={() => go(index)}
        >
          {LABELS[id]}
        </button>
      ))}
    </nav>
  );
}

interface Spot {
  key: string;
  href: string;
  place: number;
  name: string;
  prestige: number;
  picture: (size: number) => ReactNode;
}

const groupSpot = (group: LeaderboardGroup): Spot => ({
  key: group.public_id,
  href: `/g/${group.public_id}`,
  place: group.place,
  name: group.name,
  prestige: group.prestige,
  picture: (size) => <GroupIcon icon={group.icon} name={group.name} size={size} />,
});

const playerSpot = (player: LeaderboardPlayer): Spot => ({
  key: player.public_id,
  href: player.you ? "/profile" : `/u/${player.public_id}`,
  place: player.place,
  name: player.name,
  prestige: player.prestige,
  picture: (size) => <Avatar avatar={player.avatar} size={size} label="" />,
});

/** The top three as a podium: first in the middle and a step higher, second on its left, third
 *  on its right. A place nobody holds yet is drawn empty, so the podium keeps its shape. */
function Podium({ spots, empty }: { spots: Spot[]; empty: string }) {
  if (spots.length === 0) return <p className={`${styles.empty} ${styles.podiumEmpty}`}>{empty}</p>;
  const order = [spots[1], spots[0], spots[2]];
  return (
    <div className={styles.podium}>
      {order.map((spot, column) =>
        spot ? (
          <a key={spot.key} className={`${styles.podiumSpot} ${column === 1 ? styles.podiumFirst : ""}`} href={spot.href}>
            <span className={styles.podiumPlace}>{spot.place}</span>
            {spot.picture(column === 1 ? 60 : 48)}
            <span className={styles.podiumName}>{spot.name}</span>
            <PrestigeCount value={spot.prestige} />
          </a>
        ) : (
          <span key={`empty-${column}`} className={`${styles.podiumSpot} ${styles.podiumOpen}`} aria-hidden="true">
            <span className={styles.podiumPlace}>{column === 0 ? 2 : 3}</span>
            <span className={styles.podiumBlank} />
            <span className={styles.podiumName}>Open</span>
          </span>
        ),
      )}
    </div>
  );
}

/** Where you stand on a board, in a line. */
function standing(board: Leaderboard, which: (typeof BOARDS)[number]) {
  if (which === "players") {
    return board.you.place
      ? `You're #${board.you.place} of ${board.player_count.toLocaleString()}`
      : "Win a game or a Best Quote to get on the board";
  }
  const best = board.your_groups[0];
  if (best) return `${best.name} is #${best.place} of ${board.group_count.toLocaleString()}`;
  return "A group is ranked once its members start winning";
}

/**
 * The global leaderboard at the top of the Social screen (Ryan, Nov 12, 2026): the top three
 * groups by their members' combined prestige, and the top three players by their own, as two
 * tabs that slide like the rest of the menu. Under the podium is where you stand, and the way to
 * the whole board. Avatars here hold still, as they do on every leaderboard.
 */
export function LeaderboardCard() {
  const { board } = useLeaderboard();
  const { track, bar, active, go } = usePager(BOARDS.length, 0);
  const which = BOARDS[active];

  return (
    <section className={`${styles.panel} ${styles.boardCard} ${styles.calm}`} aria-label="Leaderboard">
      <div className={styles.boardHead}>
        <h2 className={styles.panelTitle}>Leaderboard</h2>
        <BoardTabs bar={bar} active={active} go={go} small />
      </div>
      <div className={styles.podiumTrack} ref={track}>
        <div className={styles.boardScreen}>
          {board ? <Podium spots={board.groups.slice(0, 3).map(groupSpot)} empty="No group is ranked yet. Win a game and yours is first." /> : <div className={styles.podiumLoading} />}
        </div>
        <div className={styles.boardScreen}>
          {board ? <Podium spots={board.players.slice(0, 3).map(playerSpot)} empty="Nobody is ranked yet. Win a game and you're first." /> : <div className={styles.podiumLoading} />}
        </div>
      </div>
      <a className={styles.boardFoot} href={`/leaderboard${which === "players" ? "#players" : ""}`}>
        <span className={styles.menuRowDetail}>{board ? standing(board, which) : "Finding the leaders…"}</span>
        <span className={styles.boardAll}>
          See all
          <Chevron />
        </span>
      </a>
    </section>
  );
}

/* ---------- The whole board ---------- */

function Place({ value }: { value: number }) {
  return <span className={`${styles.scoreRank} ${value <= 3 ? styles.boardTop : ""}`}>{value}</span>;
}

export function GroupBoard({ board }: { board: Leaderboard }) {
  if (board.groups.length === 0) return <p className={styles.empty}>No group is ranked yet. Win a game and yours is first.</p>;
  return (
    <div className={styles.rows}>
      {board.groups.map((group) => (
        <a key={group.public_id} className={`${styles.rankRow} ${group.role ? styles.scoreYou : ""}`} href={`/g/${group.public_id}`}>
          <Place value={group.place} />
          <GroupIcon icon={group.icon} name={group.name} size={40} />
          <span className={styles.menuRowText}>
            <span className={styles.menuRowTitle}>{group.name}</span>
            <span className={styles.menuRowDetail}>
              {group.member_count} {group.member_count === 1 ? "member" : "members"}
              {group.role ? " · yours" : ""}
            </span>
          </span>
          <PrestigeCount value={group.prestige} />
        </a>
      ))}
    </div>
  );
}

export function PlayerBoard({ board }: { board: Leaderboard }) {
  if (board.players.length === 0) return <p className={styles.empty}>Nobody is ranked yet. Win a game and you're first.</p>;
  return (
    <div className={styles.rows}>
      {board.players.map((player) => (
        <a key={player.public_id} className={`${styles.rankRow} ${player.you ? styles.scoreYou : ""}`} href={player.you ? "/profile" : `/u/${player.public_id}`}>
          <Place value={player.place} />
          <Avatar avatar={player.avatar} size={36} label="" />
          <span className={styles.menuRowText}>
            <span className={styles.menuRowTitle}>{player.you ? `${player.name} (you)` : player.name}</span>
            <span className={styles.menuRowDetail}>
              Level {player.level}
              {player.handle ? ` · @${player.handle}` : ""}
            </span>
          </span>
          <PrestigeCount value={player.prestige} />
        </a>
      ))}
    </div>
  );
}

/** Your own standing, said under a board: always, so it's there when you're below the cut. */
export function Standing({ board, which }: { board: Leaderboard; which: (typeof BOARDS)[number] }) {
  return <p className={styles.settingsHint}>{standing(board, which)}.</p>;
}
