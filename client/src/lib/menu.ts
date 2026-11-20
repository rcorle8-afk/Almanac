// The main menu's three screens, in swipe order. Play sits in the middle and is where the menu
// opens; the other two are one swipe to either side.

export const SCREENS = [
  { id: "social", label: "Social" },
  { id: "play", label: "Play" },
  { id: "customization", label: "Customization" },
] as const;

export type Screen = (typeof SCREENS)[number]["id"];

export const HOME_SCREEN: Screen = "play";

/** The menu opened on one screen: "/" for Play, "/#social" and "/#customization" for the others. */
export const menuHref = (screen: Screen) => (screen === HOME_SCREEN ? "/" : `/#${screen}`);

/** Where the menu opens for this address. A room link or a join error always opens on Play, since
 *  that's where the room code goes. */
export function startScreen(search: string, hash: string): number {
  const params = new URLSearchParams(search);
  const named = hash.replace(/^#/, "");
  const asked = params.has("room") || params.has("error") ? HOME_SCREEN : named === "friends" ? "social" : named;
  const index = SCREENS.findIndex((screen) => screen.id === asked);
  return index >= 0 ? index : SCREENS.findIndex((screen) => screen.id === HOME_SCREEN);
}

/** Which of the Social screen's tabs the address names: /#friends is Friends (1), anything else
 *  Groups (0), where it opens. */
export const startSocialTab = (hash: string) => (hash === "#friends" ? 1 : 0);
