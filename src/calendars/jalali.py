"""تبدیل تاریخ شمسی (جلالی) و میلادی.

الگوریتم: چرخه‌ی ۳۳ ساله با جدول نقاط شکست (همان الگوریتم jalaali-js) که برای
سال‌های رسمی تقویم ایران (از جمله کبیسه بودن ۱۳۹۹ و ۱۴۰۳ و ۱۴۰۸) درست است.
اگر کتابخانه‌ی jdatetime نصب باشد، تست‌ها نتیجه را با آن هم مقایسه می‌کنند.
"""
from __future__ import annotations

import datetime as _dt
from dataclasses import dataclass

_BREAKS = [-61, 9, 38, 199, 426, 686, 756, 818, 1111, 1181, 1210, 1635,
           2060, 2097, 2192, 2262, 2324, 2394, 2456, 3178]

JALALI_MONTHS_FA = ["فروردین", "اردیبهشت", "خرداد", "تیر", "مرداد", "شهریور",
                    "مهر", "آبان", "آذر", "دی", "بهمن", "اسفند"]
# نام روزهای هفته: ایندکس = date.weekday() (دوشنبه = 0)
WEEKDAYS_FA = ["دوشنبه", "سه‌شنبه", "چهارشنبه", "پنج‌شنبه", "جمعه", "شنبه", "یک‌شنبه"]
WEEKDAYS_EN = ["MONDAY", "TUESDAY", "WEDNESDAY", "THURSDAY", "FRIDAY", "SATURDAY", "SUNDAY"]
GREGORIAN_MONTHS_EN = ["JANUARY", "FEBRUARY", "MARCH", "APRIL", "MAY", "JUNE", "JULY",
                       "AUGUST", "SEPTEMBER", "OCTOBER", "NOVEMBER", "DECEMBER"]


def _tdiv(a: int, b: int) -> int:
    """تقسیم صحیح با گرد کردن به سمت صفر (مثل ~~(a/b) در JS)."""
    q = abs(a) // abs(b)
    return q if (a >= 0) == (b > 0) else -q


def _tmod(a: int, b: int) -> int:
    return a - _tdiv(a, b) * b


def _jal_cal(jy: int, without_leap: bool = False):
    bl = len(_BREAKS)
    gy = jy + 621
    leap_j = -14
    jp = _BREAKS[0]
    if jy < jp or jy >= _BREAKS[bl - 1]:
        raise ValueError(f"سال شمسی خارج از بازه‌ی پشتیبانی‌شده: {jy}")
    jump = 0
    for i in range(1, bl):
        jm = _BREAKS[i]
        jump = jm - jp
        if jy < jm:
            break
        leap_j += _tdiv(jump, 33) * 8 + _tdiv(_tmod(jump, 33), 4)
        jp = jm
    n = jy - jp
    leap_j += _tdiv(n, 33) * 8 + _tdiv(_tmod(n, 33) + 3, 4)
    if _tmod(jump, 33) == 4 and jump - n == 4:
        leap_j += 1
    leap_g = _tdiv(gy, 4) - _tdiv((_tdiv(gy, 100) + 1) * 3, 4) - 150
    march = 20 + leap_j - leap_g
    if without_leap:
        return gy, march, None
    if jump - n < 6:
        n = n - jump + _tdiv(jump + 4, 33) * 33
    leap = _tmod(_tmod(n + 1, 33) - 1, 4)
    if leap == -1:
        leap = 4
    return gy, march, leap


def is_jalali_leap(jy: int) -> bool:
    return _jal_cal(jy)[2] == 0


def jalali_month_length(jy: int, jm: int) -> int:
    if not 1 <= jm <= 12:
        raise ValueError("ماه شمسی باید بین ۱ و ۱۲ باشد")
    if jm <= 6:
        return 31
    if jm <= 11:
        return 30
    return 30 if is_jalali_leap(jy) else 29


_JDN_OFFSET = 1721425  # date.toordinal() + این مقدار = Julian Day Number


def _g2d(gy: int, gm: int, gd: int) -> int:
    return _dt.date(gy, gm, gd).toordinal() + _JDN_OFFSET


