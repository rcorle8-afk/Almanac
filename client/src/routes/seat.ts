// A player's seat in a room, kept so a refresh or dropped connection can reclaim it.

export interface Seat {
  name: string;
  token: string | null;
}

const key = (room: string) => `almanac:seat:${room}`;

export function readSeat(room: string): Seat | null {
  try {
    const stored = localStorage.getItem(key(room));
    return stored ? JSON.parse(stored) : null;
  } catch {
    return null;
  }
}

export function writeSeat(room: string, seat: Seat) {
  localStorage.setItem(key(room), JSON.stringify(seat));
}

export function clearSeat(room: string) {
  localStorage.removeItem(key(room));
}
