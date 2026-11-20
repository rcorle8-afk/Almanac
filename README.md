# Almanac

A multiplayer almanac game: players trade on the answer to a numeric question through an order book, and the true answer settles the trades. See [CLAUDE.md](CLAUDE.md) for the full spec.

One screen hosts at `/host`. Players join from their phones at `/` with the room code.

Working on Almanac with the team? Read [CONTRIBUTING.md](CONTRIBUTING.md) after Setup.

## Setup

Requires Python 3.12 and Node 20 or newer.

Windows:

```bash
python -m venv .venv
.venv/Scripts/python -m pip install -r requirements.txt
npm install --prefix client
```

macOS or Linux:

```bash
python3.12 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
npm install --prefix client
```

The commands in the rest of this file are written for Windows. On macOS or Linux, use `.venv/bin/python` wherever they say `.venv/Scripts/python`.

Nothing else is needed to run and test locally: no keys, no accounts with any service, no database to set up. The question bank ships in the repo, and the server creates `data/almanac.db` the first time it starts.

## Run

Development, in two terminals from the repo root:

```bash
.venv/Scripts/python -m uvicorn server.app:app --reload --host 0.0.0.0 --port 8000
```

```bash
npm run dev --prefix client
```

Then open the URL Vite prints. It forwards `/ws` to the server on `PORT` from `.env`, or 8000 if unset.

To serve everything from one port instead, run `npm run build --prefix client` and start only uvicorn. The server hosts `client/dist` when it exists. Phones on your Wi-Fi can join at your computer's local IP address, for example `http://192.168.1.20:8000`.

### Signing in locally

Sign in with Google needs `GOOGLE_CLIENT_ID`, which you don't need on your own machine. To test anything that takes an account, start the server with `ALLOW_DEV_LOGIN=1`, which adds a dev sign-in box that takes any name. The server reads its settings from the shell that starts it, not from a `.env` file, so set it there.

Windows (PowerShell):

```powershell
$env:ALLOW_DEV_LOGIN = "1"
.venv/Scripts/python -m uvicorn server.app:app --reload --host 0.0.0.0 --port 8000
```

macOS or Linux:

```bash
ALLOW_DEV_LOGIN=1 .venv/bin/python -m uvicorn server.app:app --reload --host 0.0.0.0 --port 8000
```

Sign-in and every page that uses an account (profile, locker, marketplace, Social) call `/api`, and the Vite dev server forwards only `/ws`. So for those, use the one-port setup above: build the client and open `http://localhost:8000`. The Vite URL is fine for playing as a guest. Never set `ALLOW_DEV_LOGIN` on a deployed server.

## Questions

Games serve questions marked `verified` (you opened `source_url` and confirmed the `answer`) or `agent_verified` (the verifier below passed every evidence check).

```bash
.venv/Scripts/python -m server.questions.validate --require 30
```

To playtest before enough are ready, set `ALLOW_UNVERIFIED_QUESTIONS=1` for that run. Never set it on a deployed server.

### Verifying questions automatically

`verify.py` has Claude research each `unverified` question without seeing the stored answer. A good estimate is enough. Python then checks each quote against the page text the API returned to Claude, or fetches the page itself if that text isn't available, and marks the question `agent_verified` if all of these hold:

- At least one source's quote appears word for word on its page and contains the stated number. Alternatively, Claude's calculation reruns in Python and at least one of its inputs is confirmed that way.
- Every estimate is within 10% of the others and of the stored answer.
- The agent didn't flag the wording as ambiguous or the answer as likely to change.

Sources that fail to check out are saved as notes and don't block approval. PDF reports count like web pages: the verifier reads their text with `pypdf`, from Claude's copy or its own download. A quote may state its number written out ("1.3 million") or in powers of ten ("1.41 × 10^33"), and a calculation the agent leaves as a plain count is read in the question's unit (1,303,533 Earths is 1.3 million Earths). The agent is told that a question naming its year or report has a fixed answer and isn't ambiguous just because older figures exist.

