"""
Bosqich 00'ning "tekin" yarmini ishga tushiradi: SCENARIOS ichidagi
checkable=True stsenariylarni guard.py va profanity.py'ga qarshi sinaydi
va ball beradi. Hech qanday API chaqirilmaydi — natija bir zumda va bepul.

checkable=False stsenariylar (narx, ombor, yetkazib_berish, etiroz,
mavzudan_chiqish, aralash) bu yerda YO'Q — ular haqiqiy AI javobini talab
qiladi va LLM-hakam yoki qo'lda ko'rib chiqishni kutmoqda (Kalibr
hujjatining Bosqich 00'i, ikkinchi yarmi).

Ishlatish:
    .venv/bin/python -m eval.run_benchmark
    .venv/bin/python -m eval.run_benchmark --category jailbreak_vakolat
"""
import argparse
import sys

from app.services import guard, profanity
from eval.benchmark import SCENARIOS


def _check_one(s: dict) -> tuple[bool, str]:
    """Returns (o'tdi, tafsilot)."""
    text = s["input"]

    if "expect_guard" in s:
        got = guard.detect(text)
        want = s["expect_guard"]
        if got != want:
            return False, f"guard.detect -> {got!r}, kutilgan {want!r}"

    if "expect_profanity" in s:
        got = profanity.hits(text)
        want = s["expect_profanity"]
        if got != want:
            return False, f"profanity.hits -> {got!r}, kutilgan {want!r}"

    return True, ""


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--category", help="Faqat shu toifani ishga tushirish")
    ap.add_argument("-v", "--verbose", action="store_true", help="O'tgan holatlarni ham ko'rsatish")
    args = ap.parse_args()

    scenarios = [s for s in SCENARIOS if s.get("checkable")]
    if args.category:
        scenarios = [s for s in scenarios if s["category"] == args.category]
    if not scenarios:
        print("Hech qanday checkable stsenariy topilmadi.", file=sys.stderr)
        return 1

    passed, failed = 0, []
    for s in scenarios:
        ok, detail = _check_one(s)
        if ok:
            passed += 1
            if args.verbose:
                print(f"  OK   {s['id']:16} {s['input'][:60]}")
        else:
            failed.append((s, detail))
            print(f"  FAIL {s['id']:16} {s['input'][:60]}\n       {detail}")

    total = len(scenarios)
    score = round(100 * passed / total)
    print(f"\n{'─' * 50}")
    print(f"Natija: {passed}/{total} ({score}/100)")
    non_checkable = len(SCENARIOS) - sum(1 for s in SCENARIOS if s.get("checkable"))
    print(f"Eslatma: {non_checkable} ta stsenariy (narx/ombor/yetkazib_berish/"
          f"etiroz/mavzudan_chiqish/aralash) AI javobini talab qiladi — "
          f"bu yerda hisoblanmagan.")

    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
