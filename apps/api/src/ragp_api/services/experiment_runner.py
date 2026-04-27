"""Generates pipeline combinations (cartesian product) and queues runs."""

import itertools
from typing import Any


def build_combinations(plugin_grid: dict[str, list[dict[str, Any]]]) -> list[list[dict[str, Any]]]:
    """Build cartesian product of plugin variants across pipeline slots."""
    slots = list(plugin_grid.keys())
    variants = [plugin_grid[slot] for slot in slots]
    combinations = list(itertools.product(*variants))

    result = []
    for combo in combinations:
        nodes = []
        for _slot, variant in zip(slots, combo, strict=False):
            nodes.append(
                {
                    "plugin_kind": variant["plugin_kind"],
                    "plugin_name": variant["plugin_name"],
                    "params": variant.get("params", {}),
                }
            )
        result.append(nodes)
    return result


async def enqueue_experiment(
    experiment_id: str,
    nodes_combinations: list[list[dict[str, Any]]],
) -> None:
    # TODO: integrate with a real task queue (Celery / ARQ / etc.)
    pass
