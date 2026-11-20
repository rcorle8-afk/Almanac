import type { ReactNode } from "react";
import type { GroupIconData } from "../lib/social";
import styles from "../styles.module.css";

/* A shield's colour and the ink drawn on it. The names are the server's (social.GROUP_COLORS),
   from the same family as the banners: blues, a forest green, purples and paper white, with
   no buy green, sell red or gold. A server test checks every name is here. */
export const GROUP_COLORS: Record<string, { tile: string; ink: string; label: string }> = {
  blue: { tile: "#2563eb", ink: "#ffffff", label: "Royal blue" },
  sky: { tile: "#7cc4ff", ink: "#06213f", label: "Sky" },
  navy: { tile: "#12254a", ink: "#cfe3ff", label: "Navy" },
  forest: { tile: "#14532d", ink: "#c9f7d6", label: "Forest" },
  mint: { tile: "#a7f3d0", ink: "#06382a", label: "Mint" },
  purple: { tile: "#4c1d95", ink: "#e4d9ff", label: "Deep purple" },
  lavender: { tile: "#c4b5fd", ink: "#27125c", label: "Lavender" },
  paper: { tile: "#f4f1e8", ink: "#12254a", label: "Paper" },
};

/* A wreath's leaves: five up each side of a circle, each turned out from the stem, with its
   mirror image. [x, y, degrees turned]. */
const LAUREL_LEAVES = [112, 140, 168, 196, 224].flatMap((degrees) => {
  const angle = (degrees * Math.PI) / 180;
  const x = Number((12 + 7.6 * Math.cos(angle)).toFixed(2));
  const y = Number((12.6 + 7.6 * Math.sin(angle)).toFixed(2));
  return [
    [x, y, degrees + 55],
    [24 - x, y, 125 - degrees],
  ];
});

const dot = (x: number, y: number, r = 1) => <circle key={`${x}-${y}`} cx={x} cy={y} r={r} fill="currentColor" stroke="none" />;

/* The drawings, as lines on a 24px grid in the shield's ink (social.GROUP_GLYPHS). "letters"
   has no drawing: it is the group's initials, and what every group starts with. The first
   dozen are single marks; the rest are fuller pictures (`fine`: a thinner line, so the detail
   holds at small sizes). */
