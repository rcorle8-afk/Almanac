import { useEffect, useRef, useState } from "react";
import { MAX_DRINKS_PER_ROUND, pointsPerDrink, strengthLabel } from "../lib/drinks";
import { fetchCategories, type QuestionCategory } from "../lib/host";
import type { ClientMessage, GameState } from "../lib/types";
import styles from "../styles.module.css";
import { HostInvite } from "./HostInvite";

const ROOM_CAPACITY = 120;
const MAX_BOTS = 20;
const BOT_LEVELS = [
  { level: 1, label: "Easy", blurb: "often off by a factor of two" },
  { level: 2, label: "Medium", blurb: "usually within 50%" },
  { level: 3, label: "Hard", blurb: "within about 15%, and quick to punish a bad price" },
];

// Settings the host will get later, listed so the drawer already reads as the place for them.
const COMING_SOON = ["A scripted host that narrates a demo"];

type CaseMode = GameState["config"]["case_mode"];
// The host's switch for case questions (a short setup, then the question, for more points).
const CASE_MODES: { id: CaseMode; label: string; blurb: string }[] = [
  { id: "extra", label: "Extra", blurb: "Extra: case questions can come up in any round." },
  { id: "default", label: "Default", blurb: "Default: the last three rounds are case questions." },
  { id: "off", label: "Off", blurb: "Off: no case questions this game." },
];

type Timers = GameState["config"]["timers"];
type Pace = { label: string; blurb: string; rounds: number; timers: Timers; hint: number };
// Two ways to run a room: the standard game, and a gentler one for a first-timers' table.
const PACES: Pace[] = [
  {
    label: "Standard",
    blurb: "7 rounds · 5s read · 20s quote · 45s trade",
    rounds: 7,
    timers: {
      question: 5,
      quoting: 20,
      trading: 45,
      reveal: 10,
      scores: 10,
      case_question: 15,
      case_trading: 75,
    },
    hint: 15,
  },
  {
    label: "First-timers",
    blurb: "5 rounds · 10s read · 40s quote · 60s trade",
    rounds: 5,
    timers: {
      question: 10,
      quoting: 40,
      trading: 60,
      reveal: 15,
      scores: 15,
      case_question: 25,
      case_trading: 90,
    },
    hint: 20,
  },
];

interface NumberFieldProps {
  label: string;
  value: number;
  min: number;
  max: number;
  step?: number;
  unit?: string;
  disabled?: boolean;
  onCommit: (value: number) => void;
}

/** A number box that sends on blur or Enter, not on every keystroke, and clamps to its range. */
function NumberField({ label, value, min, max, step = 1, unit, disabled, onCommit }: NumberFieldProps) {
  const [draft, setDraft] = useState(String(value));
  useEffect(() => setDraft(String(value)), [value]);
  function commit() {
    const next = Math.min(max, Math.max(min, Number(draft)));
    if (Number.isNaN(next)) {
      setDraft(String(value));
      return;
    }
    setDraft(String(next));
    if (next !== value) onCommit(next);
  }
  return (
    <label className={`${styles.hostOption} ${styles.hostField}`}>
      <span>
        {label}
        {unit && <span className={styles.settingsCount}> {unit}</span>}
      </span>
      <input
        type="number"
        min={min}
        max={max}
        step={step}
        value={draft}
        disabled={disabled}
        onChange={(event) => setDraft(event.target.value)}
        onBlur={commit}
        onKeyDown={(event) => {
          if (event.key === "Enter") (event.target as HTMLInputElement).blur();
        }}
      />
    </label>
  );
}

export function GearIcon() {
  return (
    <svg
      width="20"
      height="20"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      <circle cx="12" cy="12" r="3" />
      <path d="M19.4 15a1.7 1.7 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-1.8-.3 1.7 1.7 0 0 0-1 1.5V21a2 2 0 1 1-4 0v-.1a1.7 1.7 0 0 0-1.1-1.5 1.7 1.7 0 0 0-1.8.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0 .3-1.8 1.7 1.7 0 0 0-1.5-1H3a2 2 0 1 1 0-4h.1a1.7 1.7 0 0 0 1.5-1.1 1.7 1.7 0 0 0-.3-1.8l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.7 1.7 0 0 0 1.8.3H9a1.7 1.7 0 0 0 1-1.5V3a2 2 0 1 1 4 0v.1a1.7 1.7 0 0 0 1 1.5 1.7 1.7 0 0 0 1.8-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0-.3 1.8V9a1.7 1.7 0 0 0 1.5 1H21a2 2 0 1 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1z" />
    </svg>
  );
}

interface HostSettingsProps {
  state: GameState;
  send: (message: ClientMessage) => void;
  onClose: () => void;
  notice?: string | null; // how the last table invite went
  onSignedIn: () => void; // the host screen signed in from the drawer: its socket reconnects
}

