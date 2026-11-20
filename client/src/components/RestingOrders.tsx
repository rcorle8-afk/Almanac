import { cleanNumber } from "../lib/format";
import type { Order } from "../lib/types";
import styles from "../styles.module.css";

interface RestingOrdersProps {
  orders: Order[];
  onCancel: (orderId: string) => void;
}

export function RestingOrders({ orders, onCancel }: RestingOrdersProps) {
  if (orders.length === 0) return null;
  return (
    <section className={styles.panel}>
      <h2 className={styles.panelTitle}>Your resting orders</h2>
      <div className={styles.restingChips}>
        {orders.map((order) => (
          <span key={order.id} className={styles.chipOrder}>
            <span className={order.side === "BUY" ? styles.gain : styles.loss}>
              {order.side === "BUY" ? "Buy" : "Sell"} {order.remaining} @ {cleanNumber(Number(order.price))}
            </span>
            <button
              type="button"
              className={styles.chipCancel}
              aria-label={`Cancel ${order.side === "BUY" ? "buy" : "sell"} ${order.remaining} at ${order.price}`}
              onClick={() => onCancel(order.id)}
            >
              ✕
            </button>
          </span>
        ))}
      </div>
    </section>
  );
}
