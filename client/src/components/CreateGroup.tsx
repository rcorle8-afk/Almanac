import { useEffect, useRef, useState, type ChangeEvent, type FormEvent } from "react";
import { squarePicture } from "../lib/picture";
import { createGroup, uploadGroupImage } from "../lib/social";
import styles from "../styles.module.css";
import { GroupIcon, GroupIconPicker } from "./GroupIcon";

const BIO_LIMIT = 160;
const NAME_MIN = 3;
const NAME_LIMIT = 32;

function message(caught: unknown) {
  return caught instanceof Error ? caught.message : "That didn't work.";
}

interface CreateGroupProps {
  coins: number;
  cost: number;
  onClose: () => void;
}

/**
 * Starting a group, all in one place (Ryan, Nov 11, 2026): the name, the bio, the shield's
 * drawing and colour or a picture, and the price, with a live preview of the shield at the top.
 * Nothing is spent until Create; everything chosen here can be changed later on the group's page.
 */
export function CreateGroup({ coins, cost, onClose }: CreateGroupProps) {
  const dialog = useRef<HTMLDialogElement>(null);
  const picker = useRef<HTMLInputElement>(null);
  const [name, setName] = useState("");
  const [bio, setBio] = useState("");
  const [glyph, setGlyph] = useState("letters");
  const [color, setColor] = useState("blue");
  const [picture, setPicture] = useState<{ blob: Blob; url: string } | null>(null);
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);
  const short = cost - coins;
  const ready = name.trim().length >= NAME_MIN && short <= 0;

  // A real dialog: the page behind can't be reached, and Escape closes it.
  useEffect(() => {
    const el = dialog.current;
    if (el && !el.open) el.showModal();
  }, []);

  // The chosen picture's preview is a temporary address; give it back when it changes or we close.
  useEffect(() => {
    const url = picture?.url;
    return () => {
      if (url) URL.revokeObjectURL(url);
    };
  }, [picture]);

  async function picked(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    event.target.value = "";
    if (!file) return;
    setProblem(null);
    try {
      const blob = await squarePicture(file);
      setPicture({ blob, url: URL.createObjectURL(blob) });
    } catch (caught) {
      setProblem(message(caught));
    }
  }

  async function create(event: FormEvent) {
    event.preventDefault();
    if (!ready || busy) return;
    setBusy(true);
    setProblem(null);
    try {
      const group = await createGroup({ name, bio, glyph, color });
      if (picture) {
        // The group exists and is paid for by now, so a picture that won't upload is only
        // mentioned: it can be added on the group's page.
        await uploadGroupImage(group.public_id, picture.blob).catch((caught) =>
          alert(`${group.name} is started, but the picture didn't upload: ${message(caught)} You can add it on the group's page.`),
        );
      }
      location.assign(`/g/${group.public_id}`);
    } catch (caught) {
      setProblem(message(caught));
      setBusy(false);
    }
  }

  return (
    <dialog
      ref={dialog}
      className={styles.dialog}
      aria-label="Start a group"
      onClose={onClose}
      // A click on the dimmed page behind lands on the dialog element itself.
      onClick={(event) => event.target === dialog.current && dialog.current?.close()}
    >
      <form className={styles.dialogBody} onSubmit={create}>
        <div className={styles.roadHead}>
          <h2 className={styles.heading}>Start a group</h2>
          <button type="button" className={styles.linkButton} onClick={() => dialog.current?.close()}>
            Close
          </button>
        </div>

        <div className={styles.groupHead}>
          <GroupIcon icon={{ glyph, color, image: picture?.url ?? null }} name={name || "?"} size={72} />
          <div className={styles.groupHeadText}>
            <strong className={styles.dialogName}>{name.trim() || "Your group"}</strong>
            <span className={styles.rowMuted}>{bio.trim() || "A club, a class, or your regulars."}</span>
          </div>
        </div>

        <label className={styles.field}>
          Name
          <input
            className={styles.input}
            value={name}
            minLength={NAME_MIN}
            maxLength={NAME_LIMIT}
            placeholder="IU FinTech Club"
            autoComplete="off"
            required
            autoFocus
            onChange={(event) => setName(event.target.value)}
          />
        </label>

        <label className={styles.field}>
          Bio
          <textarea
            className={styles.bioInput}
            value={bio}
            maxLength={BIO_LIMIT}
            rows={2}
            placeholder="What the group is, and when it plays."
            onChange={(event) => setBio(event.target.value)}
          />
          <span className={styles.rowMuted}>
            {bio.length} / {BIO_LIMIT}
          </span>
        </label>

        <div className={styles.field} role="group" aria-label="Shield">
          Shield
          <input ref={picker} type="file" accept="image/png,image/jpeg,image/webp" hidden onChange={picked} />
          <div className={styles.buttonRow}>
            <button type="button" className={styles.smallButton} onClick={() => picker.current?.click()}>
              {picture ? "Change picture" : "Upload a picture"}
            </button>
            {picture && (
              <button type="button" className={styles.smallButton} onClick={() => setPicture(null)}>
                Remove picture
              </button>
            )}
          </div>
          <span className={styles.rowMuted}>
            {picture ? "Your picture shows on the shield instead of the drawing." : "Or pick a drawing and a colour."}
          </span>
          <GroupIconPicker glyph={glyph} color={color} name={name || "?"} onGlyph={setGlyph} onColor={setColor} />
        </div>

        {problem && (
          <p className={styles.error} role="alert">
            {problem}
          </p>
        )}

        <div className={styles.dialogFoot}>
          <p className={styles.settingsHint}>
            {short > 0
              ? `Starting a group costs ${cost.toLocaleString()} coins. You have ${coins.toLocaleString()}: ${short.toLocaleString()} more to go.`
              : `You have ${coins.toLocaleString()} coins, so ${(coins - cost).toLocaleString()} will be left. Disbanding a group doesn't give them back.`}
          </p>
          <button type="submit" className={`${styles.button} ${styles.primary}`} disabled={!ready || busy}>
            {busy ? "Starting…" : `Create for ${cost.toLocaleString()} coins`}
          </button>
        </div>
      </form>
    </dialog>
  );
}
