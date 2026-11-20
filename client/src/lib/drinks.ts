// Drinks mode, as the server scores it (server/rooms.py drinks_for): one drink per
// (100 / strength) points lost in a round, at most 6 a round.

export const STRENGTH_LABELS: Record<number, string> = {
  1: "Light",
  2: "Social",
  3: "Medium",
  4: "Strong",
  5: "Savage",
};

export const MAX_DRINKS_PER_ROUND = 6;

export function pointsPerDrink(strength: number) {
  return Math.round(100 / strength);
}

export function strengthLabel(strength: number) {
  return STRENGTH_LABELS[strength] ?? `Level ${strength}`;
}
