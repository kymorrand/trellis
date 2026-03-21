"""
trellis.hands.vault — Obsidian Vault Read/Write Operations

Ivy's interface to the knowledge base. Read, write, search, and
organize Markdown files in the Obsidian vault.

Security: Restricted to IVY_VAULT_PATH only. No filesystem access outside the vault.
"""

import logging
import re
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)

# Directories that are internal to Ivy — not searched for user knowledge
INTERNAL_DIRS = {"_ivy", ".git", ".obsidian", ".trash"}


def search_vault(vault_path: Path, query: str, max_results: int = 5) -> list[dict]:
    """Search vault files for a query string. Returns matching files with context.

    Returns list of dicts: {"path": relative_path, "matches": [matched_lines]}
    """
    vault_path = Path(vault_path)
    if not vault_path.is_dir():
        logger.warning(f"Vault path does not exist: {vault_path}")
        return []

    if not query.strip():
        return []

    results = []
    query_lower = query.lower()
    # Split query into individual words for flexible matching
    query_words = query_lower.split()

    for md_file in vault_path.rglob("*.md"):
        # Skip internal directories
        rel = md_file.relative_to(vault_path)
        if any(part in INTERNAL_DIRS for part in rel.parts):
            continue

        try:
            content = md_file.read_text(errors="replace")
        except OSError as e:
            logger.warning(f"Failed to read {md_file}: {e}")
            continue

        content_lower = content.lower()

        # Check if any query words appear in the file
        matching_words = [w for w in query_words if w in content_lower]
        if not matching_words:
            continue

        # Extract matching lines for context
        matches = []
        for line in content.splitlines():
            if any(w in line.lower() for w in query_words):
                matches.append(line.strip())
                if len(matches) >= 3:
                    break

        results.append({
            "path": str(rel),
            "matches": matches,
            "relevance": len(matching_words) / len(query_words),
        })

    # Sort by relevance (most matching words first)
    results.sort(key=lambda r: r["relevance"], reverse=True)
    return results[:max_results]


def read_vault_file(vault_path: Path, relative_path: str) -> str | None:
    """Read a file from the vault by its relative path."""
    vault_path = Path(vault_path)
    target = (vault_path / relative_path).resolve()

    # Security: ensure the resolved path is still within the vault
    if not target.is_relative_to(vault_path.resolve()):
        logger.warning(f"Attempted vault escape: {relative_path}")
        return None

    if not target.exists():
        return None

    return target.read_text(errors="replace")


def save_to_vault(
    vault_path: Path,
    content: str,
    title: str,
    category: str = "drop",
) -> Path:
    """Save a new item to the vault.

    Categories:
        drop    → _ivy/inbox/drops/  (quick captures, random items)
        knowledge → knowledge/        (reference material, Kyle's workspace)
    """
    vault_path = Path(vault_path)
    now = datetime.now()

    # Sanitize title for filename
    safe_title = re.sub(r'[^\w\s-]', '', title).strip()
    safe_title = re.sub(r'\s+', '-', safe_title).lower()
    if not safe_title:
        safe_title = now.strftime("%H%M%S")

    date_str = now.strftime("%Y-%m-%d")

    if category == "knowledge":
        dest_dir = vault_path / "knowledge"
        filename = f"{safe_title}.md"
    else:
        dest_dir = vault_path / "_ivy" / "inbox" / "drops"
        filename = f"{date_str}-{safe_title}.md"

    dest_dir.mkdir(parents=True, exist_ok=True)
    dest_path = dest_dir / filename

    # Don't overwrite — append a number if needed
    counter = 1
    while dest_path.exists():
        stem = dest_path.stem
        dest_path = dest_dir / f"{stem}-{counter}.md"
        counter += 1

    # Write with frontmatter
    frontmatter = (
        f"---\n"
        f"created: {now.strftime('%Y-%m-%d %H:%M')}\n"
        f"source: ivy-discord\n"
        f"tags: [{category}]\n"
        f"---\n\n"
    )
    dest_path.write_text(frontmatter + content, encoding="utf-8")

    rel_path = dest_path.relative_to(vault_path)
    logger.info(f"Saved to vault: {rel_path}")
    return dest_path


def format_search_results(results: list[dict]) -> str:
    """Format search results into a readable string for Ivy's context."""
    if not results:
        return ""

    parts = []
    for r in results:
        parts.append(f"**{r['path']}**")
        for match in r["matches"]:
            parts.append(f"  > {match}")
    return "\n".join(parts)
