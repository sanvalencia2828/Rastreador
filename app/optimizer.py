from __future__ import annotations

import math
import os
from typing import Iterable

try:
    from ortools.constraint_solver import pywrapcp  # type: ignore
except ImportError:  # pragma: no cover
    pywrapcp = None


def _path_cost(matrix: list[list[float]], order: Iterable[int]) -> float:
    values = list(order)
    if len(values) < 2:
        return 0.0
    total = 0.0
    for idx in range(len(values) - 1):
        total += float(matrix[values[idx]][values[idx + 1]])
    return total


def _two_opt_open_path(matrix: list[list[float]], route: list[int]) -> list[int]:
    if len(route) < 3:
        return route

    best = list(route)
    improved = True
    while improved:
        improved = False
        for i in range(1, len(best) - 1):
            for j in range(i + 1, len(best) - 1):
                candidate = best[:]
                candidate[i : j + 1] = reversed(candidate[i : j + 1])
                if _path_cost(matrix, candidate) < _path_cost(matrix, best):
                    best = candidate
                    improved = True
                    break
            if improved:
                break
    return best


def _solve_slot(matrix: list[list[float]], start_idx: int, end_idx: int, slot_nodes: list[int]) -> list[int]:
    if not slot_nodes:
        return []

    if len(slot_nodes) == 1:
        return [slot_nodes[0]]

    current = start_idx
    remaining = list(slot_nodes)
    path = [start_idx]
    while remaining:
        next_node = min(remaining, key=lambda node: float(matrix[current][node]))
        path.append(next_node)
        remaining.remove(next_node)
        current = next_node
    path.append(end_idx)

    ordered = path[1:-1]
    ordered = _two_opt_open_path(matrix, ordered)
    return ordered


def _assign_nodes_to_segments(
    matrix: list[list[float]],
    anchor_indices: list[int],
    movable_indices: list[int],
) -> dict[int, list[int]]:
    del matrix
    segments: dict[int, list[int]] = {idx: [] for idx in range(len(anchor_indices) - 1)}
    if not movable_indices:
        return segments

    for node in movable_indices:
        best_segment = 0
        for segment_index in range(len(anchor_indices) - 1):
            if anchor_indices[segment_index] < node < anchor_indices[segment_index + 1]:
                best_segment = segment_index
                break
        segments[best_segment].append(node)
    return segments


def optimize_open_path(matrix: list[list[float]], anchor_indices: list[int], movable_indices: list[int]) -> list[int]:
    """
    matrix: NxN duraciones en segundos (de OSRM /table).
    anchor_indices: posiciones fijas ordenadas, incluye entry y exit.
    movable_indices: nodos a reordenar.

    Estrategia:
    - Entre cada par consecutivo de anclas, insertar los movibles
      respetando orden de aparición (slots).
    - Para cada segmento entre anclas A_i y A_{i+1}, resolver TSP de camino
      abierto (A_i → ... → A_{i+1}) con los movibles asignados a ese slot.
    - Asignación de slot: por ahora, vecino más cercano a la ancla de inicio.
    - Refinamiento: 2-opt dentro de cada slot.
    - Para instancias grandes (>30 movibles), llamar a OR-Tools.
    """
    if not matrix:
        return []
    if len(anchor_indices) < 2:
        return list(anchor_indices)

    if not movable_indices:
        return list(anchor_indices)

    threshold = int(os.getenv("OPTIMIZER_THRESHOLD_ORTOOLS", "30"))
    if len(movable_indices) > threshold and pywrapcp is not None:
        return _optimize_with_ortools(matrix, anchor_indices, movable_indices)

    segments = _assign_nodes_to_segments(matrix, anchor_indices, movable_indices)
    ordered: list[int] = [anchor_indices[0]]

    for segment_index in range(len(anchor_indices) - 1):
        start_anchor = anchor_indices[segment_index]
        end_anchor = anchor_indices[segment_index + 1]
        slot_nodes = segments[segment_index]
        if slot_nodes:
            ordered.extend(_solve_slot(matrix, start_anchor, end_anchor, slot_nodes))
        ordered.append(end_anchor)

    deduped: list[int] = []
    seen: set[int] = set()
    for item in ordered:
        if item in seen:
            continue
        seen.add(item)
        deduped.append(item)

    if deduped[0] != anchor_indices[0] or deduped[-1] != anchor_indices[-1]:
        deduped[0] = anchor_indices[0]
        deduped[-1] = anchor_indices[-1]

    return deduped


def _optimize_with_ortools(
    matrix: list[list[float]],
    anchor_indices: list[int],
    movable_indices: list[int],
) -> list[int]:
    if pywrapcp is None:
        return optimize_open_path(matrix, anchor_indices, movable_indices)

    fixed = list(anchor_indices)
    all_nodes = [*anchor_indices, *movable_indices]
    if len(all_nodes) != len(set(all_nodes)):
        return optimize_open_path(matrix, anchor_indices, movable_indices)

    model = pywrapcp.Solver("open_path_tsp")
    num_nodes = len(all_nodes)
    assignment = {}
    for i in range(num_nodes):
        for j in range(num_nodes):
            if i == j:
                continue
            assignment[(i, j)] = model.BoolVar(f"x_{i}_{j}")

    for i in range(num_nodes):
        model.Add(sum(assignment[(i, j)] for j in range(num_nodes) if i != j) <= 1)
        model.Add(sum(assignment[(j, i)] for j in range(num_nodes) if i != j) <= 1)

    starts = [0]
    ends = [num_nodes - 1]
    if len(fixed) >= 2:
        starts = [all_nodes.index(fixed[0])]
        ends = [all_nodes.index(fixed[-1])]

    for node in range(num_nodes):
        if node in starts:
            continue
        if node in ends:
            continue
        model.Add(sum(assignment[(node, j)] for j in range(num_nodes) if node != j) == sum(assignment[(j, node)] for j in range(num_nodes) if node != j))

    model.Minimize(
        sum(
            float(matrix[i][j]) * assignment[(i, j)]
            for i in range(num_nodes)
            for j in range(num_nodes)
            if i != j
        )
    )

    solver = model.Solver()
    status = solver.Solve(model)
    if status not in (pywrapcp.Solver.OPTIMAL, pywrapcp.Solver.FEASIBLE):
        return optimize_open_path(matrix, anchor_indices, movable_indices)

    route = []
    current = starts[0]
    visited = {current}
    while True:
        next_node = None
        for j in range(num_nodes):
            if j == current or j in visited:
                continue
            if assignment[(current, j)].SolutionValue() > 0.5:
                next_node = j
                break
        if next_node is None:
            break
        route.append(next_node)
        current = next_node
        visited.add(current)

    if not route:
        return list(anchor_indices)
    return [all_nodes[i] for i in route]
