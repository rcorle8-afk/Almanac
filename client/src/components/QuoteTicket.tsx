import { useState, type FormEvent } from "react";
import type { Quote } from "../lib/types";
import styles from "../styles.module.css";

const WIDE_RATIO = 10;

interface QuoteTicketProps {
  tick: string;
  quote: Quote | null;
  error: string | null;
  onSubmit: (bid: string, ask: string) => void;
}

export function QuoteTicket({ tick, quote, error, onSubmit }: QuoteTicketProps) {
  const [bid, setBid] = useState(quote?.bid ?? "");
  const [ask, setAsk] = useState(quote?.ask ?? "");
  const wide = Number(bid) > 0 && Number(ask) / Number(bid) > WIDE_RATIO;

  function submit(event: FormEvent) {
    event.preventDefault();
    onSubmit(bid, ask);
  }

  return (
    <form className={styles.panel} onSubmit={submit}>
      <h2 className={styles.panelTitle}>Your sealed quote</h2>
      <div className={styles.actions}>
        <label className={styles.field}>
          Bid
          <input
            className={styles.input}
            type="number"
            inputMode="decimal"
            min={tick}
            step={tick}
            value={bid}
            required
            onChange={(event) => setBid(event.target.value)}
          />
        </label>
        <label className={styles.field}>
          Ask
          <input
            className={styles.input}
            type="number"
            inputMode="decimal"
            min={tick}
            step={tick}
            value={ask}
            required
            onChange={(event) => setAsk(event.target.value)}
          />
        </label>
      </div>
      {wide && (
        <p className={styles.warning}>
          That's over {WIDE_RATIO} times wide, so it's unlikely to win the Best Quote bonus.
        </p>
      )}
      <button type="submit" className={`${styles.button} ${styles.primary}`}>
        {quote ? "Update quote" : "Submit quote"}
      </button>
      {quote && !error && (
        <p className={styles.notice}>
          Sealed at {quote.bid} / {quote.ask}. You can change it until the timer ends.
        </p>
      )}
      {error && (
        <p className={styles.error} role="alert">
          {error}
        </p>
      )}
    </form>
  );
}
