import { useState } from "react";
import { cleanNumber } from "../lib/format";
import type { Book, Order, Side } from "../lib/types";
import styles from "../styles.module.css";

interface OrderTicketProps {
  book: Book;
  restingOrders: Order[];
  position: number;
  positionLimit: number;
  tick: string;
  maxSize: number;
  price: string;
  onPriceChange: (price: string) => void;
  onSubmit: (side: Side, price: string, size: number) => void;
  error: string | null;
}

function positionLabel(position: number) {
  if (position === 0) return "Flat";
  return `${position > 0 ? "Long" : "Short"} ${Math.abs(position)}`;
}

export function OrderTicket({
  book,
  restingOrders,
  position,
  positionLimit,
  tick,
  maxSize,
  price,
  onPriceChange,
  onSubmit,
  error,
}: OrderTicketProps) {
  const [size, setSize] = useState(1);

  // The server rejects self-trades too; this just stops the click.
  const crossesOwn = (side: Side, candidate: string) =>
    restingOrders.some((order) =>
      side === "BUY"
        ? order.side === "SELL" && Number(candidate) >= Number(order.price)
        : order.side === "BUY" && Number(candidate) <= Number(order.price),
    );

  const bestBid = book.bids[0]?.price;
  const bestAsk = book.asks[0]?.price;
  const hasPrice = price !== "";
  const shown = (value: string) => cleanNumber(Number(value));

  return (
    <section className={styles.panel}>
      <div className={styles.ticketHead}>
        <h2 className={styles.panelTitle}>Your order</h2>
        <span className={styles.ticketPosition}>
          <strong>{positionLabel(position)}</strong> · limit ±{positionLimit}
        </span>
      </div>
      <div className={styles.ticketRow}>
        <input
          className={styles.input}
          type="number"
          inputMode="decimal"
          placeholder="Price"
          aria-label="Price"
          min={tick}
          step={tick}
          value={price}
          onChange={(event) => onPriceChange(event.target.value)}
        />
        <div className={styles.sizes} role="group" aria-label="Size">
          {Array.from({ length: maxSize }, (_, index) => index + 1).map((option) => (
            <button
              key={option}
              type="button"
              className={`${styles.size} ${option === size ? styles.sizeActive : ""}`}
              aria-pressed={option === size}
              onClick={() => setSize(option)}
            >
              {option}
            </button>
          ))}
        </div>
      </div>
      <div className={styles.actions}>
        <button
          type="button"
          className={`${styles.button} ${styles.buy}`}
          disabled={!hasPrice || crossesOwn("BUY", price)}
          onClick={() => onSubmit("BUY", price, size)}
        >
          {hasPrice ? `Buy ${size} @ ${shown(price)}` : "Buy"}
        </button>
        <button
          type="button"
          className={`${styles.button} ${styles.sell}`}
          disabled={!hasPrice || crossesOwn("SELL", price)}
          onClick={() => onSubmit("SELL", price, size)}
        >
          {hasPrice ? `Sell ${size} @ ${shown(price)}` : "Sell"}
        </button>
      </div>
      <div className={styles.actions}>
        <button
          type="button"
          className={`${styles.button} ${styles.lift} ${styles.liftHit}`}
          disabled={!bestAsk || crossesOwn("BUY", bestAsk)}
          onClick={() => onSubmit("BUY", bestAsk, size)}
        >
          {bestAsk ? `Lift ${size} @ ${shown(bestAsk)}` : "Lift"}
        </button>
        <button
          type="button"
          className={`${styles.button} ${styles.hit} ${styles.liftHit}`}
          disabled={!bestBid || crossesOwn("SELL", bestBid)}
          onClick={() => onSubmit("SELL", bestBid, size)}
        >
          {bestBid ? `Hit ${size} @ ${shown(bestBid)}` : "Hit"}
        </button>
      </div>
      {error && (
        <p className={styles.error} role="alert">
          {error}
        </p>
      )}
    </section>
  );
}
