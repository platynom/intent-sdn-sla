"""
M3 Yen k-shortest paths.

Implements Yen's algorithm for finding the top-k loopless shortest paths in a
weighted graph, using an explicit spur-node loop.
"""

from __future__ import annotations

import heapq
from typing import Any, Dict, List

import networkx as nx


def k_shortest_paths(
    graph: nx.Graph,
    source: str,
    target: str,
    k: int = 3,
    weight: str = "delay_ms",
) -> List[List[str]]:
    """
    Compute up to k shortest loopless paths from source to target using Yen's algorithm.

    Handles edge cases:
    - source == target: returns [[source]]
    - no path exists: returns []
    - k <= 0: returns []
    - k larger than the total number of available simple paths: returns all available paths.
    """
    if k <= 0:
        return []

    if source not in graph or target not in graph:
        return []

    if source == target:
        return [[source]]

    try:
        first_path = nx.shortest_path(graph, source=source, target=target, weight=weight)
    except (nx.NetworkXNoPath, nx.NodeNotFound):
        return []

    # A holds the shortest paths determined so far
    A: List[List[str]] = [first_path]
    # B is a min-heap candidate list storing ((cost, path_index), path)
    B: List[tuple[float, int, List[str]]] = []
    # To keep track of candidates already added to avoid duplicates
    candidates_set = set()
    candidate_counter = 0

    def path_cost(p: List[str]) -> float:
        cost = 0.0
        for u, v in zip(p, p[1:]):
            edge_data: Dict[str, Any] = graph.get_edge_data(u, v, default={})
            cost += float(edge_data.get(weight, 1.0))
        return cost

    for path_idx in range(1, k):
        prev_path = A[path_idx - 1]

        # The spur node ranges from the first node up to the second-to-last node of the previous shortest path
        for i in range(len(prev_path) - 1):
            spur_node = prev_path[i]
            root_path = prev_path[: i + 1]

            # Copy graph to make temporary removals
            temp_graph = graph.copy()

            # Remove links used by previous paths in A that share the same root path
            for p in A:
                if len(p) > i and p[: i + 1] == root_path:
                    u, v = p[i], p[i + 1]
                    if temp_graph.has_edge(u, v):
                        temp_graph.remove_edge(u, v)

            # Remove all nodes in root_path except the spur_node from temp_graph
            for node in root_path[:-1]:
                if temp_graph.has_node(node):
                    temp_graph.remove_node(node)

            # Calculate spur path from spur_node to target in temp_graph
            try:
                spur_path = nx.shortest_path(
                    temp_graph, source=spur_node, target=target, weight=weight
                )
                total_path = root_path[:-1] + spur_path
                total_tuple = tuple(total_path)
                if total_tuple not in candidates_set and total_path not in A:
                    candidates_set.add(total_tuple)
                    cost = path_cost(total_path)
                    candidate_counter += 1
                    heapq.heappush(B, (cost, candidate_counter, total_path))
            except (nx.NetworkXNoPath, nx.NodeNotFound):
                pass

        if not B:
            break

        _, _, best_candidate = heapq.heappop(B)
        A.append(best_candidate)

    return A
