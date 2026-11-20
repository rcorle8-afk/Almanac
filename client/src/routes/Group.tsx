import QRCode from "qrcode";
import { useEffect, useRef, useState, type ChangeEvent, type FormEvent } from "react";
import { Avatar } from "../avatar/Avatar";
import { Bell } from "../components/Bell";
import { BookLoader } from "../components/BookLoader";
import { GroupIcon, GroupIconPicker } from "../components/GroupIcon";
import { NameCard } from "../components/NameCard";
import { PersonRow } from "../components/PersonRow";
import { SignInPanel } from "../components/SignInPanel";
import { Brand } from "../components/TopBar";
import { squarePicture } from "../lib/picture";
import {
  changeGroup,
  declineGroup,
  disbandGroup,
  fetchGroup,
  fetchGroupPreview,
  inviteLink,
  inviteToGroup,
  joinGroup,
  leaveGroup,
  onSocialChange,
  removeGroupImage,
  removeMember,
  report,
  resetInviteLink,
  searchHandles,
  uploadGroupImage,
  type Card,
  type GroupDetail,
  type GroupPreview,
  type ReportKind,
} from "../lib/social";
import styles from "../styles.module.css";
import { GroupPrestige } from "./Social";

const BIO_LIMIT = 160;
const SEARCH_DELAY_MS = 300;

function message(caught: unknown) {
  return caught instanceof Error ? caught.message : "That didn't work.";
}

const members = (n: number) => `${n} ${n === 1 ? "member" : "members"}`;

/* ---------- Inviting ---------- */

/** One friend or search result the owner can invite straight to their bell. */
function InviteRow({ group, card, sent, onSent }: { group: GroupDetail; card: Card; sent: boolean; onSent: () => void }) {
  return (
    <PersonRow card={card}>
      {sent ? (
        <span className={styles.relationTag}>Invited</span>
      ) : (
        <button
          type="button"
          className={styles.smallPrimary}
          onClick={() => inviteToGroup(group.public_id, card.public_id).then(onSent, (caught) => alert(message(caught)))}
        >
          Invite
        </button>
      )}
    </PersonRow>
  );
}

/** Ways to bring people in, on the group's own page. Every member has the link: copy it, hand
 *  it to the phone's share sheet, or show it as a QR code across a room. The owner can also
 *  swap the link for a new one and invite friends, or anyone by handle, straight to their bell. */
