import { useEffect, useMemo, useState, type FormEvent } from "react";
import { Avatar } from "../avatar/Avatar";
import { BookLoader } from "../components/BookLoader";
import { Brand } from "../components/TopBar";
import {
  PLAYERS_FILE,
  addTeammate,
  fetchPlayers,
  fetchTeam,
  removeTeammate,
  type PlayerRow,
  type PlayersReport,
  type TeamList,
} from "../lib/players";
import styles from "../styles.module.css";

type SortKey =
  | "name"
  | "level"
  | "xp"
  | "prestige"
  | "coins"
  | "games"
  | "wins"
  | "best_quotes"
  | "trades"
  | "open_rounds"
  | "badges"
  | "friends"
  | "groups"
  | "joined"
  | "last_played";

// The table's columns, in order. Everything else a player has (podiums, points, live games,
// coins spent, items owned) is in the Excel file.
const COLUMNS: { key: SortKey; label: string; title?: string; text?: boolean }[] = [
  { key: "name", label: "Player", text: true },
  { key: "level", label: "Level" },
  { key: "xp", label: "XP" },
  { key: "prestige", label: "Prestige", title: "From wins, podiums and Best Quotes" },
  { key: "coins", label: "Coins", title: "Coins they hold now" },
  { key: "games", label: "Games", title: "Hosted and live games finished" },
  { key: "wins", label: "Wins", title: "Games won, and the share of their games" },
  { key: "best_quotes", label: "Best Quotes" },
  { key: "trades", label: "Trades" },
  { key: "open_rounds", label: "Open table", title: "Rounds played at the open table" },
  { key: "badges", label: "Badges", title: "Achievement tiers earned" },
  { key: "friends", label: "Friends" },
  { key: "groups", label: "Groups", text: true },
  { key: "joined", label: "Joined", text: true },
  { key: "last_played", label: "Last played", text: true },
];

type Filter = "all" | "recent" | "never";

const count = (value: number) => value.toLocaleString();

function date(iso: string) {
  return new Date(iso).toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" });
}

/** "Today", "3 days ago", or the date once it's been a month. */
function ago(iso: string | null, now: number) {
  if (!iso) return "Never";
  const days = Math.floor((now - new Date(iso).getTime()) / 86_400_000);
  if (days <= 0) return "Today";
  if (days === 1) return "Yesterday";
  return days < 30 ? `${days} days ago` : date(iso);
}

/** Orders two players by a column. Players with nothing in it (never played) always come last. */
function compare(a: PlayerRow, b: PlayerRow, key: SortKey, down: boolean) {
  const flip = down ? -1 : 1;
  if (key === "name") return flip * a.name.localeCompare(b.name);
  if (key === "groups") return flip * (a.groups.length - b.groups.length) || a.name.localeCompare(b.name);
  if (key === "joined" || key === "last_played") {
    const [x, y] = [a[key], b[key]];
    if (x === y) return a.name.localeCompare(b.name);
    if (!x) return 1;
    if (!y) return -1;
    return flip * (x < y ? -1 : 1);
  }
  return flip * (a[key] - b[key]) || b.prestige - a.prestige || a.name.localeCompare(b.name);
}

function matches(player: PlayerRow, words: string) {
  if (!words) return true;
  const text = [player.name, player.handle ? `@${player.handle}` : "", player.email ?? "", ...player.groups]
    .join(" ")
    .toLowerCase();
  return words.split(/\s+/).every((word) => text.includes(word));
}

/** Who may open this page: the admins' own list of teammates, with a box to add one by email. */
function TeamAccess() {
  const [list, setList] = useState<TeamList | null>(null);
  const [email, setEmail] = useState("");
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);

  useEffect(() => {
    fetchTeam()
      .then(setList)
      .catch((caught: Error) => setProblem(caught.message));
  }, []);

  function change(action: Promise<TeamList>, done?: () => void) {
    setBusy(true);
    setProblem(null);
    action
      .then((answer) => {
        setList((current) => ({ ...current, ...answer }));
        done?.();
      })
      .catch((caught: Error) => setProblem(caught.message))
      .finally(() => setBusy(false));
  }

  function add(event: FormEvent) {
    event.preventDefault();
    if (email.trim()) change(addTeammate(email), () => setEmail(""));
  }

  return (
    <section className={styles.panel} aria-label="Who can see this page">
      <h2 className={styles.panelTitle}>Who can see this page</h2>
      <p className={styles.settingsHint}>
        Admins always can. A teammate you add here can open this page and download the table. They don't see
        emails or accuracy flags, and they can't change anything. Use the email of the Google account they sign
        in to Almanac with; it works even before they've signed in.
      </p>
      {list && (
        <ul className={styles.teamList}>
          {(list.admins ?? []).map((admin) => (
            <li key={`admin:${admin}`}>
              <span className={styles.teamEmail}>{admin}</span>
              <span className={styles.rowMuted}>Admin</span>
            </li>
          ))}
          {list.team.map((mate) => (
            <li key={mate.email}>
              <span className={styles.teamEmail}>{mate.email}</span>
              <span className={styles.rowMuted}>{mate.account ?? "Hasn't signed in yet"}</span>
              <button
                type="button"
                className={styles.smallButton}
                disabled={busy}
                onClick={() => change(removeTeammate(mate.email))}
              >
                Remove
              </button>
            </li>
          ))}
        </ul>
      )}
      <form className={styles.teamAdd} onSubmit={add}>
        <input
          className={styles.input}
          type="email"
          value={email}
          placeholder="teammate@gmail.com"
          aria-label="A teammate's email"
          autoComplete="off"
          onChange={(event) => setEmail(event.target.value)}
        />
        <button type="submit" className={styles.smallPrimary} disabled={busy || !email.trim()}>
          Add teammate
        </button>
      </form>
      {problem && (
        <p className={styles.error} role="alert">
          {problem}
        </p>
      )}
    </section>
  );
}

