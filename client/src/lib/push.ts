// Web push on this device (M5): the bell's notifications on the lock screen. The server side is
// server/push.py; the service worker that shows them is client/public/sw.js.

/** Where this device stands:
 *  - "install": an iPhone or iPad in Safari; push needs Almanac on the Home Screen first.
 *  - "unsupported": this browser can't do web push at all.
 *  - "unavailable": the server has no push keys, so there's nothing to turn on.
 *  - "denied": the person blocked notifications in the browser's settings.
 *  - "off" / "on": whether this device is subscribed. */
export type PushState = "install" | "unsupported" | "unavailable" | "denied" | "off" | "on";

const supported = () => "serviceWorker" in navigator && "PushManager" in window && "Notification" in window;

const appleMobile = () =>
  /iPad|iPhone|iPod/.test(navigator.userAgent) || (navigator.platform === "MacIntel" && navigator.maxTouchPoints > 1);

const installed = () =>
  window.matchMedia("(display-mode: standalone)").matches ||
  (navigator as Navigator & { standalone?: boolean }).standalone === true;

let serverKey: Promise<string | null> | null = null;

/** The server's VAPID public key, fetched once; null when push is off there. */
function fetchKey(): Promise<string | null> {
  serverKey ??= fetch("/api/push/key")
    .then((response) => (response.ok ? response.json() : { public_key: null }))
    .then((answer: { public_key: string | null }) => answer.public_key)
    .catch(() => null);
  return serverKey;
}

function keyBytes(base64url: string): Uint8Array {
  const base64 = (base64url + "=".repeat((4 - (base64url.length % 4)) % 4)).replace(/-/g, "+").replace(/_/g, "/");
  return Uint8Array.from(atob(base64), (char) => char.charCodeAt(0));
}

async function post(path: string, body: unknown): Promise<void> {
  const response = await fetch(path, {
    method: "POST",
    credentials: "same-origin",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!response.ok) {
    let detail = "That didn't work.";
    try {
      detail = (await response.json()).detail ?? detail;
    } catch {
      // not JSON
    }
    throw new Error(detail);
  }
}

async function currentSubscription(): Promise<PushSubscription | null> {
  const registration = await navigator.serviceWorker.getRegistration("/");
  return (await registration?.pushManager.getSubscription()) ?? null;
}

/** Registers the service worker. Harmless where push isn't supported; called on every load. */
export function registerServiceWorker(): void {
  if (!("serviceWorker" in navigator)) return;
  navigator.serviceWorker.register("/sw.js", { scope: "/" }).catch(() => undefined);
}

export async function pushState(): Promise<PushState> {
  if (!supported()) return appleMobile() && !installed() ? "install" : "unsupported";
  if (!(await fetchKey())) return "unavailable";
  if (Notification.permission === "denied") return "denied";
  const subscription = await currentSubscription();
  return subscription && Notification.permission === "granted" ? "on" : "off";
}

/** Asks for permission and subscribes this device. Call straight from a tap: Safari only shows
 *  the permission prompt for one, so nothing is awaited before asking. */
export async function enablePush(): Promise<void> {
  const permission = await Notification.requestPermission();
  if (permission !== "granted") {
    throw new Error(permission === "denied" ? "Notifications are blocked for Almanac in this browser." : "Not turned on.");
  }
  const key = await fetchKey();
  if (!key) throw new Error("Notifications aren't set up on this server.");
  const registration = await navigator.serviceWorker.register("/sw.js", { scope: "/" });
  await navigator.serviceWorker.ready;
  const subscription =
    (await registration.pushManager.getSubscription()) ??
    (await registration.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: keyBytes(key) }));
  await post("/api/push/subscriptions", subscription.toJSON());
}

/** Stops notifications on this device, on the server and in the browser. */
export async function disablePush(): Promise<void> {
  if (!supported()) return;
  const subscription = await currentSubscription();
  if (!subscription) return;
  await post("/api/push/subscriptions/remove", { endpoint: subscription.endpoint }).catch(() => undefined);
  await subscription.unsubscribe().catch(() => undefined);
}

/** On load, for someone who already turned push on: tells the server about this device again,
 *  in case it was dropped or the account on this phone changed. Quiet if anything's missing. */
export async function syncPush(): Promise<void> {
  if (!supported() || Notification.permission !== "granted") return;
  const subscription = await currentSubscription().catch(() => null);
  if (!subscription || !(await fetchKey())) return;
  await post("/api/push/subscriptions", subscription.toJSON()).catch(() => undefined);
}
