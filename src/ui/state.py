"""Small, feature-owned UI state containers.

Dear PyGui items remain outside these classes.  They hold only state required
to coordinate a feature across callbacks and background-task completions.
"""

from dataclasses import dataclass, field
from typing import Any


@dataclass
class CharacterState:
    """Selection and cache-write state for the character feature."""

    entries: list[dict[str, Any]] = field(default_factory=list)
    current_id: str | None = None
    selected_logo_tag: int | str | None = None
    selected_outfit_tags: list[int | str] | None = None
    selected_outfit: dict[str, Any] | None = None
    pending_cache_writes: set[str] = field(default_factory=set)


@dataclass
class NavigationState:
    """History and current asset selection."""

    back: list[dict[str, Any]] = field(default_factory=list)
    forward: list[dict[str, Any]] = field(default_factory=list)
    current_asset_id: int | None = None
    current_asset_hash: str | None = None
    current_asset_data: dict[str, Any] | None = None
    is_navigating: bool = False
