import datetime as dt
import unittest

from src.calendars.jalali import (convert_digits, day_info, gregorian_to_jalali,
                                  is_jalali_leap, jalali_month_length, jalali_to_gregorian,
                                  month_days)


class CalendarTests(unittest.TestCase):
    def test_nowruz_anchors(self):
        # اول فروردین: تاریخ‌های رسمی (اعتدال بهاری + قاعده‌ی ظهر تهران)
        anchors = {1399: (2020, 3, 20), 1400: (2021, 3, 21), 1401: (2022, 3, 21),
                   1402: (2023, 3, 21), 1403: (2024, 3, 20), 1404: (2025, 3, 21),
                   1405: (2026, 3, 21), 1406: (2027, 3, 21), 1407: (2028, 3, 20)}
        for jy, g in anchors.items():
            self.assertEqual(jalali_to_gregorian(jy, 1, 1), dt.date(*g), jy)

    def test_leap_years(self):
        self.assertTrue(is_jalali_leap(1399))
        self.assertTrue(is_jalali_leap(1403))
        self.assertTrue(is_jalali_leap(1408))
        self.assertFalse(is_jalali_leap(1404))
        self.assertFalse(is_jalali_leap(1405))
        self.assertEqual(jalali_month_length(1403, 12), 30)
        self.assertEqual(jalali_month_length(1405, 12), 29)

    def test_template_sample_date(self):
        # نمونه‌ی قالب: ۰۲ آبان ۱۴۰۵ = شنبه ۲۴ اکتبر ۲۰۲۶
        d = day_info(1405, 8, 2)
        self.assertEqual(d.date, dt.date(2026, 10, 24))
        self.assertEqual(d.weekday_fa, "شنبه")
        self.assertEqual(d.weekday_en, "SATURDAY")
        self.assertEqual(d.jalali_month_fa, "آبان")
        self.assertEqual(d.fields()["g_month_abbr"], "OCT")

    def test_roundtrip_many_years(self):
        d = dt.date(1990, 1, 1)
        while d < dt.date(2060, 1, 1):
            jy, jm, jd = gregorian_to_jalali(d)
            self.assertEqual(jalali_to_gregorian(jy, jm, jd), d)
            d += dt.timedelta(days=1)

    def test_month_days_are_consecutive(self):
        days = month_days(1405, 8)
        self.assertEqual(len(days), 30)
        for a, b in zip(days, days[1:]):
            self.assertEqual((b.date - a.date).days, 1)
            self.assertEqual((b.date.weekday() - a.date.weekday()) % 7, 1)
        # آبان ۱۴۰۵ از ۲۳ اکتبر تا ۲۱ نوامبر
        self.assertEqual(days[0].date, dt.date(2026, 10, 23))
        self.assertEqual(days[-1].date, dt.date(2026, 11, 21))

    def test_month_spanning_gregorian_months(self):
        days = month_days(1405, 8)
        self.assertEqual({d.date.month for d in days}, {10, 11})

    def test_digits(self):
        self.assertEqual(convert_digits("1405", "persian"), "۱۴۰۵")
        self.assertEqual(convert_digits("۱۴۰۵", "latin"), "1405")
        self.assertEqual(convert_digits("12", "arabic"), "١٢")

    def test_cross_check_jdatetime_if_installed(self):
        try:
            import jdatetime
        except ImportError:
            self.skipTest("jdatetime نصب نیست")
        d = dt.date(2000, 1, 1)
        while d < dt.date(2040, 1, 1):
            j = jdatetime.date.fromgregorian(date=d)
            self.assertEqual(gregorian_to_jalali(d), (j.year, j.month, j.day), d)
            d += dt.timedelta(days=1)


if __name__ == "__main__":
    unittest.main()
