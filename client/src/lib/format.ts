export function signedPoints(value: string | number) {
  const points = Number(value);
  return `${points > 0 ? "+" : ""}${points.toFixed(2)}`;
}

export function signedInteger(value: string | number) {
  const points = Math.round(Number(value));
  return `${points > 0 ? "+" : ""}${points}`;
}

/** Trims binary float noise from arithmetic on tick-sized prices. */
export function cleanNumber(value: number) {
  return `${Number(value.toFixed(4))}`;
}

export function pointsClass(points: number, styles: Record<string, string>) {
  if (points > 0) return styles.gain;
  return points < 0 ? styles.loss : styles.rowMuted;
}

/** Time left as a clock: "3:12:05" with hours to go, "4:09" inside the last hour. */
export function countdown(ms: number) {
  const total = Math.max(0, Math.ceil(ms / 1000));
  const hours = Math.floor(total / 3600);
  const minutes = Math.floor((total % 3600) / 60);
  const seconds = total % 60;
  const pad = (n: number) => String(n).padStart(2, "0");
  return hours ? `${hours}:${pad(minutes)}:${pad(seconds)}` : `${minutes}:${pad(seconds)}`;
}
