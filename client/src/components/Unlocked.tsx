import { byTier, TIER_LABEL, type EarnedAchievement } from "../lib/achievements";
import styles from "../styles.module.css";
import { Badge } from "./Badge";

/** The game-end list of tiers this game earned. Each badge arrives in turn, easiest first, with
 *  a one-shot animation that grows with the tier: bronze rises, silver rises with a sheen, gold
 *  pops with a glow, platinum spins in, mystery wobbles in with a purple glow. */
export function Unlocked({ achievements }: { achievements: EarnedAchievement[] }) {
  if (achievements.length === 0) return null;
  return (
    <section className={styles.panel} aria-live="polite">
      <h2 className={styles.panelTitle}>
        {achievements.length === 1 ? "Achievement unlocked" : `${achievements.length} achievements unlocked`}
      </h2>
      <div className={styles.unlockList}>
        {byTier(achievements).map((earned, index) => {
          const delay = { animationDelay: `${250 + index * 450}ms` };
          return (
            <div key={`${earned.id}-${earned.tier}`} className={styles.unlockRow} style={delay}>
              <span className={`${styles.reveal} ${styles[`reveal_${earned.tier}`]}`} style={delay}>
                <Badge icon={earned.icon} tier={earned.tier} size={46} label={`${earned.name}, ${earned.tier}`} />
              </span>
              <div className={styles.unlockText}>
                <div className={styles.unlockName}>
                  {earned.name}
                  <span className={`${styles.tierTag} ${styles[`tier_${earned.tier}`]}`}>
                    {TIER_LABEL[earned.tier]}
                  </span>
                </div>
                <div className={styles.unlockNeed}>{earned.requirement}</div>
                <div className={styles.gain}>{earned.reward}</div>
              </div>
            </div>
          );
        })}
      </div>
      <a className={styles.quietLink} href="/profile/achievements">
        All achievements
      </a>
    </section>
  );
}