/**
 * The players page, at /admin/players (Ryan, Nov 17, 2026): every signed-in account with its
 * standing and record, read live from the game each time it's opened. Sort by any column,
 * search, or download the whole table for Excel. Open to admins and to the teammates they add
 * at the foot of the page; a teammate sees no emails or accuracy flags.
 */
export function AdminPlayers() {
  const [report, setReport] = useState<PlayersReport | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [sort, setSort] = useState<{ key: SortKey; down: boolean }>({ key: "prestige", down: true });
  const [filter, setFilter] = useState<Filter>("all");
  const [search, setSearch] = useState("");

  function load() {
    setLoading(true);
    fetchPlayers()
      .then((answer) => {
        setReport(answer);
        setError(null);
      })
      .catch((caught: Error) => setError(caught.message))
      .finally(() => setLoading(false));
  }
  useEffect(load, []);

  const now = report ? new Date(report.as_of).getTime() : 0;
  const recent = (report?.recent_days ?? 7) * 86_400_000;
  const shown = useMemo(() => {
    if (!report) return [];
    const words = search.trim().toLowerCase();
    return report.players
      .filter((player) => {
        if (filter === "never" && player.last_played) return false;
        if (filter === "recent" && !(player.last_played && now - new Date(player.last_played).getTime() <= recent))
          return false;
        return matches(player, words);
      })
      .sort((a, b) => compare(a, b, sort.key, sort.down));
  }, [report, search, filter, sort, now, recent]);

  if (error && !report) {
    return (
      <main className={styles.narrowPage}>
        <Brand home="social" />
        <p className={styles.empty}>
          {error === "Sign in first." ? "Sign in from the main menu to open the players page." : error}
        </p>
        <a className={styles.quietLink} href="/">
          Go to the main menu
        </a>
      </main>
    );
  }
  if (!report) return <BookLoader label="Counting the players" />;

  const { summary, viewer } = report;
  const days = report.recent_days;
  const tiles = [
    { label: "Accounts", value: summary.accounts },
    { label: `New in ${days} days`, value: summary.new_recently },
    { label: `Played in ${days} days`, value: summary.played_recently },
    { label: "Games saved", value: summary.games },
    { label: "Open-table rounds", value: summary.open_rounds },
    { label: "Coins held", value: summary.coins },
  ];
  const filters: { id: Filter; label: string; count: number }[] = [
    { id: "all", label: "Everyone", count: summary.accounts },
    { id: "recent", label: `Played in ${days} days`, count: summary.played_recently },
    { id: "never", label: "Never played", count: summary.accounts - summary.played_ever },
  ];

  function sortBy(key: SortKey) {
    setSort((current) =>
      // The first click on a column puts the most first, or A first for the name; the next flips it.
      current.key === key ? { key, down: !current.down } : { key, down: key !== "name" },
    );
  }

  return (
    <main className={`${styles.playersPage} ${styles.calm}`}>
      <div className={styles.pageNav}>
        <Brand home="social" />
        <div className={styles.pageLinks}>
          <a href="/admin/overview">Overview</a>
          {viewer.admin && <a href="/admin/reports">Reports</a>}
          {viewer.admin && <a href="/admin/flags">Accuracy flags</a>}
          <a href="/social">Social</a>
        </div>
      </div>

      <div className={styles.playersHead}>
        <div>
          <h1 className={styles.heading}>Players</h1>
          <p className={styles.settingsHint}>
            Every signed-in account, read live from the game. As of{" "}
            {new Date(report.as_of).toLocaleTimeString(undefined, { hour: "numeric", minute: "2-digit" })}.
          </p>
        </div>
        <div className={styles.playersActions}>
          <button type="button" className={styles.smallButton} disabled={loading} onClick={load}>
            {loading ? "Refreshing…" : "Refresh"}
          </button>
          <a className={styles.smallPrimary} href={PLAYERS_FILE} download>
            Download Excel
          </a>
        </div>
      </div>
      {error && (
        <p className={styles.error} role="alert">
          Couldn't refresh: {error}
        </p>
      )}

      <div className={styles.playersTiles}>
        {tiles.map((tile) => (
          <div key={tile.label} className={styles.statTile}>
            <span className={styles.statValue}>{count(tile.value)}</span>
            <span className={styles.statLabel}>{tile.label}</span>
          </div>
        ))}
      </div>

      <section className={styles.panel} aria-label="Players">
        <div className={styles.playersTools}>
          <input
            className={styles.input}
            type="search"
            value={search}
            placeholder={viewer.admin ? "Search by name, handle, email or group" : "Search by name, handle or group"}
            aria-label="Search players"
            onChange={(event) => setSearch(event.target.value)}
          />
          <div className={styles.playersFilters} role="group" aria-label="Show">
            {filters.map((entry) => (
              <button
                key={entry.id}
                type="button"
                aria-pressed={filter === entry.id}
                className={`${styles.slotTab} ${filter === entry.id ? styles.slotTabActive : ""}`}
                onClick={() => setFilter(entry.id)}
              >
                {entry.label} · {count(entry.count)}
              </button>
            ))}
          </div>
        </div>

        <div className={styles.playersScroll}>
          <table className={styles.playersTable}>
            <thead>
              <tr>
                {COLUMNS.map((column) => {
                  const active = sort.key === column.key;
                  return (
                    <th
                      key={column.key}
                      scope="col"
                      title={column.title}
                      className={column.text ? undefined : styles.playerNum}
                      aria-sort={active ? (sort.down ? "descending" : "ascending") : "none"}
                    >
                      <button type="button" className={styles.sortHead} onClick={() => sortBy(column.key)}>
                        {column.label}
                        <span aria-hidden="true">{active ? (sort.down ? " ▾" : " ▴") : ""}</span>
                      </button>
                    </th>
                  );
                })}
              </tr>
            </thead>
            <tbody>
              {shown.map((player) => (
                <tr key={player.public_id}>
                  <th scope="row">
                    <a className={styles.playerCell} href={`/u/${player.public_id}`}>
                      <Avatar avatar={player.avatar} size={30} label="" />
                      <span className={styles.playerCellText}>
                        <strong>{player.name}</strong>
                        {(player.handle || player.email) && (
                          <span>{[player.handle ? `@${player.handle}` : "", player.email ?? ""].filter(Boolean).join(" · ")}</span>
                        )}
                      </span>
                    </a>
                    {player.flag === "open" && (
                      <a className={styles.playerTag} href="/admin/flags" title="An open accuracy flag, waiting for review">
                        Flag open
                      </a>
                    )}
                    {player.flag === "confirmed" && (
                      <span className={styles.playerTag} title="A confirmed accuracy flag: left off public boards">
                        Confirmed flag
                      </span>
                    )}
                  </th>
                  <td className={styles.playerNum}>{player.level}</td>
                  <td className={styles.playerNum}>{count(player.xp)}</td>
                  <td className={styles.playerNum}>{count(player.prestige)}</td>
                  <td className={styles.playerNum}>{count(player.coins)}</td>
                  <td className={styles.playerNum}>{count(player.games)}</td>
                  <td className={styles.playerNum}>
                    {count(player.wins)}
                    {player.games > 0 && <span className={styles.rowMuted}> · {Math.round((100 * player.wins) / player.games)}%</span>}
                  </td>
                  <td className={styles.playerNum}>{count(player.best_quotes)}</td>
                  <td className={styles.playerNum}>{count(player.trades)}</td>
                  <td className={styles.playerNum}>{count(player.open_rounds)}</td>
                  <td className={styles.playerNum}>{count(player.badges)}</td>
                  <td className={styles.playerNum}>{count(player.friends)}</td>
                  <td className={styles.playerGroups}>{player.groups.join(", ")}</td>
                  <td className={styles.playerDate}>{date(player.joined)}</td>
                  <td className={styles.playerDate}>{ago(player.last_played, now)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {shown.length === 0 && <p className={styles.empty}>Nobody matches that.</p>}
        <p className={styles.settingsHint}>
          Showing {count(shown.length)} of {count(summary.accounts)}. Games are hosted and live games; open-table
          rounds are counted on their own. The Excel file has every column, including podiums, points, live games,
          coins spent and items owned.
        </p>
      </section>

      {viewer.admin && <TeamAccess />}
    </main>
  );
}
