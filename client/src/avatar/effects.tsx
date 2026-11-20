/*
 * Animated parts: the effects slot and the mythical outfit. Effects are drawn in canvas space
 * (head top y=22, head centre (50, 47), shoulders from y=80); the outfit in body space like
 * any other top. The animations are CSS keyframes in styles.module.css. They play where a
 * player dresses the avatar (locker, marketplace, profile); inside a `.calm` route (the host
 * screen, the phone's game view, leaderboards) the same classes freeze each effect in a resting
 * pose, so a leaderboard of twenty avatars stays still. Legendary and mythical items are the
 * exception: Avatar.tsx wraps them in `.lively` and they move on every page. Gradient ids carry
 * the avatar's uid because a page can show dozens of avatars at once.
 */
import type { ReactNode } from "react";
import styles from "../styles.module.css";
import type { Palette, Parts } from "./parts";

const TORSO = "M 18 100 L 18 90 Q 18 74 36 74 L 64 74 Q 82 74 82 90 L 82 100 Z";

/** A flame whose base sits inside the head outline, so the head and hair hide its bottom. */
function flame(x: number, base: number, height: number, width: number, delay: number, speed: number) {
  const tongue = (w: number, h: number, bulge: number) =>
    `M ${x - w} ${base + 10} C ${x - w - bulge} ${base - h * 0.25} ${x - w * 0.45} ${base - h * 0.55} ${x} ${base - h} C ${x + w * 0.45} ${base - h * 0.55} ${x + w + bulge} ${base - h * 0.25} ${x + w} ${base + 10} Z`;
  return (
    <g
      key={x}
      className={styles.flame}
      style={{ animationDelay: `${delay}s`, animationDuration: `${speed}s` }}
    >
      <path d={tongue(width, height, 5)} fill="#f97316" />
      <path d={tongue(width * 0.55, height * 0.6, 3)} fill="#fde047" />
    </g>
  );
}

function spark(x: number, y: number, delay: number) {
  return (
    <circle
      key={`${x}-${y}`}
      cx={x}
      cy={y}
      r="1.6"
      fill="#fde68a"
      className={styles.spark}
      style={{ animationDelay: `${delay}s` }}
    />
  );
}

function bill(x: number, delay: number, speed: number) {
  return (
    <g key={x} className={styles.bill} style={{ animationDelay: `${delay}s`, animationDuration: `${speed}s` }}>
      <rect x={x - 6} y="-4" width="12" height="7" rx="1.2" fill="#22c55e" stroke="#15803d" strokeWidth="0.8" />
      <circle cx={x} cy="-0.5" r="1.6" fill="#bbf7d0" />
    </g>
  );
}

function bolt(points: string, delay: number) {
  return (
    <g>
      <circle cx="50" cy="40" r="46" fill="#fef9c3" className={styles.flash} style={{ animationDelay: `${delay}s` }} />
      <path
        d={points}
        fill="#fde047"
        stroke="#fef9c3"
        strokeWidth="1"
        strokeLinejoin="round"
        className={styles.bolt}
        style={{ animationDelay: `${delay}s` }}
      />
    </g>
  );
}

function twinkle(x: number, y: number, r: number, fill: string, delay: number) {
  const d = `M ${x} ${y - r} L ${x + r * 0.3} ${y - r * 0.3} L ${x + r} ${y} L ${x + r * 0.3} ${y + r * 0.3} L ${x} ${y + r} L ${x - r * 0.3} ${y + r * 0.3} L ${x - r} ${y} L ${x - r * 0.3} ${y - r * 0.3} Z`;
  return (
    <path key={`${x}-${y}`} d={d} fill={fill} className={styles.twinkle} style={{ animationDelay: `${delay}s` }} />
  );
}

