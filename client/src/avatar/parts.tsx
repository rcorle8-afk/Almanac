/*
 * The art for every catalog item, keyed by item id (server/cosmetics.py is the catalog).
 *
 * Two coordinate spaces, both 100 wide:
 * - Body space (hair, face, mouths, eyewear, earrings, tops): head centred at (50, 41) with
 *   its top at y=16, brows at y=31, shoulders from y=74. Avatar.tsx shifts all of it down
 *   by HEADROOM, so a part may reach up to y=-HEADROOM and still be on the canvas.
 * - Canvas space (headwear, props): the same head top sits at y=22 and the brows at y=37.
 *   Hats rest on the head top or at the hairline (y 26-30), never over the brows.
 *
 * Keys are quoted on purpose: a server test checks each item id appears here.
 */
import type { ReactNode } from "react";
import { galaxyArmour } from "./effects";

export const HEADROOM = 6;

export interface Palette {
  skin: string;
  hair: string; // a color, or url(#gradient) for rainbow hair
  eyes: string;
  top: string;
  uid: string;
}

export type Part = (palette: Palette) => ReactNode;
export type Parts = Record<string, Part>;

const MOUTH_LINE = "#7a3b2e";
const TORSO = "M 18 100 L 18 90 Q 18 74 36 74 L 64 74 Q 82 74 82 90 L 82 100 Z";

export function torso(fill: string, extra?: ReactNode): ReactNode {
  return (
    <>
      <path d={TORSO} fill={fill} />
      {extra}
    </>
  );
}

export function face(p: Palette): ReactNode {
  return (
    <>
      <path d="M 34 32 Q 40 28 46 31" stroke={p.hair} strokeWidth="2" fill="none" strokeLinecap="round" />
      <path d="M 54 31 Q 60 28 66 32" stroke={p.hair} strokeWidth="2" fill="none" strokeLinecap="round" />
      {[40, 60].map((x) => (
        <g key={x}>
          <ellipse cx={x} cy="41" rx="5" ry="5.5" fill="#fff" />
          <circle cx={x} cy="41.5" r="3" fill={p.eyes} />
          <circle cx={x} cy="41.5" r="1.4" fill="#111" />
          <circle cx={x - 1.2} cy="40" r="0.9" fill="#fff" />
        </g>
      ))}
      <path d="M 50 44 Q 48 50 51 51" stroke="rgba(0,0,0,0.25)" strokeWidth="1.5" fill="none" strokeLinecap="round" />
    </>
  );
}

export function silhouette(): ReactNode {
  return (
    <g fill="#2a3647" stroke="#3d8bff" strokeWidth="2">
      <circle cx="50" cy="38" r="22" />
      <path d="M 18 100 L 18 92 Q 18 70 40 70 L 60 70 Q 82 70 82 92 L 82 100 Z" />
    </g>
  );
}

/* ---------------------------------------------------------------------------------------------
 * Hair. Each style is a clean silhouette with a real hairline, detailed with a few wavy lines
 * that follow the way the hair falls (Ryan, Nov 4, 2026: no noisy texture, more wavy lines).
 * The lines are translucent black, so they read on any hair color, rainbow included. Geometry
 * is computed once when the module loads. Symmetric styles draw the left half and mirror it.
 * ------------------------------------------------------------------------------------------- */

const SHADE = "rgba(0,0,0,0.28)";
const TIE = "#2a3140";
const BEAD = "#e8d6a2";
const MIRROR = "translate(100 0) scale(-1 1)";

const r1 = (value: number) => Math.round(value * 10) / 10;

/** A point on an ellipse, as "x y". Angles in degrees: 0 is right, 90 is down. */
function onEllipse(cx: number, cy: number, rx: number, ry: number, deg: number): string {
  const a = (deg * Math.PI) / 180;
  return `${r1(cx + rx * Math.cos(a))} ${r1(cy + ry * Math.sin(a))}`;
}

/** Even bumps along an ellipse arc: positive depth bulges out (a curly outline), negative in. */
function scallop(cx: number, cy: number, rx: number, ry: number, from: number, to: number, n: number, depth: number): string {
  const k = 1 + depth;
  let d = "";
  for (let i = 0; i < n; i++) {
    const a0 = from + ((to - from) * i) / n;
    const a1 = from + ((to - from) * (i + 1)) / n;
    d += ` Q ${onEllipse(cx, cy, rx * k, ry * k, (a0 + a1) / 2)} ${onEllipse(cx, cy, rx, ry, a1)}`;
  }
  return d;
}

/** A wavy line along an ellipse arc: `waves` full waves of `amp` units from `from` to `to`. */
function waveArc(cx: number, cy: number, rx: number, ry: number, from: number, to: number, waves: number, amp: number): string {
  const steps = Math.max(16, Math.round(waves * 12));
  const points: string[] = [];
  for (let i = 0; i <= steps; i++) {
    const t = i / steps;
    const a = ((from + (to - from) * t) * Math.PI) / 180;
    const off = amp * Math.sin(t * waves * 2 * Math.PI);
    points.push(`${r1(cx + (rx + off) * Math.cos(a))} ${r1(cy + (ry + off) * Math.sin(a))}`);
  }
  return `M ${points.join(" L ")}`;
}

/** A wavy line from (x0, y0) to (x1, y1), bowed sideways by `bend`: `waves` full waves of
 *  `amp` units. A thick one is a loc. */
function waveLine(x0: number, y0: number, x1: number, y1: number, bend: number, waves: number, amp: number): string {
  const cx = (x0 + x1) / 2 + bend;
  const cy = (y0 + y1) / 2;
  const steps = Math.max(16, Math.round(waves * 12));
  const points: string[] = [];
  for (let i = 0; i <= steps; i++) {
    const t = i / steps;
    const u = 1 - t;
    const px = u * u * x0 + 2 * u * t * cx + t * t * x1;
    const py = u * u * y0 + 2 * u * t * cy + t * t * y1;
    let tx = 2 * u * (cx - x0) + 2 * t * (x1 - cx);
    let ty = 2 * u * (cy - y0) + 2 * t * (y1 - cy);
    const length = Math.hypot(tx, ty) || 1;
    tx /= length;
    ty /= length;
    const off = amp * Math.sin(t * waves * 2 * Math.PI);
    points.push(`${r1(px - ty * off)} ${r1(py + tx * off)}`);
  }
  return `M ${points.join(" L ")}`;
}

function lines(d: string, width = 1): ReactNode {
  return <path d={d} stroke={SHADE} strokeWidth={width} fill="none" strokeLinecap="round" strokeLinejoin="round" />;
}

/** A left half and its mirror image. */
function both(half: ReactNode): ReactNode {
  return (
    <>
      {half}
      <g transform={MIRROR}>{half}</g>
    </>
  );
}

