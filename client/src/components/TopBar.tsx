import type { ReactNode } from "react";
import { menuHref, type Screen } from "../lib/menu";
import type { GameState } from "../lib/types";
import styles from "../styles.module.css";
import { Timer, TimerBar } from "./Timer";

interface TopBarProps {
  state: GameState;
  clockOffset: number;
  connected: boolean;
  large?: boolean;
  /** A control shown at the right end, before the timer (the host's settings button). */
  action?: ReactNode;
  children: ReactNode;
}

/** The wordmark. With `home` it is a link back to that screen of the main menu, so every page
 *  has a way out; at a table (the phone's game view, the host screen) it stays plain text, so a
 *  stray tap can't walk a player out of a round. */
export function Brand({ home }: { home?: Screen }) {
  const mark = (
    <>
      <span className={styles.brandMark} />
      ALMANAC
    </>
  );
  return home ? (
    <a className={styles.brand} href={menuHref(home)} aria-label="Almanac: main menu">
      {mark}
    </a>
  ) : (
    <div className={styles.brand}>{mark}</div>
  );
}

export function TopBar({ state, clockOffset, connected, large = false, action, children }: TopBarProps) {
  return (
    <>
      <div className={styles.topBar}>
        <Brand />
        <div className={styles.topMeta}>{children}</div>
        <div className={styles.statusRight}>
          {!connected && <span className={styles.loss}>Reconnecting…</span>}
          {action}
          <Timer endsAt={state.timer_ends_at} clockOffset={clockOffset} large={large} />
        </div>
      </div>
      <TimerBar state={state} clockOffset={clockOffset} />
    </>
  );
}
