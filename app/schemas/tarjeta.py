"""Schemas de la ruta de tarjetas."""

from typing import List, Literal, Optional
from uuid import UUID

from pydantic import BaseModel, Field, StringConstraints, model_validator
from typing_extensions import Annotated

from app.services.tarjetas import CIUDADES_POR_DEFECTO

Resultado = Literal["tarjeta_entregada", "cerrado", "rechazo", "interesado", "no_encontrado"]


class _Coords(BaseModel):
    lat: Optional[float] = Field(None, ge=-90, le=90)
    lon: Optional[float] = Field(None, ge=-180, le=180)

    @model_validator(mode="after")
    def coords_in_pairs(self):
        if (self.lat is None) != (self.lon is None):
            raise ValueError("lat y lon deben venir juntos")
        return self


class EntregaCreate(_Coords):
    """Sin user_id: el dueño de la entrega es siempre el usuario del token."""

    cnpj: Annotated[str, StringConstraints(pattern=r"^\d{14}$")]
    resultado: Resultado
    nota: Optional[Annotated[str, StringConstraints(strip_whitespace=True, max_length=500)]] = None
    route_id: Optional[UUID] = None  # ruta guardada: marca su parada como visitada


class RutaTarjetasRequest(_Coords):
    cities: List[str] = Field(default_factory=lambda: list(CIUDADES_POR_DEFECTO), min_length=1)
    max_paradas: int = Field(30, ge=1, le=80)
    business_type: Optional[Annotated[str, StringConstraints(strip_whitespace=True, max_length=20)]] = None
    cnae: Optional[int] = Field(None, ge=0)
    juntar: bool = False  # todas las ciudades en una sola ruta (solo si están a menos de 25 km)
