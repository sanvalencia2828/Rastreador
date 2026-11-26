"""Schema for creating a customer."""

from typing import Optional

from pydantic import BaseModel, Field, StringConstraints, model_validator
from typing_extensions import Annotated

Text = Annotated[str, StringConstraints(strip_whitespace=True, max_length=300)]


class ClienteCreate(BaseModel):
    nombre_negocio: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=300)]
    nombre_cliente: Optional[Text] = None
    direccion: Optional[Text] = None
    bairro: Optional[Text] = None
    nota: Optional[Annotated[str, StringConstraints(strip_whitespace=True, max_length=1000)]] = None
    lat: Optional[float] = Field(None, ge=-90, le=90)
    lon: Optional[float] = Field(None, ge=-180, le=180)

    @model_validator(mode="after")
    def coords_in_pairs(self):
        if (self.lat is None) != (self.lon is None):
            raise ValueError("lat y lon deben venir juntos")
        return self
