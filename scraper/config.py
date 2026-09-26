"""Modelos de configuración de un sitio (sites/*.yaml) validados con Pydantic."""
from __future__ import annotations

from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field, field_validator

FieldType = Literal["str", "int", "float", "money", "date", "datetime", "phone", "email", "url", "list"]


class Politeness(BaseModel):
    delay_seconds: float = 2.0
    max_concurrency: int = 2
    respect_robots: bool = True
    max_retries: int = 3
    timeout_seconds: float = 20.0


class FetchConfig(BaseModel):
    mode: Literal["http", "browser"] = "http"
    headers: dict[str, str] = Field(default_factory=dict)
    # Solo modo browser (F3): selector a esperar antes de leer el HTML
    wait_for: str | None = None


class Pagination(BaseModel):
    next_selector: str | None = None
    # Alternativa: plantilla con {page}, p.ej. "/listado?page={page}"
    url_template: str | None = None
    start_page: int = 1
    max_pages: int = 10


class ListConfig(BaseModel):
    item_selector: str
    detail_url: str | None = None
    # Campos que se extraen del propio bloque del listado (relativo a item_selector)
    fields: dict[str, "FieldSpec"] = Field(default_factory=dict)


class FieldSpec(BaseModel):
    selector: str | None = None  # None -> usa el texto del elemento raíz
    type: FieldType = "str"
    required: bool = False
    default: object = None
    # Para type=list: selector devuelve varios elementos
    multiple: bool = False
    # Regex opcional aplicada al texto extraído (usa el primer grupo si existe)
    regex: str | None = None


class DetailConfig(BaseModel):
    fields: dict[str, FieldSpec] = Field(default_factory=dict)


class ExportConfig(BaseModel):
    default: Literal["csv", "xlsx", "json"] = "xlsx"
    path: str | None = None


class SiteConfig(BaseModel):
    name: str
    base_url: str
    description: str | None = None
    politeness: Politeness = Field(default_factory=Politeness)
    fetch: FetchConfig = Field(default_factory=FetchConfig)
    start_urls: list[str]
    pagination: Pagination = Field(default_factory=Pagination)
    list: ListConfig
    detail: DetailConfig | None = None
    key: list[str] = Field(default_factory=list)
    export: ExportConfig = Field(default_factory=ExportConfig)

    @field_validator("base_url")
    @classmethod
    def _strip_slash(cls, v: str) -> str:
        return v.rstrip("/")

    @property
    def all_fields(self) -> dict[str, FieldSpec]:
        fields = dict(self.list.fields)
        if self.detail:
            fields.update(self.detail.fields)
        return fields

    def validate_keys(self) -> None:
        missing = [k for k in self.key if k not in self.all_fields]
        if missing:
            raise ValueError(f"Campos de 'key' no definidos en list/detail: {missing}")


ListConfig.model_rebuild()


def load_site(path: str | Path) -> SiteConfig:
    with open(path, encoding="utf-8") as f:
        raw = yaml.safe_load(f)
    cfg = SiteConfig.model_validate(raw)
    cfg.validate_keys()
    return cfg
