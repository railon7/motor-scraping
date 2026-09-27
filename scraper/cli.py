"""CLI del motor: scraper run | dry-run | export | init-site | status | validate."""
from __future__ import annotations

import logging
from pathlib import Path

import typer
from dotenv import load_dotenv
from rich.console import Console
from rich.logging import RichHandler
from rich.table import Table

from scraper import __version__
from scraper.config import ConfigError, json_schema, load_site
from scraper.engine import Engine, RunReport
from scraper.export import export_items
from scraper.storage.repo import Repo

app = typer.Typer(help="Motor de web scraping genérico (Tazuke).", invoke_without_command=True)
console = Console()

SITE_TEMPLATE = """\
# yaml-language-server: $schema=../schemas/site.schema.json
name: {name}
description: Describe aquí qué se extrae y para qué proyecto/cliente
base_url: https://www.ejemplo.es

politeness:
  delay_seconds: 2
  max_concurrency: 2
  respect_robots: true

fetch:
  mode: http            # http | browser (requiere extra 'browser')

start_urls:
  - /listado

pagination:
  next_selector: "a.siguiente::attr(href)"
  max_pages: 5

list:
  item_selector: "div.card"
  detail_url: "a.titulo::attr(href)"     # opcional; quitar si no hay página de detalle
  fields:
    titulo: {{ selector: "a.titulo", type: str, required: true }}

detail:
  fields:
    precio:   {{ selector: ".precio", type: money }}
    fecha:    {{ selector: "time::attr(datetime)", type: date }}
    telefono: {{ selector: ".telefono", type: phone }}

key: [titulo]           # clave natural para no duplicar; vacío = URL de detalle

# Opcional: avisos si los selectores se rompen (la ejecución queda 'degraded')
# expect:
#   min_items: 10
#   fill_rate: {{ precio: 0.9 }}
# track_removed: true   # marca como desaparecidos los items que dejan de verse
# cache: {{ enabled: true, ttl_hours: 24 }}

export:
  default: xlsx
"""


def _load(site: Path):
    try:
        return load_site(site)
    except ConfigError as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(2) from None


def _cache_mode(cache: bool | None, offline: bool):
    if offline:
        return "offline"
    if cache is None:
        return None
    return "on" if cache else "off"


def _setup_logging(verbose: bool) -> None:
    load_dotenv()
    import os
    level = "DEBUG" if verbose else os.getenv("LOG_LEVEL", "INFO")
    logging.basicConfig(level=level, format="%(message)s", handlers=[RichHandler(console=console, show_path=False)])
    logging.getLogger("httpx").setLevel("WARNING")


def _print_report(rep: RunReport) -> None:
    t = Table(title=f"Ejecución {rep.site}" + (" (dry-run)" if rep.dry_run else ""))
    t.add_column("Métrica")
    t.add_column("Valor", justify="right")
    t.add_row("Estado", rep.status, style=None if rep.status in ("ok", "dry-run") else "red")
    t.add_row("Páginas", f"{rep.pages} ({rep.pages_cached} de caché)" if rep.pages_cached else str(rep.pages))
    t.add_row("Items vistos", str(rep.items_seen))
    t.add_row("Nuevos", str(rep.items_new))
    t.add_row("Actualizados", str(rep.items_updated))
    t.add_row("Sin cambios", str(rep.items_unchanged))
    if rep.items_skipped:
        t.add_row("Sin volver a descargar (incremental)", str(rep.items_skipped))
    if rep.items_gone:
        t.add_row("Desaparecidos", str(rep.items_gone), style="yellow")
    t.add_row("Errores", str(rep.errors), style="red" if rep.errors else None)
    console.print(t)
    for w in rep.warnings:
        console.print(f"[bold red]Aviso:[/bold red] {w}")
    if rep.empty_fields:
        e = Table(title="Campos vacíos (revisar selectores)")
        e.add_column("Campo")
        e.add_column("Vacíos", justify="right")
        e.add_column("% sobre vistos", justify="right")
        for k, v in sorted(rep.empty_fields.items(), key=lambda kv: -kv[1]):
            pct = 100 * v / max(rep.items_seen, 1)
            e.add_row(k, str(v), f"{pct:.0f}%", style="yellow" if pct > 50 else None)
        console.print(e)


@app.callback()
def _main(ctx: typer.Context, version: bool = typer.Option(False, "--version", help="Muestra la versión")):
    if version:
        console.print(f"motor-scraping {__version__}")
        raise typer.Exit()
    if ctx.invoked_subcommand is None:
        console.print(ctx.get_help())
        raise typer.Exit()


@app.command()
def run(site: Path = typer.Argument(..., help="Ruta al YAML del sitio"),
        limit: int = typer.Option(None, help="Máximo de items a procesar"),
        export: str = typer.Option(None, help="Exportar al terminar: csv|xlsx|json"),
        cache: bool = typer.Option(None, "--cache/--no-cache", help="Usar la caché HTTP (por defecto, lo que diga el YAML)"),
        offline: bool = typer.Option(False, "--offline", help="Solo caché, sin ninguna petición a la web"),
        verbose: bool = typer.Option(False, "-v")):
    """Ejecuta el scraping y guarda en la base de datos."""
    _setup_logging(verbose)
    cfg = _load(site)
    repo = Repo()
    rep = Engine(cfg, repo, limit=limit, cache_mode=_cache_mode(cache, offline)).run_sync()
    _print_report(rep)
    fmt = export or None
    if fmt:
        out = export_items(repo.items(cfg.name), fmt, cfg.name, cfg.export.path)
        console.print(f"[green]Exportado:[/green] {out}")