def jalali_to_gregorian(jy: int, jm: int, jd: int) -> _dt.date:
    if not (1 <= jm <= 12 and 1 <= jd <= jalali_month_length(jy, jm)):
        raise ValueError(f"تاریخ شمسی نامعتبر: {jy}/{jm}/{jd}")
    gy, march, _ = _jal_cal(jy, True)
    base = _dt.date(gy, 3, 1).toordinal() + (march - 1)
    days = (jm - 1) * 31 - _tdiv(jm, 7) * (jm - 7) + jd - 1
    return _dt.date.fromordinal(base + days)


def gregorian_to_jalali(d: _dt.date) -> tuple[int, int, int]:
    jy = d.year - 621
    gy, march, leap = _jal_cal(jy)
    jdn1f = _dt.date(gy, 3, 1).toordinal() + (march - 1)
    k = d.toordinal() - jdn1f
    if k >= 0:
        if k <= 185:
            return jy, 1 + k // 31, k % 31 + 1
        k -= 186
    else:
        jy -= 1
        k += 179
        if leap == 1:
            k += 1
    return jy, 7 + k // 30, k % 30 + 1


@dataclass(frozen=True)
class DayInfo:
    jy: int
    jm: int
    jd: int
    date: _dt.date

    @property
    def weekday_fa(self) -> str:
        return WEEKDAYS_FA[self.date.weekday()]

    @property
    def weekday_en(self) -> str:
        return WEEKDAYS_EN[self.date.weekday()]

    @property
    def jalali_month_fa(self) -> str:
        return JALALI_MONTHS_FA[self.jm - 1]

    @property
    def gregorian_month_en(self) -> str:
        return GREGORIAN_MONTHS_EN[self.date.month - 1]

    def fields(self) -> dict[str, str]:
        """مقادیر قابل استفاده در الگوی متن هر لایه (قالب‌بندی با {نام})."""
        d = self.date
        return {
            "j_day": str(self.jd), "j_day2": f"{self.jd:02d}",
            "j_month_num": str(self.jm), "j_month_num2": f"{self.jm:02d}",
            "j_month_name": self.jalali_month_fa,
            "j_year": str(self.jy), "j_year2": f"{self.jy % 100:02d}",
            "g_day": str(d.day), "g_day2": f"{d.day:02d}",
            "g_month_num": str(d.month), "g_month_num2": f"{d.month:02d}",
            "g_month_name": self.gregorian_month_en,
            "g_month_abbr": self.gregorian_month_en[:3],
            "g_year": str(d.year), "g_year2": f"{d.year % 100:02d}",
            "wd_fa": self.weekday_fa, "wd_en": self.weekday_en,
            "wd_en_abbr": self.weekday_en[:3],
        }


def day_info(jy: int, jm: int, jd: int) -> DayInfo:
    return DayInfo(jy, jm, jd, jalali_to_gregorian(jy, jm, jd))


def month_days(jy: int, jm: int) -> list[DayInfo]:
    """همه‌ی روزهای یک ماه شمسی، هر روز با تاریخ میلادیِ واقعی و نام روز هفته."""
    return [day_info(jy, jm, d) for d in range(1, jalali_month_length(jy, jm) + 1)]


def day_info_from_gregorian(d: _dt.date) -> DayInfo:
    jy, jm, jd = gregorian_to_jalali(d)
    return DayInfo(jy, jm, jd, d)


PERSIAN_DIGITS = "۰۱۲۳۴۵۶۷۸۹"
ARABIC_DIGITS = "٠١٢٣٤٥٦٧٨٩"


def convert_digits(text: str, style: str) -> str:
    """style: 'latin' | 'persian' | 'arabic' — همه‌ی ارقام متن را به سبک خواسته‌شده برمی‌گرداند."""
    if style not in ("latin", "persian", "arabic"):
        raise ValueError(style)
    target = {"latin": "0123456789", "persian": PERSIAN_DIGITS, "arabic": ARABIC_DIGITS}[style]
    out = []
    for ch in text:
        if ch in "0123456789":
            out.append(target[int(ch)])
        elif ch in PERSIAN_DIGITS:
            out.append(target[PERSIAN_DIGITS.index(ch)])
        elif ch in ARABIC_DIGITS:
            out.append(target[ARABIC_DIGITS.index(ch)])
        else:
            out.append(ch)
    return "".join(out)
