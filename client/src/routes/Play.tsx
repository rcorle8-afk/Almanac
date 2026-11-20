import { useEffect, useRef, useState } from "react";
import { GameAwards } from "../components/GameAwards";
import { InvitePrompt, LobbyChips } from "../components/TableSocial";
import { Unlocked } from "../components/Unlocked";
import { BookLoader } from "../components/BookLoader";
import { HintBanner } from "../components/HintBanner";
import { HowToPlay } from "../components/HowToPlay";
import { LockerRoom } from "../components/LockerRoom";
import { Marketplace } from "../components/Marketplace";
import { OrderTicket } from "../components/OrderTicket";
import { PhoneHeader } from "../components/PhoneHeader";
import { QuestionCard } from "../components/QuestionCard";
import { QuoteTicket } from "../components/QuoteTicket";
import { RestingOrders } from "../components/RestingOrders";
import { Scores } from "../components/Scores";
import { SignInPanel } from "../components/SignInPanel";
import { Wheels } from "../components/Wheels";
import { YourTrades } from "../components/YourTrades";
import type { Account } from "../lib/auth";
import { strengthLabel } from "../lib/drinks";
import { cleanNumber, pointsClass, signedPoints } from "../lib/format";
import { useGame } from "../lib/ws";
import type { ServerMessage } from "../lib/types";
import styles from "../styles.module.css";
import { clearSeat, readSeat, writeSeat } from "./seat";

// These mean this tab has no seat, so the player goes back to the join form.
const SEATLESS_ERRORS = new Set([
  "room_not_found",
  "room_full",
  "game_started",
  "name_taken",
  "bad_name",
  "group_only", // a members-only room: back to the main menu, where they can sign in
]);
const MAX_ORDER_SIZE = 5;
const LOST_ROOM_MESSAGE =
  "That game ended early because the server restarted. Ask the host for the new room code.";

// The phone keeps its socket open in every view; the header stays, the body below it changes.
type View = "game" | "locker" | "shop";
const VIEWS: { id: View; label: string }[] = [
  { id: "game", label: "Game" },
  { id: "locker", label: "Locker" },
  { id: "shop", label: "Shop" },
];

/** Drinks mode: what this round's losses cost you, once the round is settled. */
function DrinkCall({ drinks, total, strength }: { drinks: number; total: number; strength: number }) {
  const verdict = drinks === 0 ? "Safe" : `Drink ${drinks}`;
  const why =
    drinks === 0
      ? "No losses this round."
      : drinks === 1
        ? "One drink for this round's losses."
        : `${drinks} drinks for this round's losses.`;
  return (
    <section className={`${styles.panel} ${styles.drinkCall}`} role="status">
      <h2 className={styles.panelTitle}>Drinks mode · {strengthLabel(strength)}</h2>
      <p className={styles.drinkNumber}>{verdict}</p>
      <p className={styles.empty}>
        {why} {total} {total === 1 ? "drink" : "drinks"} so far this game.
      </p>
    </section>
  );
}

/** Where a guest's sign-in from the phone stands: tying the seat, or refused. */
function LinkStatus({ linking, linkNote }: { linking: Account | null; linkNote: string | null }) {
  return (
    <>
      {linking && (
        <p className={styles.notice} role="status">
          Signed in as {linking.name}. Tying this seat to your account…
        </p>
      )}
      {linkNote && (
        <p className={styles.error} role="alert">
          {linkNote}
        </p>
      )}
    </>
  );
}

