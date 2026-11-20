import type { Phase } from "../lib/types";
import styles from "../styles.module.css";

const STEPS: { phase: Phase; label: string }[] = [
  { phase: "QUESTION", label: "Question" },
  { phase: "QUOTING", label: "Sealed quotes" },
  { phase: "TRADING", label: "Trading" },
  { phase: "REVEAL", label: "Answer" },
  { phase: "SCORES", label: "Scores" },
];

export function PhaseSteps({ phase }: { phase: Phase }) {
  const current = STEPS.findIndex((step) => step.phase === phase);
  return (
    <ol className={styles.steps} style={{ listStyle: "none", margin: 0, padding: 0 }}>
      {STEPS.map((step, index) => (
        <li
          key={step.phase}
          className={[
            styles.step,
            index < current ? styles.stepDone : "",
            index === current ? styles.stepActive : "",
          ].join(" ")}
          aria-current={index === current ? "step" : undefined}
        >
          {step.label}
        </li>
      ))}
    </ol>
  );
}
