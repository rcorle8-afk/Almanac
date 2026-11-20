// Screens side by side that you swipe between: the main menu's three, and the Social screen's
// Groups and Friends inside it. One hook, so both slide the same way.

import { useCallback, useEffect, useLayoutEffect, useRef, useState, type RefObject } from "react";

/** Smooth, unless the player has asked their device for less motion. */
export const motion = (): ScrollBehavior =>
  window.matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth";

/**
 * The screens sit in one sideways scroller that snaps to a whole screen, so the swipe is the
 * browser's own: it follows the finger, and a drag that starts downward scrolls the screen
 * instead. This hook opens it on the right screen, reports which one is in view, and writes how
 * far across it is (0 to count-1) to `--at` on the tab bar, which slides its marker. Where the
 * screens are laid out side by side instead (the main menu on a wide window) nothing scrolls
 * sideways, and it does nothing.
 *
 * Put `track` on the scroller and `bar` on the element holding the tabs and their marker.
 */
export function usePager(count: number, start: number) {
  const track = useRef<HTMLDivElement>(null);
  const bar = useRef<HTMLElement>(null);
  const at = useRef(start);
  const [active, setActive] = useState(start);

  // Before the first paint, so it never flashes its leftmost screen.
  useLayoutEffect(() => {
    const el = track.current;
    if (el) el.scrollLeft = at.current * el.clientWidth;
    bar.current?.style.setProperty("--at", String(at.current));
  }, []);

  useEffect(() => {
    const el = track.current;
    if (!el) return;
    const paged = () => el.scrollWidth > el.clientWidth + 1;
    // Runs on the scroll event itself, which the browser already sends at most once a frame.
    // Waiting for a frame of its own could leave the address a screen behind on the way out.
    const sync = () => {
      if (!paged()) return;
      const across = Math.min(count - 1, Math.max(0, el.scrollLeft / el.clientWidth));
      bar.current?.style.setProperty("--at", across.toFixed(4));
      const index = Math.round(across);
      if (index !== at.current) {
        at.current = index;
        setActive(index);
      }
    };
    el.addEventListener("scroll", sync, { passive: true });
    // A turned phone or a resized window keeps the same screen in view. Only a change of width
    // counts: a keyboard opening changes the height, and must not yank a swipe back.
    let width = 0;
    const resized = new ResizeObserver(() => {
      if (el.clientWidth === width) return;
      width = el.clientWidth;
      if (paged()) el.scrollLeft = at.current * width;
    });
    resized.observe(el);
    return () => {
      el.removeEventListener("scroll", sync);
      resized.disconnect();
    };
  }, [count]);

  const go = useCallback(
    (index: number) => {
      const el = track.current;
      if (!el || index < 0 || index >= count) return;
      el.scrollTo({ left: index * el.clientWidth, behavior: motion() });
    },
    [count],
  );

  return { track, bar, active, go };
}

/**
 * For screens of different heights inside a page that itself scrolls (Social's Groups and
 * Friends, the leaderboard's two boards): keeps the scroller exactly as tall as the screen in
 * view, so a short list isn't followed by the blank height of its taller neighbour. It follows
 * the screen as its content loads or changes.
 */
export function useFitHeight(track: RefObject<HTMLDivElement>, active: number) {
  useLayoutEffect(() => {
    const el = track.current;
    const screen = el?.children[active] as HTMLElement | undefined;
    if (!el || !screen) return;
    const fit = () => {
      el.style.height = `${screen.offsetHeight}px`;
    };
    fit();
    const watching = new ResizeObserver(fit);
    watching.observe(screen);
    return () => watching.disconnect();
  }, [track, active]);
}
