from scraper.fetch.robots import RobotsRules

BOE_LIKE = """
User-agent: *
Disallow: /diario_boe/txt.php?*lang=ca
Disallow: /diario_boe/xml.php?
Disallow: /*.pdf$
Allow: /privado/publico/
Disallow: /privado/
Crawl-delay: 3

User-agent: OtroBot
Disallow: /
"""


def test_wildcards_and_end_anchor():
    r = RobotsRules(BOE_LIKE, "TazukeScraper/0.1 (+https://tazuke.com)")
    assert not r.allowed("https://www.boe.es/diario_boe/txt.php?id=BOE-A-1&lang=ca")
    assert r.allowed("https://www.boe.es/diario_boe/txt.php?id=BOE-A-1")
    assert not r.allowed("https://www.boe.es/diario_boe/xml.php?id=BOE-A-1")
    assert not r.allowed("https://www.boe.es/docs/anexo.pdf")
    assert r.allowed("https://www.boe.es/docs/anexo.pdf?v=2")  # '$' ancla el final


def test_longest_rule_wins_and_crawl_delay():
    r = RobotsRules(BOE_LIKE, "TazukeScraper/0.1")
    assert not r.allowed("https://x.es/privado/datos")
    assert r.allowed("https://x.es/privado/publico/pagina")
    assert r.crawl_delay == 3


def test_specific_group_overrides_star():
    assert not RobotsRules(BOE_LIKE, "OtroBot/2.0").allowed("https://x.es/cualquier")
    assert RobotsRules("User-agent: *\nDisallow: /\n\nUser-agent: TazukeScraper\nAllow: /\n",
                       "TazukeScraper/0.1").allowed("https://x.es/a")


def test_empty_and_special_cases():
    assert RobotsRules("", "TazukeScraper").allowed("https://x.es/a")
    assert RobotsRules("User-agent: *\nDisallow:\n", "TazukeScraper").allowed("https://x.es/a")
    assert not RobotsRules.disallowing_all().allowed("https://x.es/")
    assert RobotsRules.allowing_all().allowed("https://x.es/")