/** Effects drawn behind the body. */
export const EFFECTS_BACK: Parts = {
  "effect_fire": () => (
    <g>
      {flame(28, 40, 30, 7, 0, 0.5)}
      {flame(38, 26, 36, 8, 0.15, 0.62)}
      {flame(50, 22, 42, 9, 0.3, 0.55)}
      {flame(62, 26, 36, 8, 0.1, 0.68)}
      {flame(72, 40, 30, 7, 0.22, 0.52)}
      {spark(36, 10, 0)}
      {spark(55, 6, 0.6)}
      {spark(66, 12, 1.1)}
    </g>
  ),
  "effect_cash": () => (
    <g>
      {bill(8, 0, 2.6)}
      {bill(20, -0.9, 3.0)}
      {bill(34, -1.7, 2.4)}
      {bill(50, -0.4, 2.9)}
      {bill(66, -2.1, 2.5)}
      {bill(80, -1.3, 3.1)}
      {bill(92, -0.6, 2.7)}
    </g>
  ),
  "effect_lightning": () => (
    <g>
      {bolt("M 18 0 L 6 30 L 15 30 L 7 56 L 28 22 L 18 22 L 26 0 Z", 0)}
      {bolt("M 84 4 L 94 28 L 86 28 L 95 52 L 74 24 L 83 24 L 76 4 Z", 2.7)}
    </g>
  ),
  "effect_void": (p) => (
    <g>
      <circle cx="50" cy="50" r="44" fill="#6d28d9" className={styles.pulse} />
      <g className={styles.orbit}>
        <ellipse cx="50" cy="50" rx="46" ry="30" fill="none" stroke={`url(#neon-${p.uid})`} strokeWidth="2.5" strokeDasharray="14 8" />
        <circle cx="96" cy="50" r="3.5" fill="#22d3ee" />
        <circle cx="27" cy="24" r="2.5" fill="#a855f7" />
        <circle cx="27" cy="76" r="2.5" fill="#3d8bff" />
      </g>
      <g className={styles.orbitReverse}>
        <ellipse cx="50" cy="50" rx="34" ry="46" fill="none" stroke={`url(#neon-${p.uid})`} strokeWidth="1.5" strokeDasharray="6 10" opacity="0.7" />
      </g>
    </g>
  ),
};

/** Effects drawn over the body. */
export const EFFECTS_FRONT: Parts = {
  "effect_sparkles": () => (
    <g>
      {twinkle(16, 24, 6, "#fff", 0)}
      {twinkle(84, 20, 5, "#fde047", 0.4)}
      {twinkle(20, 68, 4, "#fde047", 0.8)}
      {twinkle(86, 58, 6, "#fff", 1.1)}
      {twinkle(50, 5, 4, "#fff", 0.6)}
    </g>
  ),
};

/** Gradients and clips the animated parts refer to by id; goes in the avatar's <defs>. */
export function effectDefs(uid: string): ReactNode {
  return (
    <>
      <linearGradient id={`neon-${uid}`} x1="0" y1="0" x2="1" y2="1">
        <stop offset="0" stopColor="#3d8bff" />
        <stop offset="0.5" stopColor="#22d3ee" />
        <stop offset="1" stopColor="#a855f7" />
      </linearGradient>
      <linearGradient id={`galaxy-${uid}`} x1="0" y1="0" x2="1" y2="1">
        <stop offset="0" stopColor="#1e1b4b" />
        <stop offset="0.5" stopColor="#6d28d9" />
        <stop offset="1" stopColor="#1d4ed8" />
      </linearGradient>
      <linearGradient id={`sheen-${uid}`} x1="0" y1="0" x2="1" y2="0">
        <stop offset="0" stopColor="#fff" stopOpacity="0" />
        <stop offset="0.5" stopColor="#fff" stopOpacity="0.35" />
        <stop offset="1" stopColor="#fff" stopOpacity="0" />
      </linearGradient>
      <clipPath id={`torso-${uid}`}>
        <path d={TORSO} />
      </clipPath>
    </>
  );
}

/** The mythical outfit: a starfield with a light sweeping across it. */
export function galaxyArmour(p: Palette): ReactNode {
  return (
    <>
      <path d={TORSO} fill={`url(#galaxy-${p.uid})`} />
      <path d="M 50 74 L 50 100" stroke="#22d3ee" strokeWidth="1.5" opacity="0.8" />
      <path d="M 22 86 Q 50 92 78 86" stroke="#a855f7" strokeWidth="1.5" fill="none" opacity="0.8" />
      <circle cx="22" cy="78" r="7" fill="#312e81" stroke="#22d3ee" />
      <circle cx="78" cy="78" r="7" fill="#312e81" stroke="#22d3ee" />
      {twinkle(32, 92, 2.5, "#fff", 0.3)}
      {twinkle(68, 84, 2, "#fff", 0.9)}
      {twinkle(58, 96, 1.8, "#a5f3fc", 1.4)}
      <g clipPath={`url(#torso-${p.uid})`}>
        <rect x="18" y="74" width="64" height="26" fill={`url(#sheen-${p.uid})`} className={styles.sheen} />
      </g>
    </>
  );
}
