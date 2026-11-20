import { useCallback, useEffect, useRef, useState, type ReactNode } from "react";
import {
  acceptFriend,
  declineFriend,
  declineGroup,
  fetchNotifications,
  joinGroup,
  markNotificationsRead,
  SOCIAL_CHANGED,
  type Notification,
} from "../lib/social";
import styles from "../styles.module.css";

const POLL_MS = 30_000;

function ago(iso: string) {
  const minutes = Math.max(0, Math.round((Date.now() - new Date(iso).getTime()) / 60_000));
  if (minutes < 1) return "now";
  if (minutes < 60) return `${minutes}m`;
  const hours = Math.round(minutes / 60);
  return hours < 24 ? `${hours}h` : `${Math.round(hours / 24)}d`;
}

function BellIcon() {
  return (
    <svg viewBox="0 0 24 24" width="20" height="20" aria-hidden="true">
      <path
        d="M12 3a5 5 0 0 0-5 5v3.2c0 .9-.3 1.8-.9 2.5L5 15h14l-1.1-1.3a3.9 3.9 0 0 1-.9-2.5V8a5 5 0 0 0-5-5Z"
        fill="none"
        stroke="currentColor"
        strokeWidth="1.6"
        strokeLinejoin="round"
      />
      <path d="M10 18a2 2 0 0 0 4 0" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" />
    </svg>
  );
}

/** One line of the bell: what happened, and where it leads or what can be done about it. */
function Item({ item, onDone }: { item: Notification; onDone: (id: number, text: string) => void }) {
  const who = item.actor?.name ?? "Someone";
  const group = item.group?.name ?? "a group";
  const [busy, setBusy] = useState(false);

  async function act(run: () => Promise<unknown>, text: string) {
    setBusy(true);
    try {
      await run();
      onDone(item.id, text);
    } catch (caught) {
      onDone(item.id, caught instanceof Error ? caught.message : "That didn't work.");
    } finally {
      setBusy(false);
    }
  }

  let text: ReactNode;
  let actions: ReactNode = null;
  switch (item.kind) {
    case "friend_request":
      text = <><strong>{who}</strong> wants to be friends.</>;
      if (item.actor && item.open) {
        const id = item.actor.public_id;
        actions = (
          <>
            <button type="button" className={styles.smallPrimary} disabled={busy} onClick={() => act(() => acceptFriend(id), `You and ${who} are friends.`)}>
              Accept
            </button>
            <button type="button" className={styles.smallButton} disabled={busy} onClick={() => act(() => declineFriend(id), "Declined.")}>
              Decline
            </button>
          </>
        );
      }
      break;
    case "friend_accepted":
      text = <><strong>{who}</strong> accepted your friend request.</>;
      break;
    case "group_invite":
      text = <><strong>{who}</strong> invited you to <strong>{group}</strong>.</>;
      if (item.group && item.open) {
        const id = item.group.public_id;
        actions = (
          <>
            <button type="button" className={styles.smallPrimary} disabled={busy} onClick={() => act(() => joinGroup(id), `You joined ${group}.`)}>
              Join
            </button>
            <button type="button" className={styles.smallButton} disabled={busy} onClick={() => act(() => declineGroup(id), "Declined.")}>
              Decline
            </button>
          </>
        );
      }
      break;
    case "group_joined":
      text = <><strong>{who}</strong> joined <strong>{group}</strong>.</>;
      break;
    case "room_invite":
      text = <><strong>{who}</strong> opened a game for <strong>{group}</strong>.</>;
      if (item.room_code) {
        actions = (
          <a className={styles.smallPrimary} href={`/?room=${encodeURIComponent(item.room_code)}`}>
            Join {item.room_code}
          </a>
        );
      }
      break;
  }
  const link =
    item.kind === "friend_accepted" && item.actor
      ? `/u/${item.actor.public_id}`
      : item.kind === "group_joined" && item.group
        ? `/g/${item.group.public_id}`
        : null;

  return (
    <li className={item.read ? styles.bellItem : `${styles.bellItem} ${styles.bellUnread}`}>
      <span className={styles.bellText}>
        {link ? <a href={link}>{text}</a> : text}
        <span className={styles.rowMuted}> · {ago(item.at)}</span>
      </span>
      {actions && <span className={styles.bellActions}>{actions}</span>}
    </li>
  );
}

/** The notification bell (M5): an unread count, refreshed every 30 seconds while the page is
 *  open, and a list where requests and invites can be answered on the spot. Renders nothing
 *  for a guest. Opening it marks everything read. */
export function Bell() {
  const [items, setItems] = useState<Notification[] | null>(null);
  const [unread, setUnread] = useState(0);
  const [open, setOpen] = useState(false);
  const [done, setDone] = useState<Record<number, string>>({});
  const box = useRef<HTMLDivElement>(null);

  const refresh = useCallback(() => {
    fetchNotifications()
      .then((answer) => {
        setItems(answer.items);
        setUnread(answer.unread);
      })
      .catch(() => setItems((current) => current)); // signed out or offline: keep what's shown
  }, []);

  useEffect(() => {
    refresh();
    const timer = window.setInterval(() => {
      if (document.visibilityState === "visible") refresh();
    }, POLL_MS);
    const onShow = () => document.visibilityState === "visible" && refresh();
    document.addEventListener("visibilitychange", onShow);
    return () => {
      window.clearInterval(timer);
      document.removeEventListener("visibilitychange", onShow);
    };
  }, [refresh]);

  useEffect(() => {
    if (!open) return;
    const away = (event: PointerEvent) => {
      if (!box.current?.contains(event.target as Node)) setOpen(false);
    };
    document.addEventListener("pointerdown", away);
    return () => document.removeEventListener("pointerdown", away);
  }, [open]);

  if (items === null) return null; // a guest, or not loaded yet

  function toggle() {
    const opening = !open;
    setOpen(opening);
    if (opening && unread > 0) {
      setUnread(0);
      markNotificationsRead().catch(() => undefined);
    }
  }

  return (
    <div className={styles.bell} ref={box}>
      <button
        type="button"
        className={styles.bellButton}
        aria-label={unread ? `Notifications, ${unread} new` : "Notifications"}
        aria-expanded={open}
        onClick={toggle}
      >
        <BellIcon />
        {unread > 0 && <span className={styles.bellCount}>{unread > 9 ? "9+" : unread}</span>}
      </button>
      {open && (
        <div className={styles.bellPanel} role="dialog" aria-label="Notifications">
          {items.length === 0 ? (
            <p className={styles.empty}>Nothing yet. Friend requests and group invites land here.</p>
          ) : (
            <ul className={styles.bellList}>
              {items.map((item) =>
                done[item.id] ? (
                  <li key={item.id} className={styles.bellItem}>
                    <span className={styles.bellText}>{done[item.id]}</span>
                  </li>
                ) : (
                  <Item
                    key={item.id}
                    item={item}
                    onDone={(id, text) => {
                      setDone((current) => ({ ...current, [id]: text }));
                      refresh();
                      window.dispatchEvent(new Event(SOCIAL_CHANGED));
                    }}
                  />
                ),
              )}
            </ul>
          )}
          <a className={styles.bellFoot} href="/social">
            Open Social
          </a>
        </div>
      )}
    </div>
  );
}
