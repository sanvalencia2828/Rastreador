"""Schemas for authentication."""

from pydantic import BaseModel


# ------------------------------------------------------------------------------
# PYDANTIC SCHEMAS
# ------------------------------------------------------------------------------
class UserRegister(BaseModel):
    username: str
    password: str


class UserLogin(BaseModel):
    username: str
    password: str
