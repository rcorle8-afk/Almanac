import type { GameAward } from "../lib/types";
import styles from "../styles.module.css";
import { Icon } from "./Badge";

const AWARD_ICONS: Record<string, string> = {
  best_quotes: "brackets",
  biggest_round: "chart",
  most_trades: "swap",
};

/** "Ann", "Ann and Ben", "Ann, Ben and 3 others". */
function who(names: string[]) {
  if (names.length <= 2) return names.join(" and ");
  if (names.length === 3) return `${names[0]}, ${names[1]} and ${names[2]}`;
  return `${names[0]}, ${names[1]} and ${names.length - 2} others`;
}

/** The end-of-game superlatives (server Room.awards): most Best Quotes, the biggest single round
 *  and the most trades, each with who won it. `youId` marks the viewer's own. */
export function GameAwards({ awards, youId, large = false }: { awards: GameAward[]; youId?: string; large?: boolean }) {
  if (awards.length === 0) return null;
  return (
    <section className={`${styles.awardRow} ${large ? styles.awardRowLarge : ""}`} aria-label="Game awards">
      {awards.map((award) => {
        const mine = youId !== undefined && award.winners.includes(youId);
        return (
          <div key={award.id} className={`${styles.awardCard} ${mine ? styles.awardMine : ""}`}>
            <span className={styles.awardIcon}>
              <Icon name={AWARD_ICONS[award.id] ?? "trophy"} size={large ? 26 : 20} />
            </span>
            <div className={styles.awardText}>
              <div className={styles.awardTitle}>{award.title}</div>
              <div className={styles.awardWho}>{mine ? (award.names.length > 1 ? `You and ${award.names.length - 1} more` : "You") : who(award.names)}</div>
              <div className={styles.awardDetail}>{award.detail}</div>
            </div>
          </div>
        );
      })}
    </section>
  );
}
