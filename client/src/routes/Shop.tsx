import { Marketplace } from "../components/Marketplace";
import { Brand } from "../components/TopBar";
import styles from "../styles.module.css";

export function Shop() {
  return (
    <main className={styles.narrowPage}>
      <div className={styles.pageNav}>
        <Brand home="customization" />
        <div className={styles.pageLinks}>
          <a href="/locker">Locker room</a>
          <a href="/profile">Profile</a>
        </div>
      </div>
      <Marketplace />
    </main>
  );
}
