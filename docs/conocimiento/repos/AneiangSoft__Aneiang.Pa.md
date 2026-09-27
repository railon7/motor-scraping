# AneiangSoft/Aneiang.Pa
> C# (.NET) · MIT · ⭐ 71 · Último push 2026-06-22 · https://github.com/AneiangSoft/Aneiang.Pa

## Qué es (2-3 líneas)
Librería .NET para obtener "listas calientes" (hot lists) de plataformas chinas y otras (Weibo, Zhihu, GitHub Trending...) con **una receta (recipe) YAML por plataforma**. Lema del README (en chino): "una línea de código para obtener datos, un YAML para añadir una plataforma". Documentación y comentarios en chino; lo resumido aquí está traducido.

## Arquitectura en breve
- Modelo común `ScraperRecipe` (`src/Aneiang.Pa.Abstractions/ScraperRecipe.cs`): `Name`, `Category`, `DisplayName`, `Fetch` (`FetchSpec.cs`), `Parse` (`ParseSpec.cs`) y `Middlewares` por receta.
- **Tres fuentes de recetas que convergen en el mismo modelo** (`IRecipeProvider`): YAML en carpeta/recursos embebidos (`Core/Recipes/YamlRecipeProvider.cs`), JSON (`JsonRecipeProvider.cs`), DSL fluida en C# (`RecipeBuilder.cs`) y clases con atributos `[Recipe][Get][Container][Selector]` (`RecipeAttributes.cs`, `AttributeRecipeProvider.cs`).
- **Parsers polimórficos por `parse.type`**: `html` (CSS o `xpath:` prefijo, `HtmlResponseParser.cs`), `json` (JSONPath, `JsonResponseParser.cs`), `regex` con grupos con nombre (`RegexResponseParser.cs`), `embedded` (JSON incrustado en HTML, `EmbeddedJsonResponseParser.cs`).
- Post-proceso por campo fijo y ordenado en `Core/Parsing/FieldPostProcessor.cs`.
- **Middlewares** tipo ASP.NET (`IScrapeMiddleware`, `Order`, `InvokeAsync(ctx, next)`): Logging, Metrics, Tracing, Cache, CircuitBreaker, Retry, Timeout, RateLimit (`src/Aneiang.Pa/Core/Middlewares/`).
- 20 recetas incluidas en `src/Aneiang.Pa/BuiltInRecipes/*.yaml`.

## Técnicas que nos interesan

### 1. `parse.type` polimórfico: html / json / regex / embedded
- **Qué hace**: la misma receta cambia de motor de extracción según el tipo de respuesta; `json` usa `items_path` (JSONPath) y rutas con puntos para campos; `embedded` saca con una regex el JSON que viene incrustado en el HTML y luego lo trata como `json`.
- **Fragmento** (`BuiltInRecipes/baidu.yaml`):
  ```yaml
  parse:
    type: embedded
    extract_pattern: "<!--s-data:(.*?)-->"
    items_path: $.data.cards[0].content
    filter_field: isTop
    filter_equals_value: "True"
    fields:
      title: { selector: "word", trim: true }
  ```
- **Por qué importa**: muchas webs modernas llevan los datos en `<script type="application/ld+json">`, `__NEXT_DATA__` o una API JSON pública. Extraer de ahí es **más estable y más cortés** (menos peticiones, sin navegador) que CSS sobre HTML renderizado. Nosotros solo parseamos HTML.

### 2. XPath por prefijo en el mismo campo `selector`
- `HtmlResponseParser.cs`: si el selector empieza por `xpath:` se evalúa como XPath; si no, CSS. Compatible hacia atrás y sin claves nuevas. Encaja con nuestros sufijos `::text/::attr()`.

### 3. Post-proceso declarativo por campo (orden fijo)
- **Qué hace**: `default` → `collapse` (espacios) → `trim` → `regex` (primer grupo) → `map` (tabla de traducción de valores) → `base` (URL absoluta) → `url_encode` → `format` (plantilla con `{value}`).
- **Cómo**: `FieldPostProcessor.Apply`.
- **Por qué importa**: `map` (p. ej. `"Sí"→true`, `"Vendido"→"sold"`) y `format` (p. ej. `"https://x.es/ficha/{value}"`) son dos transformaciones que nos faltan. El orden fijo es simple pero rígido: preferimos lista ordenada (ver MagicBox), manteniendo claves sueltas como azúcar.

