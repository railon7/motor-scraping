# Convenciones del repositorio

- **Idioma**: documentación, mensajes de la CLI y nombres de campos en español; nombres de módulos, clases y funciones en inglés (convención Python).
- **Núcleo vs. sitios**: nada específico de una web en `scraper/`. Si un sitio necesita lógica propia, se añade un módulo en `sites/<nombre>.py` (previsto en F4 como *hook* opcional) y se documenta en su YAML.
- **Tipos nuevos**: se añaden en `scraper/pipeline/clean.py` con su test en `tests/test_clean.py`.
- **Tests**: todo cambio en el núcleo lleva test; los tests no salen a internet (fixtures en `tests/fixtures`).
- **Datos**: `data/` nunca se versiona. Los exports llevan el nombre del sitio y la fecha.
- **Ramas y commits**: `main` estable; ramas `feat/...`, `fix/...`; commits en español, imperativo ("Añade tipo money").
- **Versionado**: `scraper/__init__.py` y `pyproject.toml` en sincronía; CHANGELOG.md por versión.
- **Clonado a un proyecto**: se clona el repo completo, se borran los sitios de ejemplo y se añaden los del proyecto. Mejoras del núcleo se devuelven a este repo por PR, no se quedan en el clon.