// Shaved: a thin layer on the scalp. Solid for a buzz cut; see-through for faded sides.
const SCALP =
  "M 26.3 40 C 25.6 25 35 15.3 50 15.3 C 65 15.3 74.4 25 73.7 40 L 72.4 40 C 72 34.5 70.8 31 69 28.6 C 64.5 25.4 57.5 24 50 24 C 42.5 24 35.5 25.4 31 28.6 C 29.2 31 28 34.5 27.6 40 Z";

function shaved(p: Palette, opacity: number): ReactNode {
  return <path d={SCALP} fill={p.hair} opacity={opacity} />;
}

// Short: a crop with a soft, wavy fringe.
const SHORT =
  "M 25.4 40 C 23.2 24 31.5 10.6 50 10.6 C 68.5 10.6 76.8 24 74.6 40 L 72.6 40 C 72.3 34.2 71 30.4 68.6 27.8 Q 65.6 29.6 62.6 26.6 Q 59.4 28.6 56.2 25.8 Q 53.1 27.8 50 25.4 Q 46.9 27.8 43.8 25.8 Q 40.6 28.6 37.4 26.6 Q 34.4 29.6 31.4 27.8 C 29.4 30.4 27.8 34.2 27.4 40 Z";
const SHORT_LINES = "M 40 13.4 C 38.4 17 41.4 20.4 39.8 24.6 M 31.4 20 C 29.8 23 31.8 25.6 30.6 28.4";
const SHORT_MIDDLE = "M 50 12 C 48.4 16 51.6 19.8 50 24";

function short(p: Palette): ReactNode {
  return (
    <>
      <path d={SHORT} fill={p.hair} />
      {both(lines(SHORT_LINES))}
      {lines(SHORT_MIDDLE)}
    </>
  );
}

// Side part: parted over the left eye, the rest swept across the forehead.
const SIDE =
  "M 25.4 40 C 23.2 24 31.5 10.6 50 10.6 C 68.5 10.6 76.8 24 74.6 40 L 72.6 40 C 72.4 35 71.8 31.8 70.4 29.4 C 66 25.6 56 22.4 41.4 22.6 C 35.4 23.2 31 25.8 29 29.2 C 28 32 27.6 36 27.4 40 Z";
const SIDE_LINES =
  "M 37.6 11.6 Q 36.6 16 36 21.4 M 39.6 12.6 C 45 11.4 49 14.8 54 13.8 C 59 12.8 63.4 15.8 68 21.6 M 40.4 16.6 C 45.4 15.4 49.4 18.6 54.4 17.6 C 58.8 16.8 62 19.2 65.4 23.6 M 35.4 13 C 32.2 14.8 32.6 18.2 30 20.8 C 28.8 22.2 28.8 24.4 28.2 26.6";

// Messy: tousled flicks going their own way, and an uneven wavy fringe.
const MESSY =
  "M 25.4 41 C 22.4 36 22.6 30.4 24.4 26.4 Q 21.4 25 20.6 22.4 Q 23.8 23.4 26 22.2 C 26.6 17.4 28.8 14.2 31.8 12.2 Q 29.8 10 29.6 7.4 Q 33 9.6 35.8 9.8 C 38 8.6 40.8 8 43 8 Q 42 5.4 42.4 2.8 Q 45.6 5.8 48 7.4 Q 49.6 4.6 52.4 2.6 Q 53.2 5.8 55 8.1 C 58 8.4 61 9.4 63.4 11 Q 65.6 8.6 68.6 7.4 Q 67.8 10.6 67.6 13.6 C 71 16.6 73.4 20.6 74.4 25 Q 76.8 24.2 79.2 24.4 Q 77 26.8 75.6 29.6 C 76.6 33.2 76.2 37.4 74.6 41 L 72.6 41 C 72.2 35.4 71.2 31.8 69.8 29.6 Q 67.4 31.6 65.2 27.4 Q 62.6 31 60 26.2 Q 57.4 30.4 54.6 25.4 Q 51.6 30 48.6 25.6 Q 45.6 29.8 42.8 25.8 Q 40 29.6 37.2 26.4 Q 34.4 30 31.6 28.2 C 29.4 31.4 28.2 35.6 27.6 41 Z";
const MESSY_LINES =
  "M 36 11.6 C 34.6 15 37 18 35.6 22.4 M 47 9.6 C 45.6 13.6 48.4 17 47 21.6 M 58 10.6 C 56.6 14 59.4 17.6 58 22 M 67.4 16.4 C 68.8 19.6 67.4 22.6 69 26 M 28.6 19 C 27.4 22 29.2 24.6 28.2 27.6";

// Curly: a crown of curls with an even curly outline and fringe.
const CURLY_FRONT = `M 24.8 38.5 L ${onEllipse(50, 30, 26.4, 20, 180)}${scallop(50, 30, 26.4, 20, 180, 360, 11, 0.16)} L 75.2 38.5 L 72.6 39.5 L 70.6 32.8 L ${onEllipse(50, 33.5, 20.5, 8.5, 345)}${scallop(50, 33.5, 20.5, 8.5, 345, 195, 7, -0.4)} L 29.4 32.8 L 27.4 39.5 Z`;
const CURLY_LINES = `${waveArc(50, 30, 19, 13, 200, 340, 4, 1.1)} ${waveArc(50, 30, 12, 8, 215, 325, 3, 0.9)}`;
const CURLY_BACK = `M ${onEllipse(50, 30, 28.5, 22, 155)}${scallop(50, 30, 28.5, 22, 155, 385, 14, 0.18)} L 70 46 L 30 46 Z`;

// Coils: short, tight natural texture close to the head, drawn as small tight waves.
const COILS_FRONT = `M 25.6 40 L ${onEllipse(50, 31, 25.4, 19.2, 180)}${scallop(50, 31, 25.4, 19.2, 180, 360, 24, 0.07)} L 74.4 40 L 72.6 40 C 72.2 34.4 70.9 30.9 69.2 28.7 L ${onEllipse(50, 33.6, 19.6, 9, 338)}${scallop(50, 33.6, 19.6, 9, 338, 202, 14, -0.1)} L 30.8 28.7 C 29.1 30.9 27.8 34.4 27.4 40 Z`;
const COILS_LINES = `${waveArc(50, 31, 18, 13, 205, 335, 7, 0.7)} ${waveArc(50, 31, 10.5, 7.6, 220, 320, 4, 0.6)}`;

// Wavy: shoulder length, parted on the left, waves framing the face.
const WAVY_BACK =
  "M 24.6 40 C 21 26 30.4 9.6 50 9.6 C 69.6 9.6 79 26 75.4 40 C 78.8 46 74.8 51.4 78 57.4 C 80.8 62.6 76.8 67.4 79.8 73.4 Q 71 76.4 63 73 L 37 73 Q 29 76.4 20.2 73.4 C 23.2 67.4 19.2 62.6 22 57.4 C 25.2 51.4 21.2 46 24.6 40 Z";
