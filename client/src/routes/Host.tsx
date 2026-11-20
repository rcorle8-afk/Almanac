import QRCode from "qrcode";
import { useCallback, useEffect, useState } from "react";
import { GameAwards } from "../components/GameAwards";
import { PlayerChip } from "../components/NameCard";
import { Book } from "../components/Book";
import { BookLoader } from "../components/BookLoader";
import { HintBanner } from "../components/HintBanner";
import { HostInvite } from "../components/HostInvite";
import { GearIcon, HostSettings } from "../components/HostSettings";
import { HowToPlay } from "../components/HowToPlay";
import { PhaseSteps } from "../components/PhaseSteps";
import { QuestionCard } from "../components/QuestionCard";
import { Scores } from "../components/Scores";
import { Tape } from "../components/Tape";
import { TopBar } from "../components/TopBar";
import { strengthLabel } from "../lib/drinks";
import { useGame } from "../lib/ws";
import type { ClientMessage, GameState, ServerMessage } from "../lib/types";
import styles from "../styles.module.css";

const HOST_KEY = "almanac:host";
const NOTICE_MS = 8000;

interface StoredHost {
  room_code: string;
  token: string;
  group?: string | null; // the group a members-only room was opened for
}

function readHost(): StoredHost | null {
  try {
    return JSON.parse(localStorage.getItem(HOST_KEY) ?? "null");
  } catch {
    return null;
  }
}

// Play now on a group page opens /host?group=ID: a members-only room for that group. A stored
// room for the same group resumes; anything else starts the group's room fresh.
const GROUP = new URLSearchParams(location.search).get("group");

function createMessage() {
  return GROUP ? ({ type: "host_create", group: GROUP } as const) : ({ type: "host_create" } as const);
}

function newGame() {
  localStorage.removeItem(HOST_KEY);
  location.reload();
}

// A phone camera takes players straight to the join form with the code filled in.
// Twelve big rows fit a TV; the rest become "and N more".
const LOBBY_SCORE_ROWS = 12;

function useJoinQr(code: string) {
  const [image, setImage] = useState<string | null>(null);
  useEffect(() => {
    const url = `${location.origin}/?room=${encodeURIComponent(code)}`;
    QRCode.toDataURL(url, {
      margin: 1,
      width: 240,
      color: { dark: "#ffffffff", light: "#00000000" },
    })
      .then(setImage)
      .catch(() => setImage(null));
  }, [code]);
  return image;
}

interface InviteProps {
  send: (message: ClientMessage) => void;
  onSignedIn: () => void;
}

function Lobby({ state, send, onSignedIn }: { state: GameState } & InviteProps) {
  const qr = useJoinQr(state.room_code);
  return (
    <section className={styles.lobby}>
      <div className={styles.lobbyJoin}>
        {qr && <img className={styles.lobbyQr} src={qr} alt={`QR code to join room ${state.room_code}`} />}
        <div>
          <p className={styles.joinHint}>
            Scan, or join at <strong>{location.host}</strong> with code
          </p>
          <p className={styles.roomCode}>{state.room_code}</p>
        </div>
      </div>
      {state.group && (
        <p className={styles.groupRoomTag}>
          Members of <strong>{state.group.name}</strong> only. Sign in with your member account to join.
        </p>
      )}
      <div className={styles.lobbyPlayers}>
        {state.players.map((player) => (
          <PlayerChip key={player.id} player={player} dim={!player.connected} />
        ))}
      </div>
      {state.players.length === 0 && <p className={styles.empty}>Waiting for the first player</p>}
      {state.players.length > 0 && (
        <p className={styles.empty}>
          {state.player_count} of {state.config.max_players} seats taken
        </p>
      )}
      {/* Before the game: who is hosting, and their offer of a group to the table. */}
      <HostInvite state={state} send={send} onSignedIn={onSignedIn} />
      <HowToPlay large />
    </section>
  );
}

function QuoteProgress({ state }: { state: GameState }) {
  return (
    <section className={styles.panel}>
      <h2 className={styles.panelTitle}>
        Quotes in: {state.players.filter((player) => player.quoted).length} of{" "}
        {state.players.length}
      </h2>
      <div className={styles.lobbyPlayers}>
        {state.players.map((player) => (
          <PlayerChip key={player.id} player={player} dim={!player.quoted} />
        ))}
      </div>
    </section>
  );
}

