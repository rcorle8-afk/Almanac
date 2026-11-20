import { useEffect, useRef, useState, type CSSProperties, type FormEvent } from "react";
import { Avatar } from "../avatar/Avatar";
import { CreateGroup } from "../components/CreateGroup";
import { GroupIcon } from "../components/GroupIcon";
import { Chevron, Icon } from "../components/Icon";
import { LeaderboardCard, PrestigeCount } from "../components/Leaderboard";
import { NameCard } from "../components/NameCard";
import { PersonRow } from "../components/PersonRow";
import type { Account } from "../lib/auth";
import { useFitHeight, usePager } from "../lib/pager";
import {
  acceptFriend,
  addFriend,
  addFriendByCode,
  declineFriend,
  declineGroup,
  formatCode,
  friendLabel,
  joinGroup,
  newFriendCode,
  removeFriend,
  searchHandles,
  type Card,
  type Overview,
  type Relation,
} from "../lib/social";
import styles from "../styles.module.css";

const SEARCH_DELAY_MS = 300;
/** The Social screen's two tabs, in swipe order. Groups is where it opens. */
export const SOCIAL_TABS = ["groups", "friends"] as const;

function message(caught: unknown) {
  return caught instanceof Error ? caught.message : "That didn't work.";
}

/** A group's prestige: the four-point star and its members' prestige added up. Shown even at
 *  zero, so a group's standing is always in the same place. */
export function GroupPrestige({ value }: { value: number }) {
  return <PrestigeCount value={value} />;
}

/* ---------- You ---------- */

/** The top of the Social screen (Ryan's sketch, Nov 11, 2026): your avatar and name card, then
 *  the way to your profile, your level and your handle. Everything about you (the bio, the
 *  handle, your public page, notifications, signing out) is on the profile page it leads to. */
function ProfileCard({ account }: { account: Account }) {
  return (
    <section className={`${styles.panel} ${styles.socialMe}`} aria-label="You">
      <a className={styles.socialMeAvatar} href="/profile" aria-label="Your profile">
        <Avatar avatar={account.avatar} size={64} label="" />
      </a>
      <div className={styles.socialMeText}>
        <NameCard name={account.name} banner={account.avatar.banner} prestige={account.prestige} />
        <div className={styles.socialMeLine}>
          <a className={styles.smallButton} href="/profile">
            Profile
          </a>
          <span className={styles.rowMuted}>
            Level {account.level}
            {account.handle ? ` · @${account.handle}` : ""}
          </span>
        </div>
        {/* The team's pages: the players table and the overview for admins and the teammates
            they've added, and the two review queues for admins alone. */}
        {(account.admin || account.team) && (
          <div className={styles.socialMeLine}>
            <span className={styles.rowMuted}>Team</span>
            <a className={styles.inlineLink} href="/admin/overview">
              Overview
            </a>
            <a className={styles.inlineLink} href="/admin/players">
              Players
            </a>
            {account.admin && (
              <a className={styles.inlineLink} href="/admin/reports">
                Reports
              </a>
            )}
            {account.admin && (
              <a className={styles.inlineLink} href="/admin/flags">
                Accuracy flags
              </a>
            )}
          </div>
        )}
      </div>
    </section>
  );
}

/* ---------- Groups ---------- */

/** Your groups, each behind its shield with its combined prestige; invites waiting on you; and
 *  the way to start one. */
