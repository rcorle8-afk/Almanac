import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import "@fontsource-variable/inter";
import "@fontsource-variable/jetbrains-mono";
import "./global.css";
import { MenuBar } from "./components/MenuBar";
import type { Screen } from "./lib/menu";
import { Host } from "./routes/Host";
import { Leaderboard } from "./routes/Leaderboard";
import { Menu } from "./routes/Menu";
import { Play } from "./routes/Play";
import { Locker } from "./routes/Locker";
import { Profile } from "./routes/Profile";
import { Academia } from "./routes/Academia";
import { Achievements } from "./routes/Achievements";
import { GameLog } from "./routes/GameLog";
import { GameHistory } from "./routes/GameHistory";
import { Shop } from "./routes/Shop";
import { PublicProfile } from "./routes/PublicProfile";
import { Group } from "./routes/Group";
import { AdminReports } from "./routes/AdminReports";
import { AdminFlags } from "./routes/AdminFlags";
import { AdminOverview } from "./routes/AdminOverview";
import { AdminPlayers } from "./routes/AdminPlayers";
import { Live } from "./routes/Live";
import { Open } from "./routes/Open";
import { registerServiceWorker, syncPush } from "./lib/push";
import styles from "./styles.module.css";

const at = (prefix: string) => location.pathname.startsWith(prefix);

function route() {
  if (at("/host")) return <Host />;
  if (at("/play")) return <Play />;
  if (at("/profile/achievements")) return <Achievements />;
  if (/^\/profile\/games\/?$/.test(location.pathname)) return <GameHistory />;
  if (at("/profile/games/")) return <GameLog />;
  if (at("/profile")) return <Profile />;
  // Academia was the "trophy road" until Nov 4, 2026; /road still opens it.
  if (at("/academia") || at("/road")) return <Academia />;
  if (at("/shop")) return <Shop />;
  if (at("/locker")) return <Locker />;
  // M5: other players' profiles, group pages and the report review queue.
  if (at("/u/")) return <PublicProfile />;
  if (at("/g/")) return <Group />;
  if (at("/admin/reports")) return <AdminReports />;
  if (at("/admin/flags")) return <AdminFlags />; // M6: anti-cheat review
  if (at("/admin/players")) return <AdminPlayers />; // every account's standing, for the team
  if (at("/admin/overview")) return <AdminOverview />; // the app's structure, plans and services, for the team
  if (at("/leaderboard")) return <Leaderboard />; // the global boards: groups and players by prestige
  if (at("/live")) return <Live />; // M6: the nightly live game
  if (at("/open")) return <Open />; // M6: the endless table
  // Social was a page of its own until Nov 11, 2026; it is the menu's Social screen now, and old
  // links to /social land there.
  if (at("/social")) history.replaceState(null, "", `/${location.search}#social`);
  return <Menu />; // the main menu: Social, Play and Customization
}

/**
 * Which of the menu's three screens a page belongs to, for the navigation bar at its foot; null
 * where there is no bar to add. That is the menu itself, which draws its own, and a table (the
 * phone's game view and the host screen): the one place the bar is left out, so nobody is a
 * stray tap away from leaving a round (Ryan, Nov 11, 2026).
 */
function sectionFor(path: string): Screen | null {
  const under = (...prefixes: string[]) => prefixes.some((prefix) => path.startsWith(prefix));
  if (under("/host", "/play")) return null;
  if (under("/locker", "/shop", "/academia", "/road", "/profile/achievements")) return "customization";
  if (under("/live", "/open")) return "play";
  if (under("/profile", "/u/", "/g/", "/admin", "/leaderboard")) return "social";
  return null;
}

function App() {
  const section = sectionFor(location.pathname); // before route(), which may rewrite /social
  const page = route();
  return section ? (
    <div className={styles.withMenuBar}>
      {page}
      <MenuBar current={section} />
    </div>
  ) : (
    page
  );
}

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <App />
  </StrictMode>,
);

// Web push (M5): the service worker that shows notifications, and this device's subscription
// re-sent to the server if push was already on.
registerServiceWorker();
void syncPush();
