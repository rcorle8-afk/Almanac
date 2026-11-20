import { useEffect, useState } from "react";
import { BookLoader } from "../components/BookLoader";
import { Brand } from "../components/TopBar";
import { pointsClass, signedPoints } from "../lib/format";
import { fetchHistory, type HistoryPage, type PastGame } from "../lib/games";
import styles from "../styles.module.css";

function day(iso: string) {
  return new Date(iso).toLocaleDateString(undefined, { month: "short", day: "numeric" });
}

function month(iso: string) {
  return new Date(iso).toLocaleDateString(undefined, { month: "long", year: "numeric" });
}

/** Games grouped under the month they ended in, keeping the newest-first order. */
function byMonth(games: PastGame[]): [string, PastGame[]][] {
  const groups: [string, PastGame[]][] = [];
  for (const game of games) {
    const label = month(game.ended_at);
    const last = groups[groups.length - 1];
    if (last && last[0] === label) last[1].push(game);
    else groups.push([label, [game]]);
  }
  return groups;
}

function GameRow({ game }: { game: PastGame }) {
  return (
    <a href={`/profile/games/${game.game_id}`} className={`${styles.gameRow} ${styles.gameLink}`}>
      <span className={styles.rowMuted}>{day(game.ended_at)}</span>
      <span>{game.room_code}</span>
      <span>
        {game.rank}
        <span className={styles.rowMuted}>/{game.player_count}</span>
      </span>
      <span className={pointsClass(Number(game.points), styles)}>{signedPoints(game.points)}</span>
      <span className={styles.gain}>+{game.coins}</span>
      {/* Who won, when it wasn't you: a line of its own under the room, so a phone has room for it. */}
      {game.rank !== 1 && game.winners && <small className={styles.historyWinner}>won by {game.winners}</small>}
    </a>
  );
}

/** Every game you've finished while signed in, newest first, a page at a time. Each row opens
 *  that game's log. */
export function GameHistory() {
  const [games, setGames] = useState<PastGame[]>([]);
  const [page, setPage] = useState<HistoryPage | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  function load(before?: number | null) {
    setLoading(true);
    fetchHistory(before)
      .then((next) => {
        // The first page replaces (an effect can run twice in development); later pages append.
        setGames((shown) => (before ? [...shown, ...next.games] : next.games));
        setPage(next);
      })
      .catch((caught: Error) => setError(caught.message))
      .finally(() => setLoading(false));
  }

  useEffect(() => load(), []);

  if (error && !page) {
    return (
      <main className={styles.narrowPage}>
        <Brand home="social" />
        <p className={styles.empty}>{error}</p>
        <a className={styles.quietLink} href="/profile">
          Back to your profile
        </a>
      </main>
    );
  }
  if (!page) return <BookLoader label="Opening your games" />;

  return (
    <main className={styles.narrowPage}>
      <div className={styles.pageNav}>
        <Brand home="social" />
        <div className={styles.pageLinks}>
          <a href="/profile">Profile</a>
        </div>
      </div>

      <section className={styles.panel}>
        <h1 className={styles.heading}>Every game</h1>
        <p className={styles.empty}>
          {page.total === 0
            ? "No games yet. Finish a game while signed in and it shows up here."
            : `${page.total} ${page.total === 1 ? "game" : "games"}, newest first. Tap one for its log.`}
        </p>
      </section>

      {byMonth(games).map(([label, group]) => (
        <section key={label} className={styles.panel}>
          <h2 className={styles.panelTitle}>{label}</h2>
          <div className={styles.rows}>
            <div className={`${styles.gameRow} ${styles.scoreHead}`}>
              <span>Date</span>
              <span>Room</span>
              <span>Place</span>
              <span>Points</span>
              <span>Coins</span>
            </div>
            {group.map((game) => (
              <GameRow key={game.game_id} game={game} />
            ))}
          </div>
        </section>
      ))}

      {error && <p className={styles.notice}>{error}</p>}
      {page.next !== null && (
        <div className={styles.actions}>
          <button type="button" className={styles.button} disabled={loading} onClick={() => load(page.next)}>
            {loading ? "Loading" : "Show older games"}
          </button>
        </div>
      )}
    </main>
  );
}
