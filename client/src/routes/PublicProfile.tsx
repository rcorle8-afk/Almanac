import { useEffect, useState } from "react";
import { Avatar } from "../avatar/Avatar";
import { Bell } from "../components/Bell";
import { BookLoader } from "../components/BookLoader";
import { NameCard } from "../components/NameCard";
import { Brand } from "../components/TopBar";
import {
  acceptFriend,
  addFriend,
  blockPlayer,
  declineFriend,
  fetchPublicProfile,
  removeFriend,
  report,
  unblockPlayer,
  type PublicProfile as ProfileData,
  type Relation,
} from "../lib/social";
import styles from "../styles.module.css";
import { BadgeShelf } from "./Profile";

/** The friend controls for someone else's profile, by how you stand with them. */
function Relationship({ profile, onChange }: { profile: ProfileData; onChange: (relation: Relation) => void }) {
  const [busy, setBusy] = useState(false);
  const id = profile.public_id;

  async function run(action: () => Promise<{ relation: Relation }>, check?: string) {
    if (check && !confirm(check)) return;
    setBusy(true);
    try {
      onChange((await action()).relation);
    } catch (caught) {
      alert(caught instanceof Error ? caught.message : "That didn't work.");
    } finally {
      setBusy(false);
    }
  }

  const primary = (label: string, action: () => Promise<{ relation: Relation }>) => (
    <button type="button" className={`${styles.button} ${styles.primary}`} disabled={busy} onClick={() => run(action)}>
      {label}
    </button>
  );
  const quiet = (label: string, action: () => Promise<{ relation: Relation }>, check?: string) => (
    <button type="button" className={styles.button} disabled={busy} onClick={() => run(action, check)}>
      {label}
    </button>
  );

  switch (profile.relation) {
    case "friend":
      return <div className={styles.actions}>{quiet("Friends ✓", () => removeFriend(id), `Remove ${profile.name} from your friends?`)}{quiet("Block", () => blockPlayer(id), `Block ${profile.name}? They won't be able to find you or send requests.`)}</div>;
    case "incoming":
      return <div className={styles.actions}>{primary("Accept request", () => acceptFriend(id))}{quiet("Decline", () => declineFriend(id))}</div>;
    case "requested":
      return <div className={styles.actions}>{quiet("Cancel request", () => removeFriend(id))}{quiet("Block", () => blockPlayer(id), `Block ${profile.name}?`)}</div>;
    case "blocked":
      return <div className={styles.actions}>{quiet("Unblock", () => unblockPlayer(id))}</div>;
    case "you":
      return (
        <a className={`${styles.button} ${styles.buttonLink}`} href="/profile">
          This is you. Edit your profile
        </a>
      );
    default:
      return <div className={styles.actions}>{primary("Add friend", () => addFriend(id))}{quiet("Block", () => blockPlayer(id), `Block ${profile.name}? They won't be able to find you or send requests.`)}</div>;
  }
}

/** Another player's profile (M5), at /u/:id: their name card, standing, badges and bio, with
 *  the friend controls and a way to report the bio. */
export function PublicProfile() {
  const id = location.pathname.split("/").filter(Boolean).pop() ?? "";
  const [profile, setProfile] = useState<ProfileData | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [reported, setReported] = useState(false);

  useEffect(() => {
    fetchPublicProfile(id)
      .then(setProfile)
      .catch((caught: Error) => setError(caught.message));
  }, [id]);

  if (error) {
    return (
      <main className={styles.narrowPage}>
        <Brand home="social" />
        <p className={styles.empty}>{error === "Sign in first." ? "Sign in from the main menu to see profiles." : error}</p>
        <a className={styles.quietLink} href="/social">
          Back to Social
        </a>
      </main>
    );
  }
  if (!profile) return <BookLoader label="Opening their almanac" />;

  const stats: [string, number][] = [
    ["Games", profile.games],
    ["Wins", profile.wins],
    ["Best Quotes", profile.best_quotes],
  ];

  async function reportBio() {
    if (!confirm("Report this bio? It's hidden at once until it's reviewed.")) return;
    try {
      await report("bio", profile!.public_id);
      setReported(true);
      setProfile({ ...profile!, bio: "" });
    } catch (caught) {
      alert(caught instanceof Error ? caught.message : "That didn't work.");
    }
  }

  return (
    <main className={styles.narrowPage}>
      <div className={styles.pageNav}>
        <Brand home="social" />
        <div className={styles.navRight}>
          <div className={styles.pageLinks}>
            <a href="/social">Social</a>
          </div>
          <Bell />
        </div>
      </div>

      <header className={styles.profileHead}>
        <Avatar avatar={profile.avatar} size={72} label={`${profile.name}'s avatar`} />
        <div>
          <h1 className={styles.profileName}>
            <NameCard name={profile.name} banner={profile.avatar.banner} prestige={profile.prestige} />
          </h1>
          <p className={styles.empty}>
            {profile.handle ? `@${profile.handle} · ` : ""}Level {profile.level}
          </p>
        </div>
      </header>

      <Relationship profile={profile} onChange={(relation) => setProfile({ ...profile, relation })} />

      <section className={styles.statGrid} aria-label="Record">
        {stats.map(([label, value]) => (
          <div key={label} className={styles.statTile}>
            <span className={styles.statValue}>{value}</span>
            <span className={styles.statLabel}>{label}</span>
          </div>
        ))}
      </section>

      <section className={styles.panel} aria-label="Bio">
        <div className={styles.roadHead}>
          <h2 className={styles.panelTitle}>Bio</h2>
          {profile.bio && profile.relation !== "you" && !reported && (
            <button type="button" className={styles.linkButton} onClick={reportBio}>
              Report
            </button>
          )}
        </div>
        <p className={profile.bio ? styles.bioText : styles.empty}>
          {reported ? "Reported. Thanks; it's hidden while it's reviewed." : profile.bio || "No bio."}
        </p>
        {profile.bio_hidden && <p className={styles.notice}>Your bio is hidden from others while a report is reviewed.</p>}
      </section>

      {profile.badges.length > 0 && (
        <section className={styles.panel} aria-label="Badges">
          <h2 className={styles.panelTitle}>Badges</h2>
          <BadgeShelf badges={profile.badges} />
        </section>
      )}

      {profile.groups.length > 0 && (
        <section className={styles.panel} aria-label="Groups">
          <h2 className={styles.panelTitle}>Groups</h2>
          <div className={styles.rows}>
            {profile.groups.map((group) => (
              <a key={group.public_id} href={`/g/${group.public_id}`} className={styles.groupRow}>
                <strong>{group.name}</strong>
                <span className={styles.rowMuted}>›</span>
              </a>
            ))}
          </div>
        </section>
      )}
    </main>
  );
}
