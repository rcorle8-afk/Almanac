import { useEffect, useState, type FormEvent } from "react";
import { disablePush, enablePush, pushState, type PushState } from "../lib/push";
import { saveHandle } from "../lib/social";
import styles from "../styles.module.css";

function message(caught: unknown) {
  return caught instanceof Error ? caught.message : "That didn't work.";
}

/** The handle people can search for. On the profile page since Nov 11, 2026 (the Social page
 *  before): it is part of who you are, like the bio beside it. */
export function HandlePanel({ handle, onSaved }: { handle: string | null; onSaved: (handle: string | null) => void }) {
  const [draft, setDraft] = useState(handle ?? "");
  const [problem, setProblem] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);

  async function submit(event: FormEvent) {
    event.preventDefault();
    setProblem(null);
    try {
      const stored = await saveHandle(draft);
      setDraft(stored ?? "");
      setSaved(true);
      onSaved(stored);
    } catch (caught) {
      setProblem(message(caught));
    }
  }

  return (
    <section className={styles.panel} aria-label="Handle">
      <h2 className={styles.panelTitle}>Handle</h2>
      <form className={styles.inlineForm} style={{ marginTop: 0 }} onSubmit={submit}>
        <label className={styles.field}>
          So friends can find you by search
          <span className={styles.handleField}>
            <span className={styles.handleAt}>@</span>
            <input
              className={styles.input}
              value={draft}
              maxLength={20}
              autoCapitalize="none"
              autoComplete="off"
              placeholder="pick_one"
              onChange={(event) => {
                setDraft(event.target.value);
                setSaved(false);
              }}
            />
          </span>
        </label>
        <button type="submit" className={styles.smallButton}>
          {saved ? "Saved" : "Save"}
        </button>
      </form>
      {problem && <p className={styles.error}>{problem}</p>}
    </section>
  );
}

const PUSH_TEXT: Record<PushState, string> = {
  install:
    "On iPhone, add Almanac to your Home Screen first: tap Share, then Add to Home Screen, and open it from there.",
  unsupported: "This browser can't show notifications. Try Chrome, Edge or Firefox, or Safari from the Home Screen.",
  unavailable: "",
  denied: "Notifications are blocked for Almanac. Allow them in this browser's site settings, then come back.",
  off: "Friend requests, group invites and game invites, even when Almanac is closed.",
  on: "On for this device. Friend requests, group invites and game invites come here.",
};

/** Phone notifications (M5 web push): turns them on or off for this device, or says what's in
 *  the way. Hidden when the server has push switched off. */
export function PushPanel() {
  const [state, setState] = useState<PushState | null>(null);
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);

  useEffect(() => {
    pushState().then(setState);
  }, []);

  if (state === null || state === "unavailable") return null;

  async function toggle() {
    setBusy(true);
    setProblem(null);
    try {
      if (state === "on") await disablePush();
      else await enablePush();
    } catch (caught) {
      setProblem(message(caught));
    } finally {
      setState(await pushState());
      setBusy(false);
    }
  }

  return (
    <section className={styles.panel} aria-label="Notifications on this device">
      <div className={styles.roadHead}>
        <h2 className={styles.panelTitle}>Notifications on this device</h2>
        {(state === "off" || state === "on") && (
          <button type="button" className={state === "on" ? styles.smallButton : styles.smallPrimary} disabled={busy} onClick={toggle}>
            {state === "on" ? "Turn off" : "Turn on"}
          </button>
        )}
      </div>
      <p className={styles.settingsHint}>{PUSH_TEXT[state]}</p>
      {problem && (
        <p className={styles.error} role="alert">
          {problem}
        </p>
      )}
    </section>
  );
}