const WAVY_BACK_LINES =
  "M 23.4 48.6 C 21.8 53.6 24 58.6 22.2 64.6 C 21.2 67.6 22 70 21.4 72 M 76.6 48.6 C 78.2 53.6 76 58.6 77.8 64.6 C 78.8 67.6 78 70 78.6 72";
const WAVY_TOP =
  "M 25 39 C 23.6 23 32 11.4 50 11.4 C 68 11.4 76.4 23 75 39 L 72.8 39 C 72.3 32.4 70.2 28 66 25.4 C 59.6 21.6 49.6 21 42.4 23.4 C 35.6 25.6 31 29.6 28.6 34.6 L 27.4 39 Z";
const WAVY_LOCK =
  "M 29.4 25.4 C 25 29.6 23.6 34.8 25.4 40 C 27.2 45.2 23 50 24.6 55.6 C 25.6 59 24.2 62 22.6 64.2 C 20.2 61.2 19.8 57.6 20.8 54 C 22.2 49.4 19.6 45.2 20.6 40.4 C 21.6 35.2 24.2 29.8 29.4 25.4 Z";
const WAVY_LOCK_LINES = "M 24.4 31 C 22.6 36 25.4 40.4 24 45.2 C 22.6 50 24.6 54 23.2 59";
const WAVY_LINES =
  "M 40.4 11.6 Q 39.4 15.6 38.8 19 M 40.6 12.6 C 36 13.6 35.4 17.4 31.6 19.6 C 29.4 21 28.6 24 27.6 27 M 42 14.4 C 47 13 50 16.6 55 15.6 C 60 14.6 63.6 18 69 24.6 M 44 18.2 C 48.4 17 51 20 55.4 19.2 C 59.6 18.4 62.4 20.8 65.2 24.4";

// Long: straight, past the shoulders, parted in the middle, with a gentle wave.
const LONG_BACK =
  "M 24.2 40 C 21 22 31 9.4 50 9.4 C 69 9.4 79 22 75.8 40 L 78.6 64 C 79.8 72 80.6 80 80 87 L 20 87 C 19.4 80 20.2 72 21.4 64 Z";
const LONG_BACK_LINES =
  "M 22.8 46 C 21.4 54 23.6 60 22 68 C 20.8 74 22.4 79 21.6 84 M 77.2 46 C 78.6 54 76.4 60 78 68 C 79.2 74 77.6 79 78.4 84";
const LONG_CURTAIN =
  "M 50 11.6 C 38.4 11.6 29.6 16.8 26.8 27.4 C 25 34.6 25.2 45 24 56 C 23.4 61 22.4 65.6 21.2 69 L 25.6 69 C 27 61 27.8 49 28.6 40.6 C 29.4 32 33.2 24 40.8 19.8 C 44.8 17.6 48.4 15.4 50 13.6 Z";
const LONG_LINES =
  "M 46.4 13 C 39 15.2 33.6 20.4 31 27 C 28.8 32.6 30.6 38 28.8 44 C 27.2 49.6 28.8 55 26.6 61 C 25.8 63.4 25.4 65.4 24.8 67 M 40.6 14.8 C 35.6 17.4 32.6 21.4 30.4 26.4 C 28.4 30.8 29.6 34 28 38";

// Bob: chin length with a full fringe.
const BOB_BACK =
  "M 24.2 40 C 21 22 31 9.6 50 9.6 C 69 9.6 79 22 75.8 40 C 76.8 47 77.8 54 78.6 60.4 Q 70 64.4 62 61 L 38 61 Q 30 64.4 21.4 60.4 C 22.2 54 23.2 47 24.2 40 Z";
const BOB_SIDE =
  "M 50 11.4 C 37.4 11.4 28.6 16.6 25.8 27.4 C 24.2 35 23.8 45 23.2 53.4 C 22.9 57.6 24 61 27.4 61.8 C 29.6 62.2 30.8 60.6 30.2 58 C 29.2 50 29 41 29.8 34.6 C 30.2 31.4 31.6 29.2 33.8 28.8 Q 36.2 30.4 38.6 28.6 Q 41 30.4 43.4 28.6 Q 45.8 30.4 48.2 28.6 Q 49.2 29.4 50 29.2 Z";
const BOB_LINES =
  "M 39.6 13.6 C 38.2 18 41 22.6 39.6 28.2 M 45 12.4 C 43.6 17 46.4 21.8 45 28.6 M 27.8 25.6 C 26.2 31.4 28.6 37.4 26.8 43.4 C 25.4 48.4 27.2 52.4 26.4 57";

// Pulled back: sleek on top, for the ponytail and the top knot.
const SLEEK =
  "M 25.8 39 C 24.6 22 33.4 12.4 50 12.4 C 66.6 12.4 75.4 22 74.2 39 L 72.4 39 C 71.6 31 68.6 26.2 62.6 24 C 56 21.6 44 21.6 37.4 24 C 31.4 26.2 28.4 31 27.6 39 Z";
const TAIL =
  "M 64.6 17.8 C 72 10.2 83.4 12.6 85.4 24.4 C 87.2 35.6 82 46 84.6 60.4 C 85.2 64 83.6 66.4 81.6 67 C 79.8 61 77.4 52 76.8 43.6 C 76.2 35 73.6 27.6 66.4 22.4 Z";
const TAIL_LINES =
  "M 70 16 C 78 15 84 20 83 28 C 82 36 84.4 42 82.4 50 C 81 56 82.6 60 81.6 64 M 68.6 19.4 C 74.6 20 78.6 25 78.4 32 C 78.2 38 80 43 79.4 49";
const PONY_LINES =
  "M 30.6 30 C 32.6 25.4 37.2 24.6 40.8 21.6 C 45.4 17.8 51.4 19.4 56.6 18 C 60 17.1 62.6 17 65.4 16.9 M 37.6 24 C 41.8 20.8 45.8 21.6 50 19.2 C 54.2 16.8 59 17.8 65 17.2 M 70.6 31 C 71.8 27.6 69.4 24.4 70.4 21 C 70 20 69 19 68 18.4";
const BUN_LINES =
  "M 30 31 C 31.6 26.6 35.6 25 37.6 21.6 C 40 18 44 17.6 46.8 15.6 M 70 31 C 68.4 26.6 64.4 25 62.4 21.6 C 60 18 56 17.6 53.2 15.6 M 40.4 23.4 C 43 20.6 45.6 20.4 48.4 16 M 59.6 23.4 C 57 20.6 54.4 20.4 51.6 16";
const BUN_WAVES =
  "M 42.6 7 C 45 4.8 47.6 8.8 50 6.6 C 52.4 4.4 55 8.4 57.4 6.4 M 43 10.4 C 45.4 8.2 48 12.2 50.4 10 C 52.8 7.8 55.4 11.8 57.2 10";

