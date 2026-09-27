# Metodología de la investigación

Fecha: 2026-09-27 · Objetivo: aprender de proyectos open source de scraping para mejorar el motor, sin reinventar lo que otros ya resolvieron.

## 1. Búsqueda

Búsqueda en GitHub (`gh search repos`, ordenada por estrellas, 15–20 resultados por consulta) con las palabras clave del proyecto traducidas a 10 idiomas, más *topics* de GitHub:

| Idioma | Palabras clave |
|---|---|
| Inglés | web scraping framework, web crawler framework, scraping engine, config driven scraper, yaml scraper, scraping yaml, json scraper config, polite crawler, incremental crawler, content extraction html, scrapy alternative, no-code scraper, selector scraper declarative, llm web scraper |
| *Topics* | web-scraping, crawler, scraper, web-crawler, scraping-framework, spider, data-extraction, crawling |
| Español | motor de scraping, rastreador web, extracción de datos web, scraper español, scraping boe |
| Portugués | raspagem de dados, web scraping python brasil, crawler python dados |
| Chino | 爬虫框架 (framework de crawler), 网络爬虫 (crawler web), 通用爬虫 (crawler genérico), 配置化爬虫 (crawler configurable), 爬虫, 采集器 (recolector) |
| Japonés | スクレイピング, クローラー, スクレイパー |
| Ruso | парсер сайтов, веб скрапинг, парсер, краулер |
| Coreano | 웹 크롤러, 크롤링 |
| Alemán | webcrawler, scraper deutsch |
| Francés | extraction de données, scraper français, robot d'exploration |

Resultado: **654 repos únicos** tras filtrar ruido → [catalogo.md](catalogo.md).

Observaciones de la búsqueda:
- En inglés y chino está la masa crítica. En chino abundan tutoriales y scrapers de plataformas concretas (Weibo, Douyin, Xiaohongshu), poco reutilizables, y plataformas visuales "sin código" (EasySpider, spider-flow, 蓝天采集器/skycaiji).
- En español y portugués hay casi solo tutoriales y scripts de datos públicos (BOE, diarios oficiales, tribunales). El proyecto brasileño **querido-diario** es la excepción: cientos de spiders de diarios oficiales sobre una base común, justo el modelo "plantilla + configuración por sitio".
- En ruso y coreano predominan parsers de marketplaces concretos (Avito, Wildberries, 2GIS, Coupang).
- Una parte grande del ecosistema de 2026 gira en torno a LLMs (firecrawl, crawl4ai, ScrapeGraphAI, stagehand) y a la evasión anti-bot (CloakBrowser, camofox, botasaurus). Lo segundo queda **fuera de alcance** por el principio de cortesía y legalidad del PLAN.

## 2. Selección (24 repos)

Criterios: (1) relevancia para un motor genérico dirigido por configuración; (2) código mantenido o de referencia histórica; (3) diversidad de lenguajes y orígenes; (4) cubrir los huecos conocidos del motor (caché, reanudar, incremental, selectores rotos, datos estructurados, LLM, piloto BOE).

| Tema | Repos |
|---|---|
| Núcleo de referencia e incremental | scrapy/scrapy, scrapy-plugins/scrapy-deltafetch, okfn-brasil/querido-diario (🇧🇷) |
| Colas, cortesía y reanudación | apify/crawlee-python, gocolly/colly (Go), PuerkitoBio/gocrawl (Go), RuedigerVoigt/exoskeleton |
| Configuración declarativa | alephdata/memorious, ShivrajY/MagicBox (C#), joseconstela/webparsy (JS), AneiangSoft/Aneiang.Pa (C#, 🇨🇳), MontFerret/ferret (Go) |
| Robustez ante cambios de la web | D4Vinci/Scrapling, alirezamika/autoscraper, dgtlmoon/changedetection.io |
| Extracción de contenido y datos estructurados | adbar/trafilatura, scrapinghub/extruct, hhursev/recipe-scrapers, kingname/GeneralNewsExtractor (🇨🇳) |
| LLM, planificación y piloto | unclecode/crawl4ai, binux/pyspider (🇨🇳), PaulMcInnis/JobFunnel, dmi3kno/polite (R), Quantika14/BOE-scraping (🇪🇸) |

## 3. Análisis

Seis analistas en paralelo, uno por tema. Cada uno clonó sus repos, leyó el código real (no solo el README) y escribió una ficha por repo en [repos/](repos/) con la misma plantilla: qué es, arquitectura, técnicas con rutas de fichero, qué aplicaríamos (esfuerzo y prioridad) y qué no copiaríamos.

Reglas: no se copia código literal (solo patrones descritos con palabras propias; la licencia de cada repo consta en su ficha, y los GPL/AGPL se usan solo como fuente de ideas) y nada de evasión anti-bot.

## 4. Síntesis y aplicación

- [aprendizajes.md](aprendizajes.md): conclusiones transversales y hoja de ruta priorizada.
- Lo aplicado en el código está en el CHANGELOG (versión 0.2.0) y en la PR `mejoras-conocimiento`.
