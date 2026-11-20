import { Avatar } from "../avatar/Avatar";
import { cleanNumber, pointsClass, signedPoints } from "../lib/format";
import type { Player, YourFill } from "../lib/types";
import styles from "../styles.module.css";

const CLAMP = 200;

interface YourTradesProps {
  fills: YourFill[];
  position: number;
  players: Player[];
  /** The true answer once revealed; each fill then shows what it scored. */
  answer: string | null;
  scoring: "log" | "linear";
  multiplier: number; // a case round's points multiplier; 1 otherwise
}

/** Mirrors server/engine/scoring.py for one fill, from this player's side. */
function fillPoints(fill: YourFill, answer: number, scoring: "log" | "linear", multiplier: number) {
  const price = Number(fill.price);
  const perLot =
    scoring === "log"
      ? Math.max(-CLAMP, Math.min(CLAMP, 100 * Math.log(answer / price)))
      : answer - price;
  const asBuyer = fill.size * perLot * multiplier;
  return fill.side === "BUY" ? asBuyer : -asBuyer;
}

function lots(fills: YourFill[]) {
  return fills.reduce((total, fill) => total + fill.size, 0);
}

function averagePrice(fills: YourFill[]) {
  const notional = fills.reduce((total, fill) => total + fill.size * Number(fill.price), 0);
  return cleanNumber(notional / lots(fills));
}

/** The player's own fills this round: side, size, price, counterparty, and points once settled. */
export function YourTrades({ fills, position, players, answer, scoring, multiplier }: YourTradesProps) {
  const avatarOf = (name: string) => players.find((player) => player.name === name)?.avatar ?? null;
  const bought = fills.filter((fill) => fill.side === "BUY");
  const sold = fills.filter((fill) => fill.side === "SELL");
  const truth = answer === null ? null : Number(answer);
  const stance = position === 0 ? "Flat" : position > 0 ? `Long ${position}` : `Short ${-position}`;

  return (
    <section className={styles.panel}>
      <h2 className={styles.panelTitle}>Your trades</h2>
      {fills.length === 0 ? (
        <p className={styles.empty}>No trades yet. Lift an offer, hit a bid, or rest an order and wait.</p>
      ) : (
        <>
          <p className={styles.tradeSummary}>
            {stance}
            {bought.length > 0 && ` · bought ${lots(bought)} at an average of ${averagePrice(bought)}`}
            {sold.length > 0 && ` · sold ${lots(sold)} at an average of ${averagePrice(sold)}`}
          </p>
          <div className={styles.rows}>
            {fills.map((fill) => {
              const points = truth === null ? null : fillPoints(fill, truth, scoring, multiplier);
              return (
                <div key={fill.seq} className={styles.tradeRow}>
                  <span className={`${styles.tradeSide} ${fill.side === "BUY" ? styles.tradeBuy : styles.tradeSell}`}>
                    {fill.side === "BUY" ? "Bought" : "Sold"}
                  </span>
                  <span className={styles.tapePrice}>
                    {fill.size} @ {cleanNumber(Number(fill.price))}
                  </span>
                  <span className={styles.tradeWith}>
                    {fill.side === "BUY" ? "from" : "to"}
                    <Avatar avatar={avatarOf(fill.counterparty)} size={18} label="" />
                    <span className={styles.nameText}>{fill.counterparty}</span>
                  </span>
                  {points !== null && (
                    <span className={`${styles.tradePoints} ${pointsClass(points, styles)}`}>
                      {signedPoints(points)}
                    </span>
                  )}
                </div>
              );
            })}
          </div>
        </>
      )}
    </section>
  );
}