const GLYPHS: Record<string, { label: string; art: ReactNode; fine?: boolean }> = {
  letters: { label: "Initials", art: null },
  book: {
    label: "Almanac",
    art: <path d="M12 6.5c-2-1.4-4.6-2-8-2v13c3.4 0 6 .6 8 2 2-1.4 4.6-2 8-2v-13c-3.4 0-6 .6-8 2Zm0 0v13" />,
  },
  bars: { label: "Bar chart", art: <path d="M3 20h18M6 20v-8M12 20V4.5M18 20v-5.5" /> },
  target: {
    label: "Target",
    art: (
      <>
        <circle cx="12" cy="12" r="8.5" />
        <circle cx="12" cy="12" r="4.5" />
        {dot(12, 12)}
      </>
    ),
  },
  bolt: { label: "Lightning", art: <path d="M13 2.5 5 13.5h6l-1 8 8-11h-6l1-8Z" /> },
  crown: { label: "Crown", art: <path d="M4.5 19h15M4.5 15.5 3 7.5l5 3.5 4-6 4 6 5-3.5-1.5 8h-15Z" /> },
  star: {
    label: "Star",
    art: <path d="m12 3 2.7 5.6 6.1.8-4.5 4.3 1.1 6.1L12 16.9l-5.4 2.9 1.1-6.1-4.5-4.3 6.1-.8L12 3Z" />,
  },
  shield: { label: "Shield", art: <path d="m12 3 7 3v5.5c0 4.3-2.9 7.6-7 9.5-4.1-1.9-7-5.2-7-9.5V6l7-3Z" /> },
  flask: {
    label: "Flask",
    art: <path d="M9 3h6M10.5 3v6L5 18.5A1.7 1.7 0 0 0 6.5 21h11a1.7 1.7 0 0 0 1.5-2.5L13.5 9V3M7.5 15h9" />,
  },
  compass: {
    label: "Compass",
    art: (
      <>
        <circle cx="12" cy="12" r="8.5" />
        <path d="m15.5 8.5-2 5-5 2 2-5 5-2Z" />
      </>
    ),
  },
  dice: {
    label: "Dice",
    art: (
      <>
        <rect x="4" y="4" width="16" height="16" rx="3" />
        {[
          [8.5, 8.5],
          [15.5, 8.5],
          [12, 12],
          [8.5, 15.5],
          [15.5, 15.5],
        ].map(([x, y]) => dot(x, y, 1.1))}
      </>
    ),
  },
  rocket: {
    label: "Rocket",
    art: (
      <>
        <path d="M12 2.5c3 2.3 4.5 5.5 4.5 9.5v4.5h-9V12c0-4 1.5-7.2 4.5-9.5Z" />
        <path d="M7.5 12.5 4.5 15.5v3.5l3-1.5M16.5 12.5l3 3v3.5l-3-1.5M10 19.5c.5 1 1.2 1.7 2 2 .8-.3 1.5-1 2-2" />
        <circle cx="12" cy="9.5" r="1.6" />
      </>
    ),
  },
  flame: {
    label: "Flame",
    art: <path d="M12.5 2.5c.5 3.5 4.5 5.5 4.5 10a5 5 0 0 1-10 0c0-2 .9-3.5 2.2-4.6.2 1.7 1 2.8 2 3.1-.5-2.9.1-5.9 1.3-8.5Z" />,
  },

  owl: {
    label: "Owl",
    fine: true,
    art: (
      <>
        <path d="M6.5 10c0-3.3 2.5-5.5 5.5-5.5s5.5 2.2 5.5 5.5v4.5c0 3.1-2.5 5.5-5.5 5.5s-5.5-2.4-5.5-5.5V10Z" />
        <path d="M7 7.2 5.5 3.8l3.3 1.6M17 7.2l1.5-3.4-3.3 1.6" />
        <circle cx="9.6" cy="10.2" r="2" />
        <circle cx="14.4" cy="10.2" r="2" />
        {dot(9.6, 10.2, 0.7)}
        {dot(14.4, 10.2, 0.7)}
        <path d="M11.1 12.3h1.8L12 13.9l-.9-1.6ZM9.5 16.2c.8.7 1.6 1 2.5 1s1.7-.3 2.5-1M10 20v1.5M14 20v1.5" />
      </>
    ),
  },
  lighthouse: {
    label: "Lighthouse",
    fine: true,
    art: (
      <>
        <path d="M9.3 21 10.6 9.5h2.8L14.7 21M10 9.5v-3h4v3M9.3 6.5 12 4l2.7 2.5M9 9.5h6M5 21h14" />
        <path d="M10.3 13.3h3.4M9.9 17.2h4.2" />
        <path d="M7.5 7 4 5.6M7.5 8.6 4 10M16.5 7 20 5.6M16.5 8.6 20 10" />
      </>
    ),
  },
  mountain: {
    label: "Mountains",
    fine: true,
    art: (
      <>
        <path d="M2.5 20h19M4.5 20 9.5 8l3.9 7.4M11.3 20l4.7-7.8 4.5 7.8" />
        <path d="M7.7 12.3l1.8 1.3 1.8-1.7M14.6 14.5l1.4.9 1.4-.9" />
        <circle cx="17.5" cy="6" r="2" />
      </>
    ),
  },
  anchor: {
    label: "Anchor",
    fine: true,
    art: (
      <>
        <circle cx="12" cy="5" r="2" />
        <path d="M12 7v13.5M8.5 10.5h7M5 13.5c0 4 3 7 7 7s7-3 7-7" />
        <path d="M5 13.5 3.2 16M5 13.5l2.5 1.5M19 13.5l1.8 2.5M19 13.5 16.5 15" />
      </>
    ),
  },
  castle: {
    label: "Castle",
    fine: true,
    art: (
      <>
        <path d="M4.5 10V4.5h3V7h3V4.5h3V7h3V4.5h3V10h-15Z" />
        <path d="M6 10v11h12V10M10 21v-4a2 2 0 0 1 4 0v4M12 11.8v2.4" />
      </>
    ),
  },
  hourglass: {
    label: "Hourglass",
    fine: true,
    art: (
      <>
        <path d="M6.5 3.5h11M6.5 20.5h11" />
        <path d="M8 3.5v3c0 2.3 4 3.6 4 5.5s-4 3.2-4 5.5v3M16 3.5v3c0 2.3-4 3.6-4 5.5s4 3.2 4 5.5v3" />
        <path d="M10 7.5h4M12 12v4M9.8 18.5h4.4" />
      </>
    ),
  },
  abacus: {
    label: "Abacus",
    fine: true,
    art: (
      <>
        <rect x="3.5" y="4.5" width="17" height="15" rx="1.5" />
        <path d="M3.5 8.5h17M3.5 12h17M3.5 15.5h17" />
        {[
          [7, 8.5],
          [9.6, 8.5],
          [16.5, 8.5],
          [7.5, 12],
          [13.5, 12],
          [16.1, 12],
          [6.5, 15.5],
          [9.1, 15.5],
          [11.7, 15.5],
          [17, 15.5],
        ].map(([x, y]) => dot(x, y, 1.3))}
      </>
    ),
  },
  globe: {
    label: "Globe",
    fine: true,
    art: (
      <>
        <circle cx="12" cy="10.5" r="7.5" />
        <ellipse cx="12" cy="10.5" rx="3.2" ry="7.5" />
        <path d="M4.5 10.5h15M6 6.5h12M6 14.5h12M12 18v3M8.5 21h7" />
      </>
    ),
  },
  laurel: {
    label: "Laurel",
    fine: true,
    art: (
      <>
        <path d="M12 20.2A7.6 7.6 0 0 1 7.6 6.4M12 20.2A7.6 7.6 0 0 0 16.4 6.4" />
        {LAUREL_LEAVES.map(([x, y, turn]) => (
          <ellipse key={`${x}-${turn}`} cx={x} cy={y} rx="2" ry="0.95" transform={`rotate(${turn} ${x} ${y})`} fill="currentColor" stroke="none" />
        ))}
        <path d="m12 9 .9 1.9 2.1.3-1.5 1.5.4 2.1-1.9-1-1.9 1 .4-2.1-1.5-1.5 2.1-.3.9-1.9Z" />
      </>
    ),
  },
  trophy: {
    label: "Trophy",
    fine: true,
    art: (
      <>
        <path d="M7.5 4h9v5a4.5 4.5 0 0 1-9 0V4Z" />
        <path d="M7.5 5.5h-3c0 2.6 1.2 4 3.3 4.2M16.5 5.5h3c0 2.6-1.2 4-3.3 4.2M12 13.5V17M9.5 17h5v3.5h-5V17ZM8 20.5h8" />
      </>
    ),
  },
  scales: {
    label: "Scales",
    fine: true,
    art: (
      <>
        <path d="M12 4.5V20M8 20.5h8M5 7h14" />
        <path d="M5 7 2.8 13h4.4L5 7ZM2.8 13a2.2 2.2 0 0 0 4.4 0M19 7l-2.2 6h4.4L19 7ZM16.8 13a2.2 2.2 0 0 0 4.4 0" />
        {dot(12, 4, 1)}
      </>
    ),
  },
  ship: {
    label: "Sailing ship",
    fine: true,
    art: (
      <>
        <path d="M3.5 16h17L18 20H6l-2.5-4Z" />
        <path d="M12 3.5V16M12 5.5l6 8.5h-6M11 7.5 6.5 14H11M12 3.5l2.2.9-2.2.9" />
      </>
    ),
  },
  atom: {
    label: "Atom",
    fine: true,
    art: (
      <>
        <ellipse cx="12" cy="12" rx="9.5" ry="3.8" />
        <ellipse cx="12" cy="12" rx="9.5" ry="3.8" transform="rotate(60 12 12)" />
        <ellipse cx="12" cy="12" rx="9.5" ry="3.8" transform="rotate(120 12 12)" />
        {dot(12, 12, 1.4)}
      </>
    ),
  },
};

