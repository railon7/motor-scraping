from datetime import date, datetime

from scraper.pipeline.clean import (
    clean_date, clean_datetime, clean_email, clean_float, clean_int, clean_money, clean_phone,
)


def test_money_formats():
    assert clean_money("1.234,56 €") == 1234.56
    assert clean_money("950 €") == 950.0
    assert clean_money("12,50") == 12.5
    assert clean_money("1,234.56") == 1234.56
    assert clean_money("Precio: 2.500 €") == 2500.0
    assert clean_money("1 234,56 €") == 1234.56  # espacio duro como separador de miles
    assert clean_money("sin precio") is None


def test_float_uses_spanish_separators():
    assert clean_float("1.234,56") == 1234.56
    assert clean_float("3,5 kg") == 3.5
    assert clean_float("0.75") == 0.75


def test_dates():
    assert clean_date("12/03/2024") == date(2024, 3, 12)
    assert clean_date("2024-03-12T10:00:00") == date(2024, 3, 12)
    assert clean_date("12 de marzo de 1980") == date(1980, 3, 12)
    assert clean_date("ayer") is None


def test_dates_in_context():
    assert clean_date("12/03/2024 10:30") == date(2024, 3, 12)
    assert clean_date("Publicado el 12-03-2024") == date(2024, 3, 12)
    assert clean_date("12.03.24") == date(2024, 3, 12)
    assert clean_date("2024/03/12") == date(2024, 3, 12)
    assert clean_date("1 de Septiembre, 2024") == date(2024, 9, 1)
    assert clean_date("12 mar. 2024") == date(2024, 3, 12)
    assert clean_date("March 14, 1879") == date(1879, 3, 14)
    assert clean_date("Dec 3rd, 2023") == date(2023, 12, 3)


def test_invalid_dates_are_none():
    assert clean_date("31/02/2024") is None
    assert clean_date("12/13/2024") is None  # no se reinterpreta como mes/día


def test_datetime_keeps_time():
    assert clean_datetime("12/03/2024 10:30") == datetime(2024, 3, 12, 10, 30)
    assert clean_datetime("2024-03-12T10:00:00") == datetime(2024, 3, 12, 10, 0)
    assert clean_datetime("12 de marzo de 2024") == datetime(2024, 3, 12)


def test_phone_email_int():
    assert clean_phone("Tel: 955 12 34 56") == "+34955123456"
    assert clean_phone("0034 600 000 000") == "+34600000000"
    assert clean_phone("954 11 22 33 / 600 11 22 33") == "+34954112233"  # solo el primero
    assert clean_phone("(+34) 600-11-22-33") == "+34600112233"
    assert clean_phone("sin teléfono") is None
    assert clean_email("Contacto: Info@Ejemplo.ES ") == "info@ejemplo.es"
    assert clean_int("1.250 unidades") == 1250
