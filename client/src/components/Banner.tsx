import type { ReactNode } from "react";
import styles from "../styles.module.css";

/** The CSS for a banner id, or "" for none. Chips add it to their own class. */
export function bannerClass(id: string | null | undefined): string {
  if (!id) return "";
  const art = styles[`b_${id}`];
  return art ? `${styles.banner} ${art}` : "";
}

/** The strip behind a name. With no banner, the children render bare. */
export function Banner({
  id,
  children,
  className = "",
}: {
  id: string | null | undefined;
  children: ReactNode;
  className?: string;
}) {
  const art = bannerClass(id);
  if (!art) return <>{children}</>;
  return <span className={`${art} ${className}`}>{children}</span>;
}
