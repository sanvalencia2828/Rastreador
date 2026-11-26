"""Optimización de rutas de visita como camino abierto con anclas fijas.

Problema: dada una matriz NxN de costos (duraciones de OSRM `/table`, que pueden ser
asimétricas o traer `null`), ordenar las paradas de modo que

* el primer ancla (entrada) quede primera y el último (salida) quede último,
* las anclas intermedias (paradas bloqueadas) conserven su orden y, por defecto,
  también su posición (`seq`) en la ruta,
* el costo total del camino sea mínimo.

Estrategia:

1. Construcción por **inserción más barata**: en cada paso se elige el par
   (parada, hueco) con menor costo C = M[a][k] + M[k][b] − M[a][b], usando la
   matriz y no los índices.
2. Búsqueda local hasta que nada mejore: relocate (mover una parada a otro hueco),
   swap entre tramos (intercambiar paradas de dos tramos distintos) y 2-opt dentro
   de cada tramo, contando las aristas hacia las anclas.
3. Si hay más de OPTIMIZER_THRESHOLD_ORTOOLS movibles (30 por defecto) y OR-Tools
   está instalado, se resuelve además con RoutingModel (un vehículo, inicio y fin
   distintos y una dimensión de orden que fija las anclas), y se devuelve la mejor
   de las dos soluciones.
"""

from __future__ import annotations

import logging
import math
import os
from typing import Iterable, Sequence

try:
    from ortools.constraint_solver import pywrapcp, routing_enums_pb2  # type: ignore
except ImportError:  # pragma: no cover
    pywrapcp = None
    routing_enums_pb2 = None

log = logging.getLogger(__name__)

Matrix = Sequence[Sequence[float | None]]

_MAX_ROUNDS = 500
_EPS = 1e-9


def _cost(matrix: Matrix, a: int, b: int) -> float:
    value = matrix[a][b]
    if value is None:
        return math.inf  # OSRM devuelve null cuando no hay ruta entre dos puntos
    return float(value)


def _path_cost(matrix: Matrix, order: Iterable[int]) -> float:
    values = list(order)
    return sum(_cost(matrix, values[i], values[i + 1]) for i in range(len(values) - 1))


def _insertion_cost(matrix: Matrix, a: int, k: int, b: int) -> float:
    """Costo de insertar k entre a y b: M[a][k] + M[k][b] − M[a][b]."""
    return _cost(matrix, a, k) + _cost(matrix, k, b) - _cost(matrix, a, b)


def _segment_ids(route: list[int], anchors: set[int]) -> list[int]:
    """Para cada posición, el tramo al que pertenece (las anclas abren un tramo nuevo)."""
    ids, segment = [], -1
    for node in route:
        if node in anchors:
            segment += 1
        ids.append(segment)
    return ids


# ------------------------------------------------------------------------------
# 1. Construcción: inserción más barata (con capacidad por tramo opcional)
# ------------------------------------------------------------------------------
def _cheapest_insertion(
    matrix: Matrix,
    anchor_indices: list[int],
    movable_indices: list[int],
    capacities: list[int] | None = None,
) -> list[int]:
    """Inserta el par (nodo, hueco) más barato hasta ubicar todos los movibles.

    Solo inserta en huecos entre elementos existentes: las anclas no cambian de orden
    y la entrada y la salida quedan en los extremos. Con `capacities`, el tramo i no
    recibe más de capacities[i] paradas, y así las anclas conservan su posición.
    """
    anchors = set(anchor_indices)
    route = list(anchor_indices)
    load = [0] * (len(anchor_indices) - 1)
    remaining = list(movable_indices)
    while remaining:
        best: tuple[float, int, int, int] | None = None  # (costo, nodo, posición, tramo)
        segment = -1
        gaps = []
        for pos in range(1, len(route)):
            if route[pos - 1] in anchors:
                segment += 1
            if capacities is None or load[segment] < capacities[segment]:
                gaps.append((pos, segment))
        for node in remaining:
            for pos, segment in gaps:
                delta = _insertion_cost(matrix, route[pos - 1], node, route[pos])
                if best is None or delta < best[0] - _EPS:
                    best = (delta, node, pos, segment)
        assert best is not None, "capacidades insuficientes para los movibles"
        _, node, pos, segment = best
        route.insert(pos, node)
        load[segment] += 1
        remaining.remove(node)
    return route


