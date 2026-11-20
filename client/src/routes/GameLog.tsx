import { useEffect, useState } from "react";
import { BookLoader } from "../components/BookLoader";
import { Brand } from "../components/TopBar";
import { pointsClass, signedPoints } from "../lib/format";
import { fetchGame, type GameDetail, type LoggedRound } from "../lib/games";
import { acceptFriend, addFriend, friendLabel, type Relation } from "../lib/social";
import styles from "../styles.module.css";

const ordinal = (n: number) => {
  const tail = n % 100 >= 11 && n % 100 <= 13 ? "th" : (["th", "st", "nd", "rd"][n % 10] ?? "th");
  return `${n}${tail}`;
};

function when(iso: string) {
  return new Date(iso).toLocaleString(undefined, { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" });
}

/** Add friend beside a signed-in tablemate; once sent or accepted it says where things stand. */
function LogFriendButton({ publicId, relation: initial }: { publicId: string; relation: Relation | null }) {
  const [relation, setRelation] = useState(initial);
  const [busy, setBusy] = useState(false);
  const { label, active } = friendLabel(relation);
  if (!active) return <span className={styles.relationTag}>{label}</span>;
  return (
    <button
      type="button"
      className={styles.friendButton}
      disabled={busy}
      onClick={() => {
        setBusy(true);
        (relation === "incoming" ? acceptFriend(publicId) : addFriend(publicId))
          .then((answer) => setRelation(answer.relation), (caught: Error) => alert(caught.message))
          .finally(() => setBusy(false));
      }}
    >
      {label}
    </button>
  );
}

function RoundCard({ round }: { round: LoggedRound }) {
  return (
    <section className={styles.panel}>
      <h2 className={styles.panelTitle}>Round {round.round_no}</h2>
      <p className={styles.logQuestion}>
        {round.question} <span className={styles.rowMuted}>({round.unit})</span>
      </p>
      <p className={styles.logAnswer}>
        Answer <strong>{round.answer}</strong> {round.unit}
      </p>
      {round.fills.length === 0 ? (
        <p className={styles.empty}>You didn't trade this round.</p>
      ) : (
        <div className={styles.rows}>
          {round.fills.map((fill, index) => (
            <div key={index} className={styles.logFill}>
              <span className={fill.side === "BUY" ? styles.buyText : styles.sellText}>
                {fill.side === "BUY" ? "Bought" : "Sold"} {fill.size} @ {fill.price}
              </span>
              <span className={styles.rowMuted}>
                {fill.side === "BUY" ? "from" : "to"} {fill.counterparty}
              </span>
              <span className={pointsClass(Number(fill.points), styles)}>{signedPoints(fill.points)}</span>
            </div>
          ))}
        </div>
      )}
    </section>
  );
}

/** One past game from your side: the whole table, every round's question and answer, and
 *  your own trades with who was on the other side and what each scored. */
export function GameLog() {
  const id = location.pathname.split("/").filter(Boolean).pop() ?? "";
  const [detail, setDetail] = useState<GameDetail | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetchGame(id)
      .then(setDetail)
      .catch((caught: Error) => setError(caught.message));
  }, [id]);

  if (error) {
    return (
      <main className={styles.narrowPage}>
        <Brand home="social" />
        <p className={styles.empty}>{error}</p>
        <a className={styles.quietLink} href="/profile">
          Back to your profile
        </a>
      </main>
    );
  }
  if (!detail) return <BookLoader label="Opening the game" />;

  const { game } = detail;
  return (
    <main className={styles.narrowPage}>
      <div className={styles.pageNav}>
        <Brand home="social" />
        <div className={styles.pageLinks}>
          <a href="/profile/games">All games</a>
          <a href="/profile">Profile</a>
        </div>
      </div>

      <section className={styles.panel}>
        <h1 className={styles.heading}>Room {game.room_code}</h1>
        <p className={styles.empty}>
          {when(game.ended_at)} · {game.rounds} rounds · {game.player_count} players
        </p>
        <p className={styles.logResult}>
          {ordinal(game.rank)} of {game.player_count} ·{" "}
          <span className={pointsClass(Number(game.points), styles)}>{signedPoints(game.points)}</span> ·{" "}
          <span className={styles.gain}>+{game.coins} coins</span> · +{game.xp} XP
          {game.prestige ? ` · +${game.prestige} prestige` : ""}
        </p>
      </section>

      {!detail.detailed ? (
        <p className={styles.notice}>
          This game was saved before the game log existed, so only your result was kept.
        </p>
      ) : (
        <>
          <section className={styles.panel}>
            <h2 className={styles.panelTitle}>The table</h2>
            <div className={styles.rows}>
              {detail.players.map((player, index) => (
                <div key={index} className={`${styles.logPlayer} ${player.you ? styles.scoreYou : ""}`}>
                  <span className={styles.scoreRank}>{player.rank}</span>
                  <span className={styles.nameText}>
                    {player.public_id && !player.you ? (
                      <a className={styles.plainLink} href={`/u/${player.public_id}`}>
                        {player.name}
                      </a>
                    ) : (
                      player.name
                    )}
                    {player.you && <span className={styles.botTag}>you</span>}
                    {player.bot && <span className={styles.botTag}>bot</span>}
                  </span>
                  {player.public_id && !player.you ? (
                    <LogFriendButton publicId={player.public_id} relation={player.relation} />
                  ) : (
                    <span />
                  )}
                  <span className={pointsClass(Number(player.points), styles)}>{signedPoints(player.points)}</span>
                </div>
              ))}
            </div>
          </section>
          {detail.rounds.map((round) => (
            <RoundCard key={round.round_no} round={round} />
          ))}
        </>
      )}
    </main>
  );
}