function InvitePanel({ group, onChange }: { group: GroupDetail; onChange: () => void }) {
  const owner = group.role === "owner";
  const link = inviteLink(group.public_id, group.invite_code ?? "");
  const [copied, setCopied] = useState(false);
  const [qr, setQr] = useState<string | null>(null);
  const [sent, setSent] = useState<Set<string>>(new Set());
  const [query, setQuery] = useState("");
  const [found, setFound] = useState<Card[] | null>(null);
  const field = useRef<HTMLInputElement>(null);
  const timer = useRef<number>();
  const canShare = typeof navigator.share === "function";
  const invited = (id: string) => setSent((current) => new Set(current).add(id));
  const inside = new Set([...group.members, ...group.pending].map((card) => card.public_id));

  useEffect(() => {
    if (!copied) return;
    const done = window.setTimeout(() => setCopied(false), 2000);
    return () => window.clearTimeout(done);
  }, [copied]);

  // A new link makes the old QR code wrong.
  useEffect(() => setQr(null), [link]);

  useEffect(() => {
    window.clearTimeout(timer.current);
    const text = query.trim();
    if (text.replace(/^@/, "").length < 2) {
      setFound(null);
      return;
    }
    timer.current = window.setTimeout(() => {
      searchHandles(text)
        .then(setFound)
        .catch(() => setFound([]));
    }, SEARCH_DELAY_MS);
    return () => window.clearTimeout(timer.current);
  }, [query]);

  async function copy() {
    try {
      await navigator.clipboard.writeText(link);
      setCopied(true);
    } catch {
      // No clipboard here (an old browser, or a page not on https): select it to copy by hand.
      field.current?.select();
    }
  }

  function share() {
    // Rejects when the sheet is closed without sharing; that isn't a problem to report.
    navigator.share({ title: `Join ${group.name} on Almanac`, text: `Join ${group.name} on Almanac`, url: link }).catch(() => undefined);
  }

  function toggleQr() {
    if (qr) return setQr(null);
    QRCode.toDataURL(link, { margin: 1, width: 240, color: { dark: "#ffffffff", light: "#00000000" } })
      .then(setQr)
      .catch(() => alert("The QR code couldn't be drawn."));
  }

  function newLink() {
    if (!confirm("Make a new invite link? The old one stops working for anyone who hasn't joined yet.")) return;
    resetInviteLink(group.public_id).then(onChange, (caught) => alert(message(caught)));
  }

  return (
    <section className={styles.panel} aria-label="Invite players">
      <h2 className={styles.panelTitle}>Invite players</h2>
      <label className={styles.field}>
        Invite link
        <input ref={field} className={`${styles.input} ${styles.linkField}`} value={link} readOnly onFocus={(event) => event.target.select()} />
      </label>
      <div className={styles.inviteActions}>
        <button type="button" className={`${styles.button} ${styles.primary}`} onClick={copy}>
          {copied ? "Copied" : "Copy link"}
        </button>
        {canShare && (
          <button type="button" className={styles.button} onClick={share}>
            Share
          </button>
        )}
        <button type="button" className={styles.button} aria-expanded={qr !== null} onClick={toggleQr}>
          {qr ? "Hide QR code" : "QR code"}
        </button>
      </div>
      {qr && <img className={`${styles.lobbyQr} ${styles.inviteQr}`} src={qr} alt={`QR code to join ${group.name}`} />}
      <p className={styles.settingsHint}>
        Anyone who opens the link can join after signing in, until the group is full.{" "}
        {owner ? (
          <button type="button" className={styles.textButton} onClick={newLink}>
            Make a new link
          </button>
        ) : (
          `${group.owner.name} can replace it with a new one.`
        )}
      </p>

      {owner && (
        <>
          <h3 className={styles.subTitle}>Invite friends</h3>
          {group.invitable.length === 0 ? (
            <p className={styles.empty}>
              No friends left to invite. To invite a whole room at once, host a game signed in and use the group
              invite in its settings.
            </p>
          ) : (
            <div className={styles.rows}>
              {group.invitable.map((card) => (
                <InviteRow key={card.public_id} group={group} card={card} sent={sent.has(card.public_id)} onSent={() => invited(card.public_id)} />
              ))}
            </div>
          )}
          <label className={styles.field} style={{ marginTop: 12 }}>
            Invite by handle
            <input
              className={styles.input}
              value={query}
              maxLength={21}
              autoCapitalize="none"
              autoComplete="off"
              placeholder="@handle"
              onChange={(event) => setQuery(event.target.value)}
            />
          </label>
          {found !== null && (
            <div className={styles.rows}>
              {found.length === 0 ? (
                <p className={styles.empty}>No handle starts with that.</p>
              ) : (
                found.map((card) =>
                  inside.has(card.public_id) ? (
                    <PersonRow key={card.public_id} card={card}>
                      <span className={styles.relationTag}>{group.pending.some((p) => p.public_id === card.public_id) ? "Invited" : "Member"}</span>
                    </PersonRow>
                  ) : (
                    <InviteRow key={card.public_id} group={group} card={card} sent={sent.has(card.public_id)} onSent={() => invited(card.public_id)} />
                  ),
                )
              )}
            </div>
          )}
          {group.pending.length > 0 && (
            <p className={styles.notice}>Waiting on {group.pending.map((card) => card.name).join(", ")}.</p>
          )}
        </>
      )}
    </section>
  );
}

/* ---------- The owner's tools ---------- */

/** How the group looks to everyone: its icon (a drawing and a colour, or an uploaded picture)
 *  and its bio. Each choice saves as it's made. */
