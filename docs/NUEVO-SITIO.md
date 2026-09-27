# Añadir un sitio nuevo

## 1. Inspeccionar la web

Abre el listado en el navegador, F12 → Elements. Identifica:

- El **bloque repetido** de cada registro (p. ej. `div.card`, `article`, `tr`). Será `list.item_selector`.
- Dentro de ese bloque, los elementos con cada dato y, si existe, el **enlace a la ficha de detalle**.
- Cómo se pasa de página: enlace "Siguiente" (`pagination.next_selector`) o URL con número (`pagination.url_template: "/listado?page={page}"`).

Comprueba también si el HTML llega ya renderizado (Ver código fuente muestra los datos) o se pinta con JavaScript (entonces `fetch.mode: browser`).

## 2. Crear la configuración

```bash
scraper init-site mi-sitio
```

Edita `sites/mi-sitio.yaml`. Referencia de campos:

```yaml
fields:
  titulo:   { selector: "h2 a", type: str, required: true }
  url:      { selector: "h2 a::attr(href)", type: url }       # href/src se convierten en absolutas
  precio:   { selector: ".precio", type: money }               # "1.234,56 €" -> 1234.56
  fecha:    { selector: "time::attr(datetime)", type: date }   # ISO, dd/mm/aaaa, "12 de marzo de 2024"
  telefono: { selector: ".tel", type: phone }                  # -> +34XXXXXXXXX
  email:    { selector: ".mail", type: email }
  tags:     { selector: "a.tag", type: list }                  # todos los elementos que coincidan
  ref:      { selector: ".ref", type: str, regex: "Ref\\.\\s*(\\w+)" }  # primer grupo de la regex
  estado:   { selector: ".estado", type: str, default: "desconocido" }
```

Los campos de `list.fields` se extraen del bloque del listado; los de `detail.fields`, de la página de detalle (se descarga una por item si hay `list.detail_url`). Si un campo aparece en ambos, gana el detalle.

**Antes de escribir selectores CSS, mira si la página trae datos estructurados** (Ver código fuente → busca `application/ld+json` o `og:`). Cambian mucho menos que la maquetación:

```yaml
fields:
  nombre: { selector: "jsonld:Product.name" }                 # schema.org en JSON-LD
  precio: { selector: "jsonld:Product.offers.price", type: money }
  fotos:  { selector: "jsonld:Product.image[*]", type: list } # [*] = todos; [1] = el segundo
  imagen: { selector: "meta:og:image", type: url }            # <meta property|name|itemprop=...>
  # Varias alternativas: se usa la primera que dé valor
  titulo: { selector: ["jsonld:Article.headline", "meta:og:title", "h1"], required: true }
  fecha:  { selector: ".fecha", type: date }                  # también "hace 3 días", "ayer"
```

**Autocompletado:** la primera línea `# yaml-language-server: $schema=../schemas/site.schema.json` (la pone `init-site`) activa sugerencias y validación en VS Code con la extensión YAML de Red Hat. Si cambias el motor, regenera el esquema con `scraper schema`. Una clave mal escrita da error con sugerencia (`selecter` → "¿quisiste decir 'selector'?").

## 3. Clave natural

`key: [campo1, campo2]` identifica un registro entre ejecuciones. Elige campos estables (referencia, título+fecha, URL). Si no se indica, se usa la URL de detalle (o la del listado, lo que provocaría colisiones: evítalo).

## 4. Probar

```bash
scraper dry-run sites/mi-sitio.yaml --limit 5 -v
```

Mira la tabla **Campos vacíos**: un campo con muchos vacíos casi siempre es un selector mal escrito. Ajusta y repite hasta que la muestra tenga buena pinta.

`dry-run` guarda las páginas en caché (`data/cache/<sitio>/`), así que repetirlo mientras ajustas selectores no vuelve a pedir nada al sitio. `--offline` garantiza cero peticiones; `--no-cache` fuerza descargar de nuevo.

## 5. Ejecutar y exportar

```bash
scraper run sites/mi-sitio.yaml --export xlsx
```

Repetir la ejecución no duplica: los registros idénticos cuentan como "sin cambios"; los que cambian se actualizan y conservan `first_seen`.

## 6. Ejecuciones periódicas: incremental, desaparecidos y avisos

```yaml
detail:
  refresh_days: 7        # no vuelve a descargar un detalle si el listado no cambió y se bajó hace < 7 días
  fields: { ... }
track_removed: true      # marca gone_at en los items que dejan de publicarse
expect:                  # si no se cumple, la ejecución queda 'degraded' (selectores rotos)
  min_items: 20
  fill_rate: { precio: 0.9, fecha: 0.8 }
cache: { enabled: true, ttl_hours: 24 }
```

- Un item solo se marca como desaparecido tras una ejecución **completa y sana** (sin `--limit`, sin fallos de descarga, sin `degraded` y con menos de un 20 % de items inválidos). Si reaparece, se reactiva.
- Si falla la descarga de un detalle, el item no se toca: nunca se sustituyen datos completos por parciales.
- `scraper status` muestra el estado de cada ejecución (`ok`, `degraded`, `aborted`, `error`, `interrupted`) y el motivo. `export --solo-activos` excluye los desaparecidos; el resto de exports incluyen la columna `_gone_at`.

## 7. Cortesía

Deja `delay_seconds` en 1–3 s y `max_concurrency` en 1–2 salvo que el sitio sea claramente robusto. `respect_robots: true` siempre, salvo acuerdo con el propietario. Identifícate en `USER_AGENT` (`.env`).

El motor ya aplica por su cuenta: el `Crawl-delay` de robots.txt si es mayor que tu `delay_seconds`; frenar todo el dominio ante un 429 respetando `Retry-After`; no rastrear si robots.txt da error 5xx; y abortar la ejecución tras `politeness.max_consecutive_errors` (20 por defecto) fallos de descarga seguidos.