function GroupsTab({ overview, onChange }: { overview: Overview; onChange: () => void }) {
  const [creating, setCreating] = useState(false);
  const run = (action: () => Promise<unknown>) => action().then(onChange, (caught) => alert(message(caught)));
  const full = overview.groups_left === 0;

  return (
    <>
      {overview.group_invites.length > 0 && (
        <section className={`${styles.panel} ${styles.inviteBanner}`} aria-label="Group invites">
          <h2 className={styles.panelTitle}>Invites</h2>
          <div className={styles.rows}>
            {overview.group_invites.map((invite) => (
              <div key={invite.public_id} className={styles.groupRow}>
                <a href={`/g/${invite.public_id}`} className={styles.groupRowMain}>
                  <GroupIcon icon={invite.icon} name={invite.name} size={44} />
                  <span className={styles.personText}>
                    <strong>{invite.name}</strong>
                    <span className={styles.personDetail}>
                      {invite.invited_by ? `${invite.invited_by.name} invited you` : "You're invited"}
                    </span>
                  </span>
                </a>
                <span className={styles.personActions}>
                  <button type="button" className={styles.smallPrimary} onClick={() => run(() => joinGroup(invite.public_id))}>
                    Join
                  </button>
                  <button type="button" className={styles.smallButton} onClick={() => run(() => declineGroup(invite.public_id))}>
                    Decline
                  </button>
                </span>
              </div>
            ))}
          </div>
        </section>
      )}

      {overview.groups.length === 0 ? (
        <p className={styles.empty}>
          You're not in a group yet. Start one for your club or your regulars, or open an invite link someone sends you.
        </p>
      ) : (
        <nav className={styles.menuRows} aria-label="Your groups">
          {overview.groups.map((group) => (
            <a key={group.public_id} className={styles.menuRow} href={`/g/${group.public_id}`}>
              <GroupIcon icon={group.icon} name={group.name} size={52} />
              <span className={styles.menuRowText}>
                <span className={styles.menuRowTitle}>{group.name}</span>
                <span className={styles.groupLine}>
                  <GroupPrestige value={group.prestige} />
                  <span className={styles.menuRowDetail}>
                    {group.member_count} {group.member_count === 1 ? "member" : "members"}
                    {group.role === "owner" ? " · yours" : ""}
                  </span>
                </span>
              </span>
              <Chevron />
            </a>
          ))}
        </nav>
      )}

      <button type="button" className={styles.createGroup} disabled={full} onClick={() => setCreating(true)}>
        <span className={styles.createGroupPlus}>
          <Icon name="plus" />
        </span>
        <span className={styles.menuRowText}>
          <span className={styles.menuRowTitle}>Start a group</span>
          <span className={styles.menuRowDetail}>
            {full ? "You own as many groups as one account can" : `${overview.group_cost.toLocaleString()} coins · name, bio and shield`}
          </span>
        </span>
      </button>
      {creating && <CreateGroup coins={overview.coins} cost={overview.group_cost} onClose={() => setCreating(false)} />}
    </>
  );
}

/* ---------- Friends ---------- */

/** The button beside someone who isn't your friend yet: Add friend, Accept, or a quiet label. */
function FriendButton({ card, relation, onChange }: { card: Card; relation: Relation; onChange: (r: Relation) => void }) {
  const [busy, setBusy] = useState(false);
  const { label, active } = friendLabel(relation);
  async function act() {
    setBusy(true);
    try {
      const answer = relation === "incoming" ? await acceptFriend(card.public_id) : await addFriend(card.public_id);
      onChange(answer.relation);
    } catch (caught) {
      alert(message(caught));
    } finally {
      setBusy(false);
    }
  }
  return active ? (
    <button type="button" className={styles.smallPrimary} disabled={busy} onClick={act}>
      {label}
    </button>
  ) : (
    <span className={styles.relationTag}>{label}</span>
  );
}

function Requests({ overview, onChange }: { overview: Overview; onChange: () => void }) {
  if (overview.incoming.length === 0 && overview.outgoing.length === 0) return null;
  const run = (action: () => Promise<unknown>) => action().then(onChange, (caught) => alert(message(caught)));
  return (
    <section className={styles.panel} aria-label="Requests">
      <h2 className={styles.panelTitle}>Requests</h2>
      <div className={styles.rows}>
        {overview.incoming.map((card) => (
          <PersonRow key={card.public_id} card={card} detail="wants to be friends">
            <button type="button" className={styles.smallPrimary} onClick={() => run(() => acceptFriend(card.public_id))}>
              Accept
            </button>
            <button type="button" className={styles.smallButton} onClick={() => run(() => declineFriend(card.public_id))}>
              Decline
            </button>
          </PersonRow>
        ))}
        {overview.outgoing.map((card) => (
          <PersonRow key={card.public_id} card={card} detail="request sent">
            <button type="button" className={styles.smallButton} onClick={() => run(() => removeFriend(card.public_id))}>
              Cancel
            </button>
          </PersonRow>
        ))}
      </div>
    </section>
  );
}