function Customize({ group, onChange }: { group: GroupDetail; onChange: () => void }) {
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);
  const [bio, setBio] = useState(group.bio);
  const picker = useRef<HTMLInputElement>(null);

  useEffect(() => setBio(group.bio), [group.bio]);

  async function save(action: () => Promise<unknown>) {
    setBusy(true);
    setProblem(null);
    try {
      await action();
      onChange();
    } catch (caught) {
      setProblem(message(caught));
    } finally {
      setBusy(false);
    }
  }

  function picked(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    event.target.value = ""; // so choosing the same file again still fires
    if (file) void save(async () => uploadGroupImage(group.public_id, await squarePicture(file)));
  }

  return (
    <section className={styles.panel} aria-label="Customize">
      <h2 className={styles.panelTitle}>Customize</h2>

      <div className={styles.iconEditor}>
        <GroupIcon icon={group.icon} name={group.name} size={72} />
        <div className={styles.iconEditorText}>
          <input ref={picker} type="file" accept="image/png,image/jpeg,image/webp" hidden onChange={picked} />
          <div className={styles.buttonRow}>
            <button type="button" className={styles.smallPrimary} disabled={busy} onClick={() => picker.current?.click()}>
              {group.icon.image ? "Change picture" : "Upload a picture"}
            </button>
            {group.icon.image && (
              <button type="button" className={styles.smallButton} disabled={busy} onClick={() => save(() => removeGroupImage(group.public_id))}>
                Remove picture
              </button>
            )}
          </div>
          <span className={styles.personDetail} style={{ whiteSpace: "normal" }}>
            {group.icon.image
              ? "Your picture shows instead of the drawing below."
              : "Or pick a drawing and a colour. A picture is cropped to a square."}
          </span>
        </div>
      </div>
      {group.image_hidden && (
        <p className={styles.notice}>Someone reported the picture, so others see the drawing until it's reviewed.</p>
      )}

      <GroupIconPicker
        glyph={group.icon.glyph}
        color={group.icon.color}
        name={group.name}
        disabled={busy}
        onGlyph={(glyph) => save(() => changeGroup(group.public_id, { glyph }))}
        onColor={(color) => save(() => changeGroup(group.public_id, { color }))}
      />

      <label className={styles.field} style={{ marginTop: 14 }}>
        Bio
        <textarea
          className={styles.bioInput}
          value={bio}
          maxLength={BIO_LIMIT}
          rows={3}
          placeholder="What the group is, and when it plays."
          onChange={(event) => setBio(event.target.value)}
        />
      </label>
      <div className={styles.bioFoot}>
        <span className={styles.rowMuted}>
          {bio.length} / {BIO_LIMIT}
        </span>
        <button
          type="button"
          className={styles.smallPrimary}
          disabled={busy || bio.trim() === group.bio}
          onClick={() => save(() => changeGroup(group.public_id, { bio }))}
        >
          Save bio
        </button>
      </div>
      {group.bio_hidden && (
        <p className={styles.notice}>Someone reported the bio, so others can't see it until it's reviewed.</p>
      )}
      {problem && (
        <p className={styles.error} role="alert">
          {problem}
        </p>
      )}
    </section>
  );
}

/** Rename, and disband. */
function Manage({ group, onChange }: { group: GroupDetail; onChange: () => void }) {
  const [name, setName] = useState(group.name);
  const [problem, setProblem] = useState<string | null>(null);

  async function rename(event: FormEvent) {
    event.preventDefault();
    setProblem(null);
    try {
      await changeGroup(group.public_id, { name });
      onChange();
    } catch (caught) {
      setProblem(message(caught));
    }
  }

  return (
    <section className={styles.panel} aria-label="Manage">
      <h2 className={styles.panelTitle}>Manage</h2>
      <form className={styles.inlineForm} onSubmit={rename}>
        <label className={styles.field}>
          Name
          <input className={styles.input} value={name} maxLength={32} onChange={(event) => setName(event.target.value)} />
        </label>
        <button type="submit" className={styles.smallButton} disabled={name.trim() === group.name}>
          Rename
        </button>
      </form>
      {problem && <p className={styles.error}>{problem}</p>}
      <button
        type="button"
        className={`${styles.button} ${styles.dangerButton}`}
        style={{ marginTop: 14 }}
        onClick={() => {
          const warning = `Disband ${group.name}? Members, invites and the leaderboard go with it, and the coins it cost don't come back.`;
          if (confirm(warning)) {
            disbandGroup(group.public_id).then(() => location.assign("/social"), (caught) => alert(message(caught)));
          }
        }}
      >
        Disband group
      </button>
    </section>
  );
}

/* ---------- Reporting ---------- */

