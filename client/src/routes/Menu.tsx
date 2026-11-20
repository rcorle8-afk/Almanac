import { useCallback, useEffect, useRef, useState, type FormEvent, type ReactNode } from "react";
import { Avatar } from "../avatar/Avatar";
import { Bell } from "../components/Bell";
import { Chevron, Icon, type IconName } from "../components/Icon";
import { MenuBar } from "../components/MenuBar";
import { NameCard } from "../components/NameCard";
import { SignInPanel } from "../components/SignInPanel";
import { Brand } from "../components/TopBar";
import { fetchConfig, fetchMe, type Account } from "../lib/auth";
import { useCatalog } from "../lib/catalog";
import { countdown } from "../lib/format";
import { fetchLive, type LiveOverview } from "../lib/live";
import { HOME_SCREEN, SCREENS, startScreen, startSocialTab, type Screen } from "../lib/menu";
import { fetchOpen, type OpenOverview } from "../lib/open";
import { motion, usePager } from "../lib/pager";
import { fetchOverview, onSocialChange, type Overview } from "../lib/social";
import styles from "../styles.module.css";
import { readSeat, writeSeat } from "./seat";
import { SOCIAL_TABS, SocialScreen } from "./Social";

const NAME_LIMIT = 16;
const REFRESH_MS = 30_000;
const HOME = SCREENS.findIndex((screen) => screen.id === HOME_SCREEN);

/** An icon in its box, leading a row. */
function Lead({ name }: { name: IconName }) {
  return (
    <span className={styles.menuLead}>
      <Icon name={name} />
    </span>
  );
}

interface RowProps {
  href: string;
  title: string;
  detail?: ReactNode;
  /** What leads the row: an icon, or a mode's tag. */
  lead: ReactNode;
  /** A count or a few faces, shown before the chevron. */
  trail?: ReactNode;
}

/** One line of the menu: where it goes, and a few words on what's there right now. */
function Row({ href, title, detail, lead, trail }: RowProps) {
  return (
    <a className={styles.menuRow} href={href}>
      {lead}
      <span className={styles.menuRowText}>
        <span className={styles.menuRowTitle}>{title}</span>
        {detail && <span className={styles.menuRowDetail}>{detail}</span>}
      </span>
      {trail}
      <Chevron />
    </a>
  );
}

const Tag = ({ children }: { children: string }) => <span className={styles.menuTag}>{children}</span>;

function ScreenHead({ title, text }: { title: string; text: string }) {
  return (
    <div className={styles.menuHead}>
      <h2 className={styles.heading}>{title}</h2>
      <p className={styles.heroText}>{text}</p>
    </div>
  );
}

/** A ticking clock of its own, so one second passing redraws these few digits and not the menu. */
function Countdown({ to }: { to: number }) {
  const [now, setNow] = useState(Date.now());
  useEffect(() => {
    const tick = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(tick);
  }, []);
  return <span className={styles.menuClock}>{countdown(to - now)}</span>;
}

/* ---------- Play ---------- */

function liveDetail(live: LiveOverview): ReactNode {
  const room = live.room;
  if (room && room.phase !== "GAME_OVER") {
    if (room.phase !== "LOBBY") {
      return `On now · question ${room.round_no} of ${room.rounds_total}`;
    }
    return (
      <>
        Lobby open · starts in <Countdown to={room.starts_at ?? live.next_start} />
      </>
    );
  }
  return (
    <>
      {live.hour - 12} PM Eastern · next in <Countdown to={live.next_start} />
    </>
  );
}

function openDetail(open: OpenOverview | null) {
  if (!open) return "A table that never closes";
  if (open.people === 0) return "Sit down and it starts";
  return `${open.people} ${open.people === 1 ? "person" : "people"} at the table now`;
}

interface PlayProps {
  account: Account | null;
  /** The sign-in box, for a guest; nothing once signed in. */
  signIn: ReactNode;
}

