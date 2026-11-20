"""Achievements (M4): badges earned for what a player does, in up to five tiers.

Each achievement measures one stat, and each of its tiers is a goal for that stat with a
reward: coins, and for the harder tiers an achievement-only banner or item. Tiers are bronze,
silver, gold, platinum and mystery, and an achievement has only the tiers its difficulty
supports. A mystery tier keeps its requirement hidden until it is earned, and its badge always
shows a question mark; an achievement that is nothing but a mystery tier hides its name too.

Stats come from two places, merged into one dict of facts: the player's lifetime record
(`Database.lifetime`, keys starting life_) and, when a game is saved, that game alone
(`Room.game_facts`, keys starting game_). A stat missing from the facts simply can't be checked
then: per-game achievements are checked when a game is saved, lifetime ones whenever the record
changes (a saved game, a purchase, opening the achievements page). `Database.award_achievements`
records each new tier and pays its reward in one transaction, so nothing is paid twice.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from server.cosmetics import ITEMS, SLOTS

if TYPE_CHECKING:
    from server.db import Database

TIERS = ("bronze", "silver", "gold", "platinum", "mystery")
HIDDEN = "???"


@dataclass(frozen=True)
class Tier:
    tier: str
    goal: float
    requirement: str
    coins: int
    item: str | None = None  # an achievement-only cosmetic granted with the tier
    stat: str | None = None  # a tier may measure something other than its achievement's stat


@dataclass(frozen=True)
class Achievement:
    id: str
    name: str
    icon: str  # the client's badge icon (client/src/components/Badge.tsx)
    blurb: str
    stat: str
    tiers: tuple[Tier, ...]
    at_most: bool = False  # the goal is a ceiling (smaller is better), not a floor

    @property
    def secret(self) -> bool:
        """Nothing but a mystery tier: even the name stays hidden until it's earned."""
        return all(tier.tier == "mystery" for tier in self.tiers)

    def reached(self, tier: Tier, facts: dict[str, float]) -> bool:
        value = facts.get(tier.stat or self.stat)
        if value is None:
            return False
        if tier.stat is None and self.at_most:
            return value <= tier.goal
        return value >= tier.goal


def _t(tier: str, goal: float, requirement: str, coins: int, item: str | None = None, stat: str | None = None) -> Tier:
    return Tier(tier, goal, requirement, coins, item, stat)