export function Play() {
  const room = new URLSearchParams(location.search).get("room") ?? "";
  const [price, setPrice] = useState("");
  const [view, setView] = useState<View>("game");
  // The account a guest signed in with from the phone, while this seat is being tied to it.
  const [linking, setLinking] = useState<Account | null>(null);
  const [linkNote, setLinkNote] = useState<string | null>(null);
  const awaitingLink = useRef(false);

  const { state, connected, error, clockOffset, send, reconnect, replaced } = useGame(
    () => {
      const seat = readSeat(room);
      return { type: "join", room_code: room, name: seat?.name ?? "", token: seat?.token ?? null };
    },
    (message: ServerMessage) => {
      if (message.type === "joined") {
        writeSeat(room, { name: readSeat(room)?.name ?? "", token: message.token });
      } else if (message.type === "state" && awaitingLink.current) {
        // The first snapshot on the new socket says whether the seat took the account.
        awaitingLink.current = false;
        const mine = message.players.find((player) => player.id === message.you?.player_id);
        if (mine && !mine.signed_in) {
          setLinking(null);
          setLinkNote("That account already has a seat in this room, so this one stays a guest.");
        }
      } else if (message.type === "error" && SEATLESS_ERRORS.has(message.code)) {
        // A seat token means we were in this room; the room vanishing means the server restarted.
        const wasSeated = Boolean(readSeat(room)?.token);
        clearSeat(room);
        if (message.code === "room_not_found" && wasSeated) {
          location.assign(`/?error=${encodeURIComponent(LOST_ROOM_MESSAGE)}`);
        } else {
          location.assign(`/?room=${encodeURIComponent(room)}&error=${encodeURIComponent(message.message)}`);
        }
      }
    },
  );

  // When the host starts the game, phones in the locker or shop come back to it (host setting).
  const phase = state?.phase;
  const recallOnStart = state?.config.recall_on_start ?? false;
  const previousPhase = useRef(phase);
  useEffect(() => {
    if (previousPhase.current === "LOBBY" && phase === "QUESTION" && recallOnStart) setView("game");
    previousPhase.current = phase;
  }, [phase, recallOnStart]);

  if (replaced) {
    return (
      <main className={styles.narrowPage}>
        <p className={styles.lostRoom} role="alert">
          {replaced} Keep playing there, or reload this page to bring your seat back here.
        </p>
      </main>
    );
  }
  if (!state?.you) {
    return error ? (
      <main className={styles.narrowPage}>{error}</main>
    ) : (
      <BookLoader label="Finding your seat" />
    );
  }

  const you = state.you;
  const { question } = state;
  const roundPoints = Number(you.round_points);
  const me = state.players.find((player) => player.id === you.player_id);
  const signedIn = me?.signed_in ?? false;
  const invites = you.group_invites ?? [];
  const floatInvite = invites.length > 0 && (phase === "LOBBY" || phase === "GAME_OVER");
  // Joined mid-round: watch this one, play from the next question.
  const benched = you.sitting_out && phase !== "LOBBY" && phase !== "GAME_OVER";

  const drinkCall = state.config.drinks && me && me.drinks !== null && (
    <DrinkCall drinks={me.drinks} total={me.drinks_total} strength={state.config.drink_strength} />
  );

  // Shown through trading, the reveal and the scores; the answer is only present from the reveal.
  const trades = (
    <YourTrades
      fills={you.fills}
      position={you.position}
      players={state.players}
      answer={question?.answer ?? null}
      scoring={state.config.scoring}
      multiplier={Number(question?.multiplier ?? 1)}
    />
  );

  function signInFromPhone(user: Account) {
    setLinkNote(null);
    setLinking(user);
    awaitingLink.current = true;
    reconnect(); // the server reads the session cookie when the socket opens
  }

  return (
    // The game view is calm: avatars and banners hold still. The locker and shop views move.
    <main className={`${styles.narrowPage} ${view === "game" ? styles.calm : ""} ${floatInvite ? styles.underInvite : ""}`}>
      <PhoneHeader state={state} clockOffset={clockOffset} connected={connected} youId={you.player_id} />

      <nav className={`${styles.slotTabs} ${styles.phoneNav}`} aria-label="Screens">
        {VIEWS.map((entry) => (
          <button
            key={entry.id}
            type="button"
            aria-pressed={view === entry.id}
            className={`${styles.slotTab} ${view === entry.id ? styles.slotTabActive : ""}`}
            onClick={() => setView(entry.id)}
          >
            {entry.label}
          </button>
        ))}
      </nav>

      {view !== "game" && !signedIn && (
        <>
          <LinkStatus linking={linking} linkNote={linkNote} />
          {!linking && (
            <SignInPanel
              title="Sign in to open your locker and the marketplace"
              blurb="Your avatar, coins and this game's points save to your account. Your name in the room stays the same."
              devName={me?.name}
              onSignedIn={signInFromPhone}
            />
          )}
        </>
      )}
      {view === "locker" && signedIn && <LockerRoom compact onAvatarSaved={reconnect} />}
      {view === "shop" && signedIn && <Marketplace compact onAvatarSaved={reconnect} />}

      {/* The host's group invite. Before the game and after it, it rises over the foot of
          whichever view is showing, like a notification. One sent mid-game waits for the scores,
          in the page. */}
      {floatInvite && (
        <InvitePrompt invites={invites} send={send} devName={me?.name} onSignedIn={signInFromPhone} floating />
      )}

      {view === "game" && (
        <>
          {phase === "SCORES" && (
            <InvitePrompt invites={invites} send={send} devName={me?.name} onSignedIn={signInFromPhone} floating={false} />
          )}
          {phase === "LOBBY" && (
            <>
              <section className={styles.panel}>
                <h2 className={styles.heading}>You're in</h2>
                <p className={styles.empty}>
                  Room {state.room_code}. {state.player_count}{" "}
                  {state.player_count === 1 ? "player" : "players"} so far.{" "}
                  {state.live
                    ? "Tonight's live game starts on its own when the countdown ends."
                    : state.endless
                      ? "The next question starts in a moment."
                      : state.host
                        ? `${state.host.name} is hosting and starts the game.`
                        : "The host starts the game."}
                </p>
                <LobbyChips
                  players={state.players}
                  youId={you.player_id}
                  signedIn={signedIn}
                  extra={state.player_count - state.players.length}
                />
                {state.config.drinks && (
                  <p className={styles.notice}>
                    Drinks mode is on ({strengthLabel(state.config.drink_strength).toLowerCase()}):
                    points you lose become drinks, and the questions get crazier.
                  </p>
                )}
                {signedIn ? (
                  <p className={styles.notice} role="status">
                    Signed in. This game's points and coins go to your account.
                  </p>
                ) : (
                  <LinkStatus linking={linking} linkNote={linkNote} />
                )}
              </section>
              {!signedIn && !linking && !invites.length && (
                <SignInPanel
                  title="Playing as a guest"
                  blurb="Sign in now and this game's points and coins go to your account. Your name in the room stays the same."
                  devName={me?.name}
                  onSignedIn={signInFromPhone}
                />
              )}
              <HowToPlay />
            </>
          )}

          {benched && (
            <section className={styles.panel}>
              <h2 className={styles.heading}>You're in</h2>
              <p className={styles.empty}>
                Round {state.round_no} was already under way, so you sit this one out. You play
                from the next question; watch the board meanwhile.
              </p>
            </section>
          )}

          {question?.context && phase === "TRADING" && (
            <p className={styles.caseContextCompact}>
              <span className={styles.caseLabel}>×{cleanNumber(Number(question.multiplier))} POINTS</span>
              {question.context}
            </p>
          )}
          {question && phase === "TRADING" && (
            <p className={styles.questionCompact}>
              {question.text} <span className={styles.unit}>({question.unit})</span>
            </p>
          )}
          {question && phase !== "TRADING" && phase !== "GAME_OVER" && <QuestionCard state={state} />}
          <HintBanner state={state} showPending={false} />

          {phase === "QUESTION" && <p className={styles.empty}>Quoting opens next.</p>}

          {phase === "QUOTING" && question && !benched && (
            <QuoteTicket
              tick={question.tick}
              quote={you.quote}
              error={error}
              onSubmit={(bid, ask) => send({ type: "submit_quote", bid, ask })}
            />
          )}

          {phase === "TRADING" && question && !benched && (
            <>
              <Wheels
                book={state.book}
                own={you.resting_orders}
                lastTrade={state.tape[0] ?? null}
                onPick={setPrice}
              />
              <OrderTicket
                book={state.book}
                restingOrders={you.resting_orders}
                position={you.position}
                positionLimit={state.config.position_limit}
                tick={question.tick}
                maxSize={MAX_ORDER_SIZE}
                price={price}
                onPriceChange={setPrice}
                onSubmit={(side, orderPrice, size) =>
                  send({ type: "place_order", side, price: orderPrice, size })
                }
                error={error}
              />
              <RestingOrders
                orders={you.resting_orders}
                onCancel={(orderId) => send({ type: "cancel_order", order_id: orderId })}
              />
              {trades}
            </>
          )}

          {phase === "REVEAL" && !benched && (
            <>
              {drinkCall}
              <section className={styles.panel}>
                <h2 className={styles.panelTitle}>This round</h2>
                <p className={`${styles.bigNumber} ${pointsClass(roundPoints, styles)}`}>
                  {signedPoints(roundPoints)}
                </p>
                <p className={styles.empty}>Finished at {you.position} lots.</p>
              </section>
              {trades}
            </>
          )}

          {(phase === "SCORES" || phase === "GAME_OVER") && (
            <>
              {phase === "GAME_OVER" && <h2 className={styles.heading}>Game over</h2>}
              {phase === "GAME_OVER" && state.live?.cancelled && (
                <p className={styles.notice}>
                  Not enough players joined tonight's live game, so it was called off. It's back
                  tomorrow at 9 PM Eastern.
                </p>
              )}
              {phase === "GAME_OVER" && state.live && !state.live.cancelled && (
                <p className={styles.notice}>
                  That was tonight's live game. <a href="/live">See the live standings</a>.
                </p>
              )}
              {phase === "GAME_OVER" && you.coins_awarded !== null && (
                <p className={styles.saved}>
                  Saved to your profile · <strong>+{you.coins_awarded} coins</strong> ·{" "}
                  <strong>+{you.xp_awarded} XP</strong>
                  {you.prestige_awarded ? (
                    <>
                      {" "}
                      · <strong>+{you.prestige_awarded} prestige</strong>
                    </>
                  ) : null}
                  {you.level_up !== null && (
                    <>
                      {" "}
                      · <strong className={styles.gain}>Level {you.level_up}!</strong>
                    </>
                  )}{" "}
                  · <a href="/profile">View profile</a>
                </p>
              )}
              {phase === "GAME_OVER" && <GameAwards awards={state.awards ?? []} youId={you.player_id} />}
              {phase === "GAME_OVER" && <Unlocked achievements={you.achievements ?? []} />}
              {phase === "GAME_OVER" && state.config.drinks && me && (
                <p className={styles.notice}>
                  Drinks mode: {me.drinks_total} {me.drinks_total === 1 ? "drink" : "drinks"} this
                  game.
                </p>
              )}
              {phase === "SCORES" && !benched && drinkCall}
              {phase === "SCORES" && state.endless && !benched && (
                <p className={styles.saved}>
                  {you.coins_awarded !== null ? (
                    <>
                      This round: <strong>+{you.coins_awarded} coins</strong> ·{" "}
                      <strong>+{you.xp_awarded} XP</strong>. Next question in a moment.
                    </>
                  ) : me?.signed_in ? (
                    "Quote or trade next round to earn coins and XP."
                  ) : (
                    "Sign in to bank coins and XP from every round."
                  )}
                </p>
              )}
              <Scores
                players={state.players}
                highlightId={you.player_id}
                drinks={state.config.drinks}
                total={state.player_count}
              />
              {phase === "SCORES" && !benched && trades}
            </>
          )}
        </>
      )}
    </main>
  );
}
