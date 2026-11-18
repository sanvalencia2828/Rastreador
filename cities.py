"""Única definición de las ciudades que cargan/geocodifican enriquecer_lojas.py y load_filtered_cnpj.py.

receita_code: código de municipio de la Receita (columna 21 del ESTABELE; NO es IBGE).
name: grafía tal como se guarda en estabelecimentos.municipio.
"""
from typing import NamedTuple, Optional


class City(NamedTuple):
    name: str
    receita_code: Optional[str]
    lat: float
    lon: float


CITIES = (
    City("Maringá", "7691", -23.4205, -51.9330),
    City("Apucarana", "7425", -23.5521, -51.4614),
    City("Arapongas", "7427", -23.4194, -51.4244),
    # Marialva 7687: "verificado por CEP" según scripts/descargar_maringa.py.
    City("Marialva", "7687", -23.4855, -51.7927),
    # TODO: código Receita de Mandaguari sin confirmar (no está en el repo); hasta tenerlo
    # el loader rechaza sus filas como municipio_desconocido. Confirmar por CEP en un volcado real.
    City("Mandaguari", None, -23.5478, -51.6708),
)
# TODO: confirmar contra la base de producción que municipio se guarda exactamente con
# estas grafías (p. ej. "Maringá" con tilde, no "MARINGA"); el filtro del geocodificador depende de ello.
