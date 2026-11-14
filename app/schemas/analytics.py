"""Schemas for cluster and street analytics."""

from typing import List

from pydantic import BaseModel


# ==============================================================================
# DATA MODELS
# ==============================================================================
class ClusterPoint(BaseModel):
    type: str = "Point"
    coordinates: List[float]  # [lng, lat]


class Cluster(BaseModel):
    cluster_id: int
    total_lojas: int
    center_geom: ClusterPoint


class RubroDistribucion(BaseModel):
    categoria: str
    cantidad: int


class StreetAnalytics(BaseModel):
    logradouro: str
    total_negocios: int
    distribucion_rubros: List[RubroDistribucion]
    predominancia: str