# Tiers follow difficulty, not a template: easy feats stop at silver or gold, and only the truly
# rare get a mystery tier. Coins scale with the tier; the best tiers add a cosmetic.
ACHIEVEMENTS: tuple[Achievement, ...] = (
    Achievement(
        "hot_streak",
        "Hot Streak",
        "flame",
        "Win rounds back to back. A round goes to the one player with its top score, above zero.",
        "game_round_streak",
        (
            _t("bronze", 2, "Win 2 rounds in a row in one game", 50),
            _t("silver", 3, "Win 3 rounds in a row in one game", 100),
            _t("gold", 5, "Win 5 rounds in a row in one game", 250, "banner_onaroll"),
            _t("platinum", 7, "Win 7 rounds in a row in one game", 500),
            _t("mystery", 1, "Win every round of a game of 7 or more rounds", 1000, stat="game_clean_sweep"),
        ),
    ),
    Achievement(
        "champion",
        "Champion",
        "trophy",
        "Finish first.",
        "life_wins",
        (
            _t("bronze", 1, "Win a game", 50),
            _t("silver", 5, "Win 5 games", 150),
            _t("gold", 25, "Win 25 games", 400, "banner_trophycase"),
            _t("platinum", 100, "Win 100 games", 1000, "head_laurels"),
            _t("mystery", 5, "Win 5 games in a row", 1500, stat="life_win_streak"),
        ),
    ),
    Achievement(
        "podium",
        "On the Podium",
        "podium",
        "Finish in the top three.",
        "life_podiums",
        (
            _t("bronze", 3, "Finish in the top three 3 times", 50),
            _t("silver", 15, "Finish in the top three 15 times", 150),
            _t("gold", 50, "Finish in the top three 50 times", 400),
        ),
    ),
    Achievement(
        "sharp_quote",
        "Sharp Quote",
        "brackets",
        "Win the Best Quote: the tightest quote that holds the answer.",
        "life_best_quotes",
        (
            _t("bronze", 1, "Win a Best Quote", 25),
            _t("silver", 10, "Win 10 Best Quotes", 150),
            _t("gold", 50, "Win 50 Best Quotes", 400),
            _t("platinum", 200, "Win 200 Best Quotes", 1000, "banner_deadcenter"),
        ),
    ),
    Achievement(
        "bullseye",
        "Bullseye",
        "target",
        "Quote a narrow range that still holds the answer.",
        "game_quote_ratio",
        (
            _t("bronze", 1.5, "Hold the answer with an ask no more than 50% above your bid", 50),
            _t("silver", 1.2, "Hold the answer with an ask no more than 20% above your bid", 150),
            _t("gold", 1.1, "Hold the answer with an ask no more than 10% above your bid", 300),
            _t("platinum", 1.03, "Hold the answer with an ask no more than 3% above your bid", 600),
            _t("mystery", 1, "Quote the exact answer as your bid or your ask", 1000, stat="game_exact_quote"),
        ),
        at_most=True,
    ),
    Achievement(
        "big_round",
        "Big Round",
        "chart",
        "Score big in a single round.",
        "game_best_round",
        (
            _t("bronze", 50, "Score 50 points in one round", 50),
            _t("silver", 100, "Score 100 points in one round", 100),
            _t("gold", 250, "Score 250 points in one round", 300),
            _t("platinum", 500, "Score 500 points in one round", 600),
            _t("mystery", 1000, "Score 1,000 points in one round", 1000),
        ),
    ),
    Achievement(
        "deal_maker",
        "Deal Maker",
        "swap",
        "Trade a lot in one game.",
        "game_trades",
        (
            _t("bronze", 5, "Make 5 trades in one game", 25),
            _t("silver", 15, "Make 15 trades in one game", 75),
            _t("gold", 30, "Make 30 trades in one game", 200),
            _t("platinum", 60, "Make 60 trades in one game", 400),
        ),
    ),
    Achievement(
        "regular",
        "Regular",
        "calendar",
        "Keep coming back.",
        "life_games",
        (
            _t("bronze", 5, "Finish 5 games", 50),
            _t("silver", 25, "Finish 25 games", 150),
            _t("gold", 100, "Finish 100 games", 400, "head_mortarboard"),
            _t("platinum", 500, "Finish 500 games", 1000),
        ),
    ),
    Achievement(
        "big_spender",
        "Big Spender",
        "coins",
        "Spend coins in the marketplace.",
        "life_coins_spent",
        (
            _t("bronze", 500, "Spend 500 coins", 50),
            _t("silver", 1000, "Spend 1,000 coins", 100),
            _t("gold", 2500, "Spend 2,500 coins", 250, "banner_deeppockets"),
            _t("platinum", 10000, "Spend 10,000 coins", 1000),
        ),
    ),
    Achievement(
        "collector",
        "Collector",
        "hanger",
        "Build a wardrobe: bought, earned or won.",
        "life_items_owned",
        (
            _t("bronze", 5, "Own 5 cosmetics", 50),
            _t("silver", 15, "Own 15 cosmetics", 150),
            _t("gold", 30, "Own 30 cosmetics", 400),
            _t("platinum", 50, "Own 50 cosmetics", 1000),
        ),
    ),
    Achievement(
        "full_house",
        "Full House",
        "people",
        "Play in a crowded room.",
        "game_room_size",
        (
            _t("bronze", 5, "Finish a game with 5 people in the room", 25),
            _t("silver", 10, "Finish a game with 10 people in the room", 75),
            _t("gold", 25, "Finish a game with 25 people in the room", 200, "banner_fullhouse"),
            _t("mystery", 100, "Finish a game with 100 people in the room", 1000),
        ),
    ),
    Achievement(
        "designated_driver",
        "Designated Driver",
        "glass",
        "Drinks mode, and nothing to drink.",
        "game_sober_win",
        (_t("gold", 1, "Win a drinks-mode game without a single drink", 300),),
    ),
    Achievement(
        "comeback",
        "Comeback Kid",
        "flag",
        "Down but not out.",
        "game_comeback",
        (_t("mystery", 1, "Win a game after sitting in last place at the halfway mark", 750, "banner_comeback"),),
    ),
)
BY_ID: dict[str, Achievement] = {achievement.id: achievement for achievement in ACHIEVEMENTS}