export const GROUP_GLYPH_IDS = Object.keys(GLYPHS);
export const GROUP_COLOR_IDS = Object.keys(GROUP_COLORS);
export const glyphLabel = (id: string) => GLYPHS[id]?.label ?? id;
export const DEFAULT_GROUP_ICON: GroupIconData = { glyph: "letters", color: "blue", image: null };

/** "IU FinTech Club" -> "IF"; "Quants" -> "Q". */
function initials(name: string) {
  return name
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((word) => [...word][0]?.toUpperCase() ?? "")
    .join("");
}

interface GroupIconProps {
  icon: GroupIconData;
  /** The group's name, for its initials. */
  name: string;
  size?: number;
}

/** A group's icon wherever the group is named: a shield (Ryan's sketch, Nov 11, 2026) carrying
 *  its uploaded picture when it has one this viewer may see, otherwise its drawing (or
 *  initials) on its colour. Decorative: the name is always written beside it. */
export function GroupIcon({ icon, name, size = 40 }: GroupIconProps) {
  const box = { width: size, height: size };
  if (icon.image) return <img className={styles.groupIcon} src={icon.image} alt="" style={box} />;
  const tone = GROUP_COLORS[icon.color] ?? GROUP_COLORS.blue;
  const glyph = GLYPHS[icon.glyph];
  const drawn = Math.round(size * 0.54);
  return (
    <span
      className={styles.groupIcon}
      style={{ ...box, background: tone.tile, color: tone.ink, fontSize: Math.round(size * 0.36) }}
      aria-hidden="true"
    >
      {/* Sits a little high: a shield's weight is in its top half. */}
      <span className={styles.groupIconMark}>
        {glyph?.art ? (
          <svg viewBox="0 0 24 24" width={drawn} height={drawn} className={glyph.fine ? styles.groupIconFine : undefined}>
            {glyph.art}
          </svg>
        ) : (
          initials(name) || "?"
        )}
      </span>
    </span>
  );
}

