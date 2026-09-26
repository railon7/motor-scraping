from datetime import date

from scraper.pipeline.clean import clean_date, clean_email, clean_int, clean_money, clean_phone


def test_money_formats():
    assert clean_money("1.234,56 €") == 1234.56
    assert clean_money("950 €") == 950.0
    assert clean_money("12,50") == 12.5
    assert clean_money("1,234.56") == 1234.56
    assert clean_money("Precio: 2.500 €") == 2500.0
    assert clean_money("sin precio") is None


def test_dates():
    assert clean_date("12/03/2024") == date(2024, 3, 12)
    assert clean_date("2024-03-12T10:00:00") == date(2024, 3, 12)
    assert clean_date("12 de marzo de 1980") == date(1980, 3, 12)
    assert clean_date("ayer") is None


def test_phone_email_int():
    assert clean_phone("Tel: 955 12 34 56") == "+34955123456"
    assert clean_phone("0034 600 000 000") == "+34600000000"
    assert clean_email("Contacto: Info@Ejemplo.ES ") == "info@ejemplo.es"
    assert clean_int("1.250 unidades") == 1250