// Spiky: gelled clumps rising from a short crop.
const SPIKES =
  "M 27.6 31 C 27.4 24 28.4 16 30.6 9.4 C 32 14 33.6 17.6 35.8 19.6 C 36.6 12 38.4 4.4 41.6 -1.4 C 42.6 6 44.4 12.4 46.8 16.4 C 47.6 8.4 49.4 0.4 52.6 -4.4 C 53.2 3.6 54.6 10.6 56.6 16 C 58.2 9.4 60.6 3.8 64 0.4 C 63.8 7.2 63.6 13 64.6 18.6 C 66.4 14.2 69 10.8 72.2 8.8 C 71.6 15 71.8 22 72.4 31 Z";
const SPIKE_LINES =
  "M 31.2 12 C 31 16 33 18.6 33.4 22.6 M 41.4 2.4 C 41 8 44 11.6 44.2 17.6 M 52.2 -1.4 C 51.8 5 54.4 9.6 54.2 15.6 M 62.6 3.8 C 63.2 9 61.6 12.6 63 18 M 70.4 12.6 C 70.8 16.6 69.6 19.6 70.8 23.6";

// Pompadour: a tall swept-back quiff over faded sides.
const QUIFF =
  "M 29 30.6 C 27.4 20 32 9.2 43 4.2 C 50.6 0.8 61.6 0.4 68 4.6 C 72.4 7.6 73.4 13 72 18.6 C 71.4 21.6 70.6 24.4 69.4 27 C 64.6 23.4 57.6 22 50 22.6 C 41.8 23.4 34.4 26.4 29 30.6 Z";
const QUIFF_LINES =
  "M 31.4 27 C 30.6 21 35.6 17.6 37.6 13 C 39.6 8.4 45.4 6.6 50.4 4.6 M 37.6 24.4 C 37.6 18.8 42.6 15.4 45 11.6 C 47.4 7.8 52 6.6 55.6 5.2 M 45.6 22.8 C 46.6 17.4 51 14.8 53.4 11.4 C 55.8 8 59.4 7.4 62.6 6.4 M 55.4 22.4 C 57 18.4 60.6 16.4 62.8 13.2 C 64.8 10.4 67 9.4 69.6 8.8";

// Mullet: business in front, long behind, close to the head down to the ears.
const MULLET_BACK =
  "M 26 40 C 23 22 31 10 50 10 C 69 10 77 22 74 40 C 74.6 46 75.6 50 77.6 54 C 79.6 58 80.6 64 81 70 L 77.8 69 L 79 75.6 L 73.6 72.6 L 71.6 78 L 66 74 L 34 74 L 28.4 78 L 26.4 72.6 L 21 75.6 L 22.2 69 L 19 70 C 19.4 64 20.4 58 22.4 54 C 24.4 50 25.4 46 26 40 Z";
const MULLET_LINES =
  "M 24 52 C 22 57 23.6 61 21.8 66 C 21 68.6 21.6 70 21 72 M 76 52 C 78 57 76.4 61 78.2 66 C 79 68.6 78.4 70 79 72";

// Afro: a full round cloud with an even curly outline, wavy contours, a curly hairline.
const AFRO_BACK = `M ${onEllipse(50, 31, 35, 31, 0)}${scallop(50, 31, 35, 31, 0, 360, 30, 0.1)} Z`;
const AFRO_LINES = waveArc(50, 31, 30.5, 27, 150, 390, 11, 1);
const AFRO_FRONT = `M 24.8 40 C 23.6 30 25.6 22 30 17 C 35 11.6 42 9.4 50 9.4 C 58 9.4 65 11.6 70 17 C 74.4 22 76.4 30 75.2 40 L 72.8 40 C 72.4 34.6 71.2 31 69.4 28.6 L ${onEllipse(50, 34.6, 19.4, 9.8, 338)}${scallop(50, 34.6, 19.4, 9.8, 338, 202, 9, -0.14)} L 30.6 28.6 C 28.8 31 27.6 34.6 27.2 40 Z`;
const AFRO_FRONT_LINES = `${waveArc(50, 34, 18.6, 15.6, 205, 335, 6, 0.9)} ${waveArc(50, 34, 22, 22, 215, 325, 5, 0.9)}`;

// Dreads and box braids: a darker mass behind, ropes behind the shoulders and in front of
// them. Locs are thick and wavy; braids are slimmer, straight, and end in a bead. Lists are
// the left side; `both` mirrors them.
const ROPE_MASS =
  "M 24.2 40 C 21 22 31 9.4 50 9.4 C 69 9.4 79 22 75.8 40 L 79.4 66 C 80.4 72 81 78 80.6 84 L 19.4 84 C 19 78 19.6 72 20.6 66 Z";

function ropeMass(p: Palette): ReactNode {
  return (
    <>
      <path d={ROPE_MASS} fill={p.hair} />
      <path d={ROPE_MASS} fill="rgba(0,0,0,0.38)" />
    </>
  );
}

const ROPE_CAP =
  "M 25.4 39 C 24 22 33 11.4 50 11.4 C 67 11.4 76 22 74.6 39 L 72.6 39 C 72 31 69 26 63 23.6 C 56 21.2 44 21.2 37 23.6 C 31 26 28 31 27.4 39 Z";
const loc = (x0: number, y0: number, x1: number, y1: number, bend: number) =>
  waveLine(x0, y0, x1, y1, bend, Math.round(Math.hypot(x1 - x0, y1 - y0) / 14), 0.9);
const DREADS_BACK = [
  loc(33, 17, 17.6, 82, -3),
  loc(29.4, 24, 21, 84, -2),
  loc(27, 32, 24.6, 82, 0.6),
  loc(38, 14, 27, 80, -2.6),
  loc(43.4, 12.4, 31.6, 76, -2),
].join(" ");
const DREADS_FRONT = [loc(30.8, 22.6, 23.8, 72, -2.6), loc(35.2, 19.6, 28.6, 66, -1.8)].join(" ");
const DREAD_CAP_LINES = waveArc(50, 30, 18, 14, 205, 335, 5, 0.8);

const braid = (x0: number, y0: number, x1: number, y1: number, bend: number) =>
  `M ${x0} ${y0} Q ${r1((x0 + x1) / 2 + bend)} ${r1((y0 + y1) / 2)} ${x1} ${y1}`;
const BRAIDS_BACK = [
  braid(33, 17, 18, 88, -3),
  braid(29.6, 23, 20.6, 90, -2),
  braid(27.4, 30, 23.6, 88, -1),
  braid(36.4, 14.6, 25.4, 86, -2.6),
  braid(40.6, 13, 28.8, 82, -2.2),
  braid(45, 12, 32, 78, -1.8),
].join(" ");
const BRAIDS_FRONT = [braid(30.6, 22.4, 23.6, 80, -2.2), braid(34, 20, 27.2, 77, -1.6)].join(" ");
const BRAID_BEADS = "M 23.6 80 h 0.01 M 27.2 77 h 0.01";

