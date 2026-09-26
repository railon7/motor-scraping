from scraper.parse.selectors import extract_all, extract_one, parse_html, parse_selector

HTML = '<div class="c"><a class="t" href="/x">Hola <b>mundo</b></a><span class="p">10</span><span class="p">20</span></div>'


def test_parse_selector_suffixes():
    assert parse_selector("a.t::attr(href)").kind == "attr"
    assert parse_selector("a.t::text").kind == "text"
    assert parse_selector("a.t").kind == "text"


def test_extract():
    tree = parse_html(HTML)
    assert extract_one(tree, "a.t") == "Hola mundo"
    assert extract_one(tree, "a.t::attr(href)", base_url="https://e.es/lista") == "https://e.es/x"
    assert extract_all(tree, "span.p") == ["10", "20"]
    assert extract_one(tree, "span.nada") is None