const REPORTABLE: { kind: ReportKind; label: string; there: (group: GroupDetail) => boolean }[] = [
  { kind: "group_name", label: "The name", there: () => true },
  { kind: "group_bio", label: "The bio", there: (group) => group.bio !== "" },
  { kind: "group_image", label: "The picture", there: (group) => group.icon.image !== null },
];

/** For anyone but the owner: report the name, the bio or the picture. Whatever is reported is
 *  hidden at once, until it's reviewed. */
function ReportMenu({ group, onReported }: { group: GroupDetail; onReported: () => void }) {
  const [open, setOpen] = useState(false);
  const [done, setDone] = useState(false);

  if (done) return <p className={styles.notice}>Reported. Thanks; it's hidden while it's reviewed.</p>;
  if (!open) {
    return (
      <button type="button" className={`${styles.linkButton} ${styles.reportToggle}`} onClick={() => setOpen(true)}>
        Report
      </button>
    );
  }
  return (
    <div className={styles.reportRow} role="group" aria-label="Report">
      <span className={styles.rowMuted}>Report:</span>
      {REPORTABLE.filter((entry) => entry.there(group)).map((entry) => (
        <button
          key={entry.kind}
          type="button"
          className={styles.linkButton}
          onClick={() =>
            report(entry.kind, group.public_id).then(
              () => {
                setDone(true);
                onReported();
              },
              (caught) => alert(message(caught)),
            )
          }
        >
          {entry.label}
        </button>
      ))}
      <button type="button" className={styles.linkButton} onClick={() => setOpen(false)}>
        Cancel
      </button>
    </div>
  );
}

/* ---------- The page ---------- */

/** What someone who followed an invite link sees before signing in: the group, and the way in. */
function InviteDoor({ group, onSignedIn }: { group: GroupPreview; onSignedIn: () => void }) {
  return (
    <main className={styles.narrowPage}>
      <div className={styles.pageNav}>
        <Brand home="play" />
      </div>
      <section className={`${styles.panel} ${styles.inviteBanner}`}>
        <div className={styles.groupHead}>
          <GroupIcon icon={group.icon} name={group.name} size={64} />
          <div className={styles.groupHeadText}>
            <span className={styles.rowMuted}>You're invited to</span>
            <h1 className={styles.heading}>{group.name}</h1>
            <span className={styles.groupLine}>
              <GroupPrestige value={group.prestige} />
              <span className={styles.rowMuted}>
                {members(group.member_count)} · run by {group.owner.name}
              </span>
            </span>
          </div>
        </div>
        {group.bio && <p className={styles.groupBio}>{group.bio}</p>}
      </section>
      <SignInPanel
        title="Sign in to join"
        blurb="Groups are for signed-in players, so members can find each other. Sign in and the invite is waiting."
        onSignedIn={onSignedIn}
      />
      <a className={styles.quietLink} href="/">
        What is Almanac?
      </a>
    </main>
  );
}

/** A group's page (M5), at /g/:id: who it is (icon, name, bio), its members ranked by prestige,
 *  Play now for members (a room only members can join, with an invite on every member's bell),
 *  the invite link, and the owner's tools. /g/:id?invite=CODE is that link: it shows the group
 *  to anyone, and lets a signed-in player join. */
