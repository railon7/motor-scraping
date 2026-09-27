"""Modelos de configuración de un sitio (sites/*.yaml) validados con Pydantic.

Las claves desconocidas se rechazan (una errata como `selecter:` no debe pasar en silencio)
y los errores se devuelven en castellano con la ruta del campo y una sugerencia.
"""
from __future__ import annotations

import difflib
from pathlib import Path
from typing import Literal, get_args

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

FieldType = Literal["str", "int", "float", "money", "date", "datetime", "phone", "email", "url", "list"]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Politeness(_Strict):
    delay_seconds: float = Field(2.0, description="Pausa mínima entre peticiones al mismo dominio. Si robots.txt pide un Crawl-delay mayor, se usa ese.")
    max_concurrency: int = 2
    respect_robots: bool = True
    max_retries: int = 3
    timeout_seconds: float = 20.0
    retry_status: list[int] = Field(default_factory=lambda: [408, 429, 500, 502, 503, 504],
                                    description="Códigos HTTP temporales que se reintentan; el resto de 4xx son definitivos.")
    max_consecutive_errors: int = Field(20, description="Cortacircuitos: aborta la ejecución tras N errores de descarga seguidos (0 = desactivado).")


class CacheConfig(_Strict):
    enabled: bool = Field(False, description="Guarda las respuestas en data/cache/<sitio>/. dry-run la usa siempre.")
    ttl_hours: float = Field(24, description="Horas que una respuesta se considera fresca; después se revalida con ETag/Last-Modified.")


class FetchConfig(_Strict):
    mode: Literal["http", "browser"] = "http"
    headers: dict[str, str] = Field(default_factory=dict)
    # Solo modo browser (F3): selector a esperar antes de leer el HTML
    wait_for: str | None = None


class Pagination(_Strict):
    next_selector: str | None = None
    # Alternativa: plantilla con {page}, p.ej. "/listado?page={page}"
    url_template: str | None = None
    start_page: int = 1
    max_pages: int = 10


class FieldSpec(_Strict):
    selector: str | list[str] | None = Field(
        None, description="CSS con sufijo ::text/::attr(x)/::html, o 'jsonld:Tipo.ruta', o 'meta:og:title'. "
                          "Una lista prueba cada selector en orden y se queda con el primero que dé valor. "
                          "Vacío = texto del elemento raíz.")
    type: FieldType = "str"
    required: bool = False
    default: object = None
    # Para type=list: selector devuelve varios elementos
    multiple: bool = False
    # Regex opcional aplicada al texto extraído (usa el primer grupo si existe)
    regex: str | None = None

    @property
    def selectors(self) -> list[str]:
        if self.selector is None:
            return []
        return [self.selector] if isinstance(self.selector, str) else list(self.selector)


class ListConfig(_Strict):
    item_selector: str
    detail_url: str | None = None
    # Campos que se extraen del propio bloque del listado (relativo a item_selector)
    fields: dict[str, FieldSpec] = Field(default_factory=dict)


class DetailConfig(_Strict):
    fields: dict[str, FieldSpec] = Field(default_factory=dict)
    refresh_days: float | None = Field(
        None, description="Modo incremental: no vuelve a descargar el detalle de un item ya guardado si los campos "
                          "del listado no cambiaron y se descargó hace menos de N días. Vacío = siempre se descarga.")


class Expect(_Strict):
    min_items: int | None = Field(None, description="Mínimo de items por ejecución completa; por debajo la ejecución queda 'degraded'.")
    fill_rate: dict[str, float] = Field(default_factory=dict,
                                        description="Proporción mínima (0-1) de items con el campo relleno, p. ej. {precio: 0.9}.")


class ExportConfig(_Strict):
    default: Literal["csv", "xlsx", "json"] = "xlsx"
    path: str | None = None


class SiteConfig(_Strict):
    name: str
    base_url: str
    description: str | None = None
    politeness: Politeness = Field(default_factory=Politeness)
    fetch: FetchConfig = Field(default_factory=FetchConfig)
    cache: CacheConfig = Field(default_factory=CacheConfig)
    start_urls: list[str]
    pagination: Pagination = Field(default_factory=Pagination)
    list: ListConfig
    detail: DetailConfig | None = None
    key: list[str] = Field(default_factory=list)
    track_removed: bool = Field(False, description="Marca como desaparecidos (gone_at) los items que dejan de verse en una ejecución completa y sana.")
    expect: Expect = Field(default_factory=Expect)
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
            raise ConfigError(f"Campos de 'key' no definidos en list/detail: {missing}")
        unknown = [k for k in self.expect.fill_rate if k not in self.all_fields]
        if unknown:
            raise ConfigError(f"Campos de 'expect.fill_rate' no definidos en list/detail: {unknown}")


class ConfigError(ValueError):
    """Error de configuración con mensaje legible para quien edita el YAML."""


def _allowed_keys(loc: tuple) -> list[str]:
    """Claves válidas en la posición `loc` del YAML (para sugerir ante una errata)."""
    def submodel(annotation) -> type[BaseModel] | None:
        # DetailConfig | None -> DetailConfig ; dict[str, FieldSpec] -> FieldSpec
        for a in get_args(annotation) or (annotation,):
            if isinstance(a, type) and issubclass(a, BaseModel):
                return a
            if get_args(a):
                found = submodel(a)
                if found:
                    return found
        return None

    model: type[BaseModel] | None = SiteConfig
    for part in loc[:-1]:
        if model is None or isinstance(part, int):
            continue
        if part in model.model_fields:
            model = submodel(model.model_fields[part].annotation)
        # si no, `part` es una clave libre de un dict (nombre de campo) y el modelo no cambia
    return list(model.model_fields) if model else []


def format_validation_error(err: ValidationError, source: str) -> str:
    lines = [f"Configuración no válida en {source}:"]
    for e in err.errors():
        loc = tuple(e["loc"])
        path = ".".join(str(p) for p in loc) or "(raíz)"
        if e["type"] == "extra_forbidden":
            msg = "clave desconocida"
            close = difflib.get_close_matches(str(loc[-1]), _allowed_keys(loc), n=1)
            if close:
                msg += f"; ¿quisiste decir '{close[0]}'?"
        elif e["type"] == "missing":
            msg = "falta este campo obligatorio"
        else:
            msg = e["msg"]
        lines.append(f"  - {path}: {msg}")
    return "\n".join(lines)


def load_site(path: str | Path) -> SiteConfig:
    with open(path, encoding="utf-8") as f:
        raw = yaml.safe_load(f)
    try:
        cfg = SiteConfig.model_validate(raw)
    except ValidationError as e:
        raise ConfigError(format_validation_error(e, str(path))) from None
    cfg.validate_keys()
    return cfg


def json_schema() -> dict:
    """JSON Schema del YAML de sitio (autocompletado y validación en VS Code con la extensión YAML)."""
    schema = SiteConfig.model_json_schema()
    schema["title"] = "Motor Scraping · configuración de sitio"
    return schema
