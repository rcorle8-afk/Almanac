import styles from "../styles.module.css";

/** A player's prestige: a small four-point star and the number. It sits beside the name, never
 *  on the banner, which carries the name alone. Nothing shows for no prestige. There is no
 *  tooltip: name cards are all over the social pages, which never spell the word out (Ryan,
 *  Nov 17, 2026). The label is for a screen reader, which can't see the star. */
export function Prestige({ value }: { value: number | null | undefined }) {
  if (!value) return null;
  return (
    <span className={styles.prestige} aria-label={`${value} prestige`}>
      <svg viewBox="0 0 12 12" aria-hidden="true">
        <path d="M6 0C6.6 3.6 8.4 5.4 12 6C8.4 6.6 6.6 8.4 6 12C5.4 8.4 3.6 6.6 0 6C3.6 5.4 5.4 3.6 6 0Z" />
      </svg>
      {value.toLocaleString()}
    </span>
  );
}
