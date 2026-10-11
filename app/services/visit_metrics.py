"""Per-business visit metric recalculation."""

from typing import Dict, Any, Optional

from sqlalchemy import text

from app.core.database import db_engine


def _recalculate_visit_metrics_on_connection(conn, business_id: int) -> Dict[str, Any]:
    """Recalculate one business's metrics using an existing DB connection."""
    business = conn.execute(
        text("""
            SELECT cnpj_completo
            FROM estabelecimentos
            WHERE id = :business_id
        """),
        {"business_id": business_id},
    ).fetchone()
    if not business:
        raise ValueError(f"Business {business_id} not found")

    visit_dates = [
        row[0]
        for row in conn.execute(
            text("""
                SELECT DISTINCT CAST(v.visited_at AS DATE) AS visit_date
                FROM visits v
                WHERE v.cnpj = :cnpj
                  AND v.visited_at IS NOT NULL
                ORDER BY visit_date ASC
            """),
            {"cnpj": business[0]},
        )
    ]

    visits_count = len(visit_dates)
    last_visit_date = visit_dates[-1] if visit_dates else None
    avg_visit_interval_days = None

    if visits_count >= 2:
        intervals = [
            (current - previous).days
            for previous, current in zip(visit_dates, visit_dates[1:])
        ]
        avg_visit_interval_days = sum(intervals) / len(intervals)

    conn.execute(
        text("""
            UPDATE estabelecimentos
            SET last_visit_date = :last_visit_date,
                visits_count = :visits_count,
                avg_visit_interval_days = :avg_visit_interval_days
            WHERE id = :business_id
        """),
        {
            "business_id": business_id,
            "last_visit_date": last_visit_date,
            "visits_count": visits_count,
            "avg_visit_interval_days": avg_visit_interval_days,
        },
    )

    return {
        "business_id": business_id,
        "last_visit_date": last_visit_date,
        "visits_count": visits_count,
        "avg_visit_interval_days": avg_visit_interval_days,
    }


def recalculate_visit_metrics(business_id: int) -> Dict[str, Any]:
    """Persist visit metrics for a business from its complete visit history.

    Visit timestamps are normalized to calendar dates before deduplication, so
    multiple visits on the same day count as one visit for interval purposes.
    The function owns and commits its transaction when called directly. Visit
    creation passes its active connection internally so the insert and metric
    update commit atomically.
    """
    if not db_engine:
        raise RuntimeError("Database connection unavailable")

    with db_engine.begin() as conn:
        return _recalculate_visit_metrics_on_connection(conn, business_id)


def recalculate_visit_interval(db_or_conn, business_id: int) -> Dict[str, Any]:
    """Recalculate metrics using the caller's active transaction connection."""
    return _recalculate_visit_metrics_on_connection(db_or_conn, business_id)


def _business_id_for_cnpj(conn, cnpj: Optional[str]) -> Optional[int]:
    """Resolve the canonical business id used by the metrics function."""
    if not cnpj:
        return None
    return conn.execute(
        text("""
            SELECT id
            FROM estabelecimentos
            WHERE cnpj_completo = :cnpj
            LIMIT 1
        """),
        {"cnpj": cnpj},
    ).scalar()
