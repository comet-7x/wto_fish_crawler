"""Assign a category to a resource using URL rules first, then title rules."""

from __future__ import annotations

from . import config


def classify(url_norm: str, title: str | None = None) -> str:
    """Return the category for a normalized URL (+ optional title)."""
    for rx, category in config.URL_CATEGORY_RULES:
        if rx.search(url_norm):
            return category

    if title:
        for rx, category in config.TITLE_CATEGORY_RULES:
            if rx.search(title):
                return category

    return config.DEFAULT_CATEGORY
