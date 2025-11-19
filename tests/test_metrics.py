import pandas as pd

from core.formatters import format_currency, format_time_in_stage, normalize_currency, safe_percentage


def test_format_currency():
    assert format_currency(1234.56) == "R$ 1.234,56"
    assert format_currency(None) == "R$ 0,00"


def test_safe_percentage():
    assert safe_percentage(52.345) == "52,3%"
    assert safe_percentage(None) == "0,0%"


def test_normalize_currency():
    series = pd.Series(["R$ 1.234,56", " 987,10 ", None])
    result = normalize_currency(series)
    assert result.iloc[0] == 1234.56
    assert result.iloc[1] == 987.10
    assert pd.isna(result.iloc[2])


def test_format_time_in_stage():
    assert "1 dias" in format_time_in_stage(24)
    assert format_time_in_stage(None) == "N/A"