/** Ropes with a thin dark edge, so neighbouring braids or locs stay separate. */
function ropes(d: string, width: number, p: Palette): ReactNode {
  return (
    <>
      <path d={d} stroke={SHADE} strokeWidth={width + 1.2} fill="none" strokeLinecap="round" strokeLinejoin="round" />
      <path d={d} stroke={p.hair} strokeWidth={width} fill="none" strokeLinecap="round" strokeLinejoin="round" />
    </>
  );
}

// Mohawk: shaved sides and a tall crest of clumped spikes.
const CREST =
  "M 41.4 24 C 41 16 41.6 8 43.4 1.6 L 45.4 6.4 C 46 1 47.6 -3.6 50 -6 C 52.4 -3.6 54 1 54.6 6.4 L 56.6 1.6 C 58.4 8 59 16 58.6 24 C 55.6 22.6 52.8 22 50 22 C 47.2 22 44.4 22.6 41.4 24 Z";
const CREST_LINES = "M 45 6 C 44 11 46.4 15 45.6 21.4 M 50 -3 C 49 4 51.4 10 50 21.6 M 55 6 C 56 11 53.6 15 54.4 21.4";

/** Hair drawn behind the head. */
export const HAIR_BACK: Parts = {
  "hair_long": (p) => (
    <>
      <path d={LONG_BACK} fill={p.hair} />
      {lines(LONG_BACK_LINES)}
    </>
  ),
  "hair_bob": (p) => <path d={BOB_BACK} fill={p.hair} />,
  "hair_wavy": (p) => (
    <>
      <path d={WAVY_BACK} fill={p.hair} />
      {lines(WAVY_BACK_LINES)}
    </>
  ),
  "hair_ponytail": (p) => (
    <>
      <path d={TAIL} fill={p.hair} />
      {lines(TAIL_LINES)}
    </>
  ),
  "hair_curly": (p) => <path d={CURLY_BACK} fill={p.hair} />,
  "hair_afro": (p) => (
    <>
      <path d={AFRO_BACK} fill={p.hair} />
      {lines(AFRO_LINES)}
    </>
  ),
  "hair_dreads": (p) => (
    <>
      {ropeMass(p)}
      {both(ropes(DREADS_BACK, 5.6, p))}
    </>
  ),
  "hair_braids": (p) => (
    <>
      {ropeMass(p)}
      {both(ropes(BRAIDS_BACK, 3.8, p))}
    </>
  ),
  "hair_mullet": (p) => (
    <>
      <path d={MULLET_BACK} fill={p.hair} />
      {lines(MULLET_LINES)}
    </>
  ),
};

/** Hair drawn over the face. */
export const HAIR_FRONT: Parts = {
  "hair_none": () => null,
  "hair_buzz": (p) => shaved(p, 1), // opaque: a see-through layer read as bare skin on top
  "hair_short": (p) => short(p),
  "hair_side_part": (p) => (
    <>
      <path d={SIDE} fill={p.hair} />
      {lines(SIDE_LINES)}
    </>
  ),
  "hair_messy": (p) => (
    <>
      <path d={MESSY} fill={p.hair} />
      {lines(MESSY_LINES)}
    </>
  ),
  "hair_curly": (p) => (
    <>
      <path d={CURLY_FRONT} fill={p.hair} />
      {lines(CURLY_LINES)}
    </>
  ),
  "hair_coils": (p) => (
    <>
      <path d={COILS_FRONT} fill={p.hair} />
      {lines(COILS_LINES, 0.9)}
    </>
  ),
  "hair_wavy": (p) => (
    <>
      <path d={WAVY_TOP} fill={p.hair} />
      {both(
        <>
          <path d={WAVY_LOCK} fill={p.hair} />
          {lines(WAVY_LOCK_LINES)}
        </>,
      )}
      {lines(WAVY_LINES)}
    </>
  ),
  "hair_long": (p) => (
    <>
      {both(
        <>
          <path d={LONG_CURTAIN} fill={p.hair} />
          {lines(LONG_LINES)}
        </>,
      )}
      {lines("M 50 11.6 L 50 15.6")}
    </>
  ),
  "hair_bob": (p) =>
    both(
      <>
        <path d={BOB_SIDE} fill={p.hair} />
        {lines(BOB_LINES)}
      </>,
    ),
  "hair_ponytail": (p) => (
    <>
      <path d={SLEEK} fill={p.hair} />
      {lines(PONY_LINES)}
      <rect x="64.4" y="15.4" width="6.4" height="3.6" rx="1.6" transform="rotate(-38 67.6 17.2)" fill={TIE} />
    </>
  ),
  "hair_bun": (p) => (
    <>
      <path d={SLEEK} fill={p.hair} />
      {lines(BUN_LINES)}
      <ellipse cx="50" cy="8.6" rx="8.2" ry="7.4" fill={p.hair} />
      {lines(BUN_WAVES)}
      <rect x="44.6" y="13.6" width="10.8" height="2.6" rx="1.3" fill={TIE} />
    </>
  ),
  "hair_spiky": (p) => (
    <>
      <path d={SPIKES} fill={p.hair} />
      {lines(SPIKE_LINES)}
      {short(p)}
    </>
  ),
  "hair_pompadour": (p) => (
    <>
      {shaved(p, 0.45)}
      <path d={QUIFF} fill={p.hair} />
      {lines(QUIFF_LINES)}
    </>
  ),
  "hair_mullet": (p) => short(p),
  "hair_afro": (p) => (
    <>
      <path d={AFRO_FRONT} fill={p.hair} />
      {lines(AFRO_FRONT_LINES)}
    </>
  ),
  "hair_braids": (p) => (
    <>
      <path d={ROPE_CAP} fill={p.hair} />
      {lines("M 50 11.6 L 50 22")}
      {both(
        <>
          {ropes(BRAIDS_FRONT, 3.6, p)}
          <path d={BRAID_BEADS} stroke={BEAD} strokeWidth="3.4" strokeLinecap="round" />
        </>,
      )}
    </>
  ),
  "hair_dreads": (p) => (
    <>
      <path d={ROPE_CAP} fill={p.hair} />
      {lines(DREAD_CAP_LINES)}
      {both(ropes(DREADS_FRONT, 5.2, p))}
    </>
  ),
  "hair_mohawk": (p) => (
    <>
      {shaved(p, 0.45)}
      <path d={CREST} fill={p.hair} />
      {lines(CREST_LINES)}
    </>
  ),
};

const smile = <path d="M 42 54 Q 50 62 58 54" stroke={MOUTH_LINE} strokeWidth="2.5" fill="none" strokeLinecap="round" />;
const grin = (fill: string) => (
  <path d="M 41 53 Q 50 65 59 53 Z" fill={fill} stroke={MOUTH_LINE} strokeWidth="2" strokeLinejoin="round" />
);

