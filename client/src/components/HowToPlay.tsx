import styles from "../styles.module.css";

/** The shortest version that gets a first-timer through round one; the host talks over it. */
export function HowToPlay({ large = false }: { large?: boolean }) {
  return (
    <section className={`${styles.panel} ${styles.howToPanel}`}>
      <h2 className={styles.panelTitle}>How to play</h2>
      <ol className={styles.howTo} style={large ? { fontSize: 18 } : undefined}>
        <li>Every round is a question with a number for an answer.</li>
        <li>
          Guess a range: the most you'd <strong>pay</strong> and the least you'd{" "}
          <strong>sell</strong> for.
        </li>
        <li>
          Then trade on everyone's prices: <strong>buy</strong> what looks too low,{" "}
          <strong>sell</strong> what looks too high.
        </li>
        <li>The real answer comes out. Buys below it and sells above it earn points.</li>
      </ol>
    </section>
  );
}
