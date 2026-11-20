# Almanac — Project Spec (AGENTS.md)

Working title: **Almanac** (rename before any public release; "Almanac" alone is a common word and may conflict with existing marks).

Owner: Ryan Corle. Spec written Oct 28, 2026.

## What this is

A multiplayer version of the "almanac game" played at trading firms: a numeric question is posed ("How many people visit the Mall of America each year?"), and players trade against each other on the answer by quoting bids and asks. Settlement happens when the true answer is revealed.

The problem this solves: played by hand, one person has to be the market maker and keep the ledger. This app replaces that person with an **order book**. Every player quotes, every player can trade, the engine matches and settles. Nobody is stuck running the market.

Modes, in build order:
1. **Local** — one host screen (laptop or TV) plus players' phones joining by room code, everyone in the same room. Jackbox model. This is the MVP.
2. **Live** — public rooms with strangers. Not until Local has real users. See Open Decisions.
3. **Drinks mode** — a toggle on top of scoring that turns a round's losses into drinks. Play money always.

## Non-goals (do not build these unless the milestone says so)

- Real money, purchasable currency, anything that could be cashed out. Coins are earned only by playing.
- Matchmaking, chat, native app wrappers. (Accounts came off this list on Nov 3, 2026; see M2.5.)
- Delta/diff protocols — full state snapshots only until M4
- Anti-cheat beyond short timers; looking up answers is a social rule, not a technical one
- Machine learning in the game itself (the offline question verifier is the one exception)

## Division of labor — read this first

**Codex builds the whole project to this spec, including `server/engine/orderbook.py`.** Ryan changed this on Nov 2, 2026 so the demo could be tested sooner; the engine was originally reserved for him to write by hand.

That covers the engine, server plumbing, state machine, client, question validator, and deployment, one milestone at a time. Ask before adding anything outside the current milestone.

## Tech stack (decided)

- **Server:** Python 3.12, FastAPI, native WebSockets (`websockets` via Starlette), uvicorn. Live game state in memory (dict of rooms).
- **Storage:** SQLite in one file (`server/db.py`, plain `sqlite3`, WAL), on a Fly volume at `/data` in production and `./data` locally. Holds accounts, sessions, and finished-game results, never live rooms. Chosen over the M4 Postgres plan because the app runs on one machine; move to Postgres only if that changes.
- **Accounts:** optional Sign in with Google. The browser gets a Google ID token, `POST /api/auth/google` verifies it with `google-auth`, and a random session token goes in an HttpOnly cookie. Guests play exactly as before.
- **Engine:** pure Python module, no I/O, no asyncio, deterministic.
- **Client:** React 18 + TypeScript + Vite. No UI framework; plain CSS modules. Phone-first layout, host screen is a separate route.
- **Deploy:** single Dockerfile, Fly.io, one instance (`fly deploy --ha=false`). Rooms die on restart; acceptable. The page is served with `Cache-Control: no-cache` and the content-hashed files under `/assets` as immutable (`server/app.py`); before Nov 4, 2026 browsers could keep a stale page after a deploy and run the old client against the new catalog.
- **Tests:** pytest for server/engine; Vitest only if client logic grows beyond rendering.

Why Python on the server: Ryan's working language is Python, so he can read and change the engine directly. A Node/TS server was considered and rejected for that reason alone.

## Repo layout

```
almanac/
  AGENTS.md
  README.md
  .env.example
  Dockerfile
  server/
    app.py              # FastAPI app, /ws endpoint, static client serving
    auth.py             # Google sign-in, session cookie, /api/me, /api/profile
    cosmetics.py        # avatar catalog: slots, items, bundles, coolness index, rarity, price
    achievements.py     # achievements: tiers, goals, rewards; checked at game save and purchase
    moderation.py       # the bio's length cap and word list
    images.py           # uploaded pictures (group icons): decoded and redrawn as a 256px WebP, never stored as sent
    shop.py             # /api/catalog, /api/locker, /api/shop/buy, /api/shop/buy-bundle, /api/avatar
    social.py           # M5: friends, blocks, groups, notifications, reports (rules and storage)
    social_api.py       # M5: their HTTP API under /api
    push.py             # M5: web push: subscriptions, the sender thread, /api/push
    anticheat.py        # M6: accuracy flags on the quote log, /api/admin/flags
    live.py             # M6: the nightly live game: scheduler, /api/live, the live tables
    endless.py          # M6: the endless table's page API (/api/open) and its daily and weekly boards
    db.py               # SQLite: users, sessions, games, results, coins, inventory
    rooms.py            # room registry, state machine, timers, snapshot builder
    room_codes.py       # word list for room codes
    protocol.py         # pydantic message types (client->server, server->client)
    engine/
      __init__.py
      models.py         # Order, Fill, Quote, Question, BookSnapshot (pydantic)
      orderbook.py      # matching engine
      scoring.py
    questions/
      questions.json
      validate.py       # schema + status check; CI fails on unverified questions
      verify.py         # offline Codex agent plus evidence gates
    tests/
      test_orderbook.py
      test_scoring.py
      test_rooms.py
  tools/
    dashboard/          # Ryan's dashboard: refresh.py builds its data, progress.json and services.json feed it, page/index.html is its page
  client/
    index.html
    src/
      main.tsx
      routes/Host.tsx     # big screen: book, tape, timer, scores
      routes/Menu.tsx     # the main menu at /: Social, Play (room code + name) and Customization, swiped between
      routes/Play.tsx     # phone: quote ticket, order ticket, position, mini-book
      routes/Profile.tsx  # lifetime stats, coins, game history, sign out
      routes/Shop.tsx     # marketplace: rarity-colored cards, bundles, buy, equip
      routes/Locker.tsx   # locker room: equip owned and free parts per slot
      routes/Academia.tsx # the trophy road: banners earned by level and prestige
      routes/Achievements.tsx # /profile/achievements: every tier, its requirement, reward, progress
      routes/GameLog.tsx  # /profile/games/:id: a past game's table, rounds and your trades
      routes/GameHistory.tsx # /profile/games: every game you've finished, paged, by month
      avatar/Avatar.tsx   # draws an avatar config as SVG; silhouette for guests
      avatar/parts.tsx    # the art for every still catalog item, keyed by id
      avatar/effects.tsx  # the animated items: effects slot and the mythical outfit
      lib/auth.ts         # /api/me, /api/config, Google button loader, sign out
      lib/menu.ts         # the main menu's three screens, and the link back to each
      lib/pager.ts        # screens you swipe between: the menu's three, and Social's two tabs
      components/MenuBar.tsx # Social / Play / Customization at the foot of every page but a table
      lib/catalog.ts      # /api/catalog, fetched once and shared
      lib/shop.ts         # /api/locker, buy, save avatar
      components/Book.tsx Tape.tsx OrderTicket.tsx QuoteTicket.tsx Timer.tsx Scores.tsx
      lib/ws.ts           # connect, reconnect with stored token, snapshot store
      routes/Social.tsx   # the menu's Social screen: the leaderboard card, you, then Groups and Friends as tabs
      routes/Leaderboard.tsx components/Leaderboard.tsx  # the global boards: /leaderboard, and the podium card on Social
      routes/Group.tsx PublicProfile.tsx AdminReports.tsx  # M5 pages
      components/CreateGroup.tsx ProfileSettings.tsx  # the start-a-group dialog; the handle and notifications panels on /profile
      components/Bell.tsx TableSocial.tsx  # M5: the notification bell; friend and group buttons at the table
      components/GroupIcon.tsx             # a group's icon: its drawing and colour, or its uploaded picture
      lib/social.ts lib/push.ts            # M5: the social API; web push on this device
    public/
      sw.js               # service worker: shows web pushes, opens their page; no caching
      manifest.webmanifest icon-192.png icon-512.png apple-touch-icon.png  # Home Screen install (iPhone push needs it)
      lib/types.ts        # mirrors server/protocol.py by hand; keep in sync
```

## Game rules

### Round structure (state machine)

```
LOBBY -> QUESTION -> QUOTING -> TRADING -> REVEAL -> SCORES -> (next QUESTION | GAME_OVER)
```

