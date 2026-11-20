import type { KeyboardEvent } from "react";
import { cleanNumber } from "../lib/format";
import type { Book, Level, Order, Side, TapeEntry } from "../lib/types";
import styles from "../styles.module.css";

/*
 * Two wheels drawn as big circles whose rims bulge toward the middle of the screen. Asks sit on
 * the right rim above the spread, bids on the left rim below it, so the two together read as one
 * price ladder. Pillars grow from each price toward the screen edge, one length per lot.
 */
const VIEW_W = 360;
const VIEW_H = 300;
const CENTER_X = VIEW_W / 2;
const CENTER_Y = VIEW_H / 2;
const LEVELS = 5;
const ROW = 22;
const GAP = 66; // room between the best ask and best bid for the mid and last boxes
const RIM_INNER_X = 150; // where the best level's label meets the middle column
const RIM_RADIUS = 360; // a bigger wheel means a flatter rim
const ARC_SPACING = 16;
const PILL_H = 18;
const BAR_H = 14;
const QTY_W = 16;
const EDGE = 4;
const MID_W = 54;
const MID_H = 30;
const WHEEL_CX = RIM_INNER_X - Math.sqrt(RIM_RADIUS ** 2 - (GAP / 2 + ROW / 2) ** 2);

const formatPrice = (price: string) => cleanNumber(Number(price));

function rowY(side: Side, index: number) {
  const offset = GAP / 2 + ROW / 2 + index * ROW;
  return side === "SELL" ? CENTER_Y - offset : CENTER_Y + offset;
}

function rimX(y: number) {
  return WHEEL_CX + Math.sqrt(RIM_RADIUS ** 2 - (y - CENTER_Y) ** 2);
}

function Arcs({ flip }: { flip: boolean }) {
  return (
    <>
      {[0, 1, 2].map((ring) => {
        const radius = RIM_RADIUS - ring * ARC_SPACING;
        const x = WHEEL_CX + Math.sqrt(radius ** 2 - CENTER_Y ** 2);
        const edgeX = flip ? VIEW_W - x : x;
        return (
          <path
            key={ring}
            d={`M ${edgeX} 0 A ${radius} ${radius} 0 0 ${flip ? 0 : 1} ${edgeX} ${VIEW_H}`}
            className={styles.wheelArc}
            style={{ opacity: 0.6 - ring * 0.18 }}
          />
        );
      })}
    </>
  );
}

interface RowProps {
  side: Side;
  index: number;
  level: Level;
  labelW: number;
  perLot: number;
  own: boolean;
  onPick: (price: string) => void;
}

function Row({ side, index, level, labelW, perLot, own, onPick }: RowProps) {
  const flip = side === "SELL";
  const y = rowY(side, index);
  const rim = rimX(y);
  const pillLeft = rim - labelW;
  const barEnd = pillLeft - EDGE;
  const barStart = barEnd - level.size * perLot;
  // Geometry is worked out for the left wheel and mirrored for the right one.
  const X = (x: number) => (flip ? VIEW_W - x : x);
  const rect = (from: number, to: number, top: number, height: number, cls: string, rx: number) => (
    <rect x={flip ? X(to) : from} y={top} width={to - from} height={height} rx={rx} className={cls} />
  );
  const pick = () => onPick(formatPrice(level.price));
  const onKey = (event: KeyboardEvent<SVGGElement>) => {
    if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      pick();
    }
  };

  return (
    <g className={styles.wheelRow} role="button" tabIndex={0} onClick={pick} onKeyDown={onKey}>
      <title>
        {level.size} {flip ? "offered" : "bid"} at {formatPrice(level.price)}
      </title>
      {rect(barStart, barEnd, y - BAR_H / 2, BAR_H, styles.wheelBar, 2)}
      {rect(pillLeft, rim, y - PILL_H / 2, PILL_H, own ? styles.wheelPillOwn : styles.wheelPill, 4)}
      <text x={X(rim - labelW / 2)} y={y + 4.5} textAnchor="middle" className={styles.wheelPrice}>
        {formatPrice(level.price)}
      </text>
      <text
        x={X(barStart - EDGE)}
        y={y + 4}
        textAnchor={flip ? "start" : "end"}
        className={styles.wheelQty}
      >
        {level.size}
      </text>
    </g>
  );
}

function MidBox({ y, label, value }: { y: number; label: string; value: string }) {
  return (
    <g>
      <rect x={CENTER_X - MID_W / 2} y={y} width={MID_W} height={MID_H} rx={6} className={styles.midBox} />
      <text x={CENTER_X} y={y + 11} textAnchor="middle" className={styles.midLabel}>
        {label}
      </text>
      <text x={CENTER_X} y={y + 24} textAnchor="middle" className={styles.midValue}>
        {value}
      </text>
    </g>
  );
}

interface WheelsProps {
  book: Book;
  own: Order[];
  lastTrade: TapeEntry | null;
  onPick: (price: string) => void;
}

export function Wheels({ book, own, lastTrade, onPick }: WheelsProps) {
  const asks = book.asks.slice(0, LEVELS);
  const bids = book.bids.slice(0, LEVELS);
  const shown = [...asks, ...bids];
  const maxSize = Math.max(1, ...shown.map((level) => level.size));
  const longest = Math.max(3, ...shown.map((level) => formatPrice(level.price).length));
  const labelW = 7.4 * longest + 8;
  // The outermost row has the least room; one lot is sized so the biggest pillar fits there.
  const room = rimX(rowY("BUY", LEVELS - 1)) - labelW - EDGE - QTY_W - EDGE;
  const perLot = Math.max(1, room) / maxSize;
  const ownAt = (side: Side) =>
    new Set(own.filter((order) => order.side === side).map((order) => Number(order.price)));
  const ownBids = ownAt("BUY");
  const ownAsks = ownAt("SELL");
  const bestBid = bids[0] ? Number(bids[0].price) : null;
  const bestAsk = asks[0] ? Number(asks[0].price) : null;
  const mid = bestBid !== null && bestAsk !== null ? cleanNumber((bestBid + bestAsk) / 2) : "–";
  const last = lastTrade ? formatPrice(lastTrade.price) : "–";

  return (
    <svg
      viewBox={`0 0 ${VIEW_W} ${VIEW_H}`}
      className={styles.wheels}
      role="img"
      aria-label="Order book: bids on the left wheel, offers on the right"
    >
      <Arcs flip={false} />
      <Arcs flip />
      {asks.length === 0 && (
        <text x={VIEW_W - RIM_INNER_X + 6} y={rowY("SELL", 0) + 4} className={styles.wheelEmpty}>
          no offers
        </text>
      )}
      {bids.length === 0 && (
        <text x={RIM_INNER_X - 6} y={rowY("BUY", 0) + 4} textAnchor="end" className={styles.wheelEmpty}>
          no bids
        </text>
      )}
      {asks.map((level, index) => (
        <Row
          key={level.price}
          side="SELL"
          index={index}
          level={level}
          labelW={labelW}
          perLot={perLot}
          own={ownAsks.has(Number(level.price))}
          onPick={onPick}
        />
      ))}
      {bids.map((level, index) => (
        <Row
          key={level.price}
          side="BUY"
          index={index}
          level={level}
          labelW={labelW}
          perLot={perLot}
          own={ownBids.has(Number(level.price))}
          onPick={onPick}
        />
      ))}
      <MidBox y={CENTER_Y - MID_H - 3} label="MID" value={mid} />
      <MidBox y={CENTER_Y + 3} label="LAST" value={last} />
    </svg>
  );
}
