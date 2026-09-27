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
