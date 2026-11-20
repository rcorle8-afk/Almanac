import { Avatar } from "../avatar/Avatar";
import { pointsClass, signedPoints } from "../lib/format";
import type { Player } from "../lib/types";
import styles from "../styles.module.css";
import { NameCard } from "./NameCard";

interface ScoresProps {
  players: Player[];
  highlightId?: string;
  /** Drinks mode: a column with this round's drinks and the game's running total. */
  drinks?: boolean;
  /** Rows to show; the rest become an "and N more" line (the host screen with a big room). */
  limit?: number;
  /** Everyone seated, when `players` is only the leaders plus you (a phone in a big room). */
  total?: number;
  /** The host screen: big avatars and names, so the room looks at who is beating whom. */
  large?: boolean;
}

export function Scores({ players, highlightId, drinks = false, limit, total, large = false }: ScoresProps) {
  const ranked = [...players].sort((a, b) => Number(b.total_points) - Number(a.total_points));
  const shown = limit === undefined ? ranked : ranked.slice(0, limit);
  const hidden = ranked.length - shown.length;
  const seated = total ?? players.length;
  const rowClass = [
    styles.scoreRow,
    drinks ? styles.scoreRowDrinks : "",
    large ? styles.scoreRowLarge : "",
  ].join(" ");
  const avatarSize = large ? 48 : 22;
  return (
    <section className={styles.panel}>
      <h2 className={styles.panelTitle}>
        Leaderboard
        {seated > shown.length && (
          <span className={styles.panelMeta}>
            {" "}
            · top {shown.length} of {seated}
            {highlightId && shown.some((player) => player.id === highlightId) ? ", and you" : ""}
          </span>
        )}
      </h2>
      <div className={styles.rows}>
        <div className={`${rowClass} ${styles.scoreHead}`}>
          <span />
          <span>Player</span>
          <span>Round</span>
          <span>Total</span>
          {drinks && <span>Drinks</span>}
        </div>
        {shown.map((player, index) => (
          <div
            key={player.id}
            className={[
              rowClass,
              index === 0 ? styles.scoreLeader : "",
              player.id === highlightId ? styles.scoreYou : "",
            ].join(" ")}
          >
            <span className={styles.scoreRank}>{index + 1}</span>
            <span className={`${styles.nameWithAvatar} ${player.connected ? "" : styles.rowMuted}`}>
              <Avatar avatar={player.avatar} size={avatarSize} label="" />
              {/* The host's leaderboard leaves prestige off: the card gets the whole cell for the name. */}
              <NameCard
                name={player.name}
                banner={player.avatar?.banner}
                prestige={large ? null : player.prestige}
                bot={player.bot}
              />
            </span>
            <span className={pointsClass(Number(player.round_points), styles)}>
              {player.round_points === null ? "–" : signedPoints(player.round_points)}
            </span>
            <span className={pointsClass(Number(player.total_points), styles)}>
              {signedPoints(player.total_points)}
            </span>
            {drinks && (
              <span className={styles.scoreDrinks}>
                {player.drinks === null ? "–" : player.drinks}
                <small> / {player.drinks_total}</small>
              </span>
            )}
          </div>
        ))}
      </div>
      {hidden > 0 && (
        <p className={styles.empty}>
          and {hidden} more {hidden === 1 ? "player" : "players"}
        </p>
      )}
    </section>
  );
}
