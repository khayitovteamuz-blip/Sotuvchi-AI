"""Operator jim qolgan suhbatlarga do'kon raqamini yuboradi.

Mijoz operatorga uzatilgandan keyin AI jim bo'ladi. Agar hech kim javob
bermasa, u javobsiz chatda qolib ketadi — bu MVP'ning 3-bandi bo'yicha
yo'l qo'yilmaydigan holat.

Nega fon vazifasi: mijozning keyingi xabarida tekshirish faqat u qayta
yozgandagina ishlaydi, jim ketganlar esa qamrovdan tashqarida qolardi.
Shuning uchun vaqt bo'yicha o'zi yuradi.

Nega ko'p workerda takrorlanmaydi: yuborishdan oldin suhbat bazada
"claim" qilinadi (repo.claim_contact_reminder) — shartli UPDATE, faqat
bitta worker yutadi.
"""
import asyncio
import logging
from datetime import datetime, timedelta, timezone

from app.db import repo
from app.db.base import AsyncSessionLocal
from app.services.ai_agent import CONTACT_REMINDER_MINUTES, contact_fallback_text

logger = logging.getLogger("contact_reminder")

SWEEP_INTERVAL = 120     # soniya: 30 daqiqalik chegara uchun bu yetarlicha aniq
ERROR_BACKOFF = 60
BATCH = 50


class ContactReminder:
    def __init__(self) -> None:
        self._task = None
        self._running = False

    async def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._loop())
        logger.info("Aloqa raqami eslatmasi ishga tushdi (%s daqiqa)", CONTACT_REMINDER_MINUTES)

    async def stop(self) -> None:
        self._running = False
        if self._task:
            self._task.cancel()
            await asyncio.gather(self._task, return_exceptions=True)
        logger.info("Aloqa raqami eslatmasi to'xtatildi")

    async def _loop(self) -> None:
        while self._running:
            try:
                await self.sweep()
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.error("Eslatma aylanishida xato: %s", e)
                await asyncio.sleep(ERROR_BACKOFF)
                continue
            await asyncio.sleep(SWEEP_INTERVAL)

    async def sweep(self) -> int:
        """Bir aylanish: kutib qolgan suhbatlarga raqam yuboradi. Nechta yuborilgani."""
        now = datetime.now(timezone.utc)
        cutoff = now - timedelta(minutes=CONTACT_REMINDER_MINUTES)

        async with AsyncSessionLocal() as session:
            rows = await repo.stranded_conversations(session, cutoff, limit=BATCH)

        sent = 0
        for row in rows:
            try:
                sent += int(await self._remind(row, now))
            except Exception as e:
                # Bitta suhbatdagi xato qolganlarini to'xtatmasin.
                logger.error("Eslatma yuborilmadi (conv=%s): %s", row.get("id"), e)
        if sent:
            logger.info("Aloqa raqami yuborildi: %s ta suhbat", sent)
        return sent

    async def _remind(self, row: dict, now: datetime) -> bool:
        from app.db.models import Tenant
        from app.services.bot_service import bot_service

        async with AsyncSessionLocal() as session:
            # Avval huquqni olamiz — yuborib, keyin belgilash xatosi mijozga
            # bir xil xabarni qayta yuborish bilan tugaydi.
            if not await repo.claim_contact_reminder(session, row["id"], now):
                return False

            # Quyidagi har bir chiqishda claim qaytariladi: yuborilmagan xabar
            # uchun suhbatni "eslatilgan" deb belgilab qo'yish — mijozni
            # raqamdan butunlay mahrum qilish demakdir.
            tenant = await session.get(Tenant, row["tenant_id"])
            if not tenant or not tenant.telegram_bot_token:
                await repo.release_contact_reminder(session, row["id"])
                return False

            note = contact_fallback_text(row["contact_phone"], row["ai_language"]).strip()
            if not note:
                await repo.release_contact_reminder(session, row["id"])
                return False

            ok = await bot_service.send_message(
                tenant.telegram_bot_token, row["external_id"], note,
                business_connection_id=row["telegram_business_connection_id"],
            )
            if not ok:
                # Claim yuborishdan OLDIN olinadi (ikki worker bir vaqtda
                # yubormasligi uchun), lekin yuborilmasa uni qaytarib
                # qo'yamiz — aks holda bitta tarmoq uzilishi mijozni raqamdan
                # butunlay mahrum qilardi.
                await repo.release_contact_reminder(session, row["id"])
                logger.warning("Raqam yuborilmadi, qayta uriniladi: conv=%s", row["id"])
                return False

            conv = await repo.get_conversation(session, row["tenant_id"], row["id"])
            if conv:
                await repo.add_message(session, row["tenant_id"], conv, "assistant", note)
            return True


contact_reminder = ContactReminder()
