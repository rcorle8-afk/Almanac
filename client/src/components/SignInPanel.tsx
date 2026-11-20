import { useEffect, useRef, useState } from "react";
import {
  devSignIn,
  fetchConfig,
  loadGoogle,
  signInWithGoogle,
  type Account,
  type AuthConfig,
} from "../lib/auth";
import { useCatalog } from "../lib/catalog";
import styles from "../styles.module.css";

interface SignInPanelProps {
  title: string;
  blurb: string;
  /** The name the dev sign-in uses locally. */
  devName?: string;
  onSignedIn: (user: Account) => void;
}

/** The Sign in with Google box. Renders nothing when the server offers no way to sign in. */
export function SignInPanel({ title, blurb, devName = "Dev Tester", onSignedIn }: SignInPanelProps) {
  const catalog = useCatalog();
  const [config, setConfig] = useState<AuthConfig | null>(null);
  const [error, setError] = useState<string | null>(null);
  const googleButton = useRef<HTMLDivElement>(null);
  const signedIn = useRef(onSignedIn);
  signedIn.current = onSignedIn;

  useEffect(() => {
    fetchConfig()
      .then(setConfig)
      .catch(() => setConfig({ google_client_id: "", dev_login: false }));
  }, []);

  useEffect(() => {
    if (!config?.google_client_id) return;
    let cancelled = false;
    loadGoogle()
      .then((google) => {
        if (cancelled || !googleButton.current) return;
        google.initialize({
          client_id: config.google_client_id,
          callback: (response) =>
            signInWithGoogle(response.credential)
              .then((user) => signedIn.current(user))
              .catch((caught: Error) => setError(caught.message)),
        });
        google.renderButton(googleButton.current, {
          theme: "filled_black",
          size: "large",
          shape: "pill",
          text: "signin_with",
          width: 280,
        });
      })
      .catch((caught: Error) => setError(caught.message));
    return () => {
      cancelled = true;
    };
  }, [config]);

  if (!config?.google_client_id && !config?.dev_login) return null;

  return (
    <section className={styles.panel}>
      <h2 className={styles.panelTitle}>{title}</h2>
      {config.google_client_id && <div ref={googleButton} className={styles.googleButton} />}
      {config.dev_login && (
        <button
          type="button"
          className={styles.button}
          onClick={() =>
            devSignIn(devName)
              .then((user) => signedIn.current(user))
              .catch((caught: Error) => setError(caught.message))
          }
        >
          Dev sign-in
        </button>
      )}
      <p className={styles.privacy}>
        New accounts start with {catalog?.welcome_coins ?? 750} coins for the marketplace. {blurb}
      </p>
      {error && (
        <p className={styles.error} role="alert">
          {error}
        </p>
      )}
    </section>
  );
}
