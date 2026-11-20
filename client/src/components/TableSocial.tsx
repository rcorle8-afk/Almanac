import { useEffect, useRef, useState } from "react";
import { Avatar } from "../avatar/Avatar";
import type { Account } from "../lib/auth";
import { addFriend, friendLabel, type Relation } from "../lib/social";
import type { ClientMessage, Player, TableInvite } from "../lib/types";
import styles from "../styles.module.css";
import { DEFAULT_GROUP_ICON, GroupIcon } from "./GroupIcon";
import { PrestigeCount } from "./Leaderboard";
import { PlayerChip } from "./NameCard";
import { SignInPanel } from "./SignInPanel";

/**
 * The host's group invite, on a player's phone (the host-group invite; Ryan, Nov 17, 2026).
 * With `floating` it rises over the foot of the screen like a notification, whichever of the
 * phone's views is showing, clear of the timer and the view tabs; without, it sits in the page
 * (between rounds, where a card over the scores would be in the way). One invite shows at a
 * time. A guest signs in first, then the same card offers Join: the seat takes the account, so
 * the invite follows.
 */
export function InvitePrompt({
  invites,
  send,
  devName,
  onSignedIn,
  floating,
}: {
  invites: TableInvite[];
  send: (message: ClientMessage) => void;
  devName?: string;
  onSignedIn: (user: Account) => void;
  floating: boolean;
}) {
  const invite = invites[0];
  const group = invite?.group;
  const guest = invite?.sign_in_first;
  const [signingIn, setSigningIn] = useState(false);
  // The group a guest pressed "Sign in to join" for: joined as soon as the seat has the account.
  const joinAfter = useRef<string | null>(null);
  useEffect(() => {
    setSigningIn(false);
    // A short buzz as each invite arrives, on phones that can (not iPhones).
    if (group && "vibrate" in navigator) navigator.vibrate(150);
  }, [group]);
  useEffect(() => {
    if (group && guest === false && joinAfter.current === group) {
      joinAfter.current = null;
      send({ type: "answer_group_invite", group, accept: true });
    }
  }, [group, guest, send]);

  if (!invite) return null;
  const answer = (accept: boolean) => send({ type: "answer_group_invite", group: invite.group, accept });

  return (
    <section
      key={invite.group}
      className={`${styles.invitePop} ${floating ? styles.invitePopFloating : ""}`}
      role="region"
      aria-live="polite"
      aria-label="Group invite"
    >
      <div className={styles.invitePopHead}>
        <GroupIcon icon={invite.icon ?? DEFAULT_GROUP_ICON} name={invite.name} size={52} />
        <span className={styles.invitePopText}>
          <span className={styles.invitePopLabel}>{invite.host} invited you to join</span>
          <strong className={styles.invitePopName}>{invite.name}</strong>
          <span className={styles.groupLine}>
            <PrestigeCount value={invite.prestige} />
            <span className={styles.rowMuted}>
              {invite.member_count} {invite.member_count === 1 ? "member" : "members"}
            </span>
          </span>
        </span>
      </div>
      {invite.sign_in_first && signingIn ? (
        <SignInPanel
          title="Sign in to join"
          blurb="You keep your seat and your name in this room."
          devName={devName}
          onSignedIn={(user) => {
            joinAfter.current = invite.group;
            setSigningIn(false);
            onSignedIn(user);
          }}
        />
      ) : (
        invite.sign_in_first && (
          <p className={styles.invitePopNote}>Groups are for signed-in players. You keep your seat and your name.</p>
        )
      )}
      <div className={styles.actions}>
        {invite.sign_in_first ? (
          <button
            type="button"
            className={`${styles.button} ${styles.primary}`}
            disabled={signingIn}
            onClick={() => setSigningIn(true)}
          >
            Sign in to join
          </button>
        ) : (
          <button type="button" className={`${styles.button} ${styles.primary}`} onClick={() => answer(true)}>
            Join
          </button>
        )}
        <button type="button" className={styles.button} onClick={() => answer(false)}>
          Not now
        </button>
      </div>
      {invites.length > 1 && (
        <p className={styles.invitePopNote}>
          {invites.length - 1} more {invites.length === 2 ? "invite" : "invites"} after this one.
        </p>
      )}
    </section>
  );
}

/** The lobby's player chips. Tapping a signed-in player opens a small card with their profile
 *  and an Add friend button (M5: requests from the room you're in). */
export function LobbyChips({
  players,
  youId,
  signedIn,
  extra,
}: {
  players: Player[];
  youId: string;
  signedIn: boolean;
  extra: number;
}) {
  const [picked, setPicked] = useState<string | null>(null);
  const [relations, setRelations] = useState<Record<string, Relation>>({});
  const [busy, setBusy] = useState(false);
  const chosen = players.find((player) => player.id === picked && player.public_id);

  return (
    <>
      <div className={styles.lobbyPlayers} style={{ justifyContent: "flex-start", marginTop: 10 }}>
        {players.map((player) =>
          player.public_id && player.id !== youId ? (
            <button
              key={player.id}
              type="button"
              className={styles.chipButton}
              aria-pressed={picked === player.id}
              onClick={() => setPicked(picked === player.id ? null : player.id)}
            >
              <PlayerChip player={player} dim={!player.connected} />
            </button>
          ) : (
            <PlayerChip key={player.id} player={player} dim={!player.connected} />
          ),
        )}
        {extra > 0 && <span className={styles.chipOffline}>+{extra} more</span>}
      </div>
      {chosen && chosen.public_id && (
        <div className={styles.pickedPlayer}>
          <Avatar avatar={chosen.avatar} size={36} label="" />
          <span className={styles.personText}>
            <strong>{chosen.name}</strong>
            <a className={styles.personDetail} href={`/u/${chosen.public_id}`} target="_blank" rel="noreferrer">
              View profile
            </a>
          </span>
          {signedIn ? (
            (() => {
              const relation = relations[chosen.public_id];
              const { label, active } = friendLabel(relation);
              return active ? (
                <button
                  type="button"
                  className={styles.smallPrimary}
                  disabled={busy}
                  onClick={() => {
                    setBusy(true);
                    addFriend(chosen.public_id!)
                      .then((answer) => setRelations((current) => ({ ...current, [chosen.public_id!]: answer.relation })))
                      .catch((caught: Error) => alert(caught.message))
                      .finally(() => setBusy(false));
                  }}
                >
                  {label}
                </button>
              ) : (
                <span className={styles.relationTag}>{label}</span>
              );
            })()
          ) : (
            <span className={styles.personDetail}>Sign in to add friends</span>
          )}
        </div>
      )}
    </>
  );
}
