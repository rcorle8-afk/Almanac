import type { CSSProperties, KeyboardEvent, RefObject } from "react";
import { SCREENS, menuHref, type Screen } from "../lib/menu";
import styles from "../styles.module.css";
import { Icon } from "./Icon";

interface MenuBarProps {
  /** The screen that's lit: the one in view on the menu, or the one this page belongs to. */
  current: Screen;
  /** On the menu itself: its pager's bar, so the marker follows the swipe, and how to move it.
   *  Left out everywhere else, where each tab is a link back to that screen of the menu. */
  pager?: { bar: RefObject<HTMLElement>; go: (index: number) => void };
  /** Requests and invites waiting, shown as a dot on Social. */
  waiting?: number;
}

/**
 * The navigation at the bottom of every page: Social, Play, Customization (Ryan, Nov 11, 2026).
 * It is there on the menu and on every page reached from it, so moving between the three never
 * needs the Back button. The one place it is left out is a table (the phone's game view and the
 * host screen), where a stray tap mustn't take anyone out of a round.
 */
export function MenuBar({ current, pager, waiting = 0 }: MenuBarProps) {
  const at = SCREENS.findIndex((screen) => screen.id === current);

  function keys(event: KeyboardEvent<HTMLElement>) {
    if (!pager) return;
    const step = event.key === "ArrowRight" ? 1 : event.key === "ArrowLeft" ? -1 : 0;
    const next = at + step;
    if (!step || next < 0 || next >= SCREENS.length) return;
    event.preventDefault();
    pager.go(next);
    event.currentTarget.querySelectorAll("button")[next]?.focus({ preventScroll: true });
  }

  return (
    <footer className={pager ? styles.menuFoot : `${styles.menuFoot} ${styles.menuFootFixed}`}>
      <nav
        className={styles.menuTabs}
        aria-label="Screens"
        ref={pager?.bar}
        // The menu's pager keeps --at itself as the screens slide; elsewhere it stands still.
        style={pager ? undefined : ({ "--at": at } as CSSProperties)}
        onKeyDown={keys}
      >
        <span className={styles.menuTabMarker} aria-hidden="true" />
        {SCREENS.map((screen, index) => {
          const lit = screen.id === current;
          const content = (
            <>
              <span className={styles.menuTabIcon}>
                <Icon name={screen.id} />
                {screen.id === "social" && waiting > 0 && <span className={styles.menuDot} />}
              </span>
              {screen.label}
            </>
          );
          const label = screen.id === "social" && waiting > 0 ? `Social, ${waiting} waiting` : undefined;
          const className = `${styles.menuTab} ${lit ? styles.menuTabOn : ""}`;
          return pager ? (
            <button
              key={screen.id}
              type="button"
              className={className}
              aria-current={lit ? "page" : undefined}
              aria-label={label}
              onClick={() => pager.go(index)}
            >
              {content}
            </button>
          ) : (
            <a key={screen.id} className={className} href={menuHref(screen.id)} aria-current={lit ? "true" : undefined} aria-label={label}>
              {content}
            </a>
          );
        })}
      </nav>
    </footer>
  );
}
