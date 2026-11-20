// Almanac's service worker (M5): web push and nothing else. There is no fetch handler, so it
// never caches or intercepts a page; every load goes to the network exactly as without it.
// Served from the site's root with no-cache (server/app.py), so a deploy updates it.

self.addEventListener("install", () => self.skipWaiting());
self.addEventListener("activate", (event) => event.waitUntil(self.clients.claim()));

// The server sends {title, body, url, tag} (server/push.py). A tag replaces an older
// notification about the same thing instead of stacking a second one.
self.addEventListener("push", (event) => {
  let data = {};
  try {
    data = event.data ? event.data.json() : {};
  } catch {
    data = { body: event.data ? event.data.text() : "" };
  }
  event.waitUntil(
    self.registration.showNotification(data.title || "Almanac", {
      body: data.body || "",
      tag: data.tag,
      icon: "/icon-192.png",
      badge: "/icon-192.png",
      data: { url: data.url || "/" },
    }),
  );
});

// Tapping it opens the page it's about: Social, a profile, a group, or the room to join. An
// Almanac window that's already open is reused rather than a second one opened.
self.addEventListener("notificationclick", (event) => {
  event.notification.close();
  const url = new URL(event.notification.data?.url || "/", self.location.origin).href;
  event.waitUntil(
    (async () => {
      const open = await self.clients.matchAll({ type: "window", includeUncontrolled: true });
      for (const client of open) {
        if (client.url.startsWith(self.location.origin) && "navigate" in client) {
          await client.focus();
          return client.navigate(url);
        }
      }
      return self.clients.openWindow(url);
    })(),
  );
});
