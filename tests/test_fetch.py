import httpx

from scraper.fetch.http import MAX_RETRY_AFTER, _detect_encoding, _retry_after


def test_retry_after():
    assert _retry_after(httpx.Response(429, headers={"Retry-After": "7"})) == 7
    assert _retry_after(httpx.Response(429, headers={"Retry-After": "9999"})) == MAX_RETRY_AFTER
    assert _retry_after(httpx.Response(503)) is None
    assert _retry_after(httpx.Response(503, headers={"Retry-After": "Wed, 21 Oct 2026 07:28:00 GMT"})) is None


def test_detect_encoding():
    assert _detect_encoding(b'<meta charset="ISO-8859-1">') == "iso8859-1"
    assert _detect_encoding(b'<meta http-equiv="Content-Type" content="text/html; charset=windows-1252">') == "cp1252"
    assert _detect_encoding(b"<html>sin charset</html>") == "utf-8"
    assert _detect_encoding(b'<meta charset="inventado">') == "utf-8"
