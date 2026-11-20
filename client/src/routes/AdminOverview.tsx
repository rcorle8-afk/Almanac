import { useEffect, useState, type ReactNode } from "react";
import { BookLoader } from "../components/BookLoader";
import { Brand } from "../components/TopBar";
import { fetchOverview, type Goal, type GoalStatus, type Overview, type PageAccess } from "../lib/overview";
import styles from "../styles.module.css";

const SECTIONS = [
  { id: "now", label: "Right now" },
  { id: "structure", label: "Structure" },
  { id: "plans", label: "Plans" },
  { id: "services", label: "Services" },
  { id: "shipped", label: "Shipped" },
  { id: "pages", label: "Pages" },
  { id: "code", label: "Code" },
  { id: "data", label: "Database" },
  { id: "tools", label: "Tools" },
  { id: "team", label: "Team" },
];

const STATUS: Record<GoalStatus, string> = {
  done: "Done",
  in_progress: "In progress",
  ongoing: "Ongoing",
  planned: "Planned",
  not_started: "Not started",
  untracked: "Not tracked yet",
};
// What is being worked on, then what is lined up, then what nobody has started.
const AHEAD: GoalStatus[] = ["in_progress", "planned", "not_started"];

const ACCESS: Record<PageAccess, string> = {
  everyone: "Everyone",
  signed_in: "Signed in",
  team: "Team",
  admin: "Admins",
};

const count = (value: number) => value.toLocaleString();

/** "2026-11-17" as "Nov 17, 2026", read as a calendar day and not as midnight UTC. */
function day(iso: string) {
  const [year, month, date] = iso.slice(0, 10).split("-").map(Number);
  if (!year || !month || !date) return iso;
  return new Date(year, month - 1, date).toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" });
}