export function Group() {
  const id = location.pathname.split("/").filter(Boolean).pop() ?? "";
  const [invite, setInvite] = useState(() => new URLSearchParams(location.search).get("invite"));
  const [group, setGroup] = useState<GroupDetail | null>(null);
  const [door, setDoor] = useState<GroupPreview | null>(null);
  const [error, setError] = useState<string | null>(null);

  function load() {
    fetchGroup(id, invite)
      .then((detail) => {
        setGroup(detail);
        setDoor(null);
        setError(null);
      })
      .catch((caught: Error) => {
        // Not signed in, but holding a link: show the group and the way in.
        if (caught.message === "Sign in first." && invite) {
          fetchGroupPreview(id, invite).then(setDoor, (refused: Error) => setError(refused.message));
        } else {
          setError(caught.message);
        }
      });
  }

  useEffect(load, [id, invite]);
  useEffect(() => onSocialChange(load), [id, invite]);

  if (door && !group) return <InviteDoor group={door} onSignedIn={load} />;
  if (error && !group) {
    return (
      <main className={styles.narrowPage}>
        <Brand home="social" />
        <p className={styles.empty}>{error === "Sign in first." ? "Sign in from the main menu to see groups." : error}</p>
        <a className={styles.quietLink} href="/social">
          Back to Social
        </a>
      </main>
    );
  }
  if (!group) return <BookLoader label="Gathering the group" />;

  const run = (action: () => Promise<unknown>, after: () => void = load) =>
    action().then(after, (caught) => alert(message(caught)));
  const owner = group.role === "owner";

  /** In: the link has done its job, so it comes off the address. */
  function joined() {
    history.replaceState(null, "", location.pathname);
    document.title = "Almanac"; // the link's page was titled "Join ... on Almanac"
    setInvite(null);
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

      <section className={styles.panel}>
        <div className={styles.groupHead}>
          <GroupIcon icon={group.icon} name={group.name} size={64} />
          <div className={styles.groupHeadText}>
            <h1 className={styles.heading}>{group.name}</h1>
            <span className={styles.groupLine}>
              <GroupPrestige value={group.prestige} />
              <span className={styles.rowMuted}>
                {group.member_count} of {group.max_members} members · run by {group.owner.name}
              </span>
            </span>
          </div>
        </div>
        {group.bio && <p className={styles.groupBio}>{group.bio}</p>}
        {group.name_hidden && (
          <p className={styles.notice}>Others see "Name under review" until a report is reviewed. Renaming the group replaces it.</p>
        )}
        {!owner && <ReportMenu group={group} onReported={load} />}
      </section>

      {group.role ? (
        <a className={`${styles.button} ${styles.primary} ${styles.buttonLink}`} href={`/host?group=${encodeURIComponent(group.public_id)}`}>
          Play now: host a members-only game
        </a>
      ) : group.invited ? (
        <section className={`${styles.panel} ${styles.inviteBanner}`}>
          <p>You're invited to {group.name}.</p>
          <div className={styles.actions}>
            <button
              type="button"
              className={`${styles.button} ${styles.primary}`}
              onClick={() => run(() => joinGroup(group.public_id, invite), joined)}
            >
              Join
            </button>
            {group.by_link ? (
              <a className={`${styles.button} ${styles.buttonLink}`} href="/social">
                Not now
              </a>
            ) : (
              <button type="button" className={styles.button} onClick={() => run(() => declineGroup(group.public_id))}>
                Decline
              </button>
            )}
          </div>
        </section>
      ) : null}
      {group.role && (
        <p className={styles.quietLink}>Open this on the screen everyone will watch. Every member gets the room code on their bell.</p>
      )}

      {group.role && group.invite_code && <InvitePanel group={group} onChange={load} />}

      <section className={styles.panel} aria-label="Leaderboard">
        <h2 className={styles.panelTitle}>Members</h2>
        <div className={styles.rows}>
          {group.members.map((member, index) => (
            <div key={member.public_id} className={`${styles.friendRank} ${member.you ? styles.scoreYou : ""}`}>
              <span className={styles.scoreRank}>{index + 1}</span>
              <Avatar avatar={member.avatar} size={28} label="" />
              <a className={styles.friendRankName} href={member.you ? "/profile" : `/u/${member.public_id}`}>
                <NameCard name={member.name} banner={member.avatar.banner} prestige={member.prestige} />
              </a>
              {member.role === "owner" ? (
                <span className={styles.relationTag}>owner</span>
              ) : owner ? (
                <button
                  type="button"
                  className={styles.smallButton}
                  onClick={() => {
                    if (confirm(`Remove ${member.name} from ${group.name}?`)) run(() => removeMember(group.public_id, member.public_id));
                  }}
                >
                  Remove
                </button>
              ) : (
                <span />
              )}
            </div>
          ))}
        </div>
      </section>

      {owner && <Customize group={group} onChange={load} />}
      {owner && <Manage group={group} onChange={load} />}
      {group.role === "member" && (
        <button
          type="button"
          className={styles.button}
          onClick={() => {
            if (confirm(`Leave ${group.name}?`)) run(() => leaveGroup(group.public_id), () => location.assign("/social"));
          }}
        >
          Leave group
        </button>
      )}
    </main>
  );
}
