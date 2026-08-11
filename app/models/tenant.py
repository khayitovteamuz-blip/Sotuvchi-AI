from pydantic import BaseModel


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
    business_name: str
    email: str
    password: str
