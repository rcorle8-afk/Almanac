import { useEffect, useRef, useState } from "react";
import { fetchMe, type Account } from "../lib/auth";
import { fetchMyGroups, type GroupSummary } from "../lib/social";
import type { ClientMessage, GameState } from "../lib/types";
import styles from "../styles.module.css";
import { GroupIcon } from "./GroupIcon";
import { Icon } from "./Icon";
import { SignInPanel } from "./SignInPanel";

// The group this screen last invited a table to. It is listed first the next time the menu
// opens: in the next lobby, after the game, and the next time they host.
const CHOICE_KEY = "almanac:host:group";

function readChoice() {
  try {
    return localStorage.getItem(CHOICE_KEY) ?? "";
  } catch {
    return "";
  }
}

function keepChoice(group: string) {
  try {
    localStorage.setItem(CHOICE_KEY, group);
  } catch {
    // private browsing: the choice lasts for this screen only
  }
}

/** Signing in on the host screen itself, in a dialog over the lobby. */
function HostSignIn({ onSignedIn, onClose }: { onSignedIn: (user: Account) => void; onClose: () => void }) {
  const dialog = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    const el = dialog.current;
    if (el && !el.open) el.showModal();
  }, []);
  return (
    <dialog
      ref={dialog}
      className={styles.dialog}
      aria-label="Sign in on the host screen"
      onClose={onClose}
      onClick={(event) => event.target === dialog.current && dialog.current?.close()}
    >
      <div className={`${styles.dialogBody} ${styles.hostSignIn}`}>
        <div className={styles.roadHead}>
          <h2 className={styles.heading}>Host as yourself</h2>
          <button type="button" className={styles.linkButton} onClick={() => dialog.current?.close()}>
            Close
          </button>
        </div>
        <SignInPanel
          title="Sign in on this screen"
          blurb="This screen then hosts under your account, and you can still join and play from your phone with the same one."
          devName="Host"
          onSignedIn={(user) => {
            dialog.current?.close();
            onSignedIn(user);
          }}
        />
      </div>
    </dialog>
  );
}

interface HostInviteProps {
  state: GameState;
  send: (message: ClientMessage) => void;
  /** The host screen just signed in: its socket reconnects so the server sees the account. */
  onSignedIn: () => void;
  /** In the settings drawer: the menu opens in the page, where the drawer won't clip it, and how
   *  the last invite went shows beside it. */
  compact?: boolean;
  notice?: string | null;
}

/**
 * The host-group invite (Ryan, Nov 17, 2026). A signed-in host screen is an entity of its own:
 * the account's name, avatar and groups, hosting without taking a seat, so the same account can
 * still join and play from a phone. From here the host offers any group they're in to everyone
 * at the table: each phone gets a pop-up to join, signed-in players also hear on their bell and
 * by push, and guests can accept once they sign in.
 *
 * On the screen it is one small round button, in the lobby and again on the final scores. The
 * host's groups stay out of sight until it's pressed (Ryan, Nov 17, 2026: a room shouldn't have
 * them up the whole time); then they drop down as a short menu, and picking one sends the invite.
 */
