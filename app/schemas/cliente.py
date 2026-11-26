"""Schemas for creating and editing a customer."""

from typing import Optional

from pydantic import BaseModel, Field, StringConstraints, field_validator, model_validator
from typing_extensions import Annotated

from cities import canonical_city

Text = Annotated[str, StringConstraints(strip_whitespace=True, max_length=300)]


class ClienteCreate(BaseModel):
    nombre_negocio: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=300)]
    nombre_cliente: Optional[Text] = None
    direccion: Optional[Text] = None
    bairro: Optional[Text] = None
    nota: Optional[Annotated[str, StringConstraints(strip_whitespace=True, max_length=1000)]] = None
    lat: Optional[float] = Field(None, ge=-90, le=90)
    lon: Optional[float] = Field(None, ge=-180, le=180)
    municipio: Optional[Text] = None  # falta: la ciudad más cercana a lat/lon (o Maringá sin coords)
    visita_diaria: bool = False

    @field_validator("municipio")
    @classmethod
    def known_city(cls, v):
        return _city(v)

    @model_validator(mode="after")
    def coords_in_pairs(self):
        if (self.lat is None) != (self.lon is None):
            raise ValueError("lat y lon deben venir juntos")
        return self


class ClientePatch(BaseModel):
    municipio: Optional[Text] = None
    visita_diaria: Optional[bool] = None

    @field_validator("municipio")
    @classmethod
    def known_city(cls, v):
        return _city(v)

    @model_validator(mode="after")
    def something_to_change(self):
        if self.municipio is None and self.visita_diaria is None:
            raise ValueError("nada que cambiar: envía municipio o visita_diaria")
        return self


def _city(v):
    if v is None or v == "":
        return None
    name = canonical_city(v)
    if name is None:
        raise ValueError("ciudad desconocida")
    return name
