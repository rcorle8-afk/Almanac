import { Avatar } from "../avatar/Avatar";
import type { Player, TapeEntry } from "../lib/types";
import styles from "../styles.module.css";

interface TapeProps {
  tape: TapeEntry[];
  players: Player[];
  limit?: number;
}

export function Tape({ tape, players, limit }: TapeProps) {
  // Names are unique within a room, so they are enough to find each player's avatar.
  const avatarOf = (name: string) => players.find((player) => player.name === name)?.avatar ?? null;
  return (
    <section className={styles.panel}>
      <h2 className={styles.panelTitle}>Trades</h2>
      {tape.length === 0 && <p className={styles.empty}>No trades yet</p>}
      <div className={styles.rows}>
        {tape.slice(0, limit).map((fill) => (
          <div key={fill.seq} className={`${styles.row} ${styles.tapeRow}`}>
            <span className={styles.tapePrice}>
              {fill.size} @ {fill.price}
            </span>
            <span className={styles.tapeWho}>
              <Avatar avatar={avatarOf(fill.buyer)} size={18} label="" />
              <span className={styles.nameText}>{fill.buyer}</span>
              <span className={styles.tapeVerb}>bought from</span>
              <Avatar avatar={avatarOf(fill.seller)} size={18} label="" />
              <span className={styles.nameText}>{fill.seller}</span>
            </span>
          </div>
        ))}
      </div>
    </section>
  );
}
