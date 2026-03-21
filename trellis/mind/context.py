"""
trellis.mind.context — Context Assembly & Auto-Search

Assembles the right context for each inference call.
On every non-trivial message, automatically extracts keywords and searches
the vault for relevant knowledge to include as context.

This makes Ivy contextually aware of the vault without Kyle having to
say "check the vault" — mentions of people, projects, or concepts
automatically pull in relevant vault knowledge.
"""

import logging
import re
from pathlib import Path

from trellis.hands.vault import format_search_results, search_vault

logger = logging.getLogger(__name__)

# Common English stop words that don't help vault search
STOP_WORDS = frozenset({
    "a", "an", "the", "and", "or", "but", "is", "are", "was", "were", "be",
    "been", "being", "have", "has", "had", "do", "does", "did", "will",
    "would", "could", "should", "may", "might", "can", "shall", "to", "of",
    "in", "for", "on", "with", "at", "by", "from", "as", "into", "through",
    "during", "before", "after", "above", "below", "between", "out", "off",
    "over", "under", "again", "further", "then", "once", "here", "there",
    "when", "where", "why", "how", "all", "each", "every", "both", "few",
    "more", "most", "other", "some", "such", "no", "nor", "not", "only",
    "own", "same", "so", "than", "too", "very", "just", "about", "up",
    "it", "its", "i", "me", "my", "we", "our", "you", "your", "he", "him",
    "his", "she", "her", "they", "them", "their", "this", "that", "these",
    "those", "what", "which", "who", "whom", "if", "because", "while",
    "am", "im", "ive", "dont", "doesnt", "isnt", "arent", "wasnt", "werent",
    "wont", "wouldnt", "cant", "couldnt", "shouldnt", "didnt", "hasnt",
    "havent", "hadnt", "hey", "hi", "hello", "thanks", "thank", "please",
    "yeah", "yes", "no", "ok", "okay", "sure", "right", "well", "like",
    "know", "think", "want", "need", "get", "got", "go", "going", "come",
    "make", "take", "see", "look", "tell", "say", "said", "thing", "things",
    "something", "anything", "nothing", "everything", "one", "two", "first",
    "new", "good", "great", "much", "many", "also", "still", "even", "back",
    "now", "really", "actually", "kind", "lot", "bit", "way", "time", "day",
    "let", "lets",
})

# Minimum message length (in words) to trigger auto-search
MIN_WORDS_FOR_SEARCH = 3

# Minimum relevance score for a vault result to be included
MIN_RELEVANCE = 0.5

# Max results to include in context
MAX_CONTEXT_RESULTS = 3


def extract_keywords(message: str, max_keywords: int = 3) -> list[str]:
    """Extract meaningful keywords from a user message for vault search.

    Strips stop words, punctuation, and short tokens. Returns the most
    significant words for searching the knowledge base.

    Args:
        message: The raw user message.
        max_keywords: Maximum keywords to return.

    Returns:
        List of keyword strings, possibly empty.
    """
    # Remove command prefixes
    cleaned = re.sub(r"^/(local|claude)\s*", "", message.strip(), flags=re.IGNORECASE)

    # Remove punctuation except hyphens (preserve compound words like "Mirror-Factory")
    cleaned = re.sub(r"[^\w\s-]", " ", cleaned)

    # Split into words
    words = cleaned.split()

    # Filter: keep non-stop-words that are 2+ characters
    keywords = []
    for word in words:
        lower = word.lower()
        if lower not in STOP_WORDS and len(word) >= 2:
            keywords.append(word)

    # Deduplicate while preserving order
    seen = set()
    unique = []
    for kw in keywords:
        lower = kw.lower()
        if lower not in seen:
            seen.add(lower)
            unique.append(kw)

    return unique[:max_keywords]


def should_auto_search(message: str) -> bool:
    """Determine if a message warrants automatic vault search.

    Skips very short messages, greetings, and simple commands.
    """
    stripped = message.strip()

    # Skip empty or very short messages
    word_count = len(stripped.split())
    if word_count < MIN_WORDS_FOR_SEARCH:
        return False

    # Skip messages that are just commands
    if stripped.startswith(("!", "/")):
        return False

    return True


def auto_context(vault_path: Path, message: str) -> str:
    """Automatically search the vault for context relevant to a message.

    This is the main entry point for auto-context assembly. Call it on
    every incoming message — it will decide whether to search and what
    to return.

    Args:
        vault_path: Path to the Obsidian vault.
        message: The user's message.

    Returns:
        Formatted vault search results, or empty string if nothing relevant.
    """
    if not should_auto_search(message):
        return ""

    keywords = extract_keywords(message)
    if not keywords:
        return ""

    # Search with the keywords joined as a query
    query = " ".join(keywords)
    results = search_vault(vault_path, query, max_results=MAX_CONTEXT_RESULTS)

    if not results:
        return ""

    # Filter by relevance threshold
    relevant = [r for r in results if r.get("relevance", 0) >= MIN_RELEVANCE]

    if not relevant:
        return ""

    formatted = format_search_results(relevant)
    logger.info(
        f"Auto-context: keywords={keywords}, "
        f"results={len(relevant)} relevant of {len(results)} total"
    )
    return formatted
