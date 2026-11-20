import type { ReactNode } from "react";
import { Avatar } from "../avatar/Avatar";
import type { Card } from "../lib/social";
import styles from "../styles.module.css";

/** One account in a social list: avatar, name and handle (linking to their profile), a line of
 *  detail, and whatever buttons the list offers. Plain, no banner: banners belong on
 *  leaderboards, and a list of them is too busy (Ryan, Nov 4, 2026). Levels stay off names. */
export function PersonRow({ card, detail, children }: { card: Card; detail?: ReactNode; children?: ReactNode }) {
  const line = [card.handle ? `@${card.handle}` : null, detail].filter(Boolean);
  return (
    <div className={styles.personRow}>
      <a className={styles.personMain} href={`/u/${card.public_id}`}>
        <Avatar avatar={card.avatar} size={36} label="" />
        <span className={styles.personText}>
          <span className={styles.nameText}>{card.name}</span>
          {line.length > 0 && (
            <span className={styles.personDetail}>
              {line.map((part, index) => (
                <span key={index}>
                  {index > 0 && " · "}
                  {part}
                </span>
              ))}
            </span>
          )}
        </span>
      </a>
      {children && <span className={styles.personActions}>{children}</span>}
    </div>
  );
}
