import { Avatar } from "../avatar/Avatar";
import type { Player } from "../lib/types";
import styles from "../styles.module.css";
import { bannerClass } from "./Banner";
import { Prestige } from "./Prestige";

interface NameCardProps {
  name: string;
  banner: string | null | undefined;
  prestige: number | null | undefined;
  bot?: boolean;
}

/** A player's name as everyone sees it: the name on its banner with the small prestige star,
 *  always the same size and the same content (Ryan, Nov 4, 2026). Leaderboards, the profile,
 *  the locker and the banner previews all draw this one component, so a banner can't look
 *  different from one screen to the next. With no banner, the name and star show plain. */
export function NameCard({ name, banner, prestige, bot = false }: NameCardProps) {
  return (
    <span className={`${styles.nameCard} ${bannerClass(banner)}`}>
      <span className={styles.nameText}>{name}</span>
      {bot && <span className={styles.botTag}>bot</span>}
      <Prestige value={prestige} />
    </span>
  );
}

/** A player in a lobby or quote list: a plain pill with the avatar and name, no banner (Ryan,
 *  Nov 4, 2026: a room's worth of banners is too busy on the lobby and quote screens). `dim`
 *  greys it, for a player who is offline or hasn't quoted yet. */
export function PlayerChip({ player, dim }: { player: Player; dim: boolean }) {
  return (
    <span className={dim ? styles.chipOffline : styles.chip}>
      <Avatar avatar={player.avatar} size={22} label="" />
      {player.name}
      {player.bot && <span className={styles.botTag}>bot</span>}
    </span>
  );
}