/** Your friends and you, ranked by prestige: the friends-only leaderboard. */
function FriendsBoard({ overview }: { overview: Overview }) {
  const board = [...overview.friends.map((card) => ({ card, you: false })), { card: overview.me as Card, you: true }].sort(
    (a, b) => b.card.prestige - a.card.prestige || a.card.name.localeCompare(b.card.name),
  );
  return (
    <section className={styles.panel} aria-label="Friends">
      <div className={styles.roadHead}>
        <h2 className={styles.panelTitle}>Friends</h2>
        <span className={styles.rowMuted}>{overview.friends.length}</span>
      </div>
      {overview.friends.length === 0 ? (
        <p className={styles.empty}>No friends yet. Add people you've played with, or share your friend code.</p>
      ) : (
        <div className={styles.rows}>
          {board.map(({ card, you }, index) => (
            <a key={card.public_id} href={you ? "/profile" : `/u/${card.public_id}`} className={`${styles.friendRank} ${you ? styles.scoreYou : ""}`}>
              <span className={styles.scoreRank}>{index + 1}</span>
              <Avatar avatar={card.avatar} size={28} label="" />
              <span className={styles.friendRankName}>
                <NameCard name={you ? `${card.name} (you)` : card.name} banner={card.avatar.banner} prestige={card.prestige} />
              </span>
            </a>
          ))}
        </div>
      )}
    </section>
  );
}

/** Your own friend code, to hand to someone. */
function MyCode({ start }: { start: string }) {
  const [code, setCode] = useState(start);
  const [copied, setCopied] = useState(false);
  return (
    <div className={styles.codeRow}>
      <span className={styles.personText}>
        <span className={styles.rowMuted}>Your code</span>
        <strong className={styles.friendCode}>{formatCode(code)}</strong>
      </span>
      <span className={styles.personActions}>
        <button
          type="button"
          className={styles.smallButton}
          onClick={() =>
            navigator.clipboard?.writeText(formatCode(code)).then(() => {
              setCopied(true);
              window.setTimeout(() => setCopied(false), 1500);
            })
          }
        >
          {copied ? "Copied" : "Copy"}
        </button>
        <button
          type="button"
          className={styles.smallButton}
          onClick={() => {
            if (confirm("Make a new friend code? The old one stops working.")) newFriendCode().then(setCode);
          }}
        >
          New code
        </button>
      </span>
    </div>
  );
}

/** Three ways to add someone: search by handle, a friend code, or people you've played with. */
function AddFriends({ overview, onChange }: { overview: Overview; onChange: () => void }) {
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<(Card & { relation: Relation })[] | null>(null);
  const [code, setCode] = useState("");
  const [codeNote, setCodeNote] = useState<string | null>(null);
  const [mates, setMates] = useState(overview.tablemates);
  const timer = useRef<number>();

  useEffect(() => setMates(overview.tablemates), [overview]);

  useEffect(() => {
    window.clearTimeout(timer.current);
    const text = query.trim();
    if (text.replace(/^@/, "").length < 2) {
      setResults(null);
      return;
    }
    timer.current = window.setTimeout(() => {
      searchHandles(text)
        .then(setResults)
        .catch(() => setResults([]));
    }, SEARCH_DELAY_MS);
    return () => window.clearTimeout(timer.current);
  }, [query]);

  async function addByCode(event: FormEvent) {
    event.preventDefault();
    setCodeNote(null);
    try {
      const answer = await addFriendByCode(code);
      setCodeNote(answer.relation === "friend" ? "You're friends now." : "Request sent.");
      setCode("");
      onChange();
    } catch (caught) {
      setCodeNote(message(caught));
    }
  }

  return (
    <section className={styles.panel} aria-label="Add friends">
      <h2 className={styles.panelTitle}>Add friends</h2>
      <label className={styles.field}>
        Search by handle
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
      {results !== null && (
        <div className={styles.rows}>
          {results.length === 0 ? (
            <p className={styles.empty}>No handle starts with that.</p>
          ) : (
            results.map((card) => (
              <PersonRow key={card.public_id} card={card}>
                <FriendButton
                  card={card}
                  relation={card.relation}
                  onChange={(relation) => {
                    setResults((rows) => rows?.map((row) => (row.public_id === card.public_id ? { ...row, relation } : row)) ?? null);
                    onChange();
                  }}
                />
              </PersonRow>
            ))
          )}
        </div>
      )}

      <form className={styles.inlineForm} onSubmit={addByCode}>
        <label className={styles.field}>
          Friend code
          <input
            className={`${styles.input} ${styles.friendCodeInput}`}
            value={code}
            maxLength={12}
            autoCapitalize="characters"
            autoComplete="off"
            placeholder="ABCD-2345"
            onChange={(event) => setCode(event.target.value)}
          />
        </label>
        <button type="submit" className={styles.smallButton} disabled={code.trim().length < 8}>
          Add
        </button>
      </form>
      {codeNote && <p className={styles.notice}>{codeNote}</p>}
      <MyCode start={overview.me.friend_code} />

      <h3 className={styles.subTitle}>Played with you</h3>
      {mates.length === 0 ? (
        <p className={styles.empty}>Signed-in players from your games show up here.</p>
      ) : (
        <div className={styles.rows}>
          {mates.map((card) => (
            <PersonRow key={card.public_id} card={card} detail={`played ${new Date(card.last_played).toLocaleDateString(undefined, { month: "short", day: "numeric" })}`}>
              <FriendButton
                card={card}
                relation={card.relation}
                onChange={(relation) => {
                  setMates((rows) => rows.map((row) => (row.public_id === card.public_id ? { ...row, relation } : row)));
                  onChange();
                }}
              />
            </PersonRow>
          ))}
        </div>
      )}
    </section>
  );
}