def _assign_nodes_to_segments(
    matrix: Matrix,
    anchor_indices: list[int],
    movable_indices: list[int],
    capacities: list[int] | None = None,
) -> dict[int, list[int]]:
    """Asigna cada movible al tramo entre anclas donde insertarlo cuesta menos.

    Devuelve {tramo: [nodos]}, donde el tramo i va de anchor_indices[i] a
    anchor_indices[i + 1]. Usa la matriz de costos, nunca los valores de los índices.
    """
    segments: dict[int, list[int]] = {idx: [] for idx in range(len(anchor_indices) - 1)}
    if not movable_indices:
        return segments
    route = _cheapest_insertion(matrix, anchor_indices, movable_indices, capacities)
    anchors = set(anchor_indices)
    for node, segment in zip(route, _segment_ids(route, anchors)):
        if node not in anchors:
            segments[segment].append(node)
    return segments


# ------------------------------------------------------------------------------
# 2. Búsqueda local
# ------------------------------------------------------------------------------
def _two_opt_open_path(matrix: Matrix, route: list[int]) -> list[int]:
    """2-opt con extremos fijos: route[0] y route[-1] no se mueven.

    Recibe el tramo completo (ancla_inicio, …movibles…, ancla_fin) para que cuenten
    las aristas hacia las anclas. Sirve para matrices asimétricas porque el delta
    incluye el cambio de sentido de las aristas internas del subcamino invertido.
    """
    best = list(route)
    if len(best) < 4:
        return best
    for _ in range(_MAX_ROUNDS):
        best_delta, best_move = -_EPS, None
        for i in range(1, len(best) - 2):
            reversal = 0.0  # Σ c(k+1,k) − c(k,k+1) para k en [i, j)
            for j in range(i + 1, len(best) - 1):
                reversal += _cost(matrix, best[j], best[j - 1]) - _cost(matrix, best[j - 1], best[j])
                delta = (
                    _cost(matrix, best[i - 1], best[j])
                    + _cost(matrix, best[i], best[j + 1])
                    - _cost(matrix, best[i - 1], best[i])
                    - _cost(matrix, best[j], best[j + 1])
                    + reversal
                )
                if delta < best_delta:
                    best_delta, best_move = delta, (i, j)
        if best_move is None:
            break
        i, j = best_move
        best[i : j + 1] = best[i : j + 1][::-1]
    return best


def _solve_slot(matrix: Matrix, start_idx: int, end_idx: int, slot_nodes: list[int]) -> list[int]:
    """Ordena los movibles de un tramo entre dos anclas (devuelve solo los movibles)."""
    if len(slot_nodes) <= 1:
        return list(slot_nodes)
    return _two_opt_open_path(matrix, [start_idx, *slot_nodes, end_idx])[1:-1]


def _two_opt_each_segment(matrix: Matrix, route: list[int], anchors: set[int]) -> list[int]:
    result: list[int] = [route[0]]
    start = 0
    for pos in range(1, len(route)):
        if route[pos] in anchors:
            result.extend(_two_opt_open_path(matrix, route[start : pos + 1])[1:])
            start = pos
    return result


def _relocate(matrix: Matrix, route: list[int], anchors: set[int], same_segment_only: bool) -> list[int]:
    """Mueve una parada a otro hueco si baja el costo (mejor movimiento por ronda)."""
    best = list(route)
    for _ in range(_MAX_ROUNDS):
        segment_of = _segment_ids(best, anchors)
        best_delta, best_move = -_EPS, None
        for i in range(1, len(best) - 1):
            node = best[i]
            if node in anchors:
                continue
            prev, nxt = best[i - 1], best[i + 1]
            removal_gain = _cost(matrix, prev, node) + _cost(matrix, node, nxt) - _cost(matrix, prev, nxt)
            for pos in range(1, len(best)):
                if pos in (i, i + 1):  # es el hueco que ya ocupa
                    continue
                # el hueco pos (entre pos-1 y pos) pertenece al tramo de best[pos-1]
                if same_segment_only and segment_of[pos - 1] != segment_of[i]:
                    continue
                delta = _insertion_cost(matrix, best[pos - 1], node, best[pos]) - removal_gain
                if delta < best_delta:
                    best_delta, best_move = delta, (i, pos)
        if best_move is None:
            break
        i, pos = best_move
        node = best.pop(i)
        best.insert(pos if pos < i else pos - 1, node)
    return best


