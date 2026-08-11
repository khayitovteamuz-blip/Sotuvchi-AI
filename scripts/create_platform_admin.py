"""
Create (or reset) a platform administrator.

There is no sign-up page for the platform panel on purpose: an account that can
read every business on the service must not be creatable by anyone who can reach
the website. Making it require shell access to the host is the point.

Run:  .venv/bin/python -m scripts.create_platform_admin
"""
import asyncio
import getpass
import sys
import uuid

from sqlalchemy import select

from app.core.security import hash_password
from app.db.base import AsyncSessionLocal
from app.db.models import PlatformAdmin

MIN_PASSWORD_LEN = 10


async def main() -> int:
    print("─── Platforma administratori ───\n")

    email = input("Email: ").strip().lower()
    if not email or "@" not in email:
        print("❌ Email noto'g'ri.")
        return 1

    async with AsyncSessionLocal() as db:
        existing = (
            await db.execute(select(PlatformAdmin).where(PlatformAdmin.email == email))
        ).scalars().first()

        if existing:
            print(f"\n⚠️  '{email}' allaqachon mavjud.")
            if input("Parolini yangilaymi? (ha/yo'q): ").strip().lower() not in ("ha", "h", "y", "yes"):
                print("Bekor qilindi.")
                return 0

        full_name = input("To'liq ism: ").strip() or None

        password = getpass.getpass("Parol (kamida 10 belgi): ")
        if len(password) < MIN_PASSWORD_LEN:
            print(f"❌ Parol juda qisqa — kamida {MIN_PASSWORD_LEN} belgi kerak.")
            return 1
        if password != getpass.getpass("Parolni takrorlang: "):
            print("❌ Parollar mos kelmadi.")
            return 1

        if existing:
            existing.password_hash = hash_password(password)
            existing.is_active = True
            if full_name:
                existing.full_name = full_name
            action = "yangilandi"
        else:
            db.add(
                PlatformAdmin(
                    id=f"padmin-{uuid.uuid4().hex[:12]}",
                    email=email,
                    password_hash=hash_password(password),
                    full_name=full_name,
                )
            )
            action = "yaratildi"

        await db.commit()

    print(f"\n✅ Platforma admini {action}: {email}")
    print("   Kirish:  /boshqaruv")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
