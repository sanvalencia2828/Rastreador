"""Field tarjeteo codes. The codes are the contract; labels are the UI legend."""

from __future__ import annotations

TARJETA_STATUSES: tuple[tuple[str, str, str], ...] = (
    ("TT", "A tarjetear", "Pendiente. Todavía no se marcó la visita."),
    ("TS", "Sin stock", "La loja no tenía mercadería o no se pudo trabajar."),
    ("TC", "Cerrado", "Local cerrado en el momento de la visita."),
    ("VV", "Venta", "Visita con venta."),
    ("TF", "No encontrado", "No se encontró la loja o la dirección."),
    ("PT", "Pedido", "Pedido tomado."),
    ("VS", "Visitado s/venta", "Se visitó, sin venta."),
)

TARJETA_CODES = {code for code, _label, _desc in TARJETA_STATUSES}
ROUTE_STATUSES = ("draft", "locked", "committed")


def tarjeta_legend() -> list[dict[str, str]]:
    return [
        {"code": code, "label": label, "description": description}
        for code, label, description in TARJETA_STATUSES
    ]


def normalize_route_status(status: str) -> str:
    """Map the deprecated `planned` value to `locked`."""
    value = (status or "").strip().lower()
    if value == "planned":
        return "locked"
    if value not in ROUTE_STATUSES:
        raise ValueError(f"status must be one of {', '.join(ROUTE_STATUSES)}")
    return value


def normalize_tarjeta(status: str) -> str:
    value = (status or "").strip().upper()
    if value not in TARJETA_CODES:
        raise ValueError(
            "tarjeta_status must be one of " + ", ".join(sorted(TARJETA_CODES))
        )
    return value
