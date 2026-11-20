import { useId } from "react";
import type { Tier } from "../lib/achievements";
import styles from "../styles.module.css";

/** Badge icons on a 24px grid, drawn as strokes in the badge's ink. Keys match the `icon` of
 *  each achievement in server/achievements.py. */
const ICONS: Record<string, string> = {
  flame: "M12 3c.6 2.9 3.8 4.6 3.8 8.4a3.8 3.8 0 0 1-7.6 0c0-1.7.8-2.8 1.8-3.6.1 1.3.8 2.2 1.8 2.5-.4-2.5-.4-4.9.2-7.3Z",
  trophy: "M8 4h8v4a4 4 0 0 1-8 0V4ZM8 6H5a3 3 0 0 0 3 4M16 6h3a3 3 0 0 1-3 4M12 12v4M10 16h4v4h-4zM8.5 20h7",
  podium: "M3 20v-7h6v7M9 20V8h6v12M15 20v-5h6v5M2 20h20",
  brackets: "M8 5H5v14h3M16 5h3v14h-3M12 9v6",
  target: "M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18ZM12 7.5a4.5 4.5 0 1 0 0 9 4.5 4.5 0 0 0 0-9ZM12 11.5v1",
  chart: "M3 20h18M5 16l4-4 3 3 6-7M14 8h4v4",
  swap: "M4 8h13l-3-3M20 16H7l3 3",
  calendar: "M4 6h16v14H4zM4 10h16M8 3v4M16 3v4M8 14h2M14 14h2M8 17h2",
  coins:
    "M12 4c3.9 0 7 1.3 7 3s-3.1 3-7 3-7-1.3-7-3 3.1-3 7-3ZM5 7v5c0 1.7 3.1 3 7 3s7-1.3 7-3V7M5 12v5c0 1.7 3.1 3 7 3s7-1.3 7-3v-5",
  hanger: "M10 5a2 2 0 1 1 2 2v2L3 16h18l-9-7",
  people: "M9 11a3 3 0 1 0 0-6 3 3 0 0 0 0 6ZM3 20c0-3.3 2.7-6 6-6s6 2.7 6 6M16 11a2.5 2.5 0 1 0 0-5M17 14c2.4.4 4 2.6 4 5",
  glass: "M6 4h12l-1.5 7a4.5 4.5 0 0 1-9 0L6 4ZM12 15.5V20M8.5 20h7M7 8h10",
  flag: "M5 21V4M5 4h11l-2 4 2 4H5",
  question: "M9.2 9a2.9 2.9 0 1 1 4.3 2.5c-.9.5-1.5 1.1-1.5 2.1v.6M12 17.6v.2",
};

/** One of the badge icons on its own, in the current text color (the game awards use these). */
export function Icon({ name, size = 20 }: { name: string; size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" aria-hidden="true" className={styles.badge}>
      <path
        d={ICONS[name] ?? ICONS.question}
        fill="none"
        stroke="currentColor"
        strokeWidth="1.8"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}

/** Ring (two stops), face and ink for each tier. Mystery is the deep purple one. */
const TIER_COLORS: Record<Tier, { ring: [string, string]; face: string; ink: string }> = {
  bronze: { ring: ["#7a4a24", "#d29a5c"], face: "#2b1a0e", ink: "#e9b884" },
  silver: { ring: ["#7d8693", "#e6eaef"], face: "#20252c", ink: "#e6eaef" },
  gold: { ring: ["#9a6b06", "#f5c242"], face: "#2c2106", ink: "#f7d77a" },
  platinum: { ring: ["#7fa6bd", "#eef9ff"], face: "#162530", ink: "#e8f6ff" },
  mystery: { ring: ["#4c1d95", "#a78bfa"], face: "#140d27", ink: "#c4b5fd" },
};

interface BadgeProps {
  icon: string;
  tier: Tier;
  size?: number;
  /** Not earned yet: drawn grey and faint. */
  locked?: boolean;
  label?: string;
}

/** An achievement badge: a medallion in its tier's colors with a small icon for what it's for.
 *  Every mystery tier shows a question mark, earned or not. */
export function Badge({ icon, tier, size = 40, locked = false, label }: BadgeProps) {
  const uid = useId().replace(/:/g, "");
  const colors = TIER_COLORS[tier];
  const path = ICONS[tier === "mystery" ? "question" : icon] ?? ICONS.question;
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 48 48"
      role="img"
      aria-label={label ?? `${tier} badge`}
      className={`${styles.badge} ${locked ? styles.badgeLocked : ""}`}
    >
      <defs>
        <linearGradient id={`ring-${uid}`} x1="0" y1="0" x2="1" y2="1">
          <stop offset="0" stopColor={colors.ring[1]} />
          <stop offset="1" stopColor={colors.ring[0]} />
        </linearGradient>
      </defs>
      <circle cx="24" cy="24" r="22.5" fill={`url(#ring-${uid})`} />
      <circle cx="24" cy="24" r="18" fill={colors.face} />
      <circle cx="24" cy="24" r="20.2" fill="none" stroke="rgba(255,255,255,0.22)" strokeWidth="0.8" />
      <g transform="translate(12 12)">
        <path
          d={path}
          fill="none"
          stroke={colors.ink}
          strokeWidth={tier === "mystery" ? 2.4 : 1.8}
          strokeLinecap="round"
          strokeLinejoin="round"
        />
      </g>
    </svg>
  );
}