def _swap_between_segments(matrix: Matrix, route: list[int], anchors: set[int]) -> list[int]:
    """Intercambia dos paradas de tramos distintos si baja el costo (no cambia el tamaño de los tramos)."""
    best = list(route)
    for _ in range(_MAX_ROUNDS):
        segment_of = _segment_ids(best, anchors)
        best_delta, best_move = -_EPS, None
        movable_positions = [p for p in range(1, len(best) - 1) if best[p] not in anchors]
        for a_idx, i in enumerate(movable_positions):
            x, pi, ni = best[i], best[i - 1], best[i + 1]
            for j in movable_positions[a_idx + 1 :]:
                if segment_of[j] == segment_of[i]:
                    continue  # dentro del tramo ya lo cubren 2-opt y relocate
                y, pj, nj = best[j], best[j - 1], best[j + 1]
                delta = (
                    _cost(matrix, pi, y) + _cost(matrix, y, ni) - _cost(matrix, pi, x) - _cost(matrix, x, ni)
                    + _cost(matrix, pj, x) + _cost(matrix, x, nj) - _cost(matrix, pj, y) - _cost(matrix, y, nj)
                )
                if delta < best_delta:
                    best_delta, best_move = delta, (i, j)
        if best_move is None:
            break
        i, j = best_move
        best[i], best[j] = best[j], best[i]
    return best


def _optimize_heuristic(
    matrix: Matrix,
    anchor_indices: list[int],
    movable_indices: list[int],
    capacities: list[int] | None,
) -> list[int]:
    anchors = set(anchor_indices)
    segments = _assign_nodes_to_segments(matrix, anchor_indices, movable_indices, capacities)
    route = [anchor_indices[0]]
    for segment_index in range(len(anchor_indices) - 1):
        start_anchor, end_anchor = anchor_indices[segment_index], anchor_indices[segment_index + 1]
        route.extend(_solve_slot(matrix, start_anchor, end_anchor, segments[segment_index]))
        route.append(end_anchor)

    previous = _path_cost(matrix, route)
    for _ in range(_MAX_ROUNDS):
        route = _relocate(matrix, route, anchors, same_segment_only=capacities is not None)
        route = _swap_between_segments(matrix, route, anchors)
        route = _two_opt_each_segment(matrix, route, anchors)
        cost = _path_cost(matrix, route)
        if not cost < previous - _EPS:
            break
        previous = cost
    return route


# ------------------------------------------------------------------------------
# API pública
# ------------------------------------------------------------------------------
def _position_capacities(anchor_indices: list[int], movable_indices: list[int]) -> list[int] | None:
    """Si los índices son posiciones en la ruta actual (como en /routes/{id}/optimize),
    devuelve cuántos movibles caben entre cada par de anclas para no correrlas de lugar."""
    n = len(anchor_indices) + len(movable_indices)
    if set(anchor_indices) | set(movable_indices) != set(range(n)):
        return None
    if anchor_indices != sorted(anchor_indices) or anchor_indices[0] != 0 or anchor_indices[-1] != n - 1:
        return None
    return [b - a - 1 for a, b in zip(anchor_indices, anchor_indices[1:])]


def _validate(
    route: list[int],
    anchor_indices: list[int],
    movable_indices: list[int],
    keep_positions: bool = False,
) -> bool:
    if sorted(route) != sorted([*anchor_indices, *movable_indices]):
        return False
    if route[0] != anchor_indices[0] or route[-1] != anchor_indices[-1]:
        return False
    anchors = set(anchor_indices)
    if [node for node in route if node in anchors] != list(anchor_indices):
        return False
    if keep_positions:
        return all(route[a] == a for a in anchor_indices)
    return True


