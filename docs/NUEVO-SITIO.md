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

## 3. Clave natural

`key: [campo1, campo2]` identifica un registro entre ejecuciones. Elige campos estables (referencia, título+fecha, URL). Si no se indica, se usa la URL de detalle (o la del listado, lo que provocaría colisiones: evítalo).

## 4. Probar

```bash
scraper dry-run sites/mi-sitio.yaml --limit 5 -v
```

Mira la tabla **Campos vacíos**: un campo con muchos vacíos casi siempre es un selector mal escrito. Ajusta y repite hasta que la muestra tenga buena pinta.

## 5. Ejecutar y exportar

```bash
scraper run sites/mi-sitio.yaml --export xlsx
```

Repetir la ejecución no duplica: los registros idénticos cuentan como "sin cambios"; los que cambian se actualizan y conservan `first_seen`.

## 6. Cortesía

Deja `delay_seconds` en 1–3 s y `max_concurrency` en 1–2 salvo que el sitio sea claramente robusto. `respect_robots: true` siempre, salvo acuerdo con el propietario. Identifícate en `USER_AGENT` (`.env`).