export const MOUTHS: Parts = {
  "mouth_smile": () => smile,
  "mouth_grin": () => grin("#fff"),
  "mouth_flat": () => <path d="M 43 56 L 57 56" stroke={MOUTH_LINE} strokeWidth="2.5" strokeLinecap="round" />,
  "mouth_smirk": () => <path d="M 43 56 Q 51 60 58 53" stroke={MOUTH_LINE} strokeWidth="2.5" fill="none" strokeLinecap="round" />,
  "mouth_whoa": () => <ellipse cx="50" cy="57" rx="4.5" ry="6" fill="#4a1d1d" />,
  "mouth_tongue": () => (
    <>
      {grin("#4a1d1d")}
      <ellipse cx="52" cy="60" rx="4" ry="4.5" fill="#f06292" />
    </>
  ),
  "mouth_gold": () => (
    <>
      {grin("#fff")}
      <rect x="46" y="53.5" width="4" height="4" fill="#f5c242" />
    </>
  ),
  "mouth_mustache": (p) => (
    <>
      {smile}
      <path d="M 50 51 Q 44 45 37 51 Q 42 54 50 51 Q 58 54 63 51 Q 56 45 50 51 Z" fill={p.hair} />
    </>
  ),
  "mouth_beard": (p) => (
    <>
      <path d="M 25 46 Q 27 72 50 73 Q 73 72 75 46 Q 70 58 50 60 Q 30 58 25 46 Z" fill={p.hair} />
      {smile}
    </>
  ),
};

const flower = ([x, y]: number[]) => (
  <g key={`${x}-${y}`}>
    <circle cx={x} cy={y} r="4" fill="#fff" />
    <circle cx={x} cy={y} r="1.6" fill="#facc15" />
  </g>
);

export const TOPS: Parts = {
  "top_tee_blue": (p) => torso(p.top),
  "top_tee_gray": (p) => torso(p.top),
  "top_tee_white": (p) => torso(p.top),
  "top_polo": (p) =>
    torso(
      p.top,
      <>
        <path d="M 42 74 L 50 83 L 58 74 L 54 74 L 50 78 L 46 74 Z" fill="#115e59" />
        <circle cx="50" cy="86" r="1.3" fill="#e5e7eb" />
        <circle cx="50" cy="91" r="1.3" fill="#e5e7eb" />
      </>,
    ),
  "top_flannel": (p) =>
    torso(
      p.top,
      <g stroke="rgba(0,0,0,0.35)" strokeWidth="2.5">
        <path d="M 30 74 L 30 100 M 44 76 L 44 100 M 58 76 L 58 100 M 72 74 L 72 100" />
        <path d="M 18 84 L 82 84 M 18 94 L 82 94" />
      </g>,
    ),
  "top_royal_robe": (p) =>
    torso(
      p.top,
      <>
        <path d="M 36 74 Q 50 88 64 74 L 70 78 Q 50 100 30 78 Z" fill="#f9fafb" />
        {[[34, 80], [42, 86], [58, 86], [66, 80]].map(([x, y]) => (
          <circle key={x} cx={x} cy={y} r="1.1" fill="#111827" />
        ))}
        <circle cx="50" cy="90" r="3" fill="#f5c242" stroke="#ca8a04" />
      </>,
    ),
  "top_hoodie": (p) =>
    torso(
      p.top,
      <>
        <path d="M 34 76 Q 50 64 66 76 L 66 82 Q 50 72 34 82 Z" fill="#4b5563" />
        <path d="M 46 82 L 45 96 M 54 82 L 55 96" stroke="#e5e7eb" strokeWidth="1.5" />
      </>,
    ),
  "top_jersey": (p) =>
    torso(
      p.top,
      <>
        <path d="M 18 86 L 30 86 M 70 86 L 82 86" stroke="#fff" strokeWidth="3" />
        <text x="50" y="93" textAnchor="middle" fontSize="15" fontWeight="700" fill="#fff" fontFamily="sans-serif">
          7
        </text>
      </>,
    ),
  "top_labcoat": (p) =>
    torso(
      p.top,
      <>
        <path d="M 43 74 L 50 86 L 57 74" fill="#cbd5e1" />
        <path d="M 50 86 L 50 100" stroke="#cbd5e1" strokeWidth="1.5" />
        <rect x="61" y="84" width="3" height="9" fill="#3d8bff" />
      </>,
    ),
  "top_shirt_tie": (p) =>
    torso(
      p.top,
      <>
        <path d="M 42 74 L 50 84 L 58 74 L 54 74 L 50 79 L 46 74 Z" fill="#cbd5e1" />
        <path d="M 48 80 L 52 80 L 54 98 L 50 100 L 46 98 Z" fill="#1d4ed8" />
      </>,
    ),
  "top_hivis": (p) =>
    torso(
      p.top,
      <>
        <path d="M 18 88 L 82 88 M 18 95 L 82 95" stroke="#fde047" strokeWidth="3" />
        <path d="M 46 74 L 50 84 L 54 74" fill="#374151" />
      </>,
    ),
  "top_hawaiian": (p) =>
    torso(
      p.top,
      <>
        {[
          [30, 84],
          [42, 92],
          [58, 82],
          [70, 90],
          [52, 78],
        ].map(flower)}
        <path d="M 44 74 L 50 82 L 56 74" fill="#fff" />
      </>,
    ),
  "top_suit": (p) =>
    torso(
      p.top,
      <>
        <path d="M 40 74 L 50 90 L 60 74 Z" fill="#f3f4f6" />
        <path d="M 40 74 L 50 90 L 45 100 L 37 100 L 44 84 Z" fill="#111827" />
        <path d="M 60 74 L 50 90 L 55 100 L 63 100 L 56 84 Z" fill="#111827" />
        <path d="M 48 80 L 52 80 L 53 95 L 50 99 L 47 95 Z" fill="#7f1d1d" />
      </>,
    ),
  "top_tuxedo": (p) =>
    torso(
      p.top,
      <>
        <path d="M 40 74 L 50 92 L 60 74 Z" fill="#f9fafb" />
        <path d="M 44 77 L 50 80 L 56 77 L 56 83 L 50 80 L 44 83 Z" fill="#111827" />
        <path d="M 40 74 L 50 92 L 46 100 L 38 100 L 44 84 Z" fill="#1f2937" />
        <path d="M 60 74 L 50 92 L 54 100 L 62 100 L 56 84 Z" fill="#1f2937" />
      </>,
    ),
  "top_galaxy_armour": (p) => galaxyArmour(p),
  "top_armour": (p) =>
    torso(
      p.top,
      <>
        <path d="M 50 74 L 50 100" stroke="#6b7280" strokeWidth="2" />
        <path d="M 22 86 Q 50 92 78 86 M 22 94 Q 50 100 78 94" stroke="#6b7280" strokeWidth="1.5" fill="none" />
        <circle cx="22" cy="78" r="7" fill="#d1d5db" stroke="#6b7280" />
        <circle cx="78" cy="78" r="7" fill="#d1d5db" stroke="#6b7280" />
        <circle cx="38" cy="80" r="1.5" fill="#374151" />
        <circle cx="62" cy="80" r="1.5" fill="#374151" />
      </>,
    ),
};

