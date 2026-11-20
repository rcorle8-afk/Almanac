"""Checks on text players write for others to see: the profile bio, handles and group names.

This is a first line, not moderation: length caps and a short list of words that can't be
used, matched as whole words after undoing the common letter-for-number swaps. Handles have no
spaces to split on, so the worst words are also caught inside them. Anything that gets through
can be reported (server/social.py), which hides it until Ryan reviews it.
"""

import re

BIO_LIMIT = 160
GROUP_NAME_MIN = 3
GROUP_NAME_LIMIT = 32
HANDLE_PATTERN = re.compile(r"[a-z][a-z0-9_]{2,19}")
RESERVED_HANDLES = frozenset(
    {"admin", "administrator", "almanac", "support", "moderator", "mod", "staff", "system", "official", "help", "root"}
)
# Caught even inside a longer handle ("fuckface"); short words like "dick" are left to whole-word
# matching so "dickens" and "hancock" still work.
HANDLE_SUBSTRINGS = frozenset(
    {"fuck", "shit", "cunt", "nigg", "fagg", "whore", "slut", "bitch", "pussy", "retard", "kike", "tranny", "asshole"}
)

# Common profanity. Extend freely; matching is case-insensitive and on whole words.
BLOCKED_WORDS = frozenset(
    {
        "fuck", "fucker", "fucking", "motherfucker", "shit", "bullshit", "cunt", "bitch",
        "asshole", "bastard", "dick", "dickhead", "cock", "pussy", "whore", "slut", "wanker",
        "twat", "prick", "douche", "douchebag", "nigger", "nigga", "faggot", "fag", "retard",
        "kike", "spic", "chink", "tranny",
    }
)
_SWAPS = str.maketrans({"0": "o", "1": "i", "3": "e", "4": "a", "5": "s", "7": "t", "@": "a", "$": "s", "!": "i"})


def has_blocked_word(text: str) -> bool:
    words = re.findall(r"[a-z]+", text.lower().translate(_SWAPS))
    return any(word in BLOCKED_WORDS for word in words)


def clean_bio(text: str) -> str:
    """A bio ready to store: trimmed, inner whitespace collapsed, within the length cap, and
    free of blocked words. Raises ValueError with a reason the player can read."""
    bio = re.sub(r"\s+", " ", text).strip()
    if len(bio) > BIO_LIMIT:
        raise ValueError(f"Keep it to {BIO_LIMIT} characters.")
    if has_blocked_word(bio):
        raise ValueError("That bio has a word we don't allow. Try another way to put it.")
    return bio


def clean_group_name(text: str) -> str:
    """A group name ready to store, or ValueError with a reason the player can read."""
    name = re.sub(r"\s+", " ", text).strip()
    if not GROUP_NAME_MIN <= len(name) <= GROUP_NAME_LIMIT:
        raise ValueError(f"Group names are {GROUP_NAME_MIN} to {GROUP_NAME_LIMIT} characters.")
    if has_blocked_word(name):
        raise ValueError("That name has a word we don't allow. Try another.")
    return name


def clean_handle(text: str) -> str:
    """A handle ready to store, lowercase and without the @, or ValueError with a reason."""
    handle = text.strip().removeprefix("@").lower()
    if not HANDLE_PATTERN.fullmatch(handle):
        raise ValueError("Handles are 3 to 20 letters, numbers or underscores, starting with a letter.")
    if handle in RESERVED_HANDLES:
        raise ValueError("That handle is reserved. Try another.")
    flat = handle.translate(_SWAPS)
    if has_blocked_word(flat.replace("_", " ")) or any(word in flat for word in HANDLE_SUBSTRINGS):
        raise ValueError("That handle has a word we don't allow. Try another.")
    return handle
