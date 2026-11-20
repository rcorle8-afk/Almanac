import { useEffect, useState } from "react";
import type { GameState } from "../lib/types";
import styles from "../styles.module.css";

const TICK_MS = 250;
const URGENT_SECONDS = 10;

export function useMillisecondsLeft(endsAt: number | null, clockOffset: number) {
  const [now, setNow] = useState(Date.now());

  useEffect(() => {
    const interval = window.setInterval(() => setNow(Date.now()), TICK_MS);
    return () => window.clearInterval(interval);
  }, []);

  return endsAt === null ? null : Math.max(0, endsAt - (now + clockOffset));
}

interface TimerProps {
  endsAt: number | null;
  clockOffset: number;
  large?: boolean;
}

export function Timer({ endsAt, clockOffset, large = false }: TimerProps) {
  const left = useMillisecondsLeft(endsAt, clockOffset);
  if (left === null) return null;
  const seconds = Math.ceil(left / 1000);
  const className = [
    large ? styles.timerLarge : styles.timer,
    seconds <= URGENT_SECONDS ? styles.timerUrgent : "",
  ].join(" ");
  return (
    <span className={className} role="timer">
      {seconds}s
    </span>
  );
}

export function TimerBar({ state, clockOffset }: { state: GameState; clockOffset: number }) {
  const left = useMillisecondsLeft(state.timer_ends_at, clockOffset);
  const total = state.phase_seconds; // from the server: a case question's phases run longer
  if (left === null || !total) return null;
  const fraction = Math.min(1, left / (total * 1000));
  const urgent = left <= URGENT_SECONDS * 1000;
  return (
    <div className={styles.timerTrack} aria-hidden="true">
      <div
        className={`${styles.timerFill} ${urgent ? styles.timerFillUrgent : ""}`}
        style={{ width: `${fraction * 100}%` }}
      />
    </div>
  );
}
