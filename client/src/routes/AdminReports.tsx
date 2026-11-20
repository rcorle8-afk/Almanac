import { useEffect, useState } from "react";
import { BookLoader } from "../components/BookLoader";
import { Brand } from "../components/TopBar";
import { fetchReviewQueue, resolveReport, type ReportKind, type ReviewItem } from "../lib/social";
import styles from "../styles.module.css";

/** What each kind of report is called, and what clearing it does. */
const KINDS: Record<ReportKind, { title: (item: ReviewItem) => string; clear: string }> = {
  bio: { title: (item) => `Bio of ${item.owner?.name ?? "a player"}`, clear: "Clear bio" },
  group_name: { title: () => "Group name", clear: "Reset name" },
  group_bio: { title: (item) => `Bio of the group ${item.group?.name ?? ""}`.trim(), clear: "Clear bio" },
  group_image: { title: (item) => `Picture of the group ${item.group?.name ?? ""}`.trim(), clear: "Remove picture" },
};

/** The review queue (M5), at /admin/reports, open only to accounts listed in ADMIN_EMAILS.
 *  Whatever was reported (a player's bio; a group's name, bio or picture) is already hidden;
 *  restore shows it again, clear empties the bio, renames the group "Group N", or takes the
 *  picture down. */
export function AdminReports() {
  const [queue, setQueue] = useState<ReviewItem[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  function load() {
    fetchReviewQueue()
      .then(setQueue)
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
  if (!queue) return <BookLoader label="Opening the queue" />;

  return (
    <main className={styles.narrowPage}>
      <div className={styles.pageNav}>
        <Brand home="social" />
        <div className={styles.pageLinks}>
          <a href="/admin/overview">Overview</a>
          <a href="/admin/players">Players</a>
          <a href="/admin/flags">Accuracy flags</a>
          <a href="/social">Social</a>
        </div>
      </div>
      <h1 className={styles.heading}>Reports</h1>
      {queue.length === 0 ? (
        <p className={styles.empty}>Nothing to review.</p>
      ) : (
        queue.map((item) => (
          <section key={item.id} className={styles.panel}>
            <h2 className={styles.panelTitle}>
              {KINDS[item.kind].title(item)} · {item.reporters.length} {item.reporters.length === 1 ? "report" : "reports"}
            </h2>
            {item.kind === "group_image" ? (
              item.image ? (
                <img className={styles.reviewImage} src={item.image} alt="The reported picture" />
              ) : (
                <p className={styles.empty}>The owner has already taken the picture down.</p>
              )
            ) : (
              <p className={styles.reviewText}>{item.text}</p>
            )}
            <p className={styles.empty}>
              {item.kind === "bio" && item.owner ? (
                <a className={styles.inlineLink} href={`/u/${item.owner.public_id}`}>
                  Their profile
                </a>
              ) : item.group ? (
                <a className={styles.inlineLink} href={`/g/${item.group.public_id}`}>
                  The group
                </a>
              ) : null}
              {" · reported by "}
              {item.reporters.map((card) => card.name).join(", ")}
            </p>
            <div className={styles.actions}>
              <button type="button" className={styles.button} onClick={() => resolveReport(item.id, "restore").then(load)}>
                Restore
              </button>
              <button type="button" className={`${styles.button} ${styles.dangerButton}`} onClick={() => resolveReport(item.id, "clear").then(load)}>
                {KINDS[item.kind].clear}
              </button>
            </div>
          </section>
        ))
      )}
    </main>
  );
}