/** The drawer behind the gear icon on the host screen: every host setting, in sections. */
export function HostSettings({ state, send, onClose, notice, onSignedIn }: HostSettingsProps) {
  const closeButton = useRef<HTMLButtonElement>(null);
  const { config, phase } = state;
  const inLobby = phase === "LOBBY";
  const [categories, setCategories] = useState<QuestionCategory[] | null>(null);
  const bots = state.players.filter((player) => player.bot);
  const [botCount, setBotCount] = useState(bots.length || 4);
  const [botLevel, setBotLevel] = useState(2);

  // Runs once when the drawer opens. Every setting change re-renders this component with a
  // fresh snapshot, and focusing the close button again would scroll the drawer back to the
  // top, so onClose is read through a ref instead of being a dependency.
  const close = useRef(onClose);
  close.current = onClose;
  useEffect(() => {
    closeButton.current?.focus({ preventScroll: true });
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") close.current();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  useEffect(() => {
    fetchCategories()
      .then(setCategories)
      .catch(() => setCategories([]));
  }, []);

  // No chosen categories means all of them; the server treats null and [] the same way.
  const chosen = new Set(config.categories ?? []);
  function toggleCategory(id: string, on: boolean) {
    const next = new Set(chosen);
    if (on) next.add(id);
    else next.delete(id);
    send({ type: "host_configure", categories: next.size ? [...next].sort() : [] });
  }

  return (
    <div className={styles.drawerBackdrop} onClick={onClose}>
      <aside
        className={styles.drawer}
        role="dialog"
        aria-modal="true"
        aria-labelledby="host-settings-title"
        onClick={(event) => event.stopPropagation()}
      >
        <div className={styles.drawerHead}>
          <h2 id="host-settings-title" className={styles.heading}>
            Host settings
          </h2>
          <button
            ref={closeButton}
            type="button"
            className={styles.iconButton}
            aria-label="Close settings"
            onClick={onClose}
          >
            ×
          </button>
        </div>

        {!inLobby && (
          <p className={styles.settingsNote}>
            The game is under way. Questions, rounds, bots and seats were set when it started, so
            they stay; timers and the rest apply from the next phase or round.
          </p>
        )}

        {/* The lobby and the final scores carry this too; here it's within reach in any phase,
            and a card sent mid-round waits on each phone for the next pause. */}
        <HostInvite state={state} send={send} onSignedIn={onSignedIn} notice={notice} compact />

        <section className={styles.settingsSection}>
          <h3 className={styles.panelTitle}>Game</h3>
          <label className={styles.hostOption}>
            <input
              type="checkbox"
              checked={config.recall_on_start}
              onChange={(event) =>
                send({ type: "host_configure", recall_on_start: event.target.checked })
              }
            />
            Bring everyone back from the locker and shop when the game starts
          </label>
          <NumberField
            label="Seats in this room, bots included"
            value={config.max_players}
            min={2}
            max={ROOM_CAPACITY}
            disabled={!inLobby}
            onCommit={(seats) => send({ type: "host_configure", max_players: seats })}
          />
        </section>

        <section className={styles.settingsSection}>
          <h3 className={styles.panelTitle}>Rounds and timers</h3>
          <div className={styles.buttonRow}>
            {PACES.map((pace) => {
              const active =
                config.rounds === pace.rounds &&
                config.hint_seconds_left === pace.hint &&
                (Object.keys(pace.timers) as (keyof Timers)[]).every(
                  (phase) => config.timers[phase] === pace.timers[phase],
                );
              return (
                <button
                  key={pace.label}
                  type="button"
                  className={`${styles.button} ${active ? styles.primary : ""}`}
                  title={pace.blurb}
                  onClick={() =>
                    send({
                      type: "host_configure",
                      timers: pace.timers,
                      hint_seconds_left: pace.hint,
                      ...(inLobby ? { rounds: pace.rounds } : {}),
                    })
                  }
                >
                  {pace.label}
                </button>
              );
            })}
          </div>
          <p className={styles.settingsHint}>
            {PACES.map((pace) => `${pace.label}: ${pace.blurb}`).join(". ")}. Rounds change only
            in the lobby; timers apply from the next phase. A case question (a short setup, then
            the question) gets its own longer read and trading times, and its hint is a related
            figure that arrives proportionally earlier.
          </p>
          <NumberField
            label="Rounds"
            value={config.rounds}
            min={3}
            max={15}
            disabled={!inLobby}
            onCommit={(rounds) => send({ type: "host_configure", rounds })}
          />
          {(
            [
              ["question", "Read the question"],
              ["quoting", "Sealed quotes"],
              ["trading", "Trading"],
              ["reveal", "Answer"],
              ["scores", "Scores"],
              ["case_question", "Read a case question"],
              ["case_trading", "Trading on a case question"],
            ] as [keyof Timers, string][]
          ).map(([phase, label]) => (
            <NumberField
              key={phase}
              label={label}
              unit="seconds"
              value={config.timers[phase]}
              min={1}
              max={600}
              onCommit={(seconds) => send({ type: "host_configure", timers: { [phase]: seconds } })}
            />
          ))}
          <NumberField
            label="Hint, seconds before trading closes (0 for none)"
            value={config.hint_seconds_left}
            min={0}
            max={600}
            onCommit={(seconds) => send({ type: "host_configure", hint_seconds_left: seconds })}
          />
          <NumberField
            label="Position limit"
            unit="lots"
            value={config.position_limit}
            min={1}
            max={100}
            onCommit={(lots) => send({ type: "host_configure", position_limit: lots })}
          />
        </section>

        <section className={styles.settingsSection}>
          <h3 className={styles.panelTitle}>Case questions</h3>
          <div className={styles.buttonRow} role="radiogroup" aria-label="Case questions">
            {CASE_MODES.map((mode) => (
              <button
                key={mode.id}
                type="button"
                role="radio"
                aria-checked={config.case_mode === mode.id}
                className={`${styles.button} ${config.case_mode === mode.id ? styles.primary : ""}`}
                disabled={!inLobby}
                onClick={() => send({ type: "host_configure", case_mode: mode.id })}
              >
                {mode.label}
              </button>
            ))}
          </div>
          <p className={styles.settingsHint}>
            {CASE_MODES.find((mode) => mode.id === config.case_mode)?.blurb} Case questions are
            worth 1.5× to 2.5× the points, rising to the last; the longest to read come last.
          </p>
        </section>

        <section className={styles.settingsSection}>
          <h3 className={styles.panelTitle}>Questions</h3>
          <p className={styles.settingsHint}>
            Tick the categories to draw from; none ticked means all of them. Drinks mode adds its
            own.
          </p>
          {categories === null && <p className={styles.empty}>Loading…</p>}
          {categories?.length === 0 && <p className={styles.empty}>No categories to choose.</p>}
          <div className={styles.categoryGrid}>
            {categories?.map((category) => (
              <label key={category.id} className={styles.hostOption}>
                <input
                  type="checkbox"
                  checked={chosen.has(category.id)}
                  disabled={!inLobby}
                  onChange={(event) => toggleCategory(category.id, event.target.checked)}
                />
                {category.id} <span className={styles.settingsCount}>{category.count}</span>
              </label>
            ))}
          </div>
        </section>

        <section className={styles.settingsSection}>
          <h3 className={styles.panelTitle}>Bots</h3>
          <p className={styles.settingsHint}>
            Bots quote around the real answer and trade when a price looks wrong to them. They
            never earn coins or Best Quote.
            {bots.length > 0 && ` ${bots.length} seated now.`}
          </p>
          <div className={styles.botControls}>
            <NumberField
              label="How many"
              value={botCount}
              min={0}
              max={MAX_BOTS}
              disabled={!inLobby}
              onCommit={setBotCount}
            />
            <label className={`${styles.hostOption} ${styles.hostField}`}>
              <span>Difficulty</span>
              <select
                className={styles.select}
                value={botLevel}
                disabled={!inLobby}
                onChange={(event) => setBotLevel(Number(event.target.value))}
              >
                {BOT_LEVELS.map((entry) => (
                  <option key={entry.level} value={entry.level}>
                    {entry.label}: {entry.blurb}
                  </option>
                ))}
              </select>
            </label>
            <div className={styles.buttonRow}>
              <button
                type="button"
                className={styles.button}
                disabled={!inLobby}
                onClick={() => send({ type: "host_bots", count: botCount, level: botLevel })}
              >
                {bots.length > 0 ? "Reseat bots" : "Add bots"}
              </button>
              {bots.length > 0 && (
                <button
                  type="button"
                  className={styles.button}
                  disabled={!inLobby}
                  onClick={() => send({ type: "host_bots", count: 0, level: botLevel })}
                >
                  Remove bots
                </button>
              )}
            </div>
          </div>
          <button
            type="button"
            className={`${styles.button} ${styles.primary}`}
            disabled={!inLobby}
            onClick={() => {
              send({ type: "host_demo" });
              onClose();
            }}
          >
            Run a demo game
          </button>
          <p className={styles.settingsHint}>
            Seats six medium bots alongside anyone already in and starts at once, so you can show
            the game to a room.
          </p>
        </section>

        <section className={styles.settingsSection}>
          <h3 className={styles.panelTitle}>Drinks mode</h3>
          <label className={styles.hostOption}>
            <input
              type="checkbox"
              checked={config.drinks}
              onChange={(event) => send({ type: "host_configure", drinks: event.target.checked })}
            />
            Points lost become drinks, and the questions get crazier
          </label>
          {config.drinks && (
            <label className={`${styles.hostOption} ${styles.hostSlider}`}>
              <span>
                Strength: <strong>{strengthLabel(config.drink_strength)}</strong> · a drink for
                every {pointsPerDrink(config.drink_strength)} points lost, up to{" "}
                {MAX_DRINKS_PER_ROUND} a round
              </span>
              <input
                type="range"
                min={1}
                max={5}
                step={1}
                value={config.drink_strength}
                aria-label="Drink strength"
                onChange={(event) =>
                  send({ type: "host_configure", drink_strength: Number(event.target.value) })
                }
              />
            </label>
          )}
        </section>

        <section className={styles.settingsSection}>
          <h3 className={styles.panelTitle}>Coming soon</h3>
          <ul className={styles.comingSoon}>
            {COMING_SOON.map((item) => (
              <li key={item}>{item}</li>
            ))}
          </ul>
        </section>
      </aside>
    </div>
  );
}
