"""Naive cross-journal block search."""

from dataclasses import dataclass
from datetime import date
import re

from storage import journal_dates, journal_path, load_document


@dataclass(frozen=True)
class SearchResult:
    day: date
    block_index: int
    text: str
    ancestors: tuple[str, ...]
    match_start: int
    match_end: int


def compact_block_text(text):
    """Return one readable line for a block used as breadcrumb context."""
    return " ".join(text.split())


def search_journals(data_dir, query):
    """Find case-insensitive plain-substring matches, newest journal first."""
    if not query:
        return []

    pattern = re.compile(re.escape(query), re.IGNORECASE)
    results = []
    for day in sorted(journal_dates(data_dir), reverse=True):
        document = load_document(journal_path(data_dir, day))
        ancestors = []
        for block_index, block in enumerate(document.blocks):
            while len(ancestors) > block.level:
                ancestors.pop()

            match = pattern.search(block.text)
            if match is not None:
                results.append(
                    SearchResult(
                        day=day,
                        block_index=block_index,
                        text=block.text,
                        ancestors=tuple(ancestors),
                        match_start=match.start(),
                        match_end=match.end(),
                    )
                )

            context_text = compact_block_text(block.text)
            if len(ancestors) == block.level:
                ancestors.append(context_text)
            else:
                # Parsed documents normally only descend one level at a time,
                # but retaining the block still gives malformed outlines useful
                # context rather than dropping it from the path.
                ancestors.append(context_text)
    return results
