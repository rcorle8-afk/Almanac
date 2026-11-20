import { Avatar } from "../avatar/Avatar";
import { signedInteger } from "../lib/format";
import type { GameState, Player } from "../lib/types";
import styles from "../styles.module.css";
import { useMillisecondsLeft } from "./Timer";

const TOP_ROWS = 3;
const URGENT_SECONDS = 10;

const PHASE_LABELS: Record<GameState["phase"], string> = {
  LOBBY: "WAITING",
  QUESTION: "QUOTING IN",
  QUOTING: "QUOTES CLOSE",
  TRADING: "CLOSE IN",
  REVEAL: "SCORES IN",
  SCORES: "NEXT IN",
  GAME_OVER: "FINAL",
};

/** What the oval counts down to: the hint while one is pending, otherwise the phase end. */
function countdown(state: GameState) {
  if (state.phase === "TRADING" && state.hint === null && state.hint_at !== null) {
    return { label: "HINT IN", target: state.hint_at, canBeUrgent: false };
  }
  if (state.phase === "LOBBY" && state.timer_ends_at !== null) {
    // The live room's lobby counts down to its start (M6).
    return { label: "STARTS IN", target: state.timer_ends_at, canBeUrgent: false };
  }
  const lastRound = state.phase === "SCORES" && !state.endless && state.round_no >= state.rounds_total;
  return {
    label: lastRound ? "FINAL IN" : PHASE_LABELS[state.phase],
    target: state.timer_ends_at,
    canBeUrgent: state.phase === "TRADING",
  };
}

function clock(seconds: number) {
  return `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, "0")}`;
}

function MiniBoard({ players, youId }: { players: Player[]; youId: string }) {
  const ranked = [...players].sort((a, b) => Number(b.total_points) - Number(a.total_points));
  const rows = ranked.slice(0, TOP_ROWS);
  const you = ranked.find((player) => player.id === youId);
  if (you && !rows.includes(you)) rows.push(you);
  const scale = Math.max(1, ...rows.map((player) => Math.abs(Number(player.total_points))));

  return (
    <div className={styles.board} aria-label="Leaderboard">
      {rows.map((player) => {
        const score = Number(player.total_points);
        const isYou = player.id === youId;
        return (
          <div key={player.id} className={`${styles.boardRow} ${isYou ? styles.boardYou : ""}`}>
            <span className={styles.boardRank}>{ranked.indexOf(player) + 1}</span>
            <span className={`${styles.boardName} ${styles.nameWithAvatar}`}>
              <Avatar avatar={player.avatar} size={16} label="" />
              <span className={styles.nameText}>{isYou ? "You" : player.name}</span>
            </span>
            <span className={styles.boardTrack}>
              <span
                className={`${styles.boardBar} ${score < 0 ? styles.boardBarNegative : ""}`}
                style={{ width: `${(Math.abs(score) / scale) * 100}%` }}
              />
            </span>
            <span className={styles.boardScore}>{signedInteger(score)}</span>
          </div>
        );
      })}
    </div>
  );
}

interface PhoneHeaderProps {
  state: GameState;
  clockOffset: number;
  connected: boolean;
  youId: string;
}

export function PhoneHeader({ state, clockOffset, connected, youId }: PhoneHeaderProps) {
  const { label, target, canBeUrgent } = countdown(state);
  const left = useMillisecondsLeft(target, clockOffset);
  const seconds = left === null ? null : Math.ceil(left / 1000);
  const urgent = canBeUrgent && seconds !== null && seconds <= URGENT_SECONDS;

  return (
    <header className={styles.phoneHeader}>
      <div>
        <h1 className={styles.wordmark}>Almanac</h1>
        <div className={`${styles.timerOval} ${urgent ? styles.timerOvalUrgent : ""}`} role="timer">
          <span className={styles.timerOvalLabel}>{connected ? label : "RECONNECTING"}</span>
          <span className={styles.timerOvalValue}>{seconds === null ? "–:––" : clock(seconds)}</span>
        </div>
      </div>
      <MiniBoard players={state.players} youId={youId} />
    </header>
  );
}