function PlayScreen({ account, signIn }: PlayProps) {
  const params = new URLSearchParams(location.search);
  const [code, setCode] = useState(params.get("room") ?? "");
  const [name, setName] = useState("");
  const [open, setOpen] = useState<OpenOverview | null>(null);
  const [live, setLive] = useState<LiveOverview | null>(null);

  // Signing in offers the account's name, and never overwrites one already typed.
  const accountName = account?.name;
  useEffect(() => {
    if (accountName) setName((current) => current || accountName.slice(0, NAME_LIMIT));
  }, [accountName]);

  useEffect(() => {
    const load = () => {
      if (document.visibilityState !== "visible") return;
      fetchOpen().then(setOpen).catch(() => undefined);
      fetchLive().then(setLive).catch(() => undefined);
    };
    load();
    const poll = window.setInterval(load, REFRESH_MS);
    return () => window.clearInterval(poll);
  }, []);

  function join(event: FormEvent) {
    event.preventDefault();
    const room = code.trim().toUpperCase();
    const seat = readSeat(room);
    const sameName = seat?.name === name.trim();
    writeSeat(room, { name: name.trim(), token: sameName ? seat.token : null });
    location.assign(`/play?room=${encodeURIComponent(room)}`);
  }

  return (
    <>
      <div className={`${styles.hero} ${styles.menuHero}`}>
        <h1 className={styles.heroTitle}>
          Trade what you <span className={styles.heroAccent}>think you know.</span>
        </h1>
        <p className={styles.heroText}>
          Quote a market on the answer, trade against your friends, and settle when the truth comes
          out.
        </p>
      </div>

      {signIn}

      <form className={styles.panel} onSubmit={join}>
        <h2 className={styles.panelTitle}>Join a room</h2>
        <label className={styles.field}>
          Room code
          <input
            className={`${styles.input} ${styles.codeInput}`}
            value={code}
            maxLength={4}
            autoCapitalize="characters"
            autoComplete="off"
            required
            onChange={(event) => setCode(event.target.value)}
          />
        </label>
        <label className={styles.field}>
          Your name
          <input
            className={styles.input}
            value={name}
            maxLength={NAME_LIMIT}
            autoComplete="off"
            required
            onChange={(event) => setName(event.target.value)}
          />
        </label>
        <button type="submit" className={`${styles.button} ${styles.primary}`}>
          Join game
        </button>
        {params.get("error") && (
          <p className={styles.error} role="alert">
            {params.get("error")}
          </p>
        )}
      </form>

      <nav className={styles.menuRows} aria-label="More ways to play">
        <Row href="/open" lead={<Tag>OPEN</Tag>} title="Trade anyone, any time" detail={openDetail(open)} />
        {live?.on !== false && (
          <Row
            href="/live"
            lead={<Tag>LIVE</Tag>}
            title="Play everyone, every night"
            detail={live ? liveDetail(live) : "One game a night"}
          />
        )}
        <Row
          href="/host"
          lead={<Tag>HOST</Tag>}
          title="Host a game on this screen"
          detail="Phones join with the room code"
        />
      </nav>
    </>
  );
}

/* ---------- Social and Customization ---------- */

interface GuestProps {
  children: ReactNode;
  lead?: ReactNode;
  /** Shows the sign-in box. Missing when this server offers no way to sign in. */
  onSignIn: (() => void) | null;
}

/** What a screen that needs an account shows a guest: what's there, and the way to sign in. */
function GuestCard({ children, lead, onSignIn }: GuestProps) {
  return (
    <section className={`${styles.panel} ${styles.menuGuest}`}>
      {lead}
      <p className={styles.menuGuestText}>{children}</p>
      {onSignIn ? (
        <button type="button" className={`${styles.button} ${styles.primary}`} onClick={onSignIn}>
          Sign in
        </button>
      ) : (
        <p className={styles.empty}>Accounts aren't set up on this server.</p>
      )}
    </section>
  );
}