If sources conflict with each other or with the stored answer, the question becomes `disputed`. `--recheck` skips disputed questions, because a rerun could simply find sources that happen to agree. To release one, fix the question or answer yourself and set `"status": "unverified"`, or confirm it and set `"status": "verified"`.

Anything else becomes `needs_review`, with the reason saved in the question's `verification` field. The tool never changes an answer. It needs `ANTHROPIC_API_KEY` and spends money on each question, so `--limit` is required. It prints the run's cost at the end.

```bash
.venv/Scripts/python -m server.questions.verify --limit 5
```

It uses Sonnet by default. Pass `--model haiku` or `--model opus` to change that; the model used is saved with each result.

Spot-check results regularly. This prints random `agent_verified` questions with their sources:

```bash
.venv/Scripts/python -m server.questions.verify --audit 10
```

Add `--recheck` to retry `needs_review` questions. Redeploy afterward, because the bank ships inside the image.

## Test

```bash
.venv/Scripts/python -m pytest
```

## Deploy

The app runs on Fly.io from the Dockerfile, using [fly.toml](fly.toml). Fly builds the image on its own servers, so Docker isn't needed locally.

```bash
flyctl deploy --ha=false
```

Keep `--ha=false`. Rooms live in memory, so a second machine would split players across two sets of rooms. Rooms also die on every deploy and when an idle machine stops, so don't deploy while a game is running.

A Fly trial account without a credit card stops every machine 5 minutes after it starts, which kills any game in progress. Add a card under Billing in the Fly dashboard before hosting real games.

### Main menu

