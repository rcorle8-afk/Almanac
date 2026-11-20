import type { GameState } from "../lib/types";
import styles from "../styles.module.css";

const formatBound = (value: string) =>
  Number(value).toLocaleString(undefined, { maximumFractionDigits: 6 });

interface HintBannerProps {
  state: GameState;
  showPending?: boolean; // the phone's timer already counts down to the hint
}

export function HintBanner({ state, showPending = true }: HintBannerProps) {
  const { hint, phase, question } = state;
  // A case question's hint is a sentence with a related figure; any other is a range.
  if (hint?.text && question) {
    return (
      <div className={styles.hint} role="status">
        <span className={styles.hintLabel}>HINT</span>
        <span>{hint.text}</span>
      </div>
    );
  }
  if (hint && hint.low !== null && hint.high !== null && question) {
    return (
      <div className={styles.hint} role="status">
        <span className={styles.hintLabel}>HINT</span>
        <span>
          The answer is between <strong>{formatBound(hint.low)}</strong> and{" "}
          <strong>{formatBound(hint.high)}</strong> {question.unit}.
        </span>
      </div>
    );
  }
  if (showPending && phase === "TRADING" && state.hint_at !== null && state.timer_ends_at !== null) {
    const lead = Math.round((state.timer_ends_at - state.hint_at) / 1000);
    return <div className={styles.hintPending}>A hint drops with {lead}s left in trading.</div>;
  }
  return null;
}
