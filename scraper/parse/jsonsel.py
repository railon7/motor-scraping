"""Rutas sobre documentos JSON (APIs) para `fetch.format: json`.

Sintaxis (inspirada en JSONPath, simplificada):
    titulo                  -> clave del item actual
    url_pdf.texto           -> claves anidadas; al atravesar una lista se recorren todos sus elementos
    imagenes[0] / imagenes[*]
    ..item                  -> búsqueda recursiva: todos los valores de la clave `item` a cualquier profundidad
    $.data.metadatos.fecha  -> desde la raíz del documento
    @seccion.nombre         -> desde el ancestro más cercano al que se llegó por la clave `seccion`

`@ancestro` permite que un item de una respuesta anidada (sección -> departamento -> item)
recupere datos de sus contenedores, que es justo lo que se pierde al "aplanar" la lista.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

_TOKEN = re.compile(r"\.\.(?P<desc>[^.\[\]]+)|\.?(?P<key>[^.\[\]@$]+)|\[(?P<idx>\d+|\*)\]|(?P<root>^\$)|(?P<anc>^@[^.\[\]]+)")


@dataclass(frozen=True)
class JsonNode:
    value: object
    root: object = field(repr=False, default=None)
    ancestors: tuple = field(repr=False, default=())  # ((clave, dict), ...) desde la raíz

    def child(self, key: str, value) -> "JsonNode":
        anc = self.ancestors + ((key, value),) if isinstance(value, (dict, list)) else self.ancestors
        return JsonNode(value, self.root, anc)

    def element(self, value) -> "JsonNode":
        # Elemento de una lista: el ancestro que llegó por la clave de la lista pasa a ser el elemento,
        # así `@seccion` apunta a la sección concreta y no a la lista de secciones
        if self.ancestors and self.ancestors[-1][1] is self.value:
            key = self.ancestors[-1][0]
            anc = self.ancestors[:-1] + (((key, value),) if isinstance(value, (dict, list)) else ())
            return JsonNode(value, self.root, anc)
        return JsonNode(value, self.root, self.ancestors)

    def text(self, separator: str = " ", strip: bool = True) -> str:
        return _scalar(self.value) or ""


def parse_json(text: str) -> JsonNode:
    doc = json.loads(text)
    return JsonNode(doc, root=doc)


def _tokens(path: str) -> list[tuple[str, str]]:
    out, pos = [], 0
    path = path.strip()
    while pos < len(path):
        m = _TOKEN.match(path, pos)
        if not m or m.end() == pos:
            raise ValueError(f"ruta JSON no válida: {path!r} (cerca de {path[pos:]!r})")
        kind = next(k for k, v in m.groupdict().items() if v is not None)
        out.append((kind, m.group(kind)))
        pos = m.end()
    return out


def _flatten_lists(nodes: list[JsonNode]) -> list[JsonNode]:
    out = []
    for n in nodes:
        if isinstance(n.value, list):
            out.extend(n.element(v) for v in n.value)
        else:
            out.append(n)
    return out


def _descend(node: JsonNode, key: str, out: list[JsonNode]) -> None:
    v = node.value
    if isinstance(v, dict):
        for k, child in v.items():
            cn = node.child(k, child)
            if k == key:
                out.append(cn)
            else:
                _descend(cn, key, out)
    elif isinstance(v, list):
        for x in v:
            _descend(node.element(x), key, out)


def select(node: JsonNode, path: str) -> list[JsonNode]:
    nodes = [node]
    for kind, tok in _tokens(path):
        if kind == "root":
            nodes = [JsonNode(node.root, node.root, ())]
        elif kind == "anc":
            name = tok[1:]
            found = []
            for n in nodes:
                match = next((d for k, d in reversed(n.ancestors) if k == name), None)
                if match is not None:
                    idx = next(i for i, (k, d) in enumerate(n.ancestors) if d is match)
                    found.append(JsonNode(match, n.root, n.ancestors[: idx + 1]))
            nodes = found
        elif kind == "key":
            nodes = [n.child(tok, n.value[tok]) for n in _flatten_lists(nodes)
                     if isinstance(n.value, dict) and tok in n.value]
        elif kind == "desc":
            found: list[JsonNode] = []
            for n in nodes:
                _descend(n, tok, found)
            nodes = found
        elif kind == "idx":
            nxt = []
            for n in nodes:
                if isinstance(n.value, list):
                    if tok == "*":
                        nxt.extend(n.element(v) for v in n.value)
                    elif int(tok) < len(n.value):
                        nxt.append(n.element(n.value[int(tok)]))
                elif tok in ("*", "0"):  # un objeto suelto donde se esperaba una lista
                    nxt.append(n)
            nodes = nxt
    return nodes


def select_items(node: JsonNode, path: str) -> list[JsonNode]:
    """Items de un listado: el resultado siempre se aplana (un `item` puede ser objeto o lista)."""
    return _flatten_lists(select(node, path))


def _scalar(v) -> str | None:
    if v is None:
        return None
    if isinstance(v, (dict, list)):
        return json.dumps(v, ensure_ascii=False)
    if isinstance(v, bool):
        return "true" if v else "false"
    return str(v)


def json_values(node: JsonNode, path: str) -> list[str]:
    out = []
    for n in _flatten_lists(select(node, path)):
        s = _scalar(n.value)
        if s not in (None, ""):
            out.append(s)
    return out
