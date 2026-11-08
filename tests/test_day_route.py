"""app/services/day_route: agrupacion por dias y enlaces."""

from app.services.day_route import cluster_days, maps_links


def _blobs():
    # 3 barrios de 4 puntos, de oeste a este
    return [(-23.40 - k / 10000, -52.00 + b * 0.05) for b in range(3) for k in range(4)]


def test_cluster_days_groups_nearby_points_ordered_west_to_east_and_is_deterministic():
    pts = _blobs()
    groups, over = cluster_days(pts, 3, 10)
    assert over == [] and sorted(i for g in groups for i in g) == list(range(12))
    assert [sorted(g) for g in groups] == [[0, 1, 2, 3], [4, 5, 6, 7], [8, 9, 10, 11]]
    assert cluster_days(pts, 3, 10) == (groups, over)


def test_cluster_days_respects_cap_and_reports_overflow():
    pts = _blobs()
    groups, over = cluster_days(pts, 2, 5)  # capacidad 2*5=10 < 12
    assert all(len(g) <= 5 for g in groups) and len(over) == 2
    assert sorted([i for g in groups for i in g] + over) == list(range(12))


def test_cluster_days_with_fewer_points_than_days():
    groups, over = cluster_days([(-23.4, -51.9), (-23.5, -51.8)], 5, 10)
    assert len(groups) == 2 and over == [] and cluster_days([], 5, 10) == ([], [])


def test_maps_links_single_point_has_no_link():
    assert maps_links([(-23.4, -51.9)]) == []