def optimize_open_path(
    matrix: Matrix,
    anchor_indices: list[int],
    movable_indices: list[int],
    keep_locked_positions: bool = True,
) -> list[int]:
    """Devuelve el nuevo orden (índices de `matrix`) de todas las paradas.

    matrix: NxN de costos (duraciones en segundos de OSRM, o estimadas).
    anchor_indices: paradas fijas en su orden obligatorio; la primera es la entrada y
        la última la salida. Las intermedias son paradas bloqueadas.
    movable_indices: paradas que el optimizador puede reubicar.
    keep_locked_positions: si los índices son posiciones de la ruta actual, una parada
        bloqueada conserva su `seq`; las demás pueden cambiar de tramo intercambiándose.
        Con False, los tramos pueden crecer o achicarse y la parada bloqueada solo
        conserva su orden relativo.
    """
    if not matrix:
        return []
    if len(anchor_indices) < 2:
        return list(anchor_indices)
    anchors = list(anchor_indices)
    if len(set(anchors)) != len(anchors):
        raise ValueError("anchor_indices contiene índices repetidos")
    anchor_set = set(anchors)
    movables = [node for node in dict.fromkeys(movable_indices) if node not in anchor_set]
    if not movables:
        return anchors

    capacities = _position_capacities(anchors, movables) if keep_locked_positions else None
    keep_positions = capacities is not None
    best = _optimize_heuristic(matrix, anchors, movables, capacities)

    threshold = int(os.getenv("OPTIMIZER_THRESHOLD_ORTOOLS", "30"))
    if len(movables) > threshold and pywrapcp is not None:
        solved = _optimize_with_ortools(matrix, anchors, movables, keep_positions)
        if solved is not None and _path_cost(matrix, solved) < _path_cost(matrix, best) - _EPS:
            best = solved
    return best


def _optimize_with_ortools(
    matrix: Matrix,
    anchor_indices: list[int],
    movable_indices: list[int],
    keep_positions: bool = False,
) -> list[int] | None:
    """Camino abierto con OR-Tools Routing. Devuelve None si no hay solución válida."""
    if pywrapcp is None or routing_enums_pb2 is None:
        return None
    try:
        nodes = [*anchor_indices, *movable_indices]
        n = len(nodes)
        local = {node: i for i, node in enumerate(nodes)}

        # Routing trabaja con enteros: décimas de segundo; los pares sin ruta cuestan "infinito"
        finite = [c for a in nodes for b in nodes if a != b and math.isfinite(c := _cost(matrix, a, b))]
        unreachable = int(max(finite or [1.0]) * 10 * n) + 1
        costs = [
            [
                0 if a == b else (int(round(_cost(matrix, a, b) * 10)) if math.isfinite(_cost(matrix, a, b)) else unreachable)
                for b in nodes
            ]
            for a in nodes
        ]

        manager = pywrapcp.RoutingIndexManager(n, 1, [local[anchor_indices[0]]], [local[anchor_indices[-1]]])
        routing = pywrapcp.RoutingModel(manager)

        def transit(from_index: int, to_index: int) -> int:
            return costs[manager.IndexToNode(from_index)][manager.IndexToNode(to_index)]

        routing.SetArcCostEvaluatorOfAllVehicles(routing.RegisterTransitCallback(transit))

        # Dimensión "order": la posición de cada nodo en el camino (la entrada vale 0)
        step = routing.RegisterUnaryTransitCallback(lambda _index: 1)
        routing.AddDimension(step, 0, n, True, "order")
        order = routing.GetDimensionOrDie("order")
        solver = routing.solver()
        inner = [(a, manager.NodeToIndex(local[a])) for a in anchor_indices[1:-1]]
        if keep_positions:
            for anchor, index in inner:
                solver.Add(order.CumulVar(index) == anchor)
        for (_, before), (_, after) in zip(inner, inner[1:]):
            solver.Add(order.CumulVar(before) < order.CumulVar(after))

        params = pywrapcp.DefaultRoutingSearchParameters()
        # PATH_CHEAPEST_ARC no logra una primera solución con las restricciones de "order"
        # (agota el tiempo); FIRST_UNBOUND_MIN_VALUE las propaga y GLS mejora desde ahí
        params.first_solution_strategy = routing_enums_pb2.FirstSolutionStrategy.FIRST_UNBOUND_MIN_VALUE
        params.local_search_metaheuristic = routing_enums_pb2.LocalSearchMetaheuristic.GUIDED_LOCAL_SEARCH
        params.time_limit.FromMilliseconds(int(float(os.getenv("OPTIMIZER_ORTOOLS_TIME_LIMIT_S", "2")) * 1000))

        solution = routing.SolveWithParameters(params)
        if solution is None:
            return None

        route: list[int] = []
        index = routing.Start(0)
        while not routing.IsEnd(index):
            route.append(nodes[manager.IndexToNode(index)])
            index = solution.Value(routing.NextVar(index))
        route.append(nodes[manager.IndexToNode(index)])
    except Exception:  # pragma: no cover - la heurística siempre queda como respaldo
        log.exception("OR-Tools falló; se usa la heurística")
        return None

    return route if _validate(route, anchor_indices, movable_indices, keep_positions) else None
