from scraper.config import FieldSpec
from scraper.parse.selectors import document_base, extract_all, extract_one, parse_html
from scraper.pipeline.extract import extract_value

PAGE = """<html><head>
<base href="https://cdn.ejemplo.es/fichas/">
<meta property="og:title" content="Taladro X200">
<meta name="description" content="Un taladro">
<script type="application/ld+json">
{"@context": "https://schema.org", "@graph": [
  {"@type": "Organization", "name": "Tienda"},
  {"@type": ["Product"], "name": "Taladro X200", "sku": "X200",
   "image": ["a.jpg", "b.jpg"],
   "offers": [{"@type": "Offer", "price": "89.90", "priceCurrency": "EUR"},
              {"@type": "Offer", "price": "99.90"}],
   "brand": {"@type": "Brand", "name": "Bosch"},}
]}
</script>
</head><body><h1>Taladro</h1><a class="ficha" href="x200.html">ver</a></body></html>"""


def test_jsonld_paths():
    tree = parse_html(PAGE)  # el JSON-LD lleva una coma final: se tolera
    assert extract_one(tree, "jsonld:Product.name") == "Taladro X200"
    assert extract_one(tree, "jsonld:Product.offers.price") == "89.90"
    assert extract_one(tree, "jsonld:Product.offers[1].price") == "99.90"
    assert extract_one(tree, "jsonld:Product.brand") == "Bosch"  # objeto -> su name
    assert extract_all(tree, "jsonld:Product.image[*]") == ["a.jpg", "b.jpg"]
    assert extract_one(tree, "jsonld:Organization.name") == "Tienda"
    assert extract_one(tree, "jsonld:Event.name") is None


def test_meta():
    tree = parse_html(PAGE)
    assert extract_one(tree, "meta:og:title") == "Taladro X200"
    assert extract_one(tree, "meta:description") == "Un taladro"


def test_selector_alternatives_first_non_empty():
    tree = parse_html(PAGE)
    spec = FieldSpec(selector=["jsonld:Product.gtin", "h2", "jsonld:Product.offers.price"], type="money")
    assert extract_value(tree, spec, "https://x.es/") == 89.9


def test_base_href():
    tree = parse_html(PAGE)
    base = document_base(tree, "https://www.ejemplo.es/listado")
    assert extract_one(tree, "a.ficha::attr(href)", base_url=base) == "https://cdn.ejemplo.es/fichas/x200.html"
    assert document_base(parse_html("<p>sin base</p>"), "https://a.es/b") == "https://a.es/b"