export function HostInvite({ state, send, onSignedIn, compact = false, notice }: HostInviteProps) {
  const host = state.host;
  const hostId = host?.public_id ?? null;
  const [groups, setGroups] = useState<GroupSummary[] | null>(null);
  const [open, setOpen] = useState(false);
  const [signingIn, setSigningIn] = useState(false);
  const box = useRef<HTMLDivElement>(null);
  // Read again whenever someone joins through an invite, so the member counts keep up.
  const joined = state.invites.reduce((sum, invite) => sum + invite.joined, 0);

  useEffect(() => {
    if (!hostId) {
      setGroups(null);
      return;
    }
    let stale = false;
    fetchMyGroups()
      .then((mine) => !stale && setGroups(mine))
      .catch(() => !stale && setGroups((current) => current ?? []));
    return () => {
      stale = true;
    };
  }, [hostId, joined]);

  // The menu closes on Escape, or on a press anywhere outside it.
  useEffect(() => {
    if (!open) return;
    const away = (event: PointerEvent) => {
      if (!box.current?.contains(event.target as Node)) setOpen(false);
    };
    const key = (event: KeyboardEvent) => {
      if (event.key === "Escape") setOpen(false);
    };
    document.addEventListener("pointerdown", away);
    document.addEventListener("keydown", key);
    return () => {
      document.removeEventListener("pointerdown", away);
      document.removeEventListener("keydown", key);
    };
  }, [open]);

  // This browser may be signed in already (from the main menu, after this room opened); then the
  // socket only needs to reconnect. Otherwise, the sign-in box.
  function signIn() {
    setOpen(false);
    fetchMe()
      .then((user) => (user ? onSignedIn() : setSigningIn(true)))
      .catch(() => setSigningIn(true));
  }

  const humans = state.players.filter((player) => !player.bot).length;
  const last = readChoice();
  const listed = groups && [...groups].sort((a, b) => Number(b.public_id === last) - Number(a.public_id === last));
  const purpose = host ? "Invite everyone here to a group" : "Sign in to invite everyone here to a group";

  return (
    <div className={`${styles.hostInvite} ${compact ? styles.hostInviteCompact : ""}`} ref={box}>
      <button
        type="button"
        className={styles.hostInviteToggle}
        aria-label={purpose}
        title={purpose}
        aria-expanded={open}
        onClick={() => setOpen(!open)}
      >
        <Icon name="groups" />
      </button>
      {state.invites.map((invite) => (
        <span key={invite.group} className={styles.hostInviteTally} role="status">
          <strong>
            {invite.joined} of {invite.invited}
          </strong>{" "}
          joined {invite.name}
        </span>
      ))}
      {compact && notice && <span className={styles.hostInviteTally}>{notice}</span>}

      {open && (
        <div className={styles.hostInviteMenu} role="group" aria-label={purpose}>
          {!host ? (
            <>
              <p className={styles.hostInviteNote}>
                Sign in on this screen to host as yourself and invite everyone here to one of your groups. You can
                still join and play from your phone with the same account.
              </p>
              <button type="button" className={styles.smallPrimary} onClick={signIn}>
                Sign in on this screen
              </button>
            </>
          ) : !listed ? (
            <p className={styles.hostInviteNote}>Finding your groups…</p>
          ) : listed.length === 0 ? (
            <p className={styles.hostInviteNote}>
              You're not in a group yet. Start or join one from the{" "}
              <a className={styles.inlineLink} href="/#social" target="_blank" rel="noreferrer">
                Social screen
              </a>
              , then invite the table from here.
            </p>
          ) : (
            <>
              <p className={styles.hostInviteLead}>
                {humans === 0 ? "Nobody to invite yet" : "Invite everyone here to"}
              </p>
              {listed.map((group) => (
                <button
                  key={group.public_id}
                  type="button"
                  className={styles.hostGroupChoice}
                  disabled={humans === 0}
                  onClick={() => {
                    keepChoice(group.public_id);
                    send({ type: "host_group_invite", group: group.public_id });
                    setOpen(false);
                  }}
                >
                  <GroupIcon icon={group.icon} name={group.name} size={30} />
                  <span className={styles.hostGroupText}>
                    <strong>{group.name}</strong>
                    <span>
                      {group.member_count} {group.member_count === 1 ? "member" : "members"}
                    </span>
                  </span>
                </button>
              ))}
              <p className={styles.hostInviteNote}>
                Every phone gets a pop-up to join; guests sign in first. Anyone already in the group is skipped.
              </p>
            </>
          )}
        </div>
      )}

      {signingIn && (
        <HostSignIn
          onClose={() => setSigningIn(false)}
          onSignedIn={() => {
            setSigningIn(false);
            onSignedIn();
          }}
        />
      )}
    </div>
  );
}
