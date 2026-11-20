import { useEffect, useState } from "react";
import { BookLoader } from "../components/BookLoader";
import { NameCard } from "../components/NameCard";
import { rarityStyle } from "../components/ItemTile";
import { Brand } from "../components/TopBar";
import { fetchRoad, type Milestone, type Road as RoadData } from "../lib/shop";
import styles from "../styles.module.css";

function Track({
  title,
  blurb,
  milestones,
  name,
  prestige,
  standing,
  unit,
}: {
  title: string;
  blurb: string;
  milestones: Milestone[];
  name: string;
  prestige: number;
  standing: number;
  unit: string;
}) {
  const nextIndex = milestones.findIndex((m) => !m.unlocked);
  return (
    <section className={styles.panel}>
      <div className={styles.roadHead}>
        <h2 className={styles.panelTitle}>{title}</h2>
        <span className={styles.empty}>{blurb}</span>
      </div>
      {milestones.map((m, index) => (
        <div
          key={m.item.id}
          className={[
            styles.roadRow,
            m.unlocked ? "" : styles.roadLocked,
            index === nextIndex ? styles.roadNext : "",
          ].join(" ")}
        >
          <div>
            <NameCard name={name} banner={m.item.id} prestige={prestige} />
            <div className={styles.roadMeta} style={rarityStyle(m.item.rarity)}>
              <span className={styles.rarityTag}>{m.item.rarity}</span>
              <span>{m.item.name}</span>
            </div>
          </div>
          <div className={styles.roadStatus}>
            <div>
              {unit === "level" ? `Level ${m.at}` : `${m.at} prestige`}
            </div>
            <div className={m.unlocked ? styles.gain : styles.rowMuted}>
              {m.unlocked
                ? "Unlocked"
                : index === nextIndex
                  ? `${m.at - standing} ${unit === "level" ? (m.at - standing === 1 ? "level" : "levels") : "prestige"} to go`
                  : "Locked"}
            </div>
          </div>
        </div>
      ))}
    </section>
  );
}

/** Academia (the trophy road): what's been earned, what comes next, and what only winners will carry. */
export function Academia() {
  const [road, setRoad] = useState<RoadData | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetchRoad()
      .then(setRoad)
      .catch((caught: Error) => setError(caught.message));
  }, []);

  if (error) {
    return (
      <main className={styles.narrowPage}>
        <Brand home="customization" />
        <p className={styles.empty}>{error} Academia needs a signed-in account.</p>
        <a className={styles.quietLink} href="/">
          Go to the main menu
        </a>
      </main>
    );
  }
  if (!road) return <BookLoader label="Opening Academia" />;

  const { user } = road;
  return (
    <main className={styles.narrowPage}>
      <div className={styles.pageNav}>
        <Brand home="customization" />
        <div className={styles.pageLinks}>
          <a href="/locker">Locker room</a>
          <a href="/profile">Profile</a>
        </div>
      </div>

      <section className={styles.panel}>
        <h1 className={styles.heading}>Academia</h1>
        <p className={styles.empty}>
          Level {user.level} · {user.xp} XP · {user.prestige} prestige. Banners here are earned,
          never bought; wear them from the locker room.
        </p>
      </section>

      <Track
        title="Levels"
        blurb="XP from every game"
        milestones={road.levels}
        name={user.name}
        prestige={user.prestige}
        standing={user.level}
        unit="level"
      />
      <Track
        title="Prestige"
        blurb="wins, podiums, Best Quotes"
        milestones={road.prestige}
        name={user.name}
        prestige={user.prestige}
        standing={user.prestige}
        unit="prestige"
      />

      <section className={styles.panel}>
        <div className={styles.roadHead}>
          <h2 className={styles.panelTitle}>Reserved</h2>
          <span className={styles.empty}>tournaments and live games, coming</span>
        </div>
        {road.reserved.map((item) => (
          <div key={item.id} className={`${styles.roadRow} ${styles.roadLocked}`}>
            <div>
              <NameCard name={user.name} banner={item.id} prestige={user.prestige} />
              <div className={styles.roadMeta} style={rarityStyle(item.rarity)}>
                <span className={styles.rarityTag}>{item.rarity}</span>
                <span>{item.name}</span>
              </div>
            </div>
            <div className={`${styles.roadStatus} ${styles.rowMuted}`}>
              {item.source === "tournament" ? "Tournament winners" : "Live game winners"}
            </div>
          </div>
        ))}
      </section>
    </main>
  );
}