function moment(iso: string) {
  return new Date(iso).toLocaleString(undefined, { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" });
}

function uptime(seconds: number) {
  const minutes = Math.max(1, Math.round(seconds / 60));
  if (minutes < 90) return `${minutes} min`;
  const hours = Math.floor(minutes / 60);
  return hours < 48 ? `${hours} h ${minutes % 60} min` : `${Math.floor(hours / 24)} days`;
}

function size(bytes: number | null) {
  if (bytes === null) return "";
  return bytes < 1_048_576 ? `${Math.max(1, Math.round(bytes / 1024))} KB` : `${(bytes / 1_048_576).toFixed(1)} MB`;
}

function StatusChip({ status }: { status: GoalStatus }) {
  return <span className={`${styles.ovStatus} ${styles[`ovStatus_${status}`] ?? ""}`}>{STATUS[status] ?? status}</span>;
}

function Section({ id, title, lead, children }: { id: string; title: string; lead?: ReactNode; children: ReactNode }) {
  return (
    <section id={id} className={`${styles.panel} ${styles.ovSection}`} aria-labelledby={`${id}-title`}>
      <h2 id={`${id}-title`} className={styles.ovTitle}>
        {title}
      </h2>
      {lead && <p className={styles.settingsHint}>{lead}</p>}
      {children}
    </section>
  );
}

function GoalRow({ goal }: { goal: Goal }) {
  return (
    <li className={`${styles.ovGoal} ${goal.depth > 1 ? styles.ovGoalUnder : ""}`}>
      <StatusChip status={goal.status} />
      <span className={styles.ovGoalText}>
        <strong>{goal.goal}</strong>
        {goal.note && <span>{goal.note}</span>}
      </span>
      {goal.milestone && <span className={styles.ovTag}>{goal.milestone}</span>}
    </li>
  );
}

/** Plans: the milestones, what is being worked on and what's next, then every goal by area. */
function Plans({ data }: { data: Overview }) {
  const areas: { name: string; goals: Goal[] }[] = [];
  for (const goal of [...data.goals].sort((a, b) => a.order - b.order)) {
    const area = areas.find((entry) => entry.name === goal.section);
    if (area) area.goals.push(goal);
    else areas.push({ name: goal.section, goals: [goal] });
  }
  const done = data.goals.filter((goal) => goal.status === "done").length;

  return (
    <Section
      id="plans"
      title="Plans and goals"
      lead={
        <>
          {done} of {data.goals.length} goals done.
          {data.plans_as_of && ` Written ${moment(data.plans_as_of)}; it updates with each deploy.`}
        </>
      }
    >
      {data.principles.length > 0 && (
        <ul className={styles.ovPrinciples}>
          {data.principles.map((principle) => (
            <li key={principle}>{principle}</li>
          ))}
        </ul>
      )}

      <h3 className={styles.panelTitle}>Milestones</h3>
      <ol className={styles.ovMilestones}>
        {data.milestones.map((milestone) => (
          <li key={milestone.id} className={styles.ovGoal}>
            <StatusChip status={milestone.status} />
            <span className={styles.ovGoalText}>
              <strong>
                {milestone.id} · {milestone.name}
              </strong>
              <span>{milestone.summary}</span>
              {milestone.open && <span>Still open: {milestone.open}</span>}
            </span>
            {milestone.shipped && <span className={styles.ovTag}>{day(milestone.shipped)}</span>}
          </li>
        ))}
      </ol>

      {AHEAD.map((status) => {
        const goals = data.goals.filter((goal) => goal.status === status);
        if (goals.length === 0) return null;
        return (
          <div key={status}>
            <h3 className={styles.panelTitle}>
              {STATUS[status]} · {goals.length}
            </h3>
            <ul className={styles.ovGoals}>
              {goals.map((goal) => (
                <GoalRow key={goal.order} goal={{ ...goal, depth: 1 }} />
              ))}
            </ul>
          </div>
        );
      })}

      <h3 className={styles.panelTitle}>Every goal, by area</h3>
      <div className={styles.ovAreas}>
        {areas.map((area) => (
          <details key={area.name} className={styles.ovArea}>
            <summary>
              <strong>{area.name}</strong>
              <span className={styles.rowMuted}>
                {area.goals.filter((goal) => goal.status === "done").length} of {area.goals.length} done
              </span>
            </summary>
            <ul className={styles.ovGoals}>
              {area.goals.map((goal) => (
                <GoalRow key={goal.order} goal={goal} />
              ))}
            </ul>
          </details>
        ))}
      </div>
    </Section>
  );
}

/**
 * The overview page, at /admin/overview (Ryan, Nov 17, 2026): an organizational chart of the app
 * for the people working on it. How the pieces fit together, the outside services it relies on,
 * what is planned and what has shipped, every page, module and table, and what the running
 * server looks like right now. Open to admins and the teammates they've added; only admins see
 * emails. The structure is written out in server/overview.py and checked against the code.
 */
export function AdminOverview() {
  const [data, setData] = useState<Overview | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  function load() {
    setLoading(true);
    fetchOverview()
      .then((answer) => {
        setData(answer);
        setError(null);
      })
      .catch((caught: Error) => setError(caught.message))
      .finally(() => setLoading(false));
  }
  useEffect(load, []);

  if (error && !data) {
    return (
      <main className={styles.narrowPage}>
        <Brand home="social" />
        <p className={styles.empty}>
          {error === "Sign in first." ? "Sign in from the main menu to open the overview." : error}
        </p>
        <a className={styles.quietLink} href="/">
          Go to the main menu
        </a>
      </main>
    );
  }
  if (!data) return <BookLoader label="Drawing the map" />;

  const { status, viewer } = data;
  const tiles = [
    { label: "Up for", value: uptime(status.uptime_seconds), title: `Started ${moment(status.started_at)}` },
    { label: "Rooms open", value: count(status.rooms), title: `${status.rooms_in_play} in a round` },
    { label: "People at tables", value: count(status.people_at_tables) },
    { label: "Accounts", value: count(status.accounts) },
    { label: "Games saved", value: count(status.games) },
    { label: "Questions playable", value: count(status.questions_playable), title: `${count(status.questions_in_bank)} in the bank` },
  ];

  return (
    <main className={`${styles.playersPage} ${styles.calm}`}>
      <div className={styles.pageNav}>
        <Brand home="social" />
        <div className={styles.pageLinks}>
          <a href="/admin/players">Players</a>
          {viewer.admin && <a href="/admin/reports">Reports</a>}
          {viewer.admin && <a href="/admin/flags">Accuracy flags</a>}
          <a href="/social">Social</a>
        </div>
      </div>

      <div className={styles.playersHead}>
        <div>
          <h1 className={styles.heading}>Overview</h1>
          <p className={styles.settingsHint}>
            How Almanac is put together, what it runs on, and what's planned. For everyone working on it.
          </p>
        </div>
        <div className={styles.playersActions}>
          <button type="button" className={styles.smallButton} disabled={loading} onClick={load}>
            {loading ? "Refreshing…" : "Refresh"}
          </button>
        </div>
      </div>
      {error && (
        <p className={styles.error} role="alert">
          Couldn't refresh: {error}
        </p>
      )}

      <nav className={styles.ovNav} aria-label="On this page">
        {SECTIONS.map((section) => (
          <a key={section.id} href={`#${section.id}`}>
            {section.label}
          </a>
        ))}
      </nav>

      <Section
        id="now"
        title="Right now"
        lead={
          <>
            Read from the running server as this page opened. Started {moment(status.started_at)}
            {status.build ? `, serving build ${status.build}` : ""}
            {status.database_bytes !== null ? `; the database is ${size(status.database_bytes)}` : ""}. The server sleeps
            when nobody is on the site, and a visit wakes it.
          </>
        }
      >
        <div className={styles.playersTiles}>
          {tiles.map((tile) => (
            <div key={tile.label} className={styles.statTile} title={tile.title}>
              <span className={styles.statValue}>{tile.value}</span>
              <span className={styles.statLabel}>{tile.label}</span>
            </div>
          ))}
        </div>
        <ul className={styles.ovSwitches} aria-label="What is switched on">
          {status.switches.map((entry) => {
            const odd = entry.on !== entry.expected;
            return (
              <li
                key={entry.name}
                className={`${styles.ovSwitch} ${entry.on ? styles.ovSwitchOn : ""} ${odd ? styles.ovSwitchOdd : ""}`}
                title={`${entry.about}${odd ? ` The live site keeps this ${entry.expected ? "on" : "off"}.` : ""}`}
              >
                <strong>{entry.name}</strong>
                <span>
                  {entry.on ? "On" : "Off"}
                  {odd ? ` · the live site keeps it ${entry.expected ? "on" : "off"}` : ""}
                </span>
              </li>
            );
          })}
        </ul>
      </Section>

      <Section
        id="structure"
        title="How it fits together"
        lead="From what people open, down to where things are kept and what the app reaches outside for."
      >
        <ol className={styles.ovLayers}>
          {data.layers.map((layer) => (
            <li key={layer.id}>
              <div className={styles.ovLayer}>
                <div className={styles.ovLayerHead}>
                  <h3>{layer.name}</h3>
                  <p>{layer.about}</p>
                </div>
                <ul className={styles.ovParts}>
                  {layer.parts.map((part) => (
                    <li key={part.name} className={styles.ovPart}>
                      <strong>{part.name}</strong>
                      <span>{part.about}</span>
                      {part.where && <code>{part.where}</code>}
                    </li>
                  ))}
                </ul>
              </div>
              {layer.link && (
                <p className={styles.ovLink}>
                  <span aria-hidden="true">↕</span>
                  {layer.link}
                </p>
              )}
            </li>
          ))}
        </ol>
      </Section>

      <Plans data={data} />

      <Section
        id="services"
        title="Services"
        lead={
          data.cost_summary
            ? `Everything outside the app that Almanac relies on. At list prices they come to at most $${data.cost_summary.monthly_max_usd.toFixed(2)} a month, and Fly waives bills under $${data.cost_summary.fly_waiver_usd.toFixed(0)}. Prices checked ${day(data.cost_summary.prices_checked)}.`
            : "Everything outside the app that Almanac relies on."
        }
      >
        <ul className={styles.ovServices}>
          {data.services.map((service) => (
            <li key={service.service} className={styles.ovService}>
              <div className={styles.ovServiceHead}>
                <strong>{service.service}</strong>
                <span className={styles.ovTag}>{service.category}</span>
              </div>
              <p>{service.role}</p>
              <dl>
                <dt>Set up</dt>
                <dd>{service.setup}</dd>
                <dt>Cost</dt>
                <dd>{service.pricing}</dd>
                <dt>Since</dt>
                <dd>{day(service.since)}</dd>
              </dl>
              {service.link && (
                <a className={styles.inlineLink} href={service.link} target="_blank" rel="noreferrer">
                  Its documentation
                </a>
              )}
            </li>
          ))}
        </ul>
        {data.costs.length > 0 && (
          <div className={styles.ovScroll}>
            <table className={styles.ovTable}>
              <thead>
                <tr>
                  <th scope="col">What is paid for</th>
                  <th scope="col">Service</th>
                  <th scope="col" className={styles.ovNum}>
                    At most, a month
                  </th>
                  <th scope="col">How that's worked out</th>
                </tr>
              </thead>
              <tbody>
                {data.costs.map((cost) => (
                  <tr key={cost.item}>
                    <th scope="row">{cost.item}</th>
                    <td>{cost.service}</td>
                    <td className={styles.ovNum}>${cost.monthly_max_usd.toFixed(2)}</td>
                    <td className={styles.ovWrap}>{cost.basis}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Section>

      <Section id="shipped" title="What shipped when" lead="The main releases, newest first.">
        <ol className={styles.ovTimeline}>
          {[...data.timeline].reverse().map((entry) => (
            <li key={`${entry.date}:${entry.title}`}>
              <span className={styles.ovTag}>{day(entry.date)}</span>
              <span className={styles.ovGoalText}>
                <strong>{entry.title}</strong>
                <span>{entry.detail}</span>
              </span>
            </li>
          ))}
        </ol>
      </Section>

      <Section id="pages" title="Pages" lead="Every address the app answers, and who can open it.">
        <div className={styles.ovScroll}>
          <table className={styles.ovTable}>
            <thead>
              <tr>
                <th scope="col">Page</th>
                <th scope="col">Address</th>
                <th scope="col">Who</th>
                <th scope="col">What it's for</th>
              </tr>
            </thead>
            <tbody>
              {data.pages.map((page) => (
                <tr key={page.path}>
                  <th scope="row">{page.name}</th>
                  <td>
                    <code>
                      {page.path}
                      {page.path.length > 1 && page.path.endsWith("/") ? "…" : ""}
                    </code>
                  </td>
                  <td>
                    <span className={`${styles.ovStatus} ${styles[`ovAccess_${page.access}`] ?? ""}`}>{ACCESS[page.access]}</span>
                  </td>
                  <td className={styles.ovWrap}>{page.about}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Section>

      <Section
        id="code"
        title="Code map"
        lead={
          data.project
            ? `${count(data.project.code_files)} source files, ${count(data.project.code_lines)} lines and ${count(data.project.tests)} automated tests as of ${day(data.project.date)}. The spec for all of it is CLAUDE.md, at the top of the project.`
            : "The spec for all of it is CLAUDE.md, at the top of the project."
        }
      >
        <h3 className={styles.panelTitle}>Server · server/</h3>
        <div className={styles.ovScroll}>
          <table className={styles.ovTable}>
            <thead>
              <tr>
                <th scope="col">Module</th>
                <th scope="col" className={styles.ovNum}>
                  Lines
                </th>
                <th scope="col">What it does</th>
              </tr>
            </thead>
            <tbody>
              {data.modules.map((module) => (
                <tr key={module.name}>
                  <th scope="row">
                    <code>{module.name}</code>
                  </th>
                  <td className={styles.ovNum}>{module.lines === null ? "" : count(module.lines)}</td>
                  <td className={styles.ovWrap}>{module.about || "Not described yet."}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <h3 className={styles.panelTitle}>Client · client/src/</h3>
        <div className={styles.ovScroll}>
          <table className={styles.ovTable}>
            <tbody>
              {data.client.map((area) => (
                <tr key={area.name}>
                  <th scope="row">
                    <code>{area.name}</code>
                  </th>
                  <td className={styles.ovWrap}>{area.about}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Section>

      <Section id="data" title="Database" lead="Every table in the one SQLite file, with how many rows it holds right now.">
        <div className={styles.ovScroll}>
          <table className={styles.ovTable}>
            <thead>
              <tr>
                <th scope="col">Table</th>
                <th scope="col" className={styles.ovNum}>
                  Rows
                </th>
                <th scope="col">What it holds</th>
              </tr>
            </thead>
            <tbody>
              {data.tables.map((table) => (
                <tr key={table.name}>
                  <th scope="row">
                    <code>{table.name}</code>
                  </th>
                  <td className={styles.ovNum}>{count(table.rows)}</td>
                  <td className={styles.ovWrap}>{table.about || "Not described yet."}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Section>

      <Section id="tools" title="Tools and versions" lead="What the server, the client and the deploy are built with.">
        <div className={styles.ovScroll}>
          <table className={styles.ovTable}>
            <thead>
              <tr>
                <th scope="col">Tool</th>
                <th scope="col">Version</th>
                <th scope="col">Where</th>
                <th scope="col">What it's for</th>
              </tr>
            </thead>
            <tbody>
              {data.stack.map((tool) => (
                <tr key={`${tool.layer}:${tool.tool}`}>
                  <th scope="row">{tool.tool}</th>
                  <td>
                    <code>{tool.version}</code>
                  </td>
                  <td>{tool.layer}</td>
                  <td className={styles.ovWrap}>{tool.role}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Section>

      <Section
        id="team"
        title="Team"
        lead={
          <>
            {data.team.admin_count} {data.team.admin_count === 1 ? "admin" : "admins"} and {data.team.teammate_count}{" "}
            {data.team.teammate_count === 1 ? "teammate" : "teammates"} can open the team pages. Admins also review
            reports and accuracy flags.{" "}
            {viewer.admin ? (
              <>
                Add or remove teammates at the foot of the{" "}
                <a className={styles.inlineLink} href="/admin/players">
                  Players page
                </a>
                ; admins are set in the ADMIN_EMAILS secret on Fly.
              </>
            ) : (
              "An admin adds teammates by email."
            )}
          </>
        }
      >
        <ul className={styles.teamList}>
          {data.team.admins.map((person, index) => (
            <li key={`admin:${person.email ?? person.name ?? index}`}>
              <span className={styles.teamEmail}>{person.name ?? person.email}</span>
              {person.name && person.email && <span className={styles.rowMuted}>{person.email}</span>}
              {!person.name && <span className={styles.rowMuted}>Hasn't signed in yet</span>}
              <span className={styles.ovTag}>Admin</span>
            </li>
          ))}
          {data.team.teammates.map((person, index) => (
            <li key={`mate:${person.email ?? person.name ?? index}`}>
              <span className={styles.teamEmail}>{person.name ?? person.email}</span>
              {person.name && person.email && <span className={styles.rowMuted}>{person.email}</span>}
              {!person.name && <span className={styles.rowMuted}>Hasn't signed in yet</span>}
              <span className={styles.ovTag}>Teammate</span>
            </li>
          ))}
        </ul>
      </Section>
    </main>
  );
}