interface PickerProps {
  glyph: string;
  color: string;
  /** The group's name, for the initials choice. */
  name: string;
  disabled?: boolean;
  onGlyph: (glyph: string) => void;
  onColor: (color: string) => void;
}

/** Every drawing, shown on the chosen colour, then every colour. Used where a group is
 *  customized and where one is created. */
export function GroupIconPicker({ glyph, color, name, disabled = false, onGlyph, onColor }: PickerProps) {
  return (
    <>
      <div className={styles.iconChoices} role="group" aria-label="Icon">
        {GROUP_GLYPH_IDS.map((id) => (
          <button
            key={id}
            type="button"
            className={`${styles.iconChoice} ${glyph === id ? styles.iconChoiceOn : ""}`}
            aria-pressed={glyph === id}
            aria-label={glyphLabel(id)}
            title={glyphLabel(id)}
            disabled={disabled}
            onClick={() => onGlyph(id)}
          >
            <GroupIcon icon={{ glyph: id, color, image: null }} name={name} size={40} />
          </button>
        ))}
      </div>
      <div className={styles.swatches} role="group" aria-label="Colour">
        {GROUP_COLOR_IDS.map((id) => (
          <button
            key={id}
            type="button"
            className={`${styles.colorPick} ${color === id ? styles.colorPickOn : ""}`}
            style={{ background: GROUP_COLORS[id].tile }}
            aria-pressed={color === id}
            aria-label={GROUP_COLORS[id].label}
            title={GROUP_COLORS[id].label}
            disabled={disabled}
            onClick={() => onColor(id)}
          />
        ))}
      </div>
    </>
  );
}