def due(facts: dict[str, float]) -> list[tuple[Achievement, Tier]]:
    """Every tier these facts reach, earned before or not."""
    return [(a, t) for a in ACHIEVEMENTS for t in a.tiers if a.reached(t, facts)]


def reward_text(tier: Tier, hide_item: bool = False) -> str:
    """"+250 coins and the On a Roll banner"; a hidden tier names only the kind of item."""
    text = f"+{tier.coins:,} coins"
    if tier.item:
        item = ITEMS[tier.item]
        kind = "banner" if item.slot == "banner" else SLOTS[item.slot].lower()
        text += f" and a {item.rarity} {kind}" if hide_item else f" and the {item.name} {kind}"
    return text


def earned_view(achievement: Achievement, tier: Tier) -> dict:
    """One newly earned tier, for the game-end screen and purchase notices."""
    return {
        "id": achievement.id,
        "name": achievement.name,
        "icon": achievement.icon,
        "tier": tier.tier,
        "requirement": tier.requirement,
        "reward": reward_text(tier),
    }


def award(db: Database, user_id: int, game: dict[str, float] | None = None) -> list[dict]:
    """Checks a player's record (and a just-finished game, if given), records every tier
    newly reached, pays its reward, and returns those tiers, hardest last."""
    facts = {**db.lifetime(user_id), **(game or {})}
    reached = due(facts)
    new = set(
        db.award_achievements(user_id, [(a.id, t.tier, t.coins, t.item) for a, t in reached])
    )
    return [earned_view(a, t) for a, t in reached if (a.id, t.tier) in new]


def badges(db: Database, user_id: int) -> list[dict]:
    """The tiers a player holds, hardest first, for the badge shelf on a profile. Earned, so a
    mystery tier's requirement is no secret any more."""
    order = {tier: index for index, tier in enumerate(TIERS)}
    earned = sorted(db.earned_achievements(user_id).items(), key=lambda kv: (-order[kv[0][1]], kv[1]))
    return [
        {
            "id": aid,
            "name": BY_ID[aid].name,
            "icon": BY_ID[aid].icon,
            "tier": tier,
            "requirement": next((t.requirement for t in BY_ID[aid].tiers if t.tier == tier), ""),
            "earned_at": when,
        }
        for (aid, tier), when in earned
        if aid in BY_ID
    ]


def list_view(db: Database, user_id: int) -> dict:
    """The full list for the profile's achievements page: every achievement and tier, what it
    takes (hidden for mystery tiers not yet earned), its reward, and the player's progress."""
    earned = db.earned_achievements(user_id)
    life = db.lifetime(user_id)
    rows = []
    for achievement in ACHIEVEMENTS:
        unlocked = any((achievement.id, tier.tier) in earned for tier in achievement.tiers)
        masked = achievement.secret and not unlocked
        tiers = []
        for tier in achievement.tiers:
            when = earned.get((achievement.id, tier.tier))
            hidden = tier.tier == "mystery" and when is None
            tiers.append(
                {
                    "tier": tier.tier,
                    "requirement": HIDDEN if hidden else tier.requirement,
                    "reward": reward_text(tier, hide_item=hidden),
                    "goal": None if hidden or tier.stat else tier.goal,
                    "earned_at": when,
                }
            )
        stat = achievement.stat
        rows.append(
            {
                "id": achievement.id,
                "name": "Secret achievement" if masked else achievement.name,
                "icon": achievement.icon,
                "blurb": "Keep playing to find out." if masked else achievement.blurb,
                # Lifetime stats can show progress; per-game ones have nothing to count toward.
                "progress": life.get(stat) if stat.startswith("life_") else None,
                "tiers": tiers,
            }
        )
    total = sum(len(achievement.tiers) for achievement in ACHIEVEMENTS)
    return {"achievements": rows, "earned": len(earned), "total": total}