const count = (n: number, one: string, many = `${one}s`) => `${n} ${n === 1 ? one : many}`;

function CustomizationScreen({ account }: { account: Account }) {
  // XP inside the current level, as a share of the way to the next one.
  const floor = 100 * (account.level - 1) ** 2;
  const progress = Math.min(1, Math.max(0, (account.xp - floor) / Math.max(1, account.next_level_xp - floor)));

  return (
    <>
      <section className={`${styles.panel} ${styles.menuLook}`} aria-label="Your look">
        <a className={styles.menuLookAvatar} href="/locker" aria-label="Change your look in the locker room">
          <Avatar avatar={account.avatar} size={96} label="Your avatar" />
        </a>
        <NameCard name={account.name} banner={account.avatar.banner} prestige={account.prestige} />
        <div className={styles.menuLookStats}>
          <div className={styles.menuStat}>
            <span className={styles.coinsLabel}>COINS</span>
            <span className={styles.menuStatValue}>{account.coins.toLocaleString()}</span>
          </div>
          <div className={styles.menuStat}>
            <span className={styles.coinsLabel}>LEVEL {account.level}</span>
            <div className={styles.levelTrack}>
              <div className={styles.levelBar} style={{ width: `${progress * 100}%` }} />
            </div>
            <span className={styles.menuRowDetail}>
              {account.xp} / {account.next_level_xp} XP
            </span>
          </div>
        </div>
      </section>

      <nav className={styles.menuRows} aria-label="Customization">
        <Row href="/locker" lead={<Lead name="customization" />} title="Locker room" detail="Change your avatar and your banner" />
        <Row
          href="/shop"
          lead={<Lead name="bag" />}
          title="Marketplace"
          detail={`${count(account.coins, "coin")} to spend`}
        />
        <Row href="/academia" lead={<Lead name="cap" />} title="Academia" detail="Banners earned by level and prestige" />
        <Row
          href="/profile/achievements"
          lead={<Lead name="medal" />}
          title="Achievements"
          detail="Every badge, and what it pays"
        />
      </nav>
    </>
  );
}

/* ---------- The menu ---------- */

/**
 * The main menu: Social, Play and Customization as three screens you swipe between, Play in the
 * middle (Ryan, Nov 11, 2026; the three main pages he set out on Nov 4). Between them they link
 * every other page. A room link (/?room=CODE) lands on Play with the code filled in. Social is
 * a whole page in itself (routes/Social.tsx): you, then Groups and Friends as tabs of its own.
 */