export function Host() {
  const [lostRoom, setLostRoom] = useState(false);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const closeSettings = useCallback(() => setSettingsOpen(false), []);
  // `reconnect` after signing in on this screen: the server reads the account when the socket
  // opens, and the room comes back with host_resume.
  const { state, connected, error, clockOffset, send, reconnect, replaced, notice } = useGame(
    () => {
      const stored = readHost();
      const same = stored && (stored.group ?? null) === GROUP;
      return stored && same
        ? { type: "host_resume", room_code: stored.room_code, token: stored.token }
        : createMessage();
    },
    (message: ServerMessage, reply) => {
      if (message.type === "hosted") {
        const stored: StoredHost = { room_code: message.room_code, token: message.token, group: GROUP };
        localStorage.setItem(HOST_KEY, JSON.stringify(stored));
      } else if (
        message.type === "error" &&
        (message.code === "room_not_found" || message.code === "not_host")
      ) {
        localStorage.removeItem(HOST_KEY); // the stored room died with a server restart
        setLostRoom(true);
        reply(createMessage());
      }
    },
  );
  // How a table invite went, shown for a few seconds over the host screen.
  const [shownNotice, setShownNotice] = useState<string | null>(null);
  useEffect(() => {
    if (!notice) return;
    setShownNotice(notice.message);
    const timer = window.setTimeout(() => setShownNotice(null), NOTICE_MS);
    return () => window.clearTimeout(timer);
  }, [notice]);

  if (replaced) {
    return (
      <main className={`${styles.hostPage} ${styles.calm}`}>
        <p className={styles.lostRoom} role="alert">
          {replaced} Host from there, or reload this page to bring the room back here.
        </p>
      </main>
    );
  }
  if (!state) {
    return error ? (
      <main className={`${styles.hostPage} ${styles.calm}`}>
        <p className={styles.lostRoom} role="alert">
          {error}
        </p>
        {GROUP && (
          <p className={styles.empty}>
            <a className={styles.inlineLink} href="/">
              Sign in from the main menu
            </a>{" "}
            with a member's account, then press Play now again. Or{" "}
            <a className={styles.inlineLink} href="/host">
              host an open game
            </a>
            .
          </p>
        )}
      </main>
    ) : (
      <BookLoader label="Opening the almanac" />
    );
  }

  const { phase } = state;
  const inRound = phase !== "LOBBY" && phase !== "GAME_OVER";

  return (
    <main className={`${styles.hostPage} ${styles.calm}`}>
      <TopBar
        state={state}
        clockOffset={clockOffset}
        connected={connected}
        large
        action={
          <button
            type="button"
            className={styles.iconButton}
            aria-label="Host settings"
            aria-expanded={settingsOpen}
            onClick={() => setSettingsOpen(true)}
          >
            <GearIcon />
          </button>
        }
      >
        Room <strong>{state.room_code}</strong>
        {state.host && ` · Hosted by ${state.host.name}`}
        {state.group && ` · ${state.group.name}`}
        {state.round_no > 0 && ` · Round ${state.round_no} of ${state.rounds_total}`}
        {state.config.drinks && ` · Drinks mode, ${strengthLabel(state.config.drink_strength).toLowerCase()}`}
      </TopBar>

      {inRound && <PhaseSteps phase={phase} />}
      {lostRoom && phase === "LOBBY" && (
        <p className={styles.lostRoom} role="alert">
          The server restarted, so the previous room is gone and any game in it was lost. This is a
          new room. Players need to join again with the code below.
        </p>
      )}
      {phase === "LOBBY" && <Lobby state={state} send={send} onSignedIn={reconnect} />}
      {state.question && phase !== "GAME_OVER" && <QuestionCard state={state} large />}
      {(phase === "TRADING" || phase === "REVEAL") && <HintBanner state={state} />}
      {phase === "QUOTING" && <QuoteProgress state={state} />}

      {phase === "TRADING" && (
        <div className={styles.columns}>
          <Book book={state.book} own={[]} disabled onPick={() => undefined} />
          <Tape tape={state.tape} players={state.players} />
        </div>
      )}

      {phase === "REVEAL" && (
        <div className={styles.columns}>
          <Scores players={state.players} drinks={state.config.drinks} limit={LOBBY_SCORE_ROWS} large />
          <Tape tape={state.tape} players={state.players} />
        </div>
      )}

      {phase === "SCORES" && (
        <Scores players={state.players} drinks={state.config.drinks} limit={LOBBY_SCORE_ROWS} large />
      )}
      {phase === "GAME_OVER" && (
        <>
          <h1 className={styles.heading}>Final scores</h1>
          <GameAwards awards={state.awards ?? []} large />
          <Scores players={state.players} drinks={state.config.drinks} limit={LOBBY_SCORE_ROWS} large />
          {/* After the game: the host may offer a group again, the same one or another. */}
          <HostInvite state={state} send={send} onSignedIn={reconnect} />
        </>
      )}

      {/* In a round: Skip ahead, End game, Skip question, three equal buttons with End game in
          the middle. Skip question finishes the question at once and lands on its scores. */}
      <div className={`${styles.hostControls} ${inRound ? styles.hostRoundControls : ""}`}>
        {phase === "LOBBY" && (
          <button
            type="button"
            className={`${styles.button} ${styles.primary}`}
            disabled={state.player_count < 2}
            onClick={() => send({ type: "host_start" })}
          >
            {state.player_count < 2 ? "Need 2 players" : `Start game (${state.player_count})`}
          </button>
        )}
        {inRound && (
          <button
            type="button"
            className={styles.button}
            onClick={() => send({ type: "host_advance" })}
          >
            Skip ahead
          </button>
        )}
        {inRound && (
          <button
            type="button"
            className={styles.button}
            onClick={() => {
              if (window.confirm("End this game for everyone?")) send({ type: "host_end" });
            }}
          >
            End game
          </button>
        )}
        {inRound && (
          <button
            type="button"
            className={styles.button}
            disabled={phase === "SCORES"}
            onClick={() => send({ type: "host_skip_round" })}
          >
            Skip question
          </button>
        )}
        {phase === "GAME_OVER" && (
          <button
            type="button"
            className={`${styles.button} ${styles.primary}`}
            onClick={() => send({ type: "host_restart" })}
          >
            Play again
          </button>
        )}
        {phase === "GAME_OVER" && (
          <button type="button" className={styles.button} onClick={newGame}>
            New room
          </button>
        )}
      </div>
      {error && (
        <p className={styles.error} role="alert">
          {error}
        </p>
      )}
      {shownNotice && !settingsOpen && (
        <p className={styles.hostNotice} role="status">
          {shownNotice}
        </p>
      )}
      {settingsOpen && (
        <HostSettings state={state} send={send} onClose={closeSettings} notice={shownNotice} onSignedIn={reconnect} />
      )}
    </main>
  );
}
