# Consideraciones legales y de cortesía

Lista de comprobación antes de dar de alta un sitio. No es asesoramiento jurídico; ante dudas, consultar.

## Antes de scrapear

- [ ] ¿Existe una **API oficial** o un dataset descargable? Si sí, úsalo en lugar de scrapear.
- [ ] Revisa `robots.txt` y los **términos de uso** del sitio. Si prohíben expresamente la extracción automatizada, documenta la decisión y valora no hacerlo.
- [ ] ¿Los datos son **públicos** y accesibles sin iniciar sesión? El motor no está pensado para zonas autenticadas.
- [ ] ¿Se recogen **datos personales** (nombres, teléfonos, emails de personas físicas)? Entonces aplica el RGPD: necesitas base jurídica, finalidad definida, minimización y plazo de conservación. Documéntalo aquí abajo.
- [ ] ¿El contenido está protegido por **propiedad intelectual** (textos completos, imágenes)? Extrae solo los datos necesarios, no reproduzcas obras.
- [ ] Bases de datos: el derecho *sui generis* protege extracciones sustanciales. Evita volcados masivos de la totalidad de una base de datos ajena.

## Durante

- Identifícate (`USER_AGENT` con contacto), respeta `robots.txt`, mantén `delay_seconds` y `max_concurrency` bajos, no evadas captchas ni bloqueos. Si el sitio bloquea, para y reconsidera.
- `robots.txt` puede tener reglas con comodines (`/txt.php?*lang=ca`) y subdominios con políticas distintas: revísalo **en cada subdominio** que vayas a rastrear. Ejemplo real: `www.boe.es` permite casi todo, pero `subastas.boe.es` prohíbe todos los robots (`Disallow: /`).

## Registro por sitio

| Sitio | Datos extraídos | Datos personales | Base jurídica / finalidad | Conservación | Responsable | Fecha |
|---|---|---|---|---|---|---|
| ejemplo-quotes | citas, autores (sandbox público) | no | — | — | — | 2026-09-26 |
| boe-licitaciones | anuncios de licitación de la sección V-A del BOE (órgano, objeto, tipo, CPV, texto) vía API de datos abiertos + `txt.php` | residual (nombres de firmantes y contactos institucionales dentro del texto) | Información pública del BOE, reutilizable citando la fuente (condiciones de reutilización de la AEBOE); finalidad: detección de oportunidades de contratación | Mientras sea útil comercialmente; revisar anualmente | Tazuke | 2026-09-27 |

Notas BOE: `subastas.boe.es` prohíbe todos los robots (no usar); `www.boe.es/robots.txt` prohíbe `xml.php` y fichas concretas de `txt.php` (retiradas), que el motor respeta. Ampliar a la sección V-B implica notificaciones con datos personales de particulares: requiere documentar base jurídica y minimizar campos antes de activarlo.
