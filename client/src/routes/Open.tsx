import { useEffect, useState, type FormEvent } from "react";
import { Avatar } from "../avatar/Avatar";
import { BookLoader } from "../components/BookLoader";
import { Brand } from "../components/TopBar";
import { signedPoints } from "../lib/format";
import { fetchOpen, type Board, type OpenOverview } from "../lib/open";
import styles from "../styles.module.css";
import { readSeat, writeSeat } from "./seat";

const REFRESH_MS = 10_000;
const NAME_LIMIT = 16;

function BoardTable({ title, board }: { title: string; board: Board }) {
  const youShown = board.you && board.top.some((row) => row.place === board.you!.place);
  return (
    <section className={styles.panel} aria-label={title}>
      <div className={styles.roadHead}>
        <h2 className={styles.panelTitle}>{title}</h2>
        <span className={styles.rowMuted}>
          {board.players} {board.players === 1 ? "player" : "players"}
        </span>
      </div>
      {board.top.length === 0 ? (
        <p className={styles.empty}>Nobody has scored yet. The first round you play puts you on the board.</p>
      ) : (
        <ol className={styles.liveTable}>
          {[...board.top, ...(board.you && !youShown ? [board.you] : [])].map((row) => (
            <li key={row.public_id} className={`${styles.liveRow} ${board.you?.place === row.place ? styles.scoreYou : ""}`}>
              <span className={styles.scoreRank}>{row.place}</span>
              <Avatar avatar={row.avatar} size={24} label="" />
              <span className={styles.liveName}>
                <a href={`/u/${row.public_id}`}>{row.name}</a>
              </span>
              <span className={styles.liveNumber}>
                {signedPoints(row.points)} · {row.rounds} {row.rounds === 1 ? "round" : "rounds"}
              </span>
            </li>
          ))}
        </ol>
      )}
    </section>
  );
}

/** The endless table (M6): one market that never closes. Anyone can sit down at any time; a
 *  question takes under a minute, points pay out every round, and house bots keep it liquid. */
export function Open() {
  const [overview, setOverview] = useState<OpenOverview | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [name, setName] = useState(readSeat("OPEN")?.name ?? "");

  function load() {
    fetchOpen()
      .then((answer) => {
        setOverview(answer);
        setError(null);
      })
      .catch((caught: Error) => setError(caught.message));
  }

  useEffect(() => {
    load();
    const poll = window.setInterval(() => document.visibilityState === "visible" && load(), REFRESH_MS);
    return () => window.clearInterval(poll);
  }, []);

  function sitDown(event: FormEvent) {
    event.preventDefault();
    if (!overview) return;
    // A blank name seats a signed-in player under their account's name.
    const chosen = overview.signed_in ? "" : name.trim();
    const seat = readSeat(overview.code);
    writeSeat(overview.code, { name: chosen, token: seat?.name === chosen ? seat.token : null });
    location.assign(`/play?room=${encodeURIComponent(overview.code)}`);
  }

  if (!overview) {
    return error ? (
      <main className={styles.narrowPage}>
        <Brand home="play" />
        <p className={styles.empty}>{error}</p>
      </main>
    ) : (
      <BookLoader label="Finding the table" />
    );
  }

  return (
    <main className={styles.narrowPage}>
      <div className={styles.pageNav}>
        <Brand home="play" />
        <div className={styles.pageLinks}>
          <a href="/">Play</a>
          <a href="/live">Live</a>
        </div>
      </div>

      <form className={`${styles.panel} ${styles.liveHero}`} onSubmit={sitDown}>
        <span className={styles.liveTag}>OPEN TABLE</span>
        <h1 className={styles.liveTitle}>Trade anyone, any time</h1>
        <p className={styles.settingsHint}>
          {overview.people > 0
            ? `${overview.people} ${overview.people === 1 ? "person" : "people"} at the table now`
            : "Nobody's at the table right now. Sit down and it starts"}
          {overview.bots > 0 ? `, with ${overview.bots} house ${overview.bots === 1 ? "bot" : "bots"}.` : "."}{" "}
          A question takes under a minute, and you can leave whenever you like.
        </p>
        {!overview.signed_in && (
          <label className={styles.field}>
            Your name
            <input
              id="open-name"
              className={styles.input}
              value={name}
              maxLength={NAME_LIMIT}
              autoComplete="off"
              required
              onChange={(event) => setName(event.target.value)}
            />
          </label>
        )}
        <button type="submit" className={`${styles.button} ${styles.primary}`}>
          Sit down
        </button>
        <p className={styles.settingsHint}>
          {overview.signed_in
            ? "Every round you quote or trade in pays coins and XP and counts on today's board."
            : "Guests play for fun. Sign in from the main menu to bank coins and XP every round and get on the boards."}
        </p>
      </form>

      <BoardTable title="Today" board={overview.today} />
      <BoardTable title="This week" board={overview.week} />

      <details className={styles.panel}>
        <summary className={styles.panelTitle}>How the house bots work</summary>
        <p className={styles.settingsHint}>
          When fewer than {overview.house_traders} people are at the table, house bots fill the
          seats so there's always someone to trade with. They're marked BOT. They never know the
          answer: each question they share one guess that's usually 25 to 60% off, and they move
          their prices as people trade with them. Points won off the house pay a quarter of the
          coins that points won off people do.
        </p>
      </details>
    </main>
  );
}
