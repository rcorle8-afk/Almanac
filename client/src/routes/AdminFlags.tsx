import { useEffect, useState } from "react";
import { BookLoader } from "../components/BookLoader";
import { Brand } from "../components/TopBar";
import { decideFlag, fetchFlags, type AccuracyFlag } from "../lib/social";
import styles from "../styles.module.css";

const percent = (share: number) => `${Math.round(100 * share)}%`;

function odds(pValue: number) {
  if (pValue <= 0) return "practically never";
  const oneIn = 1 / pValue;
  if (oneIn >= 1e9) return "less than once in a billion";
  if (oneIn >= 1e6) return `about once in ${Math.round(oneIn / 1e6).toLocaleString()} million`;
  return `about once in ${Math.round(oneIn).toLocaleString()}`;
}

function day(iso: string | null) {
  return iso ? new Date(iso).toLocaleDateString(undefined, { month: "short", day: "numeric" }) : "";
}

/** One flagged player: the case in plain numbers, their recent quotes, and the two decisions. */
function FlagCard({ flag, onDone }: { flag: AccuracyFlag; onDone: () => void }) {
  const [busy, setBusy] = useState(false);
  async function decide(action: "clear" | "confirm") {
    setBusy(true);
    try {
      await decideFlag(flag.id, action);
      onDone();
    } finally {
      setBusy(false);
    }
  }
  const open = flag.status === "open";
  return (
    <section className={styles.panel}>
      <div className={styles.roadHead}>
        <h2 className={styles.panelTitle}>
          <a className={styles.inlineLink} href={`/u/${flag.player.public_id}`}>
            {flag.player.name}
          </a>
          {flag.player.handle ? ` · @${flag.player.handle}` : ""}
        </h2>
        <span className={styles.rowMuted}>
          {open ? `Flagged ${day(flag.created_at)}` : `${flag.status === "cleared" ? "Cleared" : "Confirmed"} ${day(flag.reviewed_at)}`}
        </span>
      </div>
      <div className={styles.statGrid}>
        <div className={styles.statTile}>
          <span className={styles.statValue}>
            {flag.bullseyes}/{flag.quotes}
          </span>
          <span className={styles.statLabel}>Bullseyes</span>
        </div>
        <div className={styles.statTile}>
          <span className={styles.statValue}>{percent(flag.rate)}</span>
          <span className={styles.statLabel}>Their rate</span>
        </div>
        <div className={styles.statTile}>
          <span className={styles.statValue}>{percent(flag.baseline)}</span>
          <span className={styles.statLabel}>Everyone else</span>
        </div>
      </div>
      <p className={styles.settingsHint}>
        An honest player at everyone else's rate would land this many bullseyes {odds(flag.p_value)}.
        {flag.beats != null &&
          flag.regulars != null &&
          (flag.beats === flag.regulars
            ? ` More accurate than every other regular player (${flag.regulars}).`
            : ` More accurate than ${flag.beats} of the ${flag.regulars} other regular players.`)}
      </p>
      <div className={styles.flagQuotes}>
        <table className={styles.flagTable}>
          <thead>
            <tr>
              <th>Question</th>
              <th>Quote</th>
              <th>Answer</th>
              <th>Spread</th>
              <th>Took</th>
            </tr>
          </thead>
          <tbody>
            {flag.recent.map((quote, index) => (
              <tr key={index} className={quote.bullseye ? styles.flagHit : undefined}>
                <td>{quote.question ?? "A question from an older game"}</td>
                <td className={styles.flagNum}>
                  {quote.bid} / {quote.ask}
                </td>
                <td className={styles.flagNum}>{quote.answer}</td>
                <td className={styles.flagNum}>{quote.spread == null ? "" : `×${quote.spread.toFixed(2)}`}</td>
                <td className={styles.flagNum}>{quote.seconds === null ? "" : `${quote.seconds}s`}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {open && (
        <div className={styles.actions}>
          <button type="button" className={styles.button} disabled={busy} onClick={() => decide("clear")}>
            Clear: honest
          </button>
          <button
            type="button"
            className={`${styles.button} ${styles.dangerButton}`}
            disabled={busy}
            onClick={() => decide("confirm")}
          >
            Confirm: looking answers up
          </button>
        </div>
      )}
    </section>
  );
}

/** The accuracy flags (M6 anti-cheat), at /admin/flags, open only to accounts in ADMIN_EMAILS.
 *  Flags are silent: a flagged player sees nothing. Clearing ends a flag and judges them again
 *  only on later quotes; confirming records the judgment for live mode to act on. */
export function AdminFlags() {
  const [data, setData] = useState<Awaited<ReturnType<typeof fetchFlags>> | null>(null);
  const [error, setError] = useState<string | null>(null);

  function load() {
    fetchFlags()
      .then(setData)
      .catch((caught: Error) => setError(caught.message));
  }

  useEffect(load, []);

  if (error) {
    return (
      <main className={styles.narrowPage}>
        <Brand home="social" />
        <p className={styles.empty}>{error}</p>
      </main>
    );
  }
  if (!data) return <BookLoader label="Opening the flags" />;
  const open = data.flags.filter((flag) => flag.status === "open");
  const reviewed = data.flags.filter((flag) => flag.status !== "open");

  return (
    <main className={styles.narrowPage}>
      <div className={styles.pageNav}>
        <Brand home="social" />
        <div className={styles.pageLinks}>
          <a href="/admin/overview">Overview</a>
          <a href="/admin/players">Players</a>
          <a href="/admin/reports">Reports</a>
          <a href="/social">Social</a>
        </div>
      </div>
      <h1 className={styles.heading}>Accuracy flags</h1>
      <p className={styles.settingsHint}>
        A bullseye is a sealed quote that holds the answer with the ask at most {data.bullseye_ratio}× the bid.
        Players are judged once they have {data.min_quotes} quotes, against everyone else's bullseye rate. A
        flagged player isn't told and nothing changes for them.
      </p>
      {open.length === 0 ? (
        <p className={styles.empty}>No open flags.</p>
      ) : (
        open.map((flag) => <FlagCard key={flag.id} flag={flag} onDone={load} />)
      )}
      {reviewed.length > 0 && (
        <>
          <h2 className={styles.heading}>Reviewed</h2>
          {reviewed.map((flag) => (
            <FlagCard key={flag.id} flag={flag} onDone={load} />
          ))}
        </>
      )}
    </main>
  );
}
