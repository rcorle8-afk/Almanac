import { useEffect, useState } from "react";
import { Avatar } from "../avatar/Avatar";
import { BookLoader } from "../components/BookLoader";
import { SignInPanel } from "../components/SignInPanel";
import { Brand } from "../components/TopBar";
import { countdown, signedPoints } from "../lib/format";
import { fetchLive, type LiveOverview } from "../lib/live";
import styles from "../styles.module.css";
import { readSeat, writeSeat } from "./seat";

const REFRESH_MS = 10_000;

function localTime(ms: number) {
  return new Date(ms).toLocaleTimeString(undefined, { hour: "numeric", minute: "2-digit" });
}

function join(code: string) {
  // A blank name seats a signed-in player under their account's name.
  writeSeat(code, { name: "", token: readSeat(code)?.token ?? null });
  location.assign(`/play?room=${encodeURIComponent(code)}`);
}

/** The nightly live game (M6): a countdown, the door in, and the live tables. */
export function Live() {
  const [overview, setOverview] = useState<LiveOverview | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [now, setNow] = useState(Date.now());

  function load() {
    fetchLive()
      .then((answer) => {
        setOverview(answer);
        setError(null);
      })
      .catch((caught: Error) => setError(caught.message));
  }

  useEffect(() => {
    load();
    const poll = window.setInterval(() => document.visibilityState === "visible" && load(), REFRESH_MS);
    const tick = window.setInterval(() => setNow(Date.now()), 1000);
    return () => {
      window.clearInterval(poll);
      window.clearInterval(tick);
    };
  }, []);

  if (!overview) {
    return error ? (
      <main className={styles.narrowPage}>
        <Brand home="play" />
        <p className={styles.empty}>{error}</p>
      </main>
    ) : (
      <BookLoader label="Finding tonight's game" />
    );
  }

  const room = overview.room;
  const open = room !== null && room.phase !== "GAME_OVER";
  const startsAt = room?.starts_at ?? overview.next_start;
  const inLobby = open && room.phase === "LOBBY";
  const playing = open && room.phase !== "LOBBY";
  const opensIn = overview.next_start - overview.lobby_minutes * 60_000 - now;

  return (
    <main className={styles.narrowPage}>
      <div className={styles.pageNav}>
        <Brand home="play" />
        <div className={styles.pageLinks}>
          <a href="/">Play</a>
          <a href="/social">Social</a>
        </div>
      </div>

      <section className={`${styles.panel} ${styles.liveHero}`} aria-live="polite">
        <span className={styles.liveTag}>LIVE</span>
        {playing ? (
          <>
            <h1 className={styles.liveTitle}>Tonight's game is on</h1>
            <p className={styles.settingsHint}>
              Question {room.round_no} of {room.rounds_total} · {room.players} playing. Join now and you
              play from the next question.
            </p>
          </>
        ) : inLobby ? (
          <>
            <h1 className={styles.liveTitle}>Starts in {countdown(startsAt - now)}</h1>
            <p className={styles.settingsHint}>
              The lobby is open · {room.players} {room.players === 1 ? "player" : "players"} in so far.
            </p>
          </>
        ) : (
          <>
            <h1 className={styles.liveTitle}>Next game in {countdown(overview.next_start - now)}</h1>
            <p className={styles.settingsHint}>
              Every night at {overview.hour - 12} PM Eastern ({localTime(overview.next_start)} where you
              are). The lobby opens {overview.lobby_minutes} minutes before
              {opensIn > 0 ? `, in ${countdown(opensIn)}` : ""}.
            </p>
            {room?.cancelled && (
              <p className={styles.notice}>Last night's game was called off: fewer than two players came.</p>
            )}
          </>
        )}

        {open &&
          (overview.signed_in ? (
            <button type="button" className={`${styles.button} ${styles.primary}`} onClick={() => join(room.code)}>
              {playing ? "Join the game" : "Join the lobby"}
            </button>
          ) : null)}
        {!overview.signed_in && (
          <SignInPanel
            title="Sign in to play live"
            blurb="The live game is for signed-in players, so the standings mean something. Sign in once and you can join every night."
            onSignedIn={load}
          />
        )}
        <p className={styles.settingsHint}>
          {overview.rounds} questions, quotes and trading as usual, against everyone who turns up.
        </p>
      </section>

      {overview.last && (
        <section className={styles.panel} aria-label="Last live game">
          <div className={styles.roadHead}>
            <h2 className={styles.panelTitle}>Last live game</h2>
            <span className={styles.rowMuted}>
              {new Date(overview.last.ended_at).toLocaleDateString(undefined, { month: "short", day: "numeric" })} ·{" "}
              {overview.last.players} players
            </span>
          </div>
          <ol className={styles.liveTable}>
            {overview.last.table.map((row) => (
              <li key={`${row.public_id}-${row.name}`} className={styles.liveRow}>
                <span className={styles.scoreRank}>{row.place}</span>
                <Avatar avatar={row.avatar} size={24} label="" />
                <span className={styles.liveName}>
                  {row.public_id ? <a href={`/u/${row.public_id}`}>{row.name}</a> : row.name}
                </span>
                <span className={styles.liveNumber}>{signedPoints(Number(row.points))}</span>
              </li>
            ))}
          </ol>
        </section>
      )}

      {overview.standings.length > 0 && (
        <section className={styles.panel} aria-label="Live standings">
          <div className={styles.roadHead}>
            <h2 className={styles.panelTitle}>All-time live standings</h2>
            <span className={styles.rowMuted}>Wins, then points</span>
          </div>
          <ol className={styles.liveTable}>
            {overview.standings.map((row, index) => (
              <li key={row.public_id} className={styles.liveRow}>
                <span className={styles.scoreRank}>{index + 1}</span>
                <Avatar avatar={row.avatar} size={24} label="" />
                <span className={styles.liveName}>
                  <a href={`/u/${row.public_id}`}>{row.name}</a>
                </span>
                <span className={styles.liveNumber}>
                  {row.wins} {row.wins === 1 ? "win" : "wins"} · {row.games} played
                </span>
              </li>
            ))}
          </ol>
        </section>
      )}

      <p className={styles.settingsHint}>
        Looking answers up is against the spirit of the game. Players confirmed doing it are left
        off these tables.
      </p>
    </main>
  );
}
