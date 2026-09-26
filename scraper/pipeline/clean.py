"""Normalizadores por tipo de campo. Cada uno recibe texto y devuelve un valor tipado o None."""
from __future__ import annotations

import re
from datetime import date, datetime

_MONEY = re.compile(r"-?\d(?:[\d.,\s]*\d)?")
_PHONE = re.compile(r"\+?\d[\d\s.\-()]{6,}\d")
_PHONE_CHARS = re.compile(r"[^\d+]")
_EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
# Fechas numéricas dentro de un texto: año primero (2024-03-12) o día primero (12/03/2024, 12.03.24)
_DATE_YMD = re.compile(r"\b(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})\b")
_DATE_DMY = re.compile(r"\b(\d{1,2})[-/.](\d{1,2})[-/.](\d{4}|\d{2})\b")
# Fechas con nombre de mes: "12 de marzo de 1980", "12 mar. 2024", "1 de septiembre, 2024", "March 14, 1879"
_DATE_D_MONTH_Y = re.compile(r"\b(\d{1,2})(?:\s+de)?\s+([a-záéíóúñ]+)\.?,?(?:\s+de)?,?\s+(\d{4})\b")
_DATE_MONTH_D_Y = re.compile(r"\b([a-z]+)\.?\s+(\d{1,2})(?:st|nd|rd|th)?,?\s+(\d{4})\b")
_TIME = re.compile(r"\b(\d{1,2}):(\d{2})(?::(\d{2}))?\b")
_MESES = {
    "enero": 1, "febrero": 2, "marzo": 3, "abril": 4, "mayo": 5, "junio": 6, "julio": 7,
    "agosto": 8, "septiembre": 9, "setiembre": 9, "octubre": 10, "noviembre": 11, "diciembre": 12,
    "january": 1, "february": 2, "march": 3, "april": 4, "may": 5, "june": 6, "july": 7,
    "august": 8, "september": 9, "october": 10, "november": 11, "december": 12,
}


def _month(name: str) -> int | None:
    """Mes por nombre completo o abreviatura de 3+ letras (es/en): 'mar', 'sept', 'Dec'."""
    name = name.lower()
    if name in _MESES:
        return _MESES[name]
    if len(name) >= 3:
        for full, n in _MESES.items():
            if full.startswith(name):
                return n
    return None


def _safe_date(y: int, m: int | None, d: int) -> date | None:
    if m is None:
        return None
    if y < 100:
        y += 2000 if y < 70 else 1900
    try:
        return date(y, m, d)
    except ValueError:  # 31/02, mes 13...
        return None


def clean_str(v: str) -> str:
    return re.sub(r"\s+", " ", v).strip()


def clean_int(v: str) -> int | None:
    m = re.search(r"-?\d[\d.]*", v.replace(" ", ""))
    return int(m.group(0).replace(".", "")) if m else None


def clean_float(v: str) -> float | None:
    """Mismas reglas de separadores que money: '1.234,56' -> 1234.56 ; '3,5 kg' -> 3.5"""
    return clean_money(v)


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
    """Busca la primera fecha reconocible dentro del texto (ignora hora y texto alrededor).

    Las fechas numéricas se leen día/mes/año (convención española) salvo que empiecen por el año.
    """
    s = clean_str(v)
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00")).date()
    except ValueError:
        pass
    low = s.lower()
    if m := _DATE_YMD.search(low):
        return _safe_date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    if m := _DATE_DMY.search(low):
        return _safe_date(int(m.group(3)), int(m.group(2)), int(m.group(1)))
    if m := _DATE_D_MONTH_Y.search(low):
        return _safe_date(int(m.group(3)), _month(m.group(2)), int(m.group(1)))
    if m := _DATE_MONTH_D_Y.search(low):
        return _safe_date(int(m.group(3)), _month(m.group(1)), int(m.group(2)))
    return None


def clean_datetime(v: str) -> datetime | None:
    s = clean_str(v)
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        d = clean_date(s)
        if not d:
            return None
        t = _TIME.search(s)
        h, mi, sec = (int(t.group(1)), int(t.group(2)), int(t.group(3) or 0)) if t else (0, 0, 0)
        try:
            return datetime(d.year, d.month, d.day, h, mi, sec)
        except ValueError:
            return datetime(d.year, d.month, d.day)


def clean_phone(v: str) -> str | None:
    """Primer teléfono del texto, en formato E.164 si es español: 'Tel: 955 12 34 56' -> '+34955123456'"""
    m = _PHONE.search(v)
    if not m:
        return None
    s = _PHONE_CHARS.sub("", m.group(0))
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
