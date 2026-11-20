# Contributing to Almanac

Almanac is Ryan Corle's project. This is how to get set up and how changes get in.

## Start here

1. Follow **Setup** in [README.md](README.md). You need Python 3.12 and Node 20 or newer, and nothing else: no keys, no accounts with any service.
2. Run the tests. They should all pass before you change anything.

   ```bash
   .venv/Scripts/python -m pytest
   ```

   (`.venv/bin/python` on macOS or Linux.)

3. Start the server with dev sign-in on (README, "Signing in locally"), build the client, and open `http://localhost:8000`. Host a game at `/host`; the gear icon's demo run fills the room with bots so you can watch a full game alone.

[CLAUDE.md](CLAUDE.md) is the spec: the rules, the protocol, the look and feel, and what has been built and why. Read the part that covers what you're about to touch. If you work with Claude Code, it reads that file on its own.

## How a change gets in

- Never push to `main`. Make a branch (`git switch -c yourname/what-it-does`), push it, and open a pull request.
- One pull request does one thing. Say what it changes and how you checked it.
- Before you open it, both of these pass:

  ```bash
  .venv/Scripts/python -m pytest
  npm run build --prefix client
  ```

  The build type-checks the client, so a TypeScript error fails it.
- Ryan reviews and merges, and Ryan deploys. Nobody else needs access to Fly.
- Ask Ryan before starting anything that isn't already planned. The spec says what's in scope.

## Things the tests will hold you to

- **A new server file, page or database table** needs its line in `server/overview.py`. The suite fails until it has one.
- **A new cosmetic** goes in `server/cosmetics.py` with its scores, and is drawn under the same id in `client/src/avatar/parts.tsx` (or `effects.tsx` if it moves). Prices come from the formula, never by hand.
- **A protocol change** is made in `server/protocol.py` and `client/src/lib/types.ts` together. The second mirrors the first by hand.
- **The engine stays pure.** No I/O, clocks or randomness in `server/engine/orderbook.py`.

## Adding questions

Add them to `server/questions/questions.json` with `"status": "unverified"`, following the rules under "Question bank" in CLAUDE.md, then check the file:

```bash
.venv/Scripts/python -m server.questions.validate
```

Never set `verified` or `agent_verified` yourself. Ryan runs the verifier, which costs money on his API key, and games only serve questions that have passed.

## Never commit

- A key, a token, a `.env` file, or anything under `data/`. The `.gitignore` covers the usual ones; check `git status` before you commit anyway.
- `ALLOW_DEV_LOGIN` or `ALLOW_UNVERIFIED_QUESTIONS` in `fly.toml` or any deploy setting. They are for your own machine only.

If you think you've committed a secret, tell Ryan straight away. Deleting it in a later commit doesn't remove it from the history.
