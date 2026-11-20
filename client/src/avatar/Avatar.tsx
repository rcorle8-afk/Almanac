import { useId } from "react";
import { useCatalog } from "../lib/catalog";
import type { AvatarConfig } from "../lib/types";
import styles from "../styles.module.css";
import { EFFECTS_BACK, EFFECTS_FRONT, effectDefs } from "./effects";
import * as parts from "./parts";

const FALLBACK = { skin: "#d9a375", hair: "#1f1a17", eyes: "#5a3a1a", top: "#2f6fd6" };
const RAINBOW = ["#ef4444", "#f59e0b", "#22c55e", "#3b82f6", "#a855f7"];
// Someone who has asked their device for less motion keeps calm routes fully calm.
const MOTION_ALLOWED =
  typeof window === "undefined" || !window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;

interface AvatarProps {
  avatar: AvatarConfig | null;
  size?: number;
  label?: string;
}

export function Avatar({ avatar, size = 32, label = "avatar" }: AvatarProps) {
  const catalog = useCatalog();
  const uid = useId().replace(/:/g, "");
  const svgProps = {
    width: size,
    height: size,
    viewBox: "0 0 100 100",
    role: "img" as const,
    "aria-label": label,
    className: styles.avatar,
  };

  if (!avatar) return <svg {...svgProps}>{parts.silhouette()}</svg>;

  const color = (id: string | null | undefined, fallback: string) =>
    (id && catalog?.byId[id]?.color) || fallback;
  const hair = color(avatar.hair_color, FALLBACK.hair);
  const palette: parts.Palette = {
    skin: color(avatar.skin, FALLBACK.skin),
    hair: hair === "rainbow" ? `url(#rainbow-${uid})` : hair,
    eyes: color(avatar.eyes, FALLBACK.eyes),
    top: color(avatar.top, FALLBACK.top),
    uid,
  };
  // A legendary or mythical item moves on every page, calm routes included (Ryan, Nov 17, 2026):
  // its art is wrapped in .lively, which the calm rules in styles.module.css leave alone.
  const draw = (table: parts.Parts, id: string | null | undefined) => {
    if (!id || !table[id]) return null;
    const art = table[id](palette);
    const rarity = catalog?.byId[id]?.rarity;
    const lively = MOTION_ALLOWED && (rarity === "legendary" || rarity === "mythical");
    return lively ? <g className={styles.lively}>{art}</g> : art;
  };

  return (
    <svg {...svgProps}>
      <defs>
        <linearGradient id={`rainbow-${uid}`} x1="0" y1="0" x2="1" y2="1">
          {RAINBOW.map((stop, index) => (
            <stop key={stop} offset={index / (RAINBOW.length - 1)} stopColor={stop} />
          ))}
        </linearGradient>
        {effectDefs(uid)}
      </defs>
      {draw(EFFECTS_BACK, avatar.effect)}
      {/* The body sits HEADROOM lower than its drawings, so hats have space above the head. */}
      <g transform={`translate(0 ${parts.HEADROOM})`}>
        {draw(parts.HAIR_BACK, avatar.hair)}
        {draw(parts.TOPS, avatar.top) ?? parts.torso(palette.top)}
        <rect x="44" y="56" width="12" height="20" fill={palette.skin} />
        <ellipse cx="50" cy="41" rx="24" ry="25" fill={palette.skin} />
        <circle cx="26" cy="44" r="5" fill={palette.skin} />
        <circle cx="74" cy="44" r="5" fill={palette.skin} />
        {draw(parts.EARRINGS, avatar.ears)}
        {parts.face(palette)}
        {draw(parts.MOUTHS, avatar.mouth) ?? parts.MOUTHS.mouth_smile(palette)}
        {draw(parts.HAIR_FRONT, avatar.hair)}
        {draw(parts.EYEWEAR, avatar.eyewear)}
      </g>
      {draw(parts.HEADWEAR, avatar.head)}
      {draw(EFFECTS_FRONT, avatar.effect)}
    </svg>
  );
}
