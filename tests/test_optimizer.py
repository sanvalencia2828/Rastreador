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
