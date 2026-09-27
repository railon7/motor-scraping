"""Exportadores: vuelcan los items de un sitio a CSV / XLSX / JSON."""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import pandas as pd

from scraper.storage.models import Item

XLSX_MAX_CELL = 32767


def items_to_dataframe(items: list[Item]) -> pd.DataFrame:
    rows = []
    for it in items:
        row = dict(it.data)
        row["_url"] = it.source_url
        row["_first_seen"] = it.first_seen
        row["_last_seen"] = it.last_seen
        row["_gone_at"] = it.gone_at  # vacío = sigue publicado
        rows.append(row)
    df = pd.DataFrame(rows)
    # listas -> texto separado por "; " para CSV/Excel
    for col in df.columns:
        if df[col].map(lambda v: isinstance(v, list)).any():
            df[col] = df[col].map(lambda v: "; ".join(map(str, v)) if isinstance(v, list) else v)
    return df


def export_items(items: list[Item], fmt: str, site: str, path: str | None = None) -> Path:
    fmt = fmt.lower()
    out = Path(path) if path else Path("data") / f"{site}_{datetime.now():%Y%m%d_%H%M}.{fmt}"
    out.parent.mkdir(parents=True, exist_ok=True)
    df = items_to_dataframe(items)
    if fmt == "csv":
        df.to_csv(out, index=False, sep=";", encoding="utf-8-sig")  # abre bien en Excel ES
    elif fmt == "xlsx":
        # Excel admite como máximo 32.767 caracteres por celda (textos largos como el cuerpo de un anuncio)
        for col in df.columns:
            if df[col].map(lambda v: isinstance(v, str) and len(v) > XLSX_MAX_CELL).any():
                df[col] = df[col].map(lambda v: v[: XLSX_MAX_CELL - 1] + "…" if isinstance(v, str) and len(v) > XLSX_MAX_CELL else v)
        df.to_excel(out, index=False, sheet_name=site[:31])
    elif fmt == "json":
        out.write_text(json.dumps(df.to_dict(orient="records"), ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    else:
        raise ValueError(f"Formato no soportado: {fmt}")
    return out
