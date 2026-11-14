import pytest

from app.optimizer import optimize_open_path


def test_optimize_open_path_no_movable_nodes():
    matrix = [
        [0.0, 10.0],
        [10.0, 0.0],
    ]

    result = optimize_open_path(matrix, [0, 1], [])

    assert result == [0, 1]


def test_optimize_open_path_keeps_locked_slot():
    matrix = [
        [0, 4, 2, 5, 10],
        [4, 0, 3, 6, 9],
        [2, 3, 0, 4, 8],
        [5, 6, 4, 0, 7],
        [10, 9, 8, 7, 0],
    ]

    result = optimize_open_path(matrix, [0, 2, 4], [1, 3])

    assert result[0] == 0
    assert result[2] == 2
    assert result[-1] == 4
    assert 1 in result[1:3]
    assert 3 in result[3:]


@pytest.mark.parametrize(
    "matrix, anchor_indices, movable_indices",
    [
        ([[0, 9], [9, 0]], [0, 1], []),
        ([[0, 2, 6], [2, 0, 5], [6, 5, 0]], [0, 2], [1]),
    ],
)
def test_optimize_open_path_handles_small_cases(matrix, anchor_indices, movable_indices):
    result = optimize_open_path(matrix, anchor_indices, movable_indices)

    assert result[0] == anchor_indices[0]
    assert result[-1] == anchor_indices[-1]


# ------------------------------------------------------------------------------
# Casos agregados con la corrección del optimizador
# ------------------------------------------------------------------------------
import itertools
import math
import random

from app.optimizer import _assign_nodes_to_segments, _optimize_with_ortools, _path_cost, _validate


def _euclid(points, asym=None):
    rng = random.Random(asym) if asym is not None else None
    return [
        [0.0 if i == j else math.dist(a, b) * (rng.uniform(0.7, 1.4) if rng else 1.0) for j, b in enumerate(points)]
        for i, a in enumerate(points)
    ]


def _brute_force(matrix, anchors, movables, keep_positions):
    best = math.inf
    inner = anchors[1:-1]
    for perm in itertools.permutations(inner + movables):
        route = [anchors[0], *perm, anchors[-1]]
        if [n for n in route if n in anchors] != anchors:
            continue
        if keep_positions and any(route[a] != a for a in anchors):
            continue
        best = min(best, _path_cost(matrix, route))
    return best


def test_unordered_stops_on_a_line_are_sorted():
    # paradas sobre una línea recta, cargadas en desorden: el óptimo es recorrerlas en orden
    xs = [0, 7, 2, 9, 4, 1, 8, 3, 6, 5, 10]
    matrix = _euclid([(x, 0) for x in xs])
    entry, exit_ = xs.index(0), xs.index(10)
    movable = [i for i in range(len(xs)) if i not in (entry, exit_)]
    result = optimize_open_path(matrix, [entry, exit_], movable, keep_locked_positions=False)
    assert [xs[i] for i in result] == list(range(11))


def test_assignment_uses_costs_not_index_values():
    # el nodo 1 está físicamente junto al tramo 2→3, aunque su índice cae entre 0 y 2
    points = [(0, 0), (10, 0.5), (5, 0), (10, 0)]
    matrix = _euclid(points)
    segments = _assign_nodes_to_segments(matrix, [0, 2, 3], [1])
    assert segments == {0: [], 1: [1]}
    assert optimize_open_path(matrix, [0, 2, 3], [1], keep_locked_positions=False) == [0, 2, 1, 3]


def test_locked_stop_keeps_its_position_by_default():
    # misma geometría, pero por defecto la parada bloqueada (índice 2) no cambia de seq
    points = [(0, 0), (10, 0.5), (5, 0), (10, 0)]
    result = optimize_open_path(_euclid(points), [0, 2, 3], [1])
    assert result[2] == 2


def test_stops_swap_segments_when_positions_are_fixed():
    # 1 está cerca de B y 3 está cerca de A: deben intercambiarse sin mover el ancla 2
    points = [(0, 0), (9, 0), (5, 0), (1, 0), (10, 0)]
    result = optimize_open_path(_euclid(points), [0, 2, 4], [1, 3])
    assert result == [0, 3, 2, 1, 4]


def test_unreachable_arcs_are_avoided():
    inf = None  # OSRM devuelve null cuando no hay ruta
    matrix = [
        [0, 1, 5, 9],
        [1, 0, inf, 2],
        [5, 1, 0, 3],
        [9, 2, 3, 0],
    ]
    result = optimize_open_path(matrix, [0, 3], [1, 2], keep_locked_positions=False)
    assert result == [0, 2, 1, 3]


@pytest.mark.parametrize("keep_positions", [True, False])
def test_valid_and_near_optimal_on_random_instances(keep_positions):
    rng = random.Random(42)
    optimal = 0
    trials = 150
    for trial in range(trials):
        n = rng.randint(3, 8)
        points = [(rng.random(), rng.random()) for _ in range(n)]
        matrix = _euclid(points, asym=trial if trial % 2 else None)
        inner = sorted(rng.sample(range(1, n - 1), rng.randint(0, min(2, n - 3))))
        anchors = [0, *inner, n - 1]
        movables = [i for i in range(1, n - 1) if i not in inner]
        result = optimize_open_path(matrix, anchors, movables, keep_locked_positions=keep_positions)
        assert _validate(result, anchors, movables, keep_positions), (anchors, result)
        best = _brute_force(matrix, anchors, movables, keep_positions)
        cost = _path_cost(matrix, result)
        assert cost <= best * 1.35 + 1e-9
        optimal += cost <= best + 1e-9
    assert optimal / trials >= 0.85


def test_ortools_large_instance(monkeypatch):
    pytest.importorskip("ortools")
    rng = random.Random(7)
    n = 45
    matrix = _euclid([(rng.random(), rng.random()) for _ in range(n)])
    anchors = [0, 15, 30, n - 1]
    movables = [i for i in range(n) if i not in anchors]
    solved = _optimize_with_ortools(matrix, anchors, movables, keep_positions=True)
    assert solved is not None and _validate(solved, anchors, movables, keep_positions=True)

    monkeypatch.setenv("OPTIMIZER_THRESHOLD_ORTOOLS", "100000")
    heuristic = optimize_open_path(matrix, anchors, movables)
    monkeypatch.setenv("OPTIMIZER_THRESHOLD_ORTOOLS", "10")
    result = optimize_open_path(matrix, anchors, movables)
    assert _validate(result, anchors, movables, keep_positions=True)
    assert _path_cost(matrix, result) <= _path_cost(matrix, heuristic) + 1e-6
