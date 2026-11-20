import { LockerRoom } from "../components/LockerRoom";
import { Brand } from "../components/TopBar";
import styles from "../styles.module.css";

export function Locker() {
  return (
    <main className={styles.narrowPage}>
      <div className={styles.pageNav}>
        <Brand home="customization" />
        <div className={styles.pageLinks}>
          <a href="/shop">Marketplace</a>
          <a href="/profile">Profile</a>
        </div>
      </div>
      <LockerRoom />
    </main>
  );
}
