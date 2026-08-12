import re

from pydantic import BaseModel, field_validator

# The email is the login, so a typo here locks an owner out of their own shop.
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[a-zA-Z]{2,}$")
MIN_PASSWORD_LEN = 8


class Tenant(BaseModel):
    id: str
    business_name: str
    email: str
    password_hash: str
    created_at: str = ""
    is_active: bool = True

    def to_safe_dict(self) -> dict:
        """Return tenant info without password_hash"""
        return {
            "id": self.id,
            "business_name": self.business_name,
            "email": self.email,
            "created_at": self.created_at,
            "is_active": self.is_active,
        }


class TenantLogin(BaseModel):
    email: str
    password: str


class TenantRegister(BaseModel):
    """Registration was accepting a one-character password while the platform
    admin script demanded ten — the account holding every customer's phone
    number was the weaker of the two."""

    business_name: str
    email: str
    password: str

    @field_validator("business_name")
    @classmethod
    def _name(cls, v: str) -> str:
        v = v.strip()
        if len(v) < 2:
            raise ValueError("Biznes nomi kamida 2 ta belgidan iborat bo'lsin.")
        if len(v) > 120:
            raise ValueError("Biznes nomi juda uzun (120 belgidan oshmasin).")
        return v

    @field_validator("email")
    @classmethod
    def _email(cls, v: str) -> str:
        v = v.strip().lower()
        if not EMAIL_RE.match(v):
            raise ValueError("Email noto'g'ri yozilgan.")
        return v

    @field_validator("password")
    @classmethod
    def _password(cls, v: str) -> str:
        if len(v) < MIN_PASSWORD_LEN:
            raise ValueError(f"Parol kamida {MIN_PASSWORD_LEN} ta belgidan iborat bo'lsin.")
        if len(v) > 200:
            raise ValueError("Parol juda uzun.")
        return v
