import { cleanNumber } from "../lib/format";
import type { GameState } from "../lib/types";
import styles from "../styles.module.css";

const BEST_QUOTE_BONUS = 25; // server/engine/scoring.py, times the round's multiplier

export function QuestionCard({ state, large = false }: { state: GameState; large?: boolean }) {
  const question = state.question!;
  const multiplier = cleanNumber(Number(question.multiplier));
  return (
    <header className={styles.header}>
      {question.context && (
        <p className={large ? styles.caseContextLarge : styles.caseContext}>
          <span className={styles.caseLabel}>CASE · ×{multiplier} POINTS</span>
          {question.context}
        </p>
      )}
      <h1 className={large ? styles.questionLarge : styles.question}>
        {question.text} <span className={styles.unit}>({question.unit})</span>
      </h1>
      {question.answer && (
        <div className={styles.answer}>
          <span className={styles.answerLabel}>ANSWER</span>
          <span className={styles.answerValue}>
            {question.answer} {question.unit}
          </span>
          <a href={question.source_url ?? undefined} target="_blank" rel="noreferrer">
            {question.source_note}
          </a>
          {state.best_quote && (
            <p className={styles.bestQuote}>
              Best quote: {state.best_quote.name}, {state.best_quote.bid} / {state.best_quote.ask}{" "}
              <span className={styles.gain}>+{cleanNumber(BEST_QUOTE_BONUS * Number(question.multiplier))}</span>
            </p>
          )}
        </div>
      )}
    </header>
  );
}
