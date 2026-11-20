import { useEffect } from "react";
import { Bell } from "../components/Bell";
import { BookLoader } from "../components/BookLoader";
import { BOARDS, BoardTabs, GroupBoard, PlayerBoard, Standing, useLeaderboard } from "../components/Leaderboard";
import { Brand } from "../components/TopBar";
import { useFitHeight, usePager } from "../lib/pager";
import type { Leaderboard as Boards } from "../lib/social";
import styles from "../styles.module.css";

/** The two boards as tabs that slide like the menu's. A component of its own, so the swipe is
 *  set up when the lists are on the page: the hooks find their elements once, when they mount,
 *  and the page above shows a loader first. */
function BoardPages({ board }: { board: Boards }) {
  const { track, bar, active, go } = usePager(BOARDS.length, location.hash === "#players" ? 1 : 0);
  useFitHeight(track, active);

  // The address remembers the tab, so Back from a group or a player returns to it.
  useEffect(() => {
    const hash = BOARDS[active] === "players" ? "#players" : "";
    if (location.hash !== hash) history.replaceState(null, "", location.pathname + hash);
  }, [active]);

  return (
    <>
      <div className={styles.stickyTabs}>
        <BoardTabs bar={bar} active={active} go={go} />
      </div>
      <div className={`${styles.subTrack} ${styles.boardPages}`} ref={track}>
        <section className={styles.subScreen} aria-label="Groups">
          <div className={styles.boardPage}>
            <Standing board={board} which="groups" />
            <div className={styles.panel}>
              <GroupBoard board={board} />
            </div>
          </div>
        </section>
        <section className={styles.subScreen} aria-label="Players">
          <div className={styles.boardPage}>
            <Standing board={board} which="players" />
            <div className={styles.panel}>
              <PlayerBoard board={board} />
            </div>
          </div>
        </section>
      </div>
    </>
  );
}

/**
 * The whole global leaderboard, at /leaderboard (Ryan, Nov 12, 2026): the top fifty groups by
 * their members' combined prestige and the top fifty players by their own. Your own rows are
 * marked, and your place is given above each board even when it's below the fifty.
 * /leaderboard#players opens on Players.
 */
export function Leaderboard() {
  const { board, error } = useLeaderboard();

  if (error && !board) {
    return (
      <main className={styles.narrowPage}>
        <Brand home="social" />
        <p className={styles.empty}>{error === "Sign in first." ? "Sign in from the main menu to see the leaderboard." : error}</p>
        <a className={styles.quietLink} href="/">
          Go to the main menu
        </a>
      </main>
    );
  }
  if (!board) return <BookLoader label="Ranking everyone" />;

  return (
    // Calm: on a leaderboard every avatar holds still.
    <main className={`${styles.narrowPage} ${styles.calm}`}>
      <div className={styles.pageNav}>
        <Brand home="social" />
        <Bell />
      </div>
      <h1 className={styles.heading}>Leaderboard</h1>
      <BoardPages board={board} />
      <p className={styles.settingsHint}>
        Win games to climb the board. A group climbs with its members.
      </p>
    </main>
  );
}
