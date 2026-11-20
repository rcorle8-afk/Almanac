import { useEffect, useState } from "react";
import { Badge } from "../components/Badge";
import { BookLoader } from "../components/BookLoader";
import { Brand } from "../components/TopBar";
import {
  earnedLine,
  fetchAchievements,
  TIER_LABEL,
  type Achievement,
  type AchievementList,
} from "../lib/achievements";
import styles from "../styles.module.css";

function day(iso: string) {
  return new Date(iso).toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" });
}

/** The best tier held, for the card's big badge; the first tier, faint, if none yet. */
function headline(achievement: Achievement) {
  const held = achievement.tiers.filter((tier) => tier.earned_at);
  return held.length ? { tier: held[held.length - 1].tier, locked: false } : { tier: achievement.tiers[0].tier, locked: true };
}

function AchievementCard({ achievement }: { achievement: Achievement }) {
  const top = headline(achievement);
  return (
    <section className={styles.panel}>
      <div className={styles.achievementHead}>
        <Badge icon={achievement.icon} tier={top.tier} size={52} locked={top.locked} label={achievement.name} />
        <div>
          <h2 className={styles.achievementName}>{achievement.name}</h2>
          <p className={styles.empty}>{achievement.blurb}</p>
          {achievement.progress !== null && (
            <p className={styles.achievementProgress}>So far: {achievement.progress.toLocaleString()}</p>
          )}
        </div>
      </div>
      <div className={styles.tierList}>
        {achievement.tiers.map((tier) => (
          <div key={tier.tier} className={`${styles.tierRow} ${tier.earned_at ? "" : styles.tierRowLocked}`}>
            <Badge icon={achievement.icon} tier={tier.tier} size={30} locked={!tier.earned_at} />
            <div className={styles.tierText}>
              <div>
                <span className={`${styles.tierTag} ${styles[`tier_${tier.tier}`]}`}>{TIER_LABEL[tier.tier]}</span>{" "}
                {tier.requirement}
              </div>
              <div className={styles.tierReward}>{tier.reward}</div>
            </div>
            <div className={styles.tierStatus}>
              {tier.earned_at ? (
                <span className={styles.gain}>Earned {day(tier.earned_at)}</span>
              ) : tier.goal !== null && achievement.progress !== null ? (
                <span className={styles.rowMuted}>
                  {Math.min(achievement.progress, tier.goal).toLocaleString()} / {tier.goal.toLocaleString()}
                </span>
              ) : (
                <span className={styles.rowMuted}>Locked</span>
              )}
            </div>
          </div>
        ))}
      </div>
    </section>
  );
}

/** Every achievement, what each tier takes and pays, and what this player has earned. Mystery
 *  tiers keep their requirement hidden until they're earned. */
export function Achievements() {
  const [list, setList] = useState<AchievementList | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetchAchievements()
      .then(setList)
      .catch((caught: Error) => setError(caught.message));
  }, []);

  if (error) {
    return (
      <main className={styles.narrowPage}>
        <Brand home="customization" />
        <p className={styles.empty}>{error}</p>
        <a className={styles.quietLink} href="/">
          Go to the main menu
        </a>
      </main>
    );
  }
  if (!list) return <BookLoader label="Opening your achievements" />;

  return (
    <main className={styles.narrowPage}>
      <div className={styles.pageNav}>
        <Brand home="customization" />
        <div className={styles.pageLinks}>
          <a href="/profile">Profile</a>
          <a href="/academia">Academia</a>
        </div>
      </div>
      <section className={styles.panel}>
        <h1 className={styles.heading}>Achievements</h1>
        <p className={styles.empty}>
          {list.earned} of {list.total} earned. Tiers run bronze, silver, gold and platinum; a mystery
          tier keeps what it takes a secret until you earn it.
        </p>
        {list.new.length > 0 && <p className={styles.notice}>Just credited: {earnedLine(list.new)}</p>}
      </section>
      {list.achievements.map((achievement) => (
        <AchievementCard key={achievement.id} achievement={achievement} />
      ))}
    </main>
  );
}
