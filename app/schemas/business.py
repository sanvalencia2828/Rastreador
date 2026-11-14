"""Schemas for business endpoints."""

from typing import List

from pydantic import BaseModel


class TechBusiness(BaseModel):
    cnpj: str
    nome_fantasia: str
    cnae: str
    cnae_label: str
    cnae_icon: str
    bairro: str
    logradouro: str
    municipio: str
    business_type: str


class TechBusinessesResponse(BaseModel):
    total: int
    offset: int
    limit: int
    items: List[TechBusiness]


# ==============================================================================
# BUSINESS STATUS (global per-loja flag: visited / client)
# ==============================================================================
class BusinessStatusUpdate(BaseModel):
    status: str  # "visited" o "client"
