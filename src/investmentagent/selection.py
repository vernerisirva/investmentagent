"""The existing production ordering and minimum-country policy, shared with shadows."""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from typing import Any, Callable, Hashable, Iterable, TypeVar

from investmentagent.long_term_quality import LongTermGateTier


SELECTION_POLICY_VERSION = "production-country-minimum-v1"
T = TypeVar("T")


def gate_order(tier: str) -> int:
    return {
        LongTermGateTier.HIGH_CONVICTION.value: 0,
        LongTermGateTier.FUNDAMENTAL_WATCHLIST.value: 1,
        LongTermGateTier.SPECULATIVE_MONITOR.value: 2,
        LongTermGateTier.INSUFFICIENT_EVIDENCE.value: 3,
    }[tier]


@dataclass(frozen=True)
class SelectionPolicy:
    limit: int
    minimum_country_counts: tuple[tuple[str, int], ...] = ()

    def __post_init__(self) -> None:
        if type(self.limit) is not int or self.limit < 1:
            raise ValueError("selection limit must be a positive integer")
        countries = []
        for country, count in self.minimum_country_counts:
            if (not isinstance(country, str) or not country
                    or type(count) is not int or count < 0):
                raise ValueError("invalid minimum-country selection constraint")
            countries.append(country)
        if len(countries) != len(set(countries)):
            raise ValueError("duplicate minimum-country constraint")

    def as_payload(self) -> dict[str, Any]:
        return {
            "version": SELECTION_POLICY_VERSION,
            "limit": self.limit,
            # Constraint iteration order is part of production behavior, even when infeasible.
            "minimum_country_counts": [list(pair) for pair in self.minimum_country_counts],
            "ordering": "gate (long-term), score descending, ticker ascending, stable input order",
            "full_ranking": "constrained selection first, then remaining base-ranked members",
            "weighting": "equal decision-time weights; missing returns do not renormalize",
        }

    @classmethod
    def from_payload(cls, value: dict[str, Any]) -> SelectionPolicy:
        if not isinstance(value, dict):
            raise ValueError("missing selection configuration")
        try:
            result = cls(
                value["limit"],
                tuple(tuple(pair) for pair in value["minimum_country_counts"]),
            )
        except (KeyError, TypeError) as exc:
            raise ValueError("malformed selection configuration") from exc
        if result.as_payload() != value:
            raise ValueError("unsupported selection policy or configuration")
        return result


def select_ranked(
    ranked_items: Iterable[T],
    *,
    limit: int,
    minimum_country_counts: dict[str, int],
    rank_key: Callable[[T], Any],
    identity: Callable[[T], Hashable],
    country: Callable[[T], str],
) -> list[T]:
    """Preserve production's sequential replacements and stable final sort exactly."""
    ranked_items = list(ranked_items)
    selected = list(ranked_items[:limit])
    selected_keys = {identity(item) for item in selected}
    for requested_country, required_count in minimum_country_counts.items():
        normalized_country = requested_country.upper()
        if required_count <= 0:
            continue
        missing_count = required_count - sum(
            country(item) == normalized_country for item in selected
        )
        if missing_count <= 0:
            continue
        replacements = [
            item for item in ranked_items[limit:]
            if country(item) == normalized_country and identity(item) not in selected_keys
        ][:missing_count]
        for replacement in replacements:
            protected = {key.upper(): value for key, value in minimum_country_counts.items()}
            counts = Counter(country(item) for item in selected)
            index = next(
                (i for i in range(len(selected) - 1, -1, -1)
                 if counts[country(selected[i])] > protected.get(country(selected[i]), 0)),
                None,
            )
            if index is None:
                break
            selected_keys.remove(identity(selected.pop(index)))
            selected.append(replacement)
            selected_keys.add(identity(replacement))
    return sorted(selected, key=rank_key)


def rank_and_select(
    items: Iterable[T],
    *,
    policy: SelectionPolicy,
    rank_key: Callable[[T], Any],
    identity: Callable[[T], Hashable],
    country: Callable[[T], str],
) -> tuple[tuple[T, ...], tuple[T, ...]]:
    ranked = sorted(items, key=rank_key)
    selected = select_ranked(
        ranked, limit=policy.limit,
        minimum_country_counts=dict(policy.minimum_country_counts),
        rank_key=rank_key, identity=identity, country=country,
    )
    selected_objects = {id(item) for item in selected}
    full_order = (*selected, *(item for item in ranked if id(item) not in selected_objects))
    return full_order, tuple(selected)