@app.command("dry-run")
def dry_run(site: Path = typer.Argument(...),
            limit: int = typer.Option(10, help="Items a probar"),
            cache: bool = typer.Option(True, "--cache/--no-cache", help="Reutilizar páginas ya descargadas (por defecto sí)"),
            offline: bool = typer.Option(False, "--offline", help="Solo caché, sin ninguna petición a la web"),
            verbose: bool = typer.Option(False, "-v")):
    """Prueba selectores sin escribir en la BBDD; muestra una muestra de registros."""
    _setup_logging(verbose)
    cfg = _load(site)
    rep = Engine(cfg, repo=None, dry_run=True, limit=limit, cache_mode=_cache_mode(cache, offline)).run_sync()
    _print_report(rep)
    if rep.sample:
        console.rule("Muestra")
        for i, row in enumerate(rep.sample, 1):
            console.print(f"[bold]#{i}[/bold] {row}")


@app.command()
def export(site: Path = typer.Argument(...),
           fmt: str = typer.Option(None, "--fmt", "-f", help="csv|xlsx|json (defecto: el del YAML)"),
           out: Path = typer.Option(None, "--out", "-o"),
           solo_activos: bool = typer.Option(False, "--solo-activos", help="Excluir los items marcados como desaparecidos")):
    """Exporta los items almacenados de un sitio."""
    _setup_logging(False)
    cfg = _load(site)
    repo = Repo()
    items = repo.items(cfg.name, include_gone=not solo_activos)
    if not items:
        console.print("[yellow]No hay items almacenados para este sitio.[/yellow]")
        raise typer.Exit(1)
    path = export_items(items, fmt or cfg.export.default, cfg.name, str(out) if out else cfg.export.path)
    console.print(f"[green]{len(items)} items exportados a[/green] {path}")


@app.command()
def status(site: Path = typer.Argument(None, help="YAML del sitio (opcional: todos si se omite)")):
    """Muestra las últimas ejecuciones."""
    _setup_logging(False)
    repo = Repo()
    name = _load(site).name if site else None
    runs = repo.last_runs(name)
    t = Table(title="Últimas ejecuciones")
    for c in ("id", "site", "estado", "inicio", "págs", "nuevos", "actualiz.", "igual", "saltados", "desaparec.", "errores"):
        t.add_column(c)
    for r in runs:
        style = None if r.status in ("ok", "dry-run", "running") else "red"
        t.add_row(str(r.id), r.site, r.status, f"{r.started_at:%Y-%m-%d %H:%M}", str(r.pages),
                  str(r.items_new), str(r.items_updated), str(r.items_unchanged), str(r.items_skipped or 0),
                  str(r.items_gone or 0), str(r.errors), style=style)
    console.print(t)
    for r in runs:
        if r.notes:
            console.print(f"[red]Run {r.id}:[/red] {r.notes}")
    if name:
        total, active = repo.count_items(name), repo.count_items(name, include_gone=False)
        console.print(f"Items almacenados para [bold]{name}[/bold]: {total} ({active} activos)")


@app.command()
def validate(site: Path = typer.Argument(...)):
    """Valida la sintaxis del YAML sin ejecutar nada."""
    cfg = _load(site)
    console.print(f"[green]OK[/green] {cfg.name}: {len(cfg.all_fields)} campos, key={cfg.key}, modo={cfg.fetch.mode}")


@app.command()
def schema(out: Path = typer.Option(Path("schemas/site.schema.json"), "--out", "-o")):
    """Genera el JSON Schema del YAML de sitio (autocompletado y validación en VS Code)."""
    import json
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(json_schema(), ensure_ascii=False, indent=2), encoding="utf-8")
    console.print(f"[green]Esquema escrito en[/green] {out}. Con la extensión YAML de VS Code, la primera línea "
                  "'# yaml-language-server: $schema=../schemas/site.schema.json' del YAML activa el autocompletado.")


@app.command("init-site")
def init_site(name: str = typer.Argument(..., help="Nombre del sitio (sin espacios)"),
              sites_dir: Path = typer.Option(Path("sites"))):
    """Genera un YAML esqueleto en sites/<nombre>.yaml."""
    sites_dir.mkdir(parents=True, exist_ok=True)
    path = sites_dir / f"{name}.yaml"
    if path.exists():
        console.print(f"[red]Ya existe[/red] {path}")
        raise typer.Exit(1)
    path.write_text(SITE_TEMPLATE.format(name=name), encoding="utf-8")
    console.print(f"[green]Creado[/green] {path}. Edita selectores y prueba con: scraper dry-run {path}")


if __name__ == "__main__":
    app()
