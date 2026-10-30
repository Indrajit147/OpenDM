"""Sort downloads into categories by file extension (spec 6.3)."""

from collections.abc import Sequence
from pathlib import Path

from opendm.core.models import Category


def match_category(filename: str, categories: Sequence[Category]) -> Category:
    """The category whose longest matching extension is longest; ties go to the first.

    Falls back to the category marked ``fallback`` (or the last one).
    """
    name = filename.lower()
    best: Category | None = None
    best_len = 0
    for category in categories:
        for ext in category.extensions:
            if len(ext) > best_len and name.endswith("." + ext) and len(name) > len(ext) + 1:
                best, best_len = category, len(ext)
    if best is not None:
        return best
    return next((c for c in categories if c.fallback), categories[-1])


def category_folder(category: Category, base: Path) -> Path:
    """Where the category's files go: ``base``, a folder inside it, or an absolute path."""
    if not category.folder:
        return base
    folder = Path(category.folder)
    return folder if folder.is_absolute() else base / folder
