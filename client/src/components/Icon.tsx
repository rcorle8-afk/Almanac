import styles from "../styles.module.css";

/* Line icons for menus and tabs, drawn on a 24px grid in the current text colour. */
const ICONS = {
  social: (
    <>
      <circle cx="9" cy="8" r="3.2" />
      <path d="M3 19c0-3.3 2.7-5.5 6-5.5s6 2.2 6 5.5" />
      <circle cx="17.2" cy="9" r="2.4" />
      <path d="M16.8 13.6c2.5.3 4.2 2 4.2 4.6" />
    </>
  ),
  play: <path d="M8 20V5M4.5 8.5 8 5l3.5 3.5M16 4v15M12.5 15.5 16 19l3.5-3.5" />,
  customization: <path d="M8.5 4 3.5 7l2 3.5 2-1V20h9V9.5l2 1 2-3.5-5-3c-.6 1.3-1.9 2-3.5 2s-2.9-.7-3.5-2Z" />,
  groups: (
    <>
      <path d="m12 3 7 3v5.5c0 4.3-2.9 7.6-7 9.5-4.1-1.9-7-5.2-7-9.5V6l7-3Z" />
      <path d="m12 8.2 1.1 2.3 2.5.3-1.8 1.8.4 2.5L12 13.9l-2.2 1.2.4-2.5-1.8-1.8 2.5-.3L12 8.2Z" />
    </>
  ),
  bag: (
    <>
      <path d="M5 8h14l-1 12H6L5 8Z" />
      <path d="M9 8V7a3 3 0 0 1 6 0v1" />
    </>
  ),
  cap: (
    <>
      <path d="M2.5 9.5 12 5l9.5 4.5L12 14 2.5 9.5Z" />
      <path d="M6.5 11.8V16c1.4 1.4 3.3 2 5.5 2s4.1-.6 5.5-2v-4.2M21.5 9.5V15" />
    </>
  ),
  medal: (
    <>
      <circle cx="12" cy="14.5" r="5" />
      <path d="M8.5 3h7M8.5 3l2 6.7M15.5 3l-2 6.7" />
    </>
  ),
  plus: <path d="M12 5v14M5 12h14" />,
};

export type IconName = keyof typeof ICONS;

export function Icon({ name }: { name: IconName }) {
  return (
    <svg className={styles.menuIcon} viewBox="0 0 24 24" aria-hidden="true">
      {ICONS[name]}
    </svg>
  );
}

export function Chevron() {
  return (
    <svg className={styles.menuChevron} viewBox="0 0 24 24" aria-hidden="true">
      <path d="m9 5 7 7-7 7" />
    </svg>
  );
}