// A laurel wreath: pairs of leaves along an arc over the forehead, two branches meeting at the top.
const LAUREL_LEAVES = (() => {
  const at = (t: number): [number, number] => {
    const u = 1 - t;
    return [u * u * 25 + 2 * u * t * 50 + t * t * 75, u * u * 39 + 2 * u * t * 13 + t * t * 39];
  };
  const leaves: { x: number; y: number; angle: number }[] = [];
  for (let i = 0; i < 7; i++) {
    const t = 0.05 + i * 0.062;
    for (const side of [1, -1]) {
      const here = side === 1 ? t : 1 - t;
      const [x, y] = at(here);
      const [nx, ny] = at(here + 0.01 * side);
      const along = (Math.atan2(ny - y, nx - x) * 180) / Math.PI;
      for (const splay of [-38, 38]) {
        leaves.push({ x: r1(x), y: r1(y), angle: r1(along + splay) });
      }
    }
  }
  return leaves;
})();

export const HEADWEAR: Parts = {
  "head_headband": () => <path d="M 26 30 Q 50 19 74 30 L 74 36 Q 50 25 26 36 Z" fill="#ef4444" />,
  "head_bandana": () => (
    <>
      <path d="M 26 34 Q 26 10 50 10 Q 74 10 74 34 L 74 37 Q 50 27 26 37 Z" fill="#1d4ed8" />
      <path d="M 74 34 L 86 30 L 82 40 Z M 74 36 L 88 42 L 80 44 Z" fill="#1e40af" />
      {[[36, 20], [50, 15], [64, 20]].map(([x, y]) => (
        <circle key={x} cx={x} cy={y} r="1.5" fill="#bfdbfe" />
      ))}
    </>
  ),
  "head_beret": () => (
    <>
      <ellipse cx="52" cy="21" rx="24" ry="9" fill="#111827" transform="rotate(-8 52 21)" />
      <path d="M 29 28 Q 50 22 72 26 L 72 31 Q 50 27 30 32 Z" fill="#1f2937" />
      <circle cx="54" cy="12" r="2" fill="#111827" />
    </>
  ),
  "head_knight": () => (
    <>
      <path d="M 25 36 Q 25 6 50 6 Q 75 6 75 36 Z" fill="#9ca3af" />
      <path d="M 25 32 L 75 32 L 75 37 L 25 37 Z" fill="#6b7280" />
      <rect x="47.5" y="36" width="5" height="16" rx="2" fill="#9ca3af" />
      <path d="M 25 37 L 25 50 Q 30 56 36 50 L 36 37 Z M 75 37 L 75 50 Q 70 56 64 50 L 64 37 Z" fill="#9ca3af" />
      <path d="M 50 6 L 50 32" stroke="#d1d5db" strokeWidth="3" />
    </>
  ),
  "head_pirate": () => (
    <>
      <path d="M 12 32 Q 50 0 88 32 Q 50 24 12 32 Z" fill="#111827" />
      <path d="M 12 32 Q 50 40 88 32 L 82 36 Q 50 44 18 36 Z" fill="#1f2937" />
      <circle cx="50" cy="19" r="3.2" fill="#f9fafb" />
      <path d="M 44 24 L 56 28 M 56 24 L 44 28" stroke="#f9fafb" strokeWidth="1.5" strokeLinecap="round" />
    </>
  ),
  "head_wizard": () => (
    <>
      <path d="M 50 0 L 32 32 L 68 32 Z" fill="#4c1d95" />
      <ellipse cx="50" cy="32" rx="30" ry="5" fill="#3b0764" />
      <path d="M 50 0 Q 56 4 60 2" stroke="#4c1d95" strokeWidth="3" fill="none" />
      {[[46, 22], [55, 16], [50, 28]].map(([x, y]) => (
        <circle key={x} cx={x} cy={y} r="1.4" fill="#fde047" />
      ))}
    </>
  ),
  "head_astronaut": () => (
    <>
      <rect x="34" y="70" width="32" height="8" rx="3" fill="#9ca3af" />
      <circle cx="50" cy="45" r="31" fill="rgba(191,219,254,0.28)" stroke="#e5e7eb" strokeWidth="3" />
      <path d="M 28 36 Q 32 20 46 17" stroke="#fff" strokeWidth="2.5" fill="none" strokeLinecap="round" opacity="0.8" />
    </>
  ),
  "head_cap": () => (
    <>
      <path d="M 26 33 Q 26 9 50 9 Q 74 9 74 33 Z" fill="#1d4ed8" />
      <path d="M 48 30 L 88 31 L 87 36 L 48 36 Z" fill="#1e40af" />
    </>
  ),
  "head_beanie": () => (
    <>
      <path d="M 24 34 Q 24 6 50 6 Q 76 6 76 34 Z" fill="#16a34a" />
      <path d="M 24 28 Q 50 22 76 28 L 76 35 Q 50 29 24 35 Z" fill="#15803d" />
      <circle cx="50" cy="6" r="5" fill="#bbf7d0" />
    </>
  ),
  "head_cowboy": () => (
    <>
      <ellipse cx="50" cy="31" rx="37" ry="7" fill="#92400e" />
      <path d="M 36 31 L 38 8 Q 50 2 62 8 L 64 31 Z" fill="#b45309" />
      <path d="M 36 26 L 64 26" stroke="#78350f" strokeWidth="3" />
    </>
  ),
  "head_chef": () => (
    <>
      <path d="M 31 31 Q 22 6 42 9 Q 50 0 58 9 Q 78 6 69 31 Z" fill="#f9fafb" />
      <rect x="31" y="28" width="38" height="7" rx="2" fill="#e5e7eb" />
    </>
  ),
  "head_hardhat": () => (
    <>
      <path d="M 25 30 Q 26 4 50 4 Q 74 4 75 30 Z" fill="#facc15" />
      <path d="M 50 4 L 50 30" stroke="#eab308" strokeWidth="4" />
      <rect x="19" y="28" width="62" height="6" rx="3" fill="#eab308" />
    </>
  ),
  "head_tophat": () => (
    <>
      <rect x="32" y="1" width="36" height="27" fill="#111827" />
      <ellipse cx="50" cy="28" rx="26" ry="4.5" fill="#111827" />
      <rect x="32" y="20" width="36" height="5" fill="#374151" />
    </>
  ),
  "head_halo": () => (
    <>
      <ellipse cx="50" cy="7" rx="17" ry="4.5" fill="none" stroke="#fde047" strokeWidth="3" />
      <ellipse cx="50" cy="7" rx="17" ry="4.5" fill="none" stroke="#fef9c3" strokeWidth="1" />
    </>
  ),
  "head_viking": () => (
    <>
      <path d="M 26 34 Q 26 9 50 9 Q 74 9 74 34 Z" fill="#9ca3af" />
      <rect x="26" y="30" width="48" height="5" fill="#6b7280" />
      <path d="M 28 30 Q 10 24 14 6 Q 20 20 32 22 Z" fill="#fef3c7" />
      <path d="M 72 30 Q 90 24 86 6 Q 80 20 68 22 Z" fill="#fef3c7" />
    </>
  ),
  "head_crown": () => (
    <>
      <path
        d="M 32 29 L 32 9 L 41 18 L 50 2 L 59 18 L 68 9 L 68 29 Z"
        fill="#f5c242"
        stroke="#ca8a04"
        strokeWidth="1.5"
        strokeLinejoin="round"
      />
      <circle cx="50" cy="23" r="3" fill="#ef4444" />
      <circle cx="40" cy="25" r="2" fill="#3b82f6" />
      <circle cx="60" cy="25" r="2" fill="#3b82f6" />
    </>
  ),
  // Achievement rewards (server/achievements.py): Regular gold and Champion platinum.
  "head_mortarboard": () => (
    <>
      <path d="M 30 31 Q 30 16 50 16 Q 70 16 70 31 L 70 33 Q 50 28 30 33 Z" fill="#111827" />
      <path d="M 15 16 L 50 6 L 85 16 L 50 26 Z" fill="#0b0f17" stroke="#1f2937" strokeWidth="1" strokeLinejoin="round" />
      <circle cx="50" cy="16" r="1.6" fill="#374151" />
      <path d="M 50 16 L 76 19 L 77 30" stroke="#d4a017" strokeWidth="1.2" fill="none" strokeLinecap="round" />
      <path d="M 75.4 29 L 78.6 29 L 79.4 35 L 74.6 35 Z" fill="#d4a017" />
    </>
  ),
  "head_laurels": () => (
    <>
      {LAUREL_LEAVES.map(({ x, y, angle }, index) => (
        <ellipse
          key={index}
          cx={x}
          cy={y}
          rx="3.6"
          ry="1.5"
          fill="#d4a017"
          stroke="#a16207"
          strokeWidth="0.5"
          transform={`rotate(${angle} ${x} ${y})`}
        />
      ))}
    </>
  ),
};