/* ---------- The screen ---------- */

interface SocialScreenProps {
  account: Account;
  /** Friends, groups and what's waiting; null while it loads. */
  overview: Overview | null;
  onChange: () => void;
  /** The tab to open on (an index into SOCIAL_TABS), and where to report the one in view. */
  startTab: number;
  onTab: (index: number) => void;
}

/**
 * The Social screen of the main menu (Ryan's sketch, Nov 11, 2026; it replaced the separate
 * /social page). From the top: the global leaderboard (added Nov 12), you, then Groups and
 * Friends as two tabs that slide like the menu's own screens. The screen scrolls as one; the
 * tabs stay at the top of it once you scroll past them, and the tab in view has its icon lit.
 */
export function SocialScreen({ account, overview, onChange, startTab, onTab }: SocialScreenProps) {
  const { track, bar, active, go } = usePager(SOCIAL_TABS.length, startTab);
  useFitHeight(track, active);
  const invites = overview?.group_invites.length ?? 0;
  const requests = overview?.incoming.length ?? 0;

  useEffect(() => onTab(active), [active, onTab]);

  const tabs = [
    { label: "Groups", icon: "groups" as const, waiting: invites },
    { label: "Friends", icon: "social" as const, waiting: requests },
  ];

  return (
    <>
      <div className={styles.socialHead}>
        <LeaderboardCard />
        <ProfileCard account={account} />
      </div>
      <div className={styles.stickyTabs}>
        <nav className={`${styles.menuTabs} ${styles.subTabs}`} aria-label="Groups and friends" ref={bar} style={{ "--tabs": tabs.length } as CSSProperties}>
          <span className={styles.menuTabMarker} aria-hidden="true" />
          {tabs.map((tab, index) => (
            <button
              key={tab.label}
              type="button"
              className={`${styles.menuTab} ${styles.subTab} ${active === index ? styles.menuTabOn : ""}`}
              aria-current={active === index ? "true" : undefined}
              aria-label={tab.waiting > 0 ? `${tab.label}, ${tab.waiting} waiting` : undefined}
              onClick={() => go(index)}
            >
              <span className={styles.menuTabIcon}>
                <Icon name={tab.icon} />
                {tab.waiting > 0 && <span className={styles.menuDot} />}
              </span>
              {tab.label}
            </button>
          ))}
        </nav>
      </div>

      <div className={styles.subTrack} ref={track}>
        <section className={styles.subScreen} aria-label="Groups">
          <div className={styles.menuColumn}>
            {overview ? <GroupsTab overview={overview} onChange={onChange} /> : <p className={styles.empty}>Gathering your groups…</p>}
          </div>
        </section>
        <section className={styles.subScreen} aria-label="Friends">
          <div className={styles.menuColumn}>
            {overview ? (
              <>
                <Requests overview={overview} onChange={onChange} />
                <FriendsBoard overview={overview} />
                <AddFriends overview={overview} onChange={onChange} />
              </>
            ) : (
              <p className={styles.empty}>Finding your people…</p>
            )}
          </div>
        </section>
      </div>
    </>
  );
}
