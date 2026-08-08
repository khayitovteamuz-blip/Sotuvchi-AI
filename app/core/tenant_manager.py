"""
Tenant Manager — manages all tenants and their per-tenant Database instances.
Data layout:
  data/tenants/tenants.json            ← all tenant records
  data/tenants/{tenant_id}/            ← per-tenant data folder
    products.json
    orders.json
    categories.json
    settings.json
"""
import json
import hashlib
import uuid
from pathlib import Path
from typing import Optional, Dict, List
from datetime import datetime

from app.models.tenant import Tenant
from app.core.config import BASE_DIR

TENANTS_DIR = BASE_DIR / "data" / "tenants"
TENANTS_DIR.mkdir(parents=True, exist_ok=True)
TENANTS_FILE = TENANTS_DIR / "tenants.json"


def _hash_password(password: str) -> str:
    return hashlib.sha256(password.encode()).hexdigest()


def _verify_password(password: str, password_hash: str) -> bool:
    return hashlib.sha256(password.encode()).hexdigest() == password_hash


class TenantManager:
    def __init__(self):
        self._tenants: Dict[str, Tenant] = {}   # tenant_id -> Tenant
        self._db_cache: Dict[str, object] = {}   # tenant_id -> Database instance
        self._load_tenants()
        self._seed_default_tenant()

    # ─── Persistence ────────────────────────────────────────────────────────
    def _load_tenants(self):
        if TENANTS_FILE.exists():
            try:
                with open(TENANTS_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    for item in data:
                        t = Tenant(**item)
                        self._tenants[t.id] = t
            except Exception:
                pass

    def _save_tenants(self):
        with open(TENANTS_FILE, "w", encoding="utf-8") as f:
            json.dump(
                [t.model_dump() for t in self._tenants.values()],
                f, ensure_ascii=False, indent=2
            )

    def _seed_default_tenant(self):
        """If no tenants exist, create a default demo tenant."""
        if not self._tenants:
            demo = Tenant(
                id="tenant-demo",
                business_name="Demo Biznes",
                email="admin@demo.com",
                password_hash=_hash_password("admin123"),
                created_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            )
            self._tenants[demo.id] = demo
            self._save_tenants()
            # Migrate existing data/products.json etc. → demo tenant folder
            self._migrate_legacy_data(demo.id)

    def _migrate_legacy_data(self, tenant_id: str):
        """Move old flat data files into the new tenant folder."""
        tenant_dir = TENANTS_DIR / tenant_id
        tenant_dir.mkdir(exist_ok=True)
        legacy_dir = BASE_DIR / "data"
        for fname in ["products.json", "orders.json", "settings.json"]:
            src = legacy_dir / fname
            dst = tenant_dir / fname
            if src.exists() and not dst.exists():
                dst.write_bytes(src.read_bytes())

    # ─── Tenant CRUD ─────────────────────────────────────────────────────────
    def get_all(self) -> List[Tenant]:
        return list(self._tenants.values())

    def get_by_id(self, tenant_id: str) -> Optional[Tenant]:
        return self._tenants.get(tenant_id)

    def get_by_email(self, email: str) -> Optional[Tenant]:
        for t in self._tenants.values():
            if t.email.lower() == email.lower():
                return t
        return None

    def register(self, business_name: str, email: str, password: str) -> Tenant:
        if self.get_by_email(email):
            raise ValueError("Bu email allaqachon ro'yxatdan o'tgan.")
        tenant_id = f"tenant-{uuid.uuid4().hex[:10]}"
        tenant = Tenant(
            id=tenant_id,
            business_name=business_name,
            email=email,
            password_hash=_hash_password(password),
            created_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        )
        self._tenants[tenant_id] = tenant
        self._save_tenants()
        # Prepare tenant data folder
        (TENANTS_DIR / tenant_id).mkdir(exist_ok=True)
        return tenant

    def authenticate(self, email: str, password: str) -> Optional[Tenant]:
        tenant = self.get_by_email(email)
        if tenant and _verify_password(password, tenant.password_hash):
            return tenant
        return None

    # ─── Per-Tenant Database ─────────────────────────────────────────────────
    def get_tenant_db(self, tenant_id: str):
        """Return (cached) Database instance for this tenant."""
        if tenant_id not in self._db_cache:
            from app.core.database import Database
            tenant_dir = TENANTS_DIR / tenant_id
            tenant_dir.mkdir(exist_ok=True)
            self._db_cache[tenant_id] = Database(tenant_data_dir=tenant_dir)
        return self._db_cache[tenant_id]

    def invalidate_db_cache(self, tenant_id: str):
        self._db_cache.pop(tenant_id, None)


tenant_manager = TenantManager()
