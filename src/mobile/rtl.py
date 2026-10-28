"""نمایش متن فارسی در Kivy (که شکل‌دهی/راست‌به‌چپ ندارد): فرم‌های اتصال + ترتیب دیداری، با فونتی که فرم‌های نمایشی را دارد."""
from __future__ import annotations

from ..vector_text.shaping import _FORMS, _resolve_forms, split_runs


def visual(text: str) -> str:
    """رشته‌ی منطقیِ فارسی/انگلیسی → رشته‌ای که چپ‌به‌راست رسم شود و درست دیده شود."""
    out: list[str] = []
    for line in text.split("\n"):
        runs, _rtl = split_runs(line, "auto")
        parts = []
        for r in runs:
            if r.rtl:
                shaped = []
                for ch, form in _resolve_forms(r.text):
                    if form in ("initial", "medial", "final", "isolated"):
                        ch = _FORMS.get(ch, {}).get(form, ch)
                    shaped.append(ch)
                parts.append("".join(reversed([c for c in shaped if c])))
            else:
                parts.append(r.text)
        out.append("".join(parts))
    return "\n".join(out)