`/` opens the main menu: three screens you swipe between, with Play in the middle. Play has the room code form and the ways in to the open table, the live game and hosting. Social, one swipe left, opens with the global leaderboard (the top three groups by combined prestige and the top three players, with See all leading to the full boards at `/leaderboard`), then your card (with the way to your profile) above two tabs, Groups and Friends, that slide the same way: your groups behind their shields with each one's combined prestige, and your friends ranked by prestige with the ways to add more. Customization, one swipe right, shows your avatar, coins and level, and leads to the locker room, the marketplace, Academia and achievements. The bar at the bottom shows which screen you're on and jumps to any of them. A room link or QR code (`/?room=CODE`) lands on Play with the code filled in. On a wide screen the three sit side by side. The same Social, Play and Customization bar sits at the foot of every other page, so the three are always one tap away; only the game itself (the phone's table and the host screen) leaves it out. The handle, the notifications switch and a button to view your public profile are on your profile page.

### Accounts

Saved progress needs two one-time pieces of setup:

- A volume for the SQLite file, which `fly.toml` mounts at `/data`:

  ```bash
  flyctl volumes create almanac_data --app almanac-game --region ord --size 1
  ```

- A Google OAuth client ID, set as `GOOGLE_CLIENT_ID` under `[env]` in `fly.toml`. In Google Cloud, create a project, set up the OAuth consent screen (External, published), then under Credentials create an OAuth client ID of type Web application with `https://almanac-game.fly.dev` and `http://localhost:8000` as authorized JavaScript origins. The client ID is public; keep the client secret out of the repo (this app never uses it).

Players sign in on the main menu, or later from the phone lobby if they joined as a guest: the seat keeps its name and takes the account, so the game's points and coins are saved to it. Locally, `ALLOW_DEV_LOGIN=1` adds a dev sign-in button so the account flow can be tested without Google.

### Levels and prestige

Every finished game pays a signed-in player XP (50 for finishing, 5 a round, 2 a trade, 15 a Best Quote) and prestige (100 for a win, 30 for a podium, 20 a Best Quote). Level n needs 100 × (n − 1)² XP. The profile shows the level with a bar to the next one, the host leaderboard shows each account's level and prestige under the name, and the formulas sit at the top of `server/db.py` next to the coin payouts.

### Banners and Academia

A banner is the card behind a player's name on leaderboards, chips and the profile. It is there to make the name stand out: a plain field (paper white, black, navy, forest green, purple or royal blue) with one small motif at the edge or under the name, such as an underline, a star, corner arcs, a sash, stripes, a wave, a set square or a mortarboard. The names are jokes about estimating. Six are for sale in the marketplace's Banners tab, priced like any other item (Ballpark, Back of the Envelope, Rule of Thumb, Educated Guess, Order of Magnitude, Fermi). The rest are earned: `/academia` shows a level track (Beginner's Luck up to Oracle) and a prestige track (Close Enough up to Crystal Ball), plus Podium and Prime Time, reserved for tournament and live-game winners once those modes exist. Earned banners unlock automatically as the account's level and prestige rise and are worn from the locker room; they can't be bought.

### Achievements and the profile

Signed-in players earn achievements for what they do: winning rounds back to back, winning games, tight quotes, big rounds, trading a lot, spending coins, collecting cosmetics, crowded rooms, and a couple of secrets. Each achievement has the tiers its difficulty supports, from bronze through silver, gold and platinum to a mystery tier, and pays coins that grow with the tier; the best tiers also give achievement-only banners or headwear. Badges earned in a game appear on the phone's game-end screen, each with a short animation that gets grander with the tier. `/profile/achievements` lists every tier with what it takes and what it pays; a mystery tier's requirement stays "???" until it's earned. The definitions, goals and rewards are all in `server/achievements.py`.

The profile also has a short bio (160 characters, edited in place) and a shelf of the badges earned so far; tap a badge to see briefly what it was for. Each recent game opens its log: everyone at the table with their final points, each round's question and answer, and your own trades with who was on the other side and what each scored. The profile shows the last 20 games; `/profile/games` has every one, grouped by month and loaded 25 at a time, with who won any game you didn't.

### End-of-game awards

When a game ends, the host screen and every phone show three awards above the final scores: Sharpest quoter (most Best Quotes), Biggest round (the best single round) and Busiest trader (the most trades). Ties share an award, and an award nobody earned is left out.

### Avatars and the marketplace

Signed-in players get an avatar that appears beside their name everywhere, and new accounts start with 750 coins. `/locker` is where they dress it: free parts are always available, and bought parts join them. The card at the top shows the avatar with the name on its banner, as other players see it, and collapses smoothly into a slim pinned row while scrolling so every change shows at once. A name with its banner always appears the same way, on leaderboards, the profile, the locker and the previews: the name on its banner with a small star and the player's prestige. Lobby and quote lists show plain name chips instead. Every everyday haircut is free (twelve of them, from a buzz cut to coils, waves and a top knot); only showpieces like the afro, box braids, dreads and the mohawk cost coins. `/shop` sells the rest for coins, in cards colored by rarity (blue common, orange rare, purple epic, gold legendary, and an animated blue-purple neon outline for mythical). The Effects slot holds animated items (sparkles, lightning, money rain, fire, and the Void aura); they are CSS animations inside the avatar's SVG. They play where a player dresses the avatar (locker, marketplace, profile) and hold still on the host screen and the phone's game view, so a leaderboard full of avatars stays calm. Legendary and mythical items are the exception: their effects, outfit and banners move on every page. The Bundles tab sells themed sets at 80% of the price of whatever the buyer doesn't own yet. Both are also reachable from the phone during a game (Game / Locker / Shop at the top of the screen), so players can browse while they wait; a host setting (gear icon on the host screen) decides whether everyone is brought back to the game screen when it starts.

Prices come from a formula, not a hand. In `server/cosmetics.py` every item has three 1–5 scores (coverage, attention, novelty) and a 0–5 motion score for how much it moves. A weighted index sets the base price (`20 × index²`, to the nearest 5 coins), motion multiplies it (`1 + 0.5 × motion`), and the price sets the rarity (rare from 100, epic from 210, legendary from 360, mythical from 1500), so items that change the avatar about as much cost about the same. To add an item, give it an id, a slot, a name, and its scores there, then draw it under the same id in `client/src/avatar/parts.tsx` (or `effects.tsx` if it moves). A bundle is a name and a list of item ids in the same file. The tests refuse a catalog whose prices break the rules, a mythical that doesn't move, or an item the client can't draw.

### Host tools

The gear icon at the top right of the host screen opens the settings drawer: seats in the room, rounds and the timer for every phase with two presets (Standard, and a slower First-timers pace for a table of newcomers), the hint lead and the position limit, question categories to draw from (none ticked means all), bots (how many and how good: easy bots are often off by a factor of two, hard ones within about 15%, and they take any price that looks wrong to them; bots never earn coins or Best Quote), a demo run that seats six bots and starts at once, and drinks mode. During a round, three buttons sit under the question: Skip ahead moves to the next phase, End game ends the game, and Skip question finishes the current question at once and jumps to its scores (any quotes that crossed still trade and settle). At game over, Play again keeps the room and its players and draws new questions; New room starts from scratch. A host screen that is signed in hosts as that account, and the same account can still join and play from a phone. In the lobby, and again on the final scores, a small round button opens the host's groups, and picking one invites everyone at the table: each phone gets a pop-up to join, signed-in players also hear on their bell and by notification, and a guest can sign in on the pop-up and join in one go. A host screen that isn't signed in can sign in from the same panel without losing the room. People can join a game that has already started: arriving while the question is up, they play that round; arriving later, they sit the round out and play from the next question. The lobby shows a four-line How to play card on the host screen and on every phone.

### Big rooms

A room holds up to 120 players. The host lobby shows a QR code that opens the join form with the code filled in, phones get the top ten players plus themselves rather than the whole list, and a room's snapshots go out at most four times a second. A local run with 100 bots quoting and trading at once used about 3% of one core and 60 MB, with orders acknowledged in a few milliseconds, so the single shared-CPU Fly machine should cope. If you want a margin for a big meeting, give it more CPU for the evening and put it back afterwards:

```bash
flyctl scale vm shared-cpu-2x --memory 1024 --app almanac-game
```

```bash
flyctl scale vm shared-cpu-1x --memory 512 --app almanac-game
```

### Social

`/social` is where signed-in players find each other: a handle to be searched by, a friend code to share, friend requests both ways, friends ranked by prestige, people you've played with, and groups. A group has an owner, up to 150 members ranked by prestige, and a Play now button that opens a host screen only members can join and invites every member. The bell (top right on the main menu and Social) lists friend requests, group invites and game invites, and they can be answered from it. Any bio or group name can be reported; a report hides it from everyone but its owner straight away, and the accounts listed in the `ADMIN_EMAILS` secret review reports at `/admin/reports`.

`/admin/players` is the team's view of every signed-in account: level, XP, prestige, coins, games, wins, Best Quotes, trades and more, read live each time it opens, sortable and searchable, with a Download Excel button for the whole table. Admins see it, and so does any teammate an admin adds by email at the foot of the page; a teammate can look and download, but sees no emails or accuracy flags and can change nothing.

`/admin/overview` is the team's map of the project, open to the same people: what the running server is doing right now, a chart of how the pieces fit together, the plans and goals with what is in progress and next, every outside service and what it costs, what shipped when, and reference tables of every page, server module, database table and tool. Its plans come from `server/overview_data.json`, which `python tools/dashboard/refresh.py` rewrites; run it before a deploy.

### Groups

Starting a group costs 1,500 coins; disbanding doesn't return them. Start a group, on the Groups tab, opens one dialog for everything: the name, the bio, the shield (a drawing and colour, or a picture) and the price. A group's page has an Invite players panel: a link to copy or hand to your phone's share sheet, a QR code for people in the room, and, for the owner, friends and anyone by handle to invite directly. Whoever opens the link can join after signing in; the owner can replace the link at any time, which turns the old one off. Pasted into a messaging app, the link previews with the group's name, bio and picture.

The owner can customize the group: a bio of up to 160 characters, and a shield carrying either one of 26 drawings on one of 8 colours or an uploaded picture (PNG, JPEG or WebP, cropped to a square). Pictures are redrawn by the server before they're stored, so nothing but the image itself is kept. A group's name, bio and picture can each be reported; a reported one is hidden from everyone but the owner until it's reviewed at `/admin/reports`.

### Open table

`/open` (linked from the main menu) is a table that never closes: anyone can sit down at any time, a question takes under a minute, and you can leave whenever you like. When fewer than six people are there, house bots (marked BOT) fill the seats so there's always someone to trade with. They never know the answer: each question they share one guess that's usually 25 to 60% off, and they move their prices as people trade with them. Signed-in players earn coins and XP every round they quote or trade in, though points won off the bots pay only a quarter of the coins, and today's and this week's boards rank everyone's points. The table idles when nobody's there, so it never spends questions on an empty room.

### Live game

Every night at 9 PM Eastern the server runs a live game everyone signed in can join: five questions, quotes and trading as usual, with no host. `/live` (linked from the main menu) counts down to it; its lobby opens ten minutes early, the game starts on its own when the countdown ends (or is called off if fewer than two players came), and the page shows the last live game's results and the all-time live standings. Players confirmed as looking answers up are left off both. `LIVE_MODE=0` turns it off. To try it locally without waiting for 9 PM, run the server with `LIVE_DEV_START_SECONDS=90` (local only), which opens a lobby at startup that starts 90 seconds later.

### Accuracy flags

Anyone who keeps sealing tight quotes that hold the exact answer is probably looking answers up. After every saved game, each signed-in player with 20 or more quotes is checked against how often everyone else lands such a "bullseye"; a record that would almost never happen honestly is flagged. Flags are silent: the player isn't told and nothing changes for them. The accounts in `ADMIN_EMAILS` review them at `/admin/flags`, with the player's recent quotes and how long each took, and either clear the flag or confirm it. Nothing is punished automatically.

### Phone notifications

The bell's friend requests, group invites and game invites also reach phones and computers as notifications, even with Almanac closed. A player turns them on per device under "Notifications on this device" on their profile page (`/profile`). On an iPhone or iPad this works only once Almanac is on the Home Screen (Share, then Add to Home Screen, then open it from there; iOS 16.4 or later); the page says so. Signing out turns them off for that device.

It needs a VAPID key pair, kept as Fly secrets, never in the repo. Make one and set it (setting secrets restarts the machine, so not during a game):

```bash
.venv/Scripts/python -m server.push --keys
```

```bash
flyctl secrets set VAPID_PUBLIC_KEY=<public> VAPID_PRIVATE_KEY=<private> --app almanac-game
```

Without the keys the server runs as before and the notifications panel is hidden. Keep the same pair afterwards: a new pair silently cuts off every device that turned notifications on, and each would have to turn them on again.

### Drinks mode

A toggle in the host settings (the gear icon at the top right of the host screen), with a strength slider from Light to Savage. When it's on, each round's losses become drinks (a drink for every 100 ÷ strength points lost, at most 6 a round): every phone says "Drink 2" or "Safe" at the reveal, the host leaderboard gets a Drinks column, and the game draws its questions from the `spicy` category first. Spicy questions live in the same bank with `"category": "spicy"` and need the same verification before a game will serve them: `python -m server.questions.verify --limit 20 --model haiku` checks the unverified ones.

The app has no public IPv6 address on purpose, because IPv6 connections to Fly drop on some networks. If `flyctl` itself fails with `EOF` errors, deploy from a different network, such as a phone hotspot.