### 4. Filtro de items declarativo
- `filter_field` + `filter_equals_value` para descartar items (p. ej. fijados/publicidad). Versión mínima de un `skip_if`/`when` por item.

### 5. Variables de contexto `{token}` rellenadas por código
- **Qué hace**: la receta usa `{token}` en cabeceras/URL; un middleware propio pone `ctx.Variables["token"]` antes de la petición (README, sección de middleware personalizado).
- **Por qué importa**: patrón limpio para separar credenciales/valores dinámicos (API key del propio cliente, fecha de hoy) del YAML: `{vars.x}`, `{env:X}`, `{today}`.

### 6. Varias fuentes de receta → un único modelo
- YAML, JSON, builder y atributos producen el mismo `ScraperRecipe`. Para nosotros: el YAML se valida a Pydantic, así que un sitio puede definirse también en Python (`SiteConfig(...)`) para casos especiales o tests, sin segundo formato.

### 7. Middlewares con orden y configuración por receta
- `ScraperRecipe.Middlewares` permite ajustar retry/cache/rate-limit por receta; los globales se registran en `PaContainer.cs`. Útil como modelo de nuestros "hooks" (`before_request`, `after_item`).

### 8. Catálogo de recetas incluidas + guía "contribuir en 3 pasos"
- README: crear `.yaml` en `recipes/`, probar, PR. Nuestra carpeta `sites/` con ejemplos variados (HTML, JSON-LD, API JSON) serviría igual como documentación viva.

## Qué aplicaríamos en nuestro motor

| # | Propuesta | Módulo afectado | Cambio en YAML | Esfuerzo | Prioridad |
|---|---|---|---|---|---|
| 1 | `parse: json` a nivel de listado/detalle (respuesta JSON) con `items_path` y campos por ruta con puntos (`json: data.precio`) | `config.py`, nuevo `parse/jsonpath.py`, `engine.py` | `list: {format: json, items_path: "data.items", fields: {precio: {json: "price.amount", type: money}}}` | M | 1 |
| 2 | Fuente `embedded`: `script` (`script#__NEXT_DATA__`, `ld+json`) o regex que devuelve JSON, luego rutas JSON | `parse/`, `pipeline/extract.py` | `fields: {sku: {script: "script[type='application/ld+json']", json: "sku"}}` | S | 1 |
| 3 | XPath por prefijo `xpath:` en `selector` (con `lxml`/`parsel`) | `parse/selectors.py` | `selector: "xpath://td[contains(.,'Ref')]/following-sibling::td"` | S | 1 |
| 4 | Transformaciones `map` y `format`/`template` | `pipeline/transforms.py` | `transform: [{map: {"Sí": true, "No": false}}]` | S | 2 |
| 5 | Filtro de items `skip_if` sencillo (campo igual/contiene/regex) | `engine.py` | `list: {skip_if: {field: tipo, equals: "Publicidad"}}` | S | 2 |
| 6 | Variables `{vars.x}`, `{env:X}`, `{today:%Y-%m-%d}` en URLs y cabeceras | `config.py` (interpolación al cargar) | `headers: {Authorization: "Bearer {env:API_KEY}"}` | S | 2 |

## Qué NO copiaríamos y por qué
- **`DouYinCookieMiddleware.cs`**: su propio comentario dice que obtiene cookies de la página de login para no ser bloqueado por el anti-scraping. Es evasión: fuera.
- **`Core/UserAgents.cs` con UA aleatorio de navegador**: suplantación; nosotros usamos UA identificable.
- **`YamlRecipeProvider` con `IgnoreUnmatchedProperties` y excepciones tragadas** (solo `Debug.WriteLine`): una receta mal escrita desaparece en silencio. Es el antipatrón exacto que queremos evitar; nosotros fallamos alto y claro.
- **Clave `selector` reutilizada para CSS, XPath y JSONPath**: ambigua; preferimos claves distintas (`selector`, `xpath:` prefijo explícito, `json`).
- **Orden fijo de post-proceso**: poco flexible frente a una lista `transform`.
- **Recetas de plataformas con condiciones de uso restrictivas** (redes sociales): no son casos que queramos cubrir.
- Licencia MIT: ideas libres, no copiamos código.
