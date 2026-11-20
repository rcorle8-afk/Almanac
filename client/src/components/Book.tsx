import type { CSSProperties } from "react";
import { cleanNumber } from "../lib/format";
import type { Book as BookLevels, Level, Order, Side } from "../lib/types";
import styles from "../styles.module.css";

interface BookProps {
  book: BookLevels;
  own: Order[];
  disabled: boolean;
  onPick: (price: string) => void;
  depth?: number;
}

export function Book({ book, own, disabled, onPick, depth }: BookProps) {
  const isOwn = (side: Side, level: Level) =>
    own.some((order) => order.side === side && Number(order.price) === Number(level.price));
  const largest = Math.max(1, ...[...book.bids, ...book.asks].map((level) => level.size));
  const bestBid = Number(book.bids[0]?.price);
  const bestAsk = Number(book.asks[0]?.price);
  const hasBothSides = book.bids.length > 0 && book.asks.length > 0;

  const row = (side: Side, level: Level) => (
    <button
      key={`${side}${level.price}`}
      type="button"
      className={[
        styles.bookRow,
        side === "SELL" ? styles.bookAsk : styles.bookBid,
        isOwn(side, level) ? styles.bookOwn : "",
      ].join(" ")}
      style={{ "--depth": `${(level.size / largest) * 70}%` } as CSSProperties}
      disabled={disabled}
      onClick={() => onPick(level.price)}
    >
      <span>
        {level.price}
        {isOwn(side, level) && <span className={styles.ownTag}>YOU</span>}
      </span>
      <span>{level.size}</span>
    </button>
  );

  return (
    <section className={styles.panel}>
      <h2 className={styles.panelTitle}>Order book</h2>
      <div className={styles.bookHead}>
        <span>Price</span>
        <span>Lots</span>
      </div>
      {book.asks.length === 0 && <p className={styles.emptySide}>No offers yet</p>}
      {book.asks
        .slice(0, depth)
        .reverse()
        .map((level) => row("SELL", level))}
      <div className={styles.spread}>
        <span>Spread {hasBothSides ? cleanNumber(bestAsk - bestBid) : "–"}</span>
        <span>Mid {hasBothSides ? cleanNumber((bestAsk + bestBid) / 2) : "–"}</span>
      </div>
      {book.bids.slice(0, depth).map((level) => row("BUY", level))}
      {book.bids.length === 0 && <p className={styles.emptySide}>No bids yet</p>}
    </section>
  );
}