export function Menu() {
  const catalog = useCatalog();
  const [account, setAccount] = useState<Account | null>(null);
  const [asked, setAsked] = useState(false); // /api/me has answered: a guest is known to be one
  const [canSignIn, setCanSignIn] = useState(false);
  const [overview, setOverview] = useState<Overview | null>(null);
  const [nudge, setNudge] = useState(false);
  const signInBox = useRef<HTMLDivElement>(null);
  const { track, bar, active, go } = usePager(SCREENS.length, startScreen(location.search, location.hash));
  const [socialTab, setSocialTab] = useState(() => startSocialTab(location.hash));

  useEffect(() => {
    fetchMe()
      .then(setAccount)
      .catch(() => undefined)
      .finally(() => setAsked(true));
    fetchConfig()
      .then((config) => setCanSignIn(Boolean(config.google_client_id) || config.dev_login))
      .catch(() => undefined);
  }, []);

  // Friends, groups and what's waiting, reloaded when the bell or the Social screen changes something.
  const reload = useCallback(() => {
    fetchOverview().then(setOverview).catch(() => undefined);
  }, []);
  const accountId = account?.id;
  useEffect(() => {
    setOverview(null);
    if (accountId === undefined) return;
    reload();
    return onSocialChange(reload);
  }, [accountId, reload]);

  // The address remembers the screen, and on Social which of its tabs, so Back from a page
  // returns to where it was opened from: /#social is Groups, /#friends is Friends.
  useEffect(() => {
    const screen: Screen = SCREENS[active].id;
    const name = screen === "social" && SOCIAL_TABS[socialTab] === "friends" ? "friends" : screen;
    const hash = screen === HOME_SCREEN ? "" : `#${name}`;
    if (location.hash !== hash) history.replaceState(null, "", location.pathname + location.search + hash);
  }, [active, socialTab]);

  useEffect(() => {
    const followHash = () => go(startScreen(location.search, location.hash));
    window.addEventListener("hashchange", followHash);
    return () => window.removeEventListener("hashchange", followHash);
  }, [go]);

  useEffect(() => {
    if (!nudge) return;
    const done = window.setTimeout(() => setNudge(false), 1600);
    return () => window.clearTimeout(done);
  }, [nudge]);

  const guest = asked && !account;

  /** Brings the one sign-in box, on Play, into view from a screen that needs an account. */
  function showSignIn() {
    const box = signInBox.current;
    if (!box) return;
    const el = track.current;
    if (el && el.scrollWidth > el.clientWidth + 1) {
      go(HOME);
      box.closest(`.${styles.menuScreen}`)?.scrollTo({ top: 0, behavior: motion() });
    } else {
      box.scrollIntoView({ behavior: motion(), block: "center" });
    }
    setNudge(true);
  }
  const onSignIn = canSignIn ? showSignIn : null;

  const waiting = (overview?.incoming.length ?? 0) + (overview?.group_invites.length ?? 0);
  const welcome = catalog?.welcome_coins ?? 750;

  return (
    <div className={styles.menu}>
      <header className={styles.menuTop}>
        <Brand />
        {account && (
          <div className={styles.navRight}>
            <Bell />
            <a className={styles.menuMe} href="/profile" aria-label="Your profile">
              <Avatar avatar={account.avatar} size={32} label="" />
            </a>
          </div>
        )}
      </header>

      <div className={styles.menuTrack} ref={track}>
        <section className={styles.menuScreen} aria-label="Social">
          {account ? (
            <SocialScreen account={account} overview={overview} onChange={reload} startTab={socialTab} onTab={setSocialTab} />
          ) : (
            <div className={styles.menuColumn}>
              <ScreenHead title="Social" text="Friends, groups, and the people you've played." />
              {guest && (
                <GuestCard onSignIn={onSignIn}>
                  Add friends, start a group, and get invited straight into games. All of it needs an
                  account, so people can find you.
                </GuestCard>
              )}
            </div>
          )}
        </section>

        <section className={styles.menuScreen} aria-label="Play">
          <div className={styles.menuColumn}>
            <PlayScreen
              account={account}
              signIn={
                guest &&
                canSignIn && (
                  <div ref={signInBox} className={nudge ? styles.menuNudge : undefined}>
                    <SignInPanel
                      title="Save your progress"
                      blurb="Signing in keeps your Google name and email so your results and coins can be saved. Or play as a guest below; you can still sign in from the lobby."
                      onSignedIn={setAccount}
                    />
                  </div>
                )
              }
            />
          </div>
        </section>

        <section className={styles.menuScreen} aria-label="Customization">
          <div className={styles.menuColumn}>
            <ScreenHead title="Customization" text="Your avatar, your banner, and what you've earned." />
            {account ? (
              <CustomizationScreen account={account} />
            ) : (
              guest && (
                <GuestCard onSignIn={onSignIn} lead={<Avatar avatar={null} size={88} label="" />}>
                  Sign in to build an avatar and wear a banner beside your name. New accounts start
                  with {welcome} coins for the marketplace.
                </GuestCard>
              )
            )}
          </div>
        </section>
      </div>

      <MenuBar current={SCREENS[active].id} pager={{ bar, go }} waiting={waiting} />
    </div>
  );
}
