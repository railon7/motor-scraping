from scraper.pipeline.dedupe import MAX_KEY_LEN, natural_key


def test_key_from_fields():
    assert natural_key({"a": "x", "b": 2}, ["a", "b"], "http://u") == "x|2"
    assert natural_key({"a": "x", "b": None}, ["a", "b"], "http://u") == "x|"


def test_empty_key_falls_back_to_url():
    # Sin esto, todos los registros con clave vacía se pisarían entre sí ("|")
    assert natural_key({"a": None, "b": ""}, ["a", "b"], "http://u/1") == "http://u/1"
    assert natural_key({"a": 1}, [], "http://u/2") == "http://u/2"


def test_long_key_is_truncated_with_hash():
    k1 = natural_key({"a": "x" * 600 + "1"}, ["a"], "u")
    k2 = natural_key({"a": "x" * 600 + "2"}, ["a"], "u")
    assert len(k1) <= MAX_KEY_LEN and len(k2) <= MAX_KEY_LEN and k1 != k2
