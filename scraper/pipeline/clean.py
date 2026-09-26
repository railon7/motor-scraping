"""Normalizadores por tipo de campo. Cada uno recibe texto y devuelve un valor tipado o None."""
from __future__ import annotations

import re
from datetime import date, datetime

_MONEY = re.compile(r"-?\d(?:[\d.,\s]*\d)?")
_PHONE_CHARS = re.compile(r"[^\d+]")
_EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
_DATE_FORMATS = ("%d/%m/%Y", "%d-%m-%Y", "%Y-%m-%d", "%d/%m/%y", "%d.%m.%Y", "%Y/%m/%d")
_MESES = {
    "enero": 1, "febrero": 2, "marzo": 3, "abril": 4, "mayo": 5, "junio": 6,
    "julio": 7, "agosto": 8, "septiembre": 9, "octubre": 10, "noviembre": 11, "diciembre": 12,
}


def clean_str(v: str) -> str:
    return re.sub(r"\s+", " ", v).strip()


def clean_int(v: str) -> int | None:
    m = re.search(r"-?\d[\d.]*", v.replace(" ", ""))
    return int(m.group(0).replace(".", "")) if m else None


def clean_float(v: str) -> float | None:
    m = re.search(r"-?\d+(?:[.,]\d+)?", v.replace(" ", ""))
    return float(m.group(0).replace(",", ".")) if m else None


def clean_money(v: str) -> float | None:
    """'1.234,56 €' -> 1234.56 ; '1,234.56' -> 1234.56 ; '950 €' -> 950.0"""
    s = v.replace(" ", " ").strip()
    m = _MONEY.search(s)
    if not m:
        return None
    num = m.group(0).replace(" ", "")
    if "," in num and "." in num:
        if num.rfind(",") > num.rfind("."):
            num = num.replace(".", "").replace(",", ".")  # formato español
        else:
            num = num.replace(",", "")  # formato inglés
    elif "," in num:
        num = num.replace(",", ".") if len(num.split(",")[-1]) <= 2 else num.replace(",", "")
    elif num.count(".") > 1 or (num.count(".") == 1 and len(num.split(".")[-1]) == 3):
        num = num.replace(".", "")
    try:
        return float(num)
    except ValueError:
        return None


def clean_date(v: str) -> date | None:
    s = clean_str(v)
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00")).date()
    except ValueError:
        pass
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(s[: len(fmt) + 4], fmt).date()
        except ValueError:
            continue
    m = re.search(r"(\d{1,2})\s+de\s+([a-záéíóú]+)\s+de\s+(\d{4})", s.lower())
    if m and m.group(2) in _MESES:
        return date(int(m.group(3)), _MESES[m.group(2)], int(m.group(1)))
    return None


def clean_datetime(v: str) -> datetime | None:
    s = clean_str(v)
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        d = clean_date(s)
        return datetime(d.year, d.month, d.day) if d else None


def clean_phone(v: str) -> str | None:
    s = _PHONE_CHARS.sub("", v)
    if s.startswith("0034"):
        s = "+34" + s[4:]
    if len(s) == 9 and s[0] in "6789":
        s = "+34" + s
    return s or None


def clean_email(v: str) -> str | None:
    m = _EMAIL.search(v)
    return m.group(0).lower() if m else None


def clean_url(v: str) -> str | None:
    s = v.strip()
    return s or None


CLEANERS = {
    "str": clean_str,
    "int": clean_int,
    "float": clean_float,
    "money": clean_money,
    "date": clean_date,
    "datetime": clean_datetime,
    "phone": clean_phone,
    "email": clean_email,
    "url": clean_url,
    "list": lambda v: v,
}


def clean_value(raw, ftype: str):
    if raw is None:
        return None
    if ftype == "list":
        return [clean_str(x) for x in raw] if isinstance(raw, list) else [clean_str(raw)]
    return CLEANERS[ftype](raw)
