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


# Paraná aproximado: rechaza coordenadas pegadas al revés o de otro estado.
PR_LAT = (-24.5, -22.5)
PR_LON = (-53.5, -50.5)
Nota = Annotated[str, StringConstraints(strip_whitespace=True, max_length=1000)]


class ClientePatch(BaseModel):
    """Solo los campos enviados cambian; nota "" o null la borra."""

    municipio: Optional[Text] = None
    visita_diaria: Optional[bool] = None
    atrasado: Optional[bool] = None
    nombre_negocio: Optional[Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=300)]] = None
    nota: Optional[Nota] = None
    lat: Optional[float] = Field(None, ge=PR_LAT[0], le=PR_LAT[1])
    lon: Optional[float] = Field(None, ge=PR_LON[0], le=PR_LON[1])

    @field_validator("municipio")
    @classmethod
    def known_city(cls, v):
        return _city(v)

    @model_validator(mode="after")
    def something_to_change(self):
        if not self.model_fields_set:
            raise ValueError("nada que cambiar")
        if (self.lat is None) != (self.lon is None):
            raise ValueError("lat y lon deben venir juntos")
        for f in ("visita_diaria", "atrasado", "nombre_negocio", "municipio"):
            if f in self.model_fields_set and getattr(self, f) is None:
                raise ValueError(f"{f} no puede ser null")
        return self


def _city(v):
    if v is None or v == "":
        return None
    name = canonical_city(v)
    if name is None:
        raise ValueError("ciudad desconocida")
    return name