| Phase | Default timer | What happens |
|---|---|---|
| LOBBY | none | Host creates room, players join, host starts |
| QUESTION | 5s | Question text + unit shown on all screens (10s until Nov 3, 2026; cut to cause some panic) |
| QUOTING | 20s | Each player submits a sealed two-sided quote (bid, ask), 1 lot per side (45s until Nov 3, 2026) |
| TRADING | 45s | Book opens with all quotes resting; players post, cancel, hit, lift. With 15s left, a hint appears |
| REVEAL | 10s | True answer + source shown; fills settled; round points computed |
| SCORES | 10s | Round and cumulative scores |

A case question (see Question bank) reads and trades on longer timers of its own: QUESTION 15s and TRADING 75s by default (`timers.case_question`, `timers.case_trading`; 25s and 90s on the First-timers pace), both in the settings drawer. Quoting, reveal and scores are the same for every question.

Timers run on the server. Server sends `timer_ends_at` (epoch ms); clients render the countdown. Server auto-advances on expiry. Host can advance early at any phase. During a round the host screen has three equal buttons, End game in the middle: Skip ahead (the next phase), End game, and Skip question (added Nov 4, 2026: `Room.skip_round` runs every phase left in the question without waiting, so crossing quotes still fill and settle, and lands on that round's SCORES; greyed on SCORES).

Late join: a player may join in any phase. Arriving while the question is up, they play that round; arriving later, they sit the round out and play from the next question. Game length: default 7 rounds, configurable 3–15. Players: 2–120 (raised from 12 on Nov 3, 2026 for a club meeting of up to 100; see the big-room notes under Protocol). Host is a screen, not a player; a host-also-plays option is an Open Decision.

### Quoting

- Quote = `bid`, `ask`, both in the question's unit, both multiples of `tick`, `0 < bid < ask`.
- Size is fixed at 1 lot per side in M2. Configurable 1–3 in M3.
- Quoting is optional. If the timer expires with no quote, the player simply has nothing resting at open.
- Incentive to quote tight: **Best Quote bonus** (+25 points) to the player whose quote contains the true answer with the smallest `ask / bid` ratio. Tie goes to the earlier submission.
- UI warns (does not block) if `ask / bid > 10`.

### Opening the book

At QUOTING → TRADING:
1. Convert every sealed quote into two limit orders (BUY at bid, SELL at ask, size 1).
2. Shuffle all orders with a seeded RNG (`seed = f"{room_code}:{round_no}"`).
3. Submit them through the engine in shuffled order. Crossing quotes fill against each other at the resting price. Those fills count.

No separate call-auction code. The same engine handles the open.

### Trading

- **Limit order:** side, price, size (1–5 lots). Rests if not crossing; otherwise matches at the resting order's price, price-time priority, remainder rests.
- **Hit / Lift:** UI shortcut that submits a marketable limit at the displayed price. Same engine path.
- **Cancel:** own resting orders only.
- **Self-trade:** an order that would cross any of your own resting orders is rejected whole. UI prevents it.
- **Position limit `L`** (default 5 lots): with `exposure_long = position + Σ(resting buy sizes)` and `exposure_short = position − Σ(resting sell sizes)`, a new BUY of size `s` is rejected if `exposure_long + s > L`; a new SELL if `exposure_short − s < −L`. This stops the "grains of sand" blowup.
- Prices must be `> 0` and multiples of `tick`.
- Book display: top 5 levels per side, aggregated size, own orders highlighted. Tape shows price, size, buyer name, seller name (`show_names: true` by default; Live mode will set it false).
- Phone trading screen (Ryan's sketch, Nov 3, 2026; `client/src/components/Wheels.tsx`): two wheels drawn as large arcs, asks on the right rim above the spread and bids on the left rim below it, so together they read as one price ladder. Each price sits in a pill on the rim with a pillar growing toward the screen edge, one length per lot, the lot count at its tip. MID and LAST boxes sit in the gap between the wheels. Below: price field, size 1–5, Buy/Sell, Lift/Hit. Above: the Almanac wordmark, an oval timer that counts down to the hint and then to the close, and a mini leaderboard (top 3 plus you) with bars proportional to score. Palette: black background, white text, blue details; green and red only for buy and sell. The phone shows the last trade price, not the named tape; the host screen keeps the tape.

### Hint

With `hint_seconds_left` (default 15) left in TRADING, every screen shows a range that contains the answer: "The answer is between 620 and 1,300 metres." The server builds it from the answer: a range 2x wide, with the answer placed at a random point between 20% and 80% of the way across on a log scale, and both ends rounded outward to two significant figures. It exists to make players reprice late and trade more. The hint stays on screen through REVEAL; `hint_seconds_left: 0` turns it off. Added Nov 2, 2026 at Ryan's request.

A case question's hint is not a range. It is the question's own `hint_text`: one sentence giving a related, sourced figure to reason from ("About 800 million are grown each day, but animal feed and spoilage mean far fewer are eaten by people."). Because it has to be read and thought about, it arrives at the same point of the longer round rather than the same number of seconds before the close: `hint_seconds_left × case_trading / trading`, so 25s before the close at the standard pace, and never later than a plain hint would (`Room._hint_lead`). Added Nov 9, 2026.

### Scoring (settlement)

True answer `T > 0`. For each fill at price `p` with size `n`:

```
buyer_points  = n * clamp(100 * ln(T / p), -200, +200)
seller_points = -buyer_points
```

Log scoring is symmetric (buying at half the truth and buying at double are ±69) and it makes a question in the millions score like a question in the tens. Zero-sum by construction. The clamp caps a single fill at about a 7.4× mispricing.

`scoring: "log" | "linear"` is a room config flag; `linear` = `n * (T - p)` for questions where everyone understands the raw unit. Default `log`.

Round points = Σ fill points + Best Quote bonus. Game score = cumulative.

Case rounds pay more (Ryan, Nov 10, 2026): a game's case questions, in the order they're played, multiply every fill (clamp included) and the Best Quote bonus by an even rise from 1.5 to 2.5, to a tenth (three cases: 1.5, 2.0, 2.5; one alone: 2.0; `round_multipliers` in `rooms.py`, the `multiplier` argument in `scoring.py`). Standard rounds are ×1. Fills stay zero-sum. The multiplier is on `question.multiplier` in the snapshot; the host and phone label a case "CASE · ×2.5 POINTS", and drinks, coins and achievements follow the multiplied points.

### Drinks mode (built Nov 3, 2026, ahead of M4)

Off by default. The host turns it on in the settings drawer (gear icon, top right of the host screen, any phase) and sets a strength from 1 to 5 with a slider (`config.drinks`, `config.drink_strength`, both changed with `host_configure`). At settlement each player's losses become drinks, computed by the server (`drinks_for` in `rooms.py`): `drinks = min(6, floor(max(0, -round_points) × strength / 100))`, so strength 1 is a drink per 100 points lost and strength 5 a drink per 20. Every `PlayerView` carries `drinks` (this round, null until settled) and `drinks_total`. The phone tells each player "Drink N" (or "Safe") at the reveal and the scores, the game-over screen gives the game total, and the host leaderboard gets a Drinks column. Winners never drink; scoring itself does not change. Drinks mode also redraws the game's questions from the `spicy` category: cruder, boozier questions (condoms at the Olympics, marijuana by the ton) that a normal game never draws; all the servable spicy ones come first and tame questions pad the rest. Spicy questions follow the same verification rules as the others.

## Engine contract (`server/engine/orderbook.py`)

This is what the M0 tests assert.

```python
class OrderBook:
    def __init__(self, tick: Decimal, max_position: int): ...
    def submit(self, order: Order) -> list[Fill]
        # raises SelfTradeError, PositionLimitError, InvalidPriceError
    def cancel(self, order_id: str, player_id: str) -> None
        # raises NotFoundError, NotOwnerError
    def snapshot(self, depth: int = 5) -> BookSnapshot
    def position(self, player_id: str) -> int
    def resting_orders(self, player_id: str) -> list[Order]
```

Models (`engine/models.py`, pydantic, Codex writes):
- `Order(id, player_id, side: BUY|SELL, price: Decimal, size: int, remaining: int, seq: int)`
- `Fill(price, size, buyer_id, seller_id, buy_order_id, sell_order_id, seq)`
- `Quote(player_id, bid, ask, submitted_at)`
- `Question(id, text, unit, answer, tick, source_url, source_note, category, difficulty, as_of, status)`
- `BookSnapshot(bids: list[Level], asks: list[Level])`, `Level(price, size)`

Invariants the tests check:
- Bids sorted price desc then seq asc; asks price asc then seq asc.
- Partial fills leave the correct remainder on both sides.
- A marketable order walks multiple levels.
- Self-trade rejection happens before any fill.
- Position limit counts resting exposure, not just filled position.
- Cancel removes exactly one order and only for its owner.
- `snapshot(depth)` aggregates size per price level and truncates.
- Determinism: same sequence of calls → same fills.

## Protocol (`server/protocol.py`, mirrored in `client/src/lib/types.ts`)

Client → server:
```
host_create {config}
host_resume {room_code, token}
host_configure {recall_on_start?, drinks?, drink_strength?, case_mode?, ...}   # settings; a field left out keeps its value; case_mode "extra" | "default" | "off", lobby only
host_start | host_advance | host_end
host_skip_round                     # Skip question: run the rest of this question at once (quotes open, fills settle) and land on its SCORES
join {room_code, name, token?}
submit_quote {bid, ask}
place_order {side, price, size}
cancel_order {order_id}
```

Server → client, on every state change, **full snapshot**:
```
state {
  room_code, phase, round_no, rounds_total, timer_ends_at, server_now,
  phase_seconds,                           # this phase's full length; a case question's read and trading run longer
  hint_at,                                 # epoch ms the hint is due, only while one is still to come
  question: {text, unit, tick, kind, context, multiplier} | null,   # kind "standard" | "case"; context is a case's setup; multiplier 1, or 1.5-2.5 on a case; answer/source only present in REVEAL+
  hint: {low, high, text} | null,          # from the hint time in TRADING to round end; a range (low, high) or, for a case, text
  book, tape (last 20),
  player_count,                            # everyone seated; phones get a trimmed players list
  you: {player_id, position, resting_orders, quote, round_points, total_points, coins_awarded, fills} | null,  # null for the host; coins_awarded set at GAME_OVER for signed-in players; fills = your own fills this round [{seq, side, price, size, counterparty}] from your side, which the phone lists with per-fill points once the answer is out
  players: [{id, name, connected, quoted, signed_in, avatar, total_points, round_points?, drinks?, drinks_total}],  # avatar: slot -> item id, null for guests; drinks only in drinks mode
  best_quote: {name, bid, ask} | null,
  config
}
hosted {room_code, token}
joined {room_code, player_id, token}
error {code, message}
```

`server_now` lets clients correct their countdown for clock skew. `quoted` shows who has quoted, never what.

Full snapshots are simpler and more robust than diffs; no diff protocol before M4. Two things make them cheap enough for a 100-player room (Nov 3, 2026): a room's broadcasts are coalesced (the first change goes out at once, anything else in the next 250ms goes out together, each snapshot built once; `Hub.publish_interval`, 0 in tests), and a phone's `players` list is only the top ten plus itself (`PLAYERS_SHOWN`, `Room.view_for`) with `player_count` giving the real total, while the host screen gets everyone. A slow phone can't hold a broadcast up for more than a second. The host lobby shows a QR code for `/?room=CODE`, and the host leaderboard shows 20 rows plus "and N more". Measured locally with 100 bots (`%TEMP%\almcheck\swarm.py`, Nov 3, 2026): orders acknowledged in 1 ms median, 2 ms p95, 300 ms worst (the coalescing window); about 45 snapshots and 150 KB per phone per round; the server at 3% of one core and 57 MB through the quoting and trading bursts.

Reconnect: on first join the server returns a `token`; client stores it in localStorage and sends it on reconnect. A dropped socket marks the player `connected: false` (greyed on host screen), never removes them. The host screen gets its own token and reclaims the room with `host_resume`. When a seat or room is reclaimed by a new socket, the old one gets `error {code: "replaced"}` and is closed; it stops reconnecting and tells the player, so two tabs on one device can't trade the seat every second.

Room codes: a four-letter word or acronym from `server/room_codes.py` (markets, math, science, letters), such as `VWAP` or `TOME`. If every word is in use, 4 random uppercase letters excluding I and O. Names ≤ 16 chars, trimmed, unique per room.

## Question bank (`server/questions/questions.json`)

```json
{
  "id": "moa-annual-visitors",
  "text": "How many people visit the Mall of America each year?",
  "unit": "million visitors",
  "answer": null,
  "tick": 0.5,
  "source_url": "",
  "source_note": "",
  "category": "places",
  "difficulty": 2,
  "as_of": "",
  "status": "unverified"
}
```

Rules:
- `status` is one of `unverified`, `needs_review`, `disputed`, `agent_verified`, `verified`. `verified` means Ryan opened `source_url` and confirmed `answer` himself; Codex and the agent never set it.
- `agent_verified` means `server/questions/verify.py` passed its evidence gates. Ryan approved this on Nov 2, 2026 so the bank can grow past what he can check by hand, and later the same day relaxed the bar: a good estimate is enough. The agent researches each question blind, without seeing the stored answer. Python code, not the model, then requires one confirmed source (a quote that appears verbatim on the page text the API returned, or that Python fetched itself, and contains the stated number), or a calculation Python reruns itself with at least one confirmed input. Every estimate must be within 10% of the others and of the stored answer, with no ambiguity or instability flags. Sources that fail to confirm are recorded as notes and don't block approval. A conflict over the number, reported by any source, becomes `disputed`, and no agent run touches it again until Ryan resolves it; otherwise a rerun could pass by picking sources that happen to agree. Anything else becomes `needs_review`. The agent never changes an `answer`.
- Games serve `verified` and `agent_verified`, and `python -m server.questions.validate --require N` fails under N servable. `ALLOW_UNVERIFIED_QUESTIONS=1` lifts this for local playtests only and is never set on a deployed server. Ryan spot-checks agent results with `python -m server.questions.verify --audit N`.
- `answer` strictly positive. No questions whose answer can be 0 or negative (temperatures, net changes).
- Scale the unit so answers land roughly between 1 and 10,000 (use "million visitors," not "visitors").
- Prefer answers that are stable for a year or more. Record `as_of`.
- Unambiguous wording: name the year, the source's definition, the geography.
- Target: 30 verified for M2, 50+ for M3. Answers need to be right to within about 10%, not exact: log scoring makes a 10% miss cost about 10 points per lot.
- Style (Ryan, Nov 2, 2026): arbitrary and a little ridiculous beats geography. The best questions are about things people know but can't really guess: Mall of America visitors, Ben & Jerry's, Pac-Man's perfect score, a $1-bill stack the height of Everest. Avoid answers that change monthly (Instagram post counts). A game draws at most one `places` question (`CATEGORY_CAPS` in `rooms.py`), unless the bank runs short.
- `category: "spicy"` marks drinks-mode questions (sex, drugs, booze; the IU-specific ones Ryan wants when a figure can be sourced). A normal game never draws them; drinks mode draws them first. Same statuses and verification as everything else.
- Case questions (`kind: "case"`, added Nov 9, 2026 for the fintech club; every other question is `kind: "standard"`). Aimed at 20–25 year-olds: AI, technology, finance and the business stories people argue about. A case has a `context` of one to three sentences that sets up the story and gives a real figure ("Facebook bought Instagram in 2012 for $1 billion, when the app had about 30 million users."), then the question, and a `hint_text` that gives a different related figure. Its categories are `ai`, `tech`, `finance` and `business`. The host's case-question switch (`config.case_mode`, settings drawer, lobby only; Nov 10, 2026) decides where cases go: `default` (the default) makes the last three rounds case questions and the rest standard, `extra` draws from everything so cases can land in any round, and `off` leaves them out. Category ticks still steer which cases and which standard questions are drawn. In every mode the game's cases are played in reading order, shortest first, so the longest is last and pays most: `reading_seconds` in `rooms.py` is the one measure for all of them, words of setup and question at 3.5 a second plus a second per figure in the setup (the bank runs from about 12s to 24s, so the longest outlast the 15s read and are finished during quoting). The answer must be pinned to a named date, year or event, because current events drift. The setup and the hint are factual claims on a screen, so each carries its own source and the sentence that states its figure (`context_source_url`, `context_source_quote`, `hint_source_url`, `hint_source_quote`); `validate.py` fails a case missing any of the six fields, and any other question that has one. The verifier researches the answer as usual (the agent sees the setup, never the hint or the stored quotes, and is asked to open both pages so Python has their text), and Python adds two gates per claim (`check_supporting` in `verify.py`): the stored quote must be on its page and state a number the text uses, and neither the setup nor the hint may state the answer. A failed gate means `needs_review`.
- The bank's size: 432 questions on Nov 12, 2026, 365 of them servable (on the live site since that day's deploy). A batch of 245 went in unverified on Nov 11 so the open table could run without repeats; the verifier run the same day (Haiku, $5.89) passed 203, sent 10 to `needs_review`, and left 32 unverified when the connection dropped mid-run. Run without `ANTHROPIC_API_KEY`, the verifier now says so and stops before the first question; before, every question failed one by one and an empty run was logged.
- Calculated questions (`category: "math"`) pass when the agent's arithmetic, rerun by Python, matches the stored answer and at least one input is confirmed from a source. Their `source_note` shows the arithmetic too.

## Main menu (built and deployed Nov 11, 2026)

`/` is the main menu (`client/src/routes/Menu.tsx`; it replaced the join page): the three main pages Ryan set out on Nov 4, 2026, Social, Play and Customization, as three screens swiped between, Play in the middle and the one it opens on. Between them they link every other page.

- **Play:** the room code and name form (a room link or QR code, `/?room=CODE`, lands here with the code filled in, and a join error shows here), then rows for the open table (how many people are at it), the nightly live game (a countdown, or the lobby or game when one is on) and Host a game. A guest's sign-in box sits above the form; it is the menu's only one.
- **Social:** a page in itself since Nov 11, 2026 (Ryan's sketch, deployed the same day; `client/src/routes/Social.tsx`), which replaced the separate `/social` page (that address now opens this screen). At the top is the global leaderboard (added Nov 12, 2026; see below), then you: avatar, name card, a Profile button, your level and handle (and, for an admin, the review links). Under that are two tabs, Groups and Friends, that slide like the menu's own screens (the same `usePager`, in `lib/pager.ts`), the tab in view with its icon lit. The screen scrolls as one; the tabs stick to the top of it once you scroll past them, and the scroller is kept as tall as the list in view (`useFitHeight`), so a short list isn't followed by a taller neighbour's blank space. Groups lists invites waiting on you, then each of your groups behind its shield with its combined prestige and size, then Start a group. Friends has requests, the friends leaderboard, and the ways to add someone (handle search, a friend code, your own code, people you've played with). Swiping carries on past the last tab: Groups, Friends, then Play. `/#social` is Groups and `/#friends` is Friends. Everything about you alone moved to `/profile`: the handle, the notifications switch, signing out, and a button to view your public profile.
- **Customization:** your avatar and name card, coins and the level bar, then Locker room, Marketplace, Academia and Achievements.

A guest sees what each side screen is for and a Sign in button that brings Play's sign-in box into view. Signed in, the top bar carries the bell and the avatar (to `/profile`). A guest's Social screen is a heading and the sign-in prompt, with no tabs.

**The global leaderboard** (Ryan, Nov 12, 2026, deployed the same day; `social.leaderboard`, `GET /api/leaderboard`, `client/src/components/Leaderboard.tsx`): two boards, groups ranked by their members' combined prestige and players ranked by their own. Only prestige above zero is ranked, equal prestige shares a place (900, 500, 500, 200 is 1, 2, 2, 4), and anyone with a confirmed accuracy flag is left off, as on the live tables. A card at the top of the Social screen shows the top three of each as a podium (first in the middle and a step up), switched by a Groups | Players tab that slides like the others; under it is where you stand ("You're #4 of 120", or your best group's place) and See all, which opens `/leaderboard`: the top fifty of each, your own rows marked, your place given even when it's below the fifty (`/leaderboard#players` opens on Players). Avatars on both hold still (`.calm`). Because every group with prestige is listed, any signed-in player can now find and open any such group's page; joining still takes an invite or the link. A reported name or picture stays hidden on the board as everywhere else.

**The bar at the foot of every page** (`client/src/components/MenuBar.tsx`, Nov 11, 2026): Social, Play and Customization are always one tap away. On the menu its marker follows the swipe; on every other page (`main.tsx` wraps each one) it is pinned to the foot, the tab for the page's own section lit (profile, players, groups and review pages under Social; the open table and live game under Play; locker, marketplace, Academia and achievements under Customization) and each tab a link back to that screen. The tab you're on has its icon lit. The one place it is left out is a table: the phone's game view (`/play`) and the host screen (`/host`), so a stray tap can't take anyone out of a round. On a wide window the menu itself shows its three screens side by side and needs no bar; every other page keeps it.

How it swipes: the three screens sit in one sideways scroller with CSS scroll snap (`usePager` in `lib/pager.ts`), so the swipe is the browser's own; each screen scrolls downward by itself and the page never scrolls. The tab bar at the bottom (Social, Play, Customization) has a marker that moves with the swipe (`--at`); tapping a tab, or the arrow keys on it, moves a screen, and a dot on Social means a request or invite is waiting. The address remembers the screen (`/#social`, `/#customization`, written with `replaceState`), so Back from a page returns to the screen it was opened from. From 1024px wide the three screens sit side by side as columns and nothing swipes. Every other page's ALMANAC wordmark is a link back to the screen that page belongs to (`Brand home=...`, `lib/menu.ts`); at a table (the phone's game view, the host screen) the wordmark stays plain text, so a stray tap can't leave a round.

## Look and feel

Ryan's direction (Nov 4, 2026): Almanac should feel like a thoughtfully designed educational game, a notch above Kahoot, at home in a business, consulting or information-systems classroom and at a kitchen table. Black, white and blue; green and red only for buy and sell; gold only as a legendary accent. Finance is the mechanic, not the costume: names and art are witty rather than Wall Street (the banners are jokes about estimating, not tickers and bells). Animation is limited to where it isn't a distraction: avatar effects and banner motion play only where a player dresses their avatar (locker, marketplace, profile, trophy road, the main menu); on the host screen and the phone's game view every avatar and banner holds still (`.calm` on those routes in `styles.module.css` freezes each effect in a designed resting pose rather than mid-frame). Loud items get cut rather than toned: the Phoenix wings were retired on Nov 4, 2026, and anyone who had bought them is refunded at startup (`RETIRED_ITEMS` in `server/db.py`); when an item is renamed after it has been sold, `RENAMED_ITEMS` there moves inventories and worn avatars to the new id, and `stored_avatar` in `cosmetics.py` drops any id the catalog no longer knows, so a catalog change never strands a player's look.

## Engineering standards

- Engine is pure: no I/O, no clocks, no randomness inside `orderbook.py`. Shuffling happens in `rooms.py` with a seeded RNG.
- Every state transition and every fill is logged with timestamp, room code, round number.
- No hardcoded ports, hosts, or origins. `.env.example` lists `PORT`, `ALLOWED_ORIGINS`, `LOG_LEVEL`, `DEFAULT_ROUNDS`, `POSITION_LIMIT`, `ALLOW_UNVERIFIED_QUESTIONS`, `GOOGLE_CLIENT_ID`, `DATABASE_PATH`, `ALLOW_DEV_LOGIN`, `VAPID_PUBLIC_KEY`, `VAPID_PRIVATE_KEY`, `VAPID_SUBJECT`. `ADMIN_EMAILS` (who reviews reports) and the VAPID private key are Fly secrets.
- `ALLOW_DEV_LOGIN=1` enables `POST /api/auth/dev`, a fake sign-in for local testing without Google. Never set it on a deployed server.
- Pydantic validates every inbound message; malformed messages get an `error` reply, never a crash.
- Dev loop: `uvicorn server.app:app --reload` and `npm run dev` in `client/`. Document both in README.
- Tests run green before a milestone is marked done. No milestone is "done" with a TODO in it.
- No secrets in the repo. No third-party services in the running game in M0–M3. From M5 the server talks to one kind: the browsers' own push services (Google's, Mozilla's, Apple's), reached only from push.py's background thread. The question verifier is an offline tool that calls the Codex API with Ryan's key from his machine; the deployed server never calls it.

## Milestones

**M0 — Engine contract.** Codex: `models.py`, `orderbook.py`, `test_orderbook.py`, `test_scoring.py`, `scoring.py`. Done when `pytest` is green.

**M1 — Hot-seat demo (one evening).** Single page, one hardcoded question, a "who's acting" selector, order ticket, book, tape, reveal and settle. No server; engine runs via a tiny local FastAPI with one in-memory room. This is the harness to find out if the game is fun without a human market maker.

**M2 — Rooms (one weekend).** Host route + Join + Play over WebSockets. Full state machine with timers, 7 rounds, sealed quotes, shuffled open, Best Quote bonus, scores, reconnect by token. 30 verified questions. Deployed to Fly.io with a shareable URL.

**M2.5 — Accounts and saved progress.** Started Nov 3, 2026 at Ryan's request, ahead of M3. Optional Sign in with Google on the main menu's Play screen (the join page until Nov 11, 2026), or from the phone lobby for a guest already seated (added Nov 3, 2026): the client reconnects its socket so the server sees the new session, and the seat keeps its name and takes the account unless that account already has a seat in the room. Guests are unchanged. A signed-in player's seat links to their account, the account reclaims its seat from any device, and a reconnecting seat picks up the account's current avatar. At GAME_OVER the server saves each signed-in player's result (points, rank, Best Quotes, trades) and pays coins: 1 per point from rounds finished positive, 20 for finishing, 50 for winning, 10 per Best Quote (`server/db.py`, easy to retune). `/profile` shows lifetime stats, coins, and recent games. The game-over screen tells signed-in players what was saved. Coins never touch real money.

**M2.6 — Avatars and marketplace.** Built Nov 3, 2026 at Ryan's request, extended the same day. Every signed-in player has a Bitmoji-style avatar, drawn as SVG from ten slots (skin, hair, hair color, eyes, expression, outfit, headwear, eyewear, earrings, effects) and shown beside their name wherever a name appears: lobby and quote chips, the tape, leaderboards, the phone mini-board, the profile. Guests show a blue silhouette. The catalog is `server/cosmetics.py` (93 items, 67 for sale, 6 bundles); the art is `client/src/avatar/parts.tsx` for still items and `effects.tsx` for animated ones, keyed by item id, and a test checks every item is drawn. Prices are never set by hand: each item has three 1–5 scores (coverage: how much of the avatar it changes; attention: how much it draws the eye; novelty: how unusual it is) and a 0–5 motion score (how much it moves), `index = 0.40·coverage + 0.35·attention + 0.25·novelty`, `price = 20·index²·(1 + 0.5·motion)` rounded to 5 coins, and rarity by price floor (rare from 100, epic from 210, legendary from 360, mythical from 1500). Equal scores mean equal prices; motion only ever raises a price. Rarity colors: common blue, rare orange, epic purple, legendary gold; mythical cards and tiles carry an animated blue-purple neon outline, and every mythical item moves (Phoenix wings, Void aura, Galaxy armour, each 1750). Effects (sparkles, occasional lightning strikes, money rain, fire that burns on the head, the mythical auras) are CSS keyframes inside the avatar's SVG, so they play wherever the avatar appears, including leaderboard rows and name chips. Bundles (knight, business, site crew, rock star, royalty, pirate) sell themed sets at 80% of the price of the items the buyer doesn't own yet, in one transaction. New accounts start with 750 coins (`WELCOME_COINS`; 350 until Nov 4, 2026). Free options (all skins and eye colors, every everyday hair style and four hair colors, three expressions, three tees) are always available. Hair was redrawn on Nov 4, 2026 to look like the real cuts: clean silhouettes with proper hairlines, detailed only with a few wavy lines in translucent black that follow the way the hair falls (Ryan cut the texture pass of curl loops, stubble dots and plait marks as messy); locs are thick wavy ropes, braids slimmer straight ones ending in a bead, each with a thin dark edge. Five styles were added; the twelve everyday cuts are free (Short, Buzz cut, Side part, Messy, Curly, Coils, Wavy, Long, Bob, Ponytail, Top knot, Bald) and only the showpieces cost coins (Spiky, Pompadour, Mullet, Afro, Box braids, Dreads, Mohawk). Anyone who had paid for a style that became free is refunded at startup (`_refund_retired` in `server/db.py` refunds any inventory row whose item is now free or retired). `/shop` sells items and bundles for coins and `/locker` equips owned and free items (its preview card shows exactly what other players see: the avatar and the name card; as the page scrolls the card collapses smoothly into a slim row pinned to the top, its top sliding under the screen edge while the avatar and name glide into place, so it never changes height and leaves no gap, and every change shows live, on the page and in the phone's Locker view); both need a sign-in, and the server validates every equip against the inventory. Purchases are one transaction: coins and inventory change together or not at all. The phone has Game, Locker and Shop views in every phase (added Nov 3, 2026): the header with the timer and mini leaderboard stays, the socket stays open, and the same locker and marketplace bodies render below, so a player can customize or buy while waiting between games or sit out a round; guests see the sign-in box there instead. A saved look reconnects the socket so every screen shows it. The host setting `recall_on_start` (settings drawer; default on) sends every phone back to the Game view when the game starts.

Roadmap from Ryan's brainstorm, agreed Nov 3, 2026. The game stays the product; social features serve it, so identity comes before the social graph, and the modes that need a crowd come last. Accounts stay optional for playing and are required for anything social.

**M3 — Host tools (before the club meeting).** Built Nov 3, 2026: categories, max players, bots (`BOT_NOISE`/`BOT_SPREAD`/`BOT_TRADES` in `rooms.py`, run as asyncio tasks by `Hub._run_bots`), the demo run, play again (`Room.restart`), the how-to card, and the quote log (`quote_log` table, `QuoteRecord`). Rounds, every phase timer, the hint lead and the position limit followed on Nov 4, 2026, with two paces as one-click presets (Standard: 7 rounds, 5/20/45/10/10, hint 15; First-timers: 5 rounds, 10/40/60/15/15, hint 20); rounds change only in the lobby, the rest from the next phase. Late join followed the same day: anyone can join mid-game; arriving during QUESTION plays that round, arriving once quoting has begun sits the round out (`Player.plays_from`, `You.sitting_out`, actions refused with `sitting_out`) and plays from the next question. Still open: quote sizes, host-disconnect pause, 50+ verified questions (a batch of 63 tame questions went in unverified on Nov 4, 2026 for Ryan to run the verifier on). Everything lives in the host settings drawer (`client/src/components/HostSettings.tsx`, gear icon, any phase). Question categories (checkboxes over the servable bank; drinks mode's spicy draw is one more category rule). Max players (2–120; the host layout reads it). Bots: "add N bots" with a difficulty; a bot's skill is how tightly it quotes around the true answer (log-normal noise scaled by level) and how often it trades; bots are marked as bots, never earn coins, never win Best Quote. A demo run: fill the room with bots and play while the host narrates (later a scripted host that skips ahead on a schedule). Play again from game over: same room, same players, new questions. A how-to card on the phone lobby and the host lobby. Quote-accuracy telemetry starts here: per signed-in player per round, how far the quote midpoint and fills sat from the answer on the log scale, stored with the game; it is the raw material for M6's anti-cheat and costs nothing now. Still from the old M3: 50+ verified questions, quote sizes 1–3, rounds and timers in the drawer, late join mid-round sits out until the next QUESTION, host disconnect pauses timers.

**M4 — Identity and progression.** Coins stay the spending currency. XP → level for playing at all; prestige for winning and Best Quotes (the number people compare); one formula each, retunable like coin payouts. Built Nov 4, 2026 (`server/db.py`): XP per game = 50 + 5 per round + 2 per trade + 15 per Best Quote; prestige = 100 for a win, 30 for second or third, 20 per Best Quote; level n needs 100·(n−1)² XP (level 2 at 100, 3 at 400, 4 at 900). Paid at game save alongside coins (`Award`), stored per game on `results` and summed on `users`; the game-over phone line shows them and any level-up; `PlayerView.level`/`prestige` carry each signed-in player's standing at the time they sat down. Everywhere a name appears with its banner (leaderboards, the profile, the locker, banner previews) it is one component, `NameCard.tsx`; the lobby and quotes-in chips on the host and the phone stay plain pills with avatar and name, no banner (Ryan: a room of banners is too busy there). The name card is the name left-aligned on the banner with a small four-point star and the prestige number, the level never shown, every banner the same fixed size (Ryan, Nov 4, 2026). On leaderboards the name cell is a size container and the card scales down as a whole to fit it instead of being squeezed (the host's round-end screen puts a narrower leaderboard beside the trades), plain names are inset to start exactly where a banner's name starts, and the host's leaderboard scales the card up for the TV but leaves prestige off; `/profile` shows the level with an XP bar to the next one. Banners (built Nov 4, 2026, redrawn several times the same day at Ryan's request, last from his hand-drawn sketches): a `banner` slot drawn as CSS behind the name on leaderboards, chips and the profile (`client/src/components/Banner.tsx`, one class per id in `styles.module.css`). The goal is to highlight the name, not compete with it: the name sits on the left of a plain field, and one quiet motif from the sketches sits at the right edge or under the name (an underline, a rule ending in a star, nested corner arcs, a sash, two stripes, a wave across the top, a drafting set square, a mortarboard). Fields are paper white (navy ink), black, navy, forest green, deep purple and royal blue, with mint, lavender and sky accents; every horizontal rule is level and 1px; motifs are background layers so they always sit under the text, and the only motion is a slow light pass on the rarer ones, outside `.calm` routes. The names are the game's own jokes about estimating. Six are for sale and priced by the index like anything else (Ballpark 60, Back of the Envelope 150, Rule of Thumb 225, Educated Guess 390, Order of Magnitude 625, Fermi 1750, the last three animated); the rest are earned and can't be bought: `Item.unlock` puts them in **Academia** (the trophy road; renamed Nov 4, 2026) at a level (Beginner's Luck 2, Usual Suspect 4, Know-It-All 7, Walking Almanac 10, Oracle 15) or at a prestige count (Close Enough 150, Spot On 500, Dead Reckoning 1200, Crystal Ball 2500), and `Item.source` reserves Podium and Prime Time for tournament and live-game winners once M6 exists. Earned items have `tier` instead of a price. `unlocked_for(level, prestige)` is computed, never stored: `/api/locker` returns it next to `owned`, `PUT /api/avatar` treats both as wearable, `/api/shop/buy` refuses earned items, and `/api/academia` feeds the `/academia` page (levels track, prestige track, reserved; the next milestone highlighted with how far to go; the old `/road` and `/api/road` still answer). The marketplace's Banners tab sits third, right after Bundles. Earned cosmetics, and later tournament and live rewards, are meant to be the top status signal; nothing on the road costs coins. Achievements (built Nov 4, 2026, `server/achievements.py`): 13 achievements, each measuring one stat, with only the tiers its difficulty supports out of bronze, silver, gold, platinum and mystery (Hot Streak, Champion, Bullseye and Big Round have all five; On the Podium three; Designated Driver is gold only; Comeback Kid is a secret, mystery only, its name hidden until earned). Stats come from the lifetime record (`Database.lifetime`: games, wins, podiums, best win streak, Best Quotes, coins spent, cosmetics owned) and from the game just saved (`Room.game_facts`: rounds won in a row, a clean sweep, best round, trades, the tightest quote that held the answer, an exact quote, people in the room, a sober drinks-mode win, a comeback from last at halfway; a round goes to the one player with its top score above zero, and a table level at zero has nobody in last). Rewards scale with the tier: coins, plus achievement-only cosmetics granted into the inventory (`source="achievement"`: six banners and the Mortarboard and Laurel wreath headwear). `Database.award_achievements` records a tier and pays it in one transaction, so nothing pays twice; awards happen at game save (shown on the phone's game-end screen, each badge arriving in turn with a one-shot animation that grows with the tier: bronze rises, silver glints, gold pops, platinum spins in, mystery wobbles in with a purple glow), after a purchase (in the marketplace notice), and on opening the list (crediting older accounts). Badges (`client/src/components/Badge.tsx`) are medallions in the tier's colors with a small icon for the feat; every mystery tier shows a question mark. `/profile/achievements` lists every tier with what it takes, its reward and progress; mystery requirements read "???" (and their item rewards are named only by kind) until earned. Profile (built the same day): a bio of up to 160 characters, trimmed and checked against a short word list (`server/moderation.py`, a first line only; M5 adds reporting before strangers see bios), and a shelf of earned badges, hardest first; tapping one shows a small bubble with its name, tier and requirement for about two and a half seconds (kept inside the panel's edges). The header's links are Locker room, Marketplace and Academia; the achievements list is reached from the Badges panel. End-of-game awards (built Nov 4, 2026, `Room.awards`, `State.awards` at GAME_OVER): Sharpest quoter (most Best Quotes), Biggest round (best single round) and Busiest trader (most trades), shown above the host's final scores and on every phone's game-over screen (yours highlighted); ties share an award, and one nobody earned is left out; bots can win the round and trade awards, never Best Quote. Game log (built the same day): every saved game now also stores its whole table (`game_players`: seat, name, signed in or bot, rank, points), its rounds (`game_rounds`: question, unit, answer) and every trade (`game_fills`, with the buyer's points); `/profile/games/:id` (from the profile's Recent games) shows the table, each round's question and answer, and your own trades with the counterparty and points (`GET /api/games/{id}`, only for someone who played in it). Games saved before the log show just your result. The profile lists the 20 most recent games (`RECENT_GAMES`); every game is on `/profile/games` (added the same day, linked as "All N games" from the profile once there are more than 20, and from every game log): newest first under month headings, 25 at a time with "Show older games" (`GET /api/games?before=<id>`, `Database.history`, a cursor on the game id), and "won by" under any game you didn't win. Each signed-in player at the table has an "Add friend" button, disabled until friends arrive in M5. With this, M4 is complete.

**M5 — Social graph.** Built Nov 4, 2026, except web push, which followed on Nov 10. What exists: `server/social.py` (rules and storage) and `server/social_api.py` (HTTP), every account named in public by a random `public_id`; a handle for search and an eight-letter friend code; friend requests from the game log, the room (`TableSocial.tsx`), a code or a search, with accept, decline, remove and block; the Social page (`/social` until Nov 11, 2026; now the main menu's Social screen, see Main menu) with friends ranked by prestige (the friends leaderboard), requests both ways, people you've played with and your groups; public profiles at `/u/:id`; groups at `/g/:id` (an owner, up to 150 members ranked by prestige, invites, leave, remove, rename, disband, at most 5 owned), a member's Play now opening a members-only room that invites every member, and a host's table invite asking everyone seated to join the owner's group; the bell (`Bell.tsx`, polled every 30s) for friend requests, acceptances, group invites, joins and room invites, answerable in place; reports that hide a bio or group name from all but its owner at once, reviewed by the accounts in the `ADMIN_EMAILS` secret at `/admin/reports`. Web push (`server/push.py`, `client/public/sw.js`, `client/src/lib/push.ts`): a player turns notifications on per device on `/profile` ("Notifications on this device"; on `/social` until Nov 11, 2026); the browser subscribes with the server's VAPID public key and the subscription is stored per account (`push_subscriptions`, at most 10 devices, a device moves to whoever subscribed on it last, sign-out unsubscribes it). `social._notify` hands each new notification's id to a background thread (`push.Pusher`) that, after the request's transaction has committed, sends it to every device of the recipient in the RFC 8292 `vapid` form Apple requires, and drops a device the push service reports gone (404/410). Friend requests, acceptances, group invites and room invites are pushed (a room invite urgent and kept by the push service for only 15 minutes); a member joining a group stays in the bell, so an owner isn't buzzed for each of 100 joiners. Tapping a notification opens the page it's about, reusing an open Almanac window. The service worker handles push only, with no fetch handler, so it never caches a page. An iPhone allows web push only from the Home Screen (iOS 16.4+), so the client ships a manifest and icons (`client/public`, served from the root by `ROOT_FILES` in `app.py`) and tells iPhone Safari users to add it first. Push is off unless `VAPID_PUBLIC_KEY` and `VAPID_PRIVATE_KEY` are set (Fly secrets; `python -m server.push --keys` makes a pair; changing the pair cuts off every subscribed device). The original plan follows. Friends (requests, accept, list, friend-only leaderboards; sent from the game log and lobbies). Groups/clans: a named group with members, a group leaderboard, group-only rooms; a group invite opens a room. Invites with notifications: in-app first (a bell on the join page), then web push (service worker, VAPID keys on Fly; iOS only as an installed web app). Bios and clan names get a filter and a report button before strangers see them. Decided Nov 4, 2026 (Ryan): friend requests come three ways, from people you've played with (game log, the room you're in), by friend code, and by search; all of it lives on a new Social page, which will later be one of the app's three main pages: Social, Play (live, local, tournaments) and Customization. Notifications start as an in-app bell; web push comes after. A report hides the bio or group name from everyone but its owner at once, until Ryan reviews it. A group room starts from the group page: a member taps Play now, the host screen opens a room only members can join, and every member gets an invite.

**Groups: the cost, invite links and customization.** Built and deployed Nov 11, 2026 at Ryan's request, on top of M5's groups (`server/social.py`, `client/src/routes/Group.tsx`).

- **Cost.** Starting a group costs 1,500 coins (`social.GROUP_COST`). The coins leave and the group appears in one transaction, so a refusal (too few coins, five groups already, a bad name) costs nothing; too few coins answers 402 with how many more are needed. A new account's 750 welcome coins aren't enough on their own. Disbanding gives nothing back, and the confirm says so. Groups made before the charge stay as they are. The Social page's create form shows the price, the balance and what's missing (`overview` returns `coins`, `group_cost`, `groups_left`), stays disabled when short, and confirms before spending. The charge isn't counted by the Big Spender achievement, which is about the marketplace.
- **Invite link.** Every group has a link, `/g/<id>?invite=<code>` (`groups.invite_code`, 12 random characters; groups from before got one at startup). Whoever opens it can join after signing in, until the group is full; someone the owner has blocked can't. A join by link tells the owner on the bell like any other. Every member sees the link on the group page (anyone who joined by it has it anyway); only the owner can swap it for a new one, which kills every copy of the old (`reset_invite_link`). The group page's Invite players panel is where inviting happens: Copy link, Share (the device's share sheet, where the browser has one), a QR code for across a room, and for the owner the friends list and a search by handle that put an invite on someone's bell. Not signed in, the link shows the group (icon, name, bio, size, who runs it; `GET /api/groups/{id}/preview`, the one group call that needs no sign-in) above a sign-in box. So that the link looks right when pasted into a messaging app, the server answers it with the page plus a title and Open Graph tags ("Join Fintech Club on Almanac", the bio, the group's picture; `invite_page` in `app.py`), everything a player wrote escaped and anything reported left out.
- **Bio.** Up to 160 characters, under the same rules as a player's (`clean_bio`), shown under the name.
- **Prestige.** A group's prestige is its members' prestige added up (`_prestige`, worked out when asked, never stored), shown with the four-point star wherever the group is listed and on its page.
- **Starting one.** Start a group on the Social screen's Groups tab opens a dialog (`components/CreateGroup.tsx`, a real `<dialog>`) with everything that can be set, and a live preview of the shield: name, bio, a picture or a drawing and colour, then the price and what will be left. `POST /api/groups` takes the bio and icon with the name and checks all of it before charging; a chosen picture is uploaded straight after, and one that fails is only mentioned, since the group exists by then.
- **Icon.** A shield (Ryan's sketch, Nov 11, 2026), cut by a CSS mask so it scales, carrying one of 26 drawings (`GROUP_GLYPHS`: the group's initials, which every group starts with; a dozen single marks such as an almanac, a bar chart and a target; and 13 fuller pictures added the same day, among them an owl, a lighthouse, an abacus, scales and a laurel wreath, drawn with a thinner line so their detail holds when small) on one of 8 colours (`GROUP_COLORS`, the banners' family: blues, forest, mint, purples, paper; no buy green, sell red or gold), or a picture the owner uploads. `client/src/components/GroupIcon.tsx` draws it wherever a group is named (its page, the Social page, the main menu), and a test checks the client knows every id. The owner's Customize panel saves each choice as it's made.
- **Uploaded pictures** (`server/images.py`, Pillow). The client crops a chosen photo to a centred square and shrinks it to 256px on a canvas before sending, so the upload is small and the original file (with where and when it was taken) never leaves the phone. The server never stores what it was sent: it accepts only PNG, JPEG and WebP (never SVG, which can carry script), up to 2 MB and 2048px a side, decodes it, turns it upright, crops, shrinks and saves it again as a 256px WebP, in `group_images`, apart from the group's row so reading a group never drags its picture along. It's served at `/api/groups/{id}/image?v=<tag>`, the tag changing with every upload, to anyone who has the address (group ids are long random links, and an invite link's preview needs it), with `Cache-Control: private`.
- **Reports.** A group's bio and picture can be reported like its name (`REPORT_KINDS`: `bio`, `group_name`, `group_bio`, `group_image`), from one Report control on the group page. The reported thing is hidden at once from everyone but the owner: the bio reads empty, the picture gives way to the drawing underneath, and the picture's address answers 404 to all but the owner and an admin. Unlike a rename, editing a reported bio or swapping a reported picture does not unhide it, so the same thing can't be put straight back; it stays hidden until reviewed, and removing it outright closes the reports. `/admin/reports` shows the bio or the picture, with Restore, or Clear bio / Remove picture.

Defaults chosen while building this, for Ryan to confirm or change: every member can share the link (not just the owner); a link join is immediate, with no approval step; direct invites to a bell stay the owner's; no refund on disband.

**M6 — Modes that need a crowd.** Started Nov 10, 2026 with anti-cheat, which has to exist before strangers play together. Built (`server/anticheat.py`, `/admin/flags`): each logged quote now also records its question and how many milliseconds after quoting opened it was sealed (`quote_log.question_id`, `quote_ms`). A quote is a bullseye when it holds the answer with ask ≤ 1.25 × bid. After every saved game, each signed-in player with at least 20 logged quotes is tested: the binomial chance of their bullseye count at everyone else's bullseye rate (shrunk toward a prior of 5 in 100, so a small or new player base can't make luck look impossible). Below 0.001 they are shadow-flagged: they aren't told and nothing changes for them. The review page (admin accounts only, linked from `/admin/reports`) shows each flag's bullseyes against everyone else's rate, the odds in plain words, how they rank among regular players, and their last 25 quotes with question, spread and seconds taken. Clear (honest) ends a flag, and only quotes made after it count from then on; Confirm records the judgment, which `anticheat.standing` exposes for live mode to act on (planned: kept off live and public leaderboards). Why a test and not the percentile first planned: with a few dozen regulars a top percentile always holds somebody. Live mode, decided by Ryan on Nov 10, 2026: a short live game of 5 questions, quotes and trading as usual, every evening at 9pm Eastern, open to signed-in accounts only, with one results page at the end; the Googling problem (open decision 3) is handled by the usual 20s quote window plus anti-cheat, and a player with a confirmed accuracy flag is left off live leaderboards (no automatic punishment beyond that). Built the same day (`server/live.py`, `/live`): a scheduler started with the server (`app.py` lifespan; `LIVE_MODE=0` turns it off) opens a room under the reserved code `LIVE` ten minutes before 9pm Eastern (daylight saving followed through `zoneinfo`; `tzdata` is a requirement because Windows and slim images lack the zone files), with five standard questions at the standard pace and case questions off (`live_config`). The room has no host: its lobby timer is the start time (`Room.schedule_live`, phones show STARTS IN), the timer starts the game with whoever is seated or calls it off with fewer than two (`Room.start_live`, `State.live.cancelled`), and the room's own timers run every phase; an empty live lobby is never dropped. Only signed-in accounts may sit (`Room.signed_in_only`, refused with `sign_in`); a blank name seats a player under their account name, so `/live`'s Join button needs nothing typed. Saved games carry `games.live`. `/live` (and `GET /api/live`) shows the countdown to the next start in Eastern and local time, the lobby or the game in progress with its player count and a Join button, a sign-in box for guests, the last live game's table and the all-time live standings (wins, then points); anyone whose latest accuracy flag is confirmed is left off both, and places are counted again without them. The main menu's Play screen links to it. `LIVE_DEV_START_SECONDS` (local only, like `ALLOW_DEV_LOGIN`) opens a lobby at startup that starts that many seconds later, for testing. Deployed Nov 10, 2026. Fly stops the machine when idle (`auto_stop_machines`), which stops the scheduler with it: the lobby opens when the first visit after 8:50pm wakes the server (a server that starts inside the lobby window opens it at once), and a night nobody visits before 9pm has no game. Not yet built: a reminder push before the lobby opens (which would also wake the server), watching without playing, rooms above 120 seats, and live rooms for other times. The endless table (Ryan, Nov 10-11, 2026; his goal: someone opens Almanac in class instead of Instagram or Clash Royale and trades against anyone, any time): one room under the reserved code `OPEN`, at `/open` and linked from the main menu's Play screen, opened the first time anyone asks for it (`Hub.endless_table`, `Room.make_endless`) and dropped like any room once empty for 30 minutes. It never ends: rounds follow each other at a quick pace (`ENDLESS_TIMERS`: 4s read, 15s quote, 30s trade, 6s answer, 5s scores; hint 10s before the close; case questions off), anyone can sit at any time (late join as usual; guests may play, but only signed-in rounds are paid and ranked), and when no person is connected at the end of a round it idles in LOBBY instead of spending questions, waking when someone sits (`Room.wake`). The deck refills itself from the standard pool, holding back the most recently played half (`RECENT_SHARE`). A seat whose connection dropped is freed after 90 seconds (`SEAT_GRACE_MS`). House bots keep it liquid: the table holds `HOUSE_TRADERS` (6) traders, bots filling in for missing people and stepping back as people arrive, still labeled BOT. They never know the answer: each question gets one shared house view, the answer times e^N(0, 0.45) (typically 25-60% off), which every house bot quotes and trades around (`Room.bot_center`), so averaging the bots points at the wrong number. In trading each house bot is a market maker (`Hub._make_market`): every 3-6 seconds it pulls its quotes and posts a fresh bid and ask, its belief moving 30% of the way toward each new trade price and into the hint's range once that's out (`learn`), shaded against the lots it holds (`house_market`). Points are paid every round (`save_endless_round`, `Database.record_endless_round`, `endless_results`): to each signed-in player who quoted or traded, coins at 1 per point won from people and the Best Quote bonus, a quarter of that for points won off the house (`HOUSE_COIN_RATE`, so farming bots pays little), 10 coins per Best Quote, and XP of 5 + 2 per trade + 15 per Best Quote; nothing for sitting. Each round is saved as a one-round game marked `games.endless`, so its quotes reach the quote log and anti-cheat; it stays out of game history and lifetime stats. The phone shows the round's coins and XP on the scores screen. `/open` (`GET /api/open`, `server/endless.py`) shows who is at the table, a Sit down button, and today's and this week's boards (Eastern days, weeks from Monday), confirmed cheats left off. Deployed Nov 11, 2026. Not yet built: a second table when the first fills, overlapping markets so one is always closing, achievements from endless rounds, and scaling past one machine. The original plan follows. Live mode: one global question at a set time, everyone online in one room (the big-room work makes it feasible; needs a scheduler, a countdown lobby, a results page); the first thing after the social layer because it can grow the player base. Anti-cheat on M3's telemetry: flag players whose quotes sit in the top percentile of accuracy over many rounds, shadow-flag for review before any punishment; needed before live mode with strangers. Nearby-game discovery ("local"): rooms visible on the same Wi-Fi or within a radius, on live mode's plumbing. Competitive matchmaking by prestige, last, because it needs players to match. Public rooms, anonymous names, reporting, Expo wrapper for iOS/Android.

**Side tracks (never in the game server).** A share-card renderer: a page that draws any question in the house style (black background, the question, the unit) for screenshots and video. A TikTok posting agent and a demo-running agent as offline tools run from Ryan's machine, like the question verifier. Voice (speak to play, voice identification) is an experiment branch, not a milestone: a loud room of 100 is the wrong place to depend on it. The game needs its real name before live mode or any marketing.

## Dashboard

Ryan's dashboard (built Nov 10, 2026, from his "Finances, information, goals dashboard" goal) is a claude.ai artifact: https://claude.ai/artifact/4YG6u8RWESgwG5vfAKvZxo. It shows progress (every goal in `Almanac Development Log.docx` with its status, the milestones, a timeline and snapshots over time), financials (cost ceilings from Fly's price list, the $5 waiver, verifier model rates and logged spend), outside services, the tool versions, and the question bank. Its data is one file built from the project by `tools/dashboard/refresh.py`; `tools/dashboard/progress.json` holds each goal's status, the milestones and the timeline, `services.json` the services and prices, and `history.json` the snapshots. The verifier logs every run's tokens and cost to `server/questions/verify_runs.jsonl` for it. While Ryan has the log open in Word the file can't be read, so `refresh.py` then uses the goals it read the last time (`tools/dashboard/out/dev-log-goals.json`, rewritten at every successful read) and says so; a goal added to the log shows up at the first refresh after Word closes it (Nov 11, 2026).

**After shipping anything, keep it current.** 1) Update `progress.json`: the status and note of any goal the work moves (statuses: done, in_progress, ongoing, planned, not_started), a milestone's status, and a timeline entry for the day. A goal Ryan adds to the log shows as "Not tracked yet" until it has an entry. 2) Run `python tools/dashboard/refresh.py` (add `--production` only if Ryan has allowed reading aggregate counts from the live database). 3) Upload `tools/dashboard/out/almanac-dashboard.json` to the artifact as an asset, run `python tools/dashboard/store_docs.py --asset-url <the new /_blob/ url>` from PowerShell, never Git Bash, which rewrites an argument that starts with `/` into a Windows path and breaks every data source (`--page` too if `tools/dashboard/page/index.html` changed), and write the files in `tools/dashboard/out/store/` with one ArtifactData batch, pinning each document to the version a list of `datasets` shows. 4) Delete the previous upload. Never put anything from the log's "Relevant Information" section on the dashboard; it holds keys.

## Open decisions (Ryan)

1. Name. "Almanac" is the working title; pick a real one before M3's shareable URL spreads.
2. Can the host also play from a phone? Default no; easy to add.
3. ~~Live mode's Googling problem~~ Decided Nov 10, 2026: the 20s quote window plus anti-cheat flags; confirmed flaggers are left off live leaderboards.
4. Linear scoring: keep as a flag or drop it for simplicity?
5. Whether crossing sealed quotes should fill at open (current spec: yes). Alternative: uncross at midpoint. Current spec reuses the engine and keeps one code path; revisit only if playtests show the open feels unfair.

## Interview answers this project supports

- "Did you write it?" — I wrote the spec and designed the game; the engine, server, and client were built with Codex to that spec. The engine does price-time priority, partial fills, and self-trade and position-limit rejection, checked by a test suite written against the contract.
- "Why log scoring?" — So a question in the millions and a question in the tens score the same, and so a 2× miss costs the same as a ½× miss. Zero-sum, capped per fill.
- "Why no market maker?" — Everyone's sealed quote seeds the book at open, so the whole table is the market maker. The Best Quote bonus rewards tight, correct quotes the way a real MM earns the spread.