export const EYEWEAR: Parts = {
  "eye_reading": () => (
    <g fill="none" stroke="#6b7280" strokeWidth="1.8">
      <path d="M 33 43 A 7 5 0 0 0 47 43 Z" />
      <path d="M 53 43 A 7 5 0 0 0 67 43 Z" />
      <path d="M 47 43 L 53 43 M 33 43 L 26 41 M 67 43 L 74 41" />
    </g>
  ),
  "eye_aviators": () => (
    <g stroke="#d4a017" strokeWidth="1.5">
      <path d="M 30 36 L 48 36 L 47 47 Q 40 51 32 46 Z" fill="rgba(17,24,39,0.8)" />
      <path d="M 52 36 L 70 36 L 68 46 Q 60 51 53 47 Z" fill="rgba(17,24,39,0.8)" />
      <path d="M 48 37 L 52 37 M 30 37 L 25 36 M 70 37 L 75 36" fill="none" />
    </g>
  ),
  "eye_visor": () => (
    <>
      <rect x="27" y="35" width="46" height="12" rx="4" fill="rgba(61,139,255,0.78)" stroke="#7cc4ff" strokeWidth="1.5" />
      <path d="M 31 39 L 69 39" stroke="#dbeafe" strokeWidth="1.5" opacity="0.8" />
      <path d="M 27 41 L 23 40 M 73 41 L 77 40" stroke="#7cc4ff" strokeWidth="2" />
    </>
  ),
  "eye_round": () => (
    <g fill="none" stroke="#374151" strokeWidth="2">
      <circle cx="40" cy="41" r="7" />
      <circle cx="60" cy="41" r="7" />
      <path d="M 47 41 L 53 41 M 33 40 L 26 38 M 67 40 L 74 38" />
    </g>
  ),
  "eye_patch": () => (
    <>
      <circle cx="60" cy="41" r="7" fill="#111827" />
      <path d="M 26 31 Q 50 39 74 31" stroke="#111827" strokeWidth="2" fill="none" />
    </>
  ),
  "eye_monocle": () => (
    <g fill="none" stroke="#f5c242" strokeWidth="2">
      <circle cx="60" cy="41" r="7.5" />
      <path d="M 66 46 Q 74 56 72 70" />
    </g>
  ),
  "eye_goggles": () => (
    <>
      <rect x="30" y="34" width="40" height="14" rx="7" fill="rgba(61,139,255,0.55)" stroke="#111827" strokeWidth="2" />
      <path d="M 30 41 L 24 39 M 70 41 L 76 39" stroke="#111827" strokeWidth="2" />
    </>
  ),
  "eye_sunglasses": () => (
    <g fill="#111827">
      <rect x="31" y="35" width="16" height="11" rx="4" />
      <rect x="53" y="35" width="16" height="11" rx="4" />
      <path d="M 47 39 L 53 39 M 31 39 L 25 37 M 69 39 L 75 37" stroke="#111827" strokeWidth="2" />
    </g>
  ),
  "eye_3d": () => (
    <>
      <rect x="31" y="35" width="16" height="11" rx="2" fill="rgba(239,68,68,0.7)" stroke="#f9fafb" strokeWidth="1.5" />
      <rect x="53" y="35" width="16" height="11" rx="2" fill="rgba(59,130,246,0.7)" stroke="#f9fafb" strokeWidth="1.5" />
      <path d="M 47 40 L 53 40" stroke="#f9fafb" strokeWidth="2" />
    </>
  ),
};

export const EARRINGS: Parts = {
  "ears_studs": () => (
    <>
      <circle cx="26" cy="48" r="1.8" fill="#f5c242" />
      <circle cx="74" cy="48" r="1.8" fill="#f5c242" />
    </>
  ),
  "ears_pearls": () => (
    <>
      <circle cx="26" cy="49" r="2.4" fill="#f8fafc" stroke="#cbd5e1" strokeWidth="0.6" />
      <circle cx="74" cy="49" r="2.4" fill="#f8fafc" stroke="#cbd5e1" strokeWidth="0.6" />
    </>
  ),
  "ears_hoops": () => (
    <g fill="none" stroke="#f5c242" strokeWidth="1.5">
      <circle cx="26" cy="51" r="4" />
      <circle cx="74" cy="51" r="4" />
    </g>
  ),
  "ears_diamonds": () => (
    <g fill="#a5f3fc" stroke="#fff" strokeWidth="0.8">
      <path d="M 26 46 L 29 49 L 26 53 L 23 49 Z" />
      <path d="M 74 46 L 77 49 L 74 53 L 71 49 Z" />
    </g>
  ),
};

// Effects (fire, money rain, lightning, sparkles, the mythicals) live in effects.tsx.
