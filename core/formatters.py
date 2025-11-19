from __future__ import annotations

from typing import Optional

import pandas as pd


def format_currency(value: Optional[float]) -> str:
    if value is None or pd.isna(value):
        return "R$ 0,00"
    return f"R$ {value:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def safe_percentage(value: Optional[float]) -> str:
    if value is None or pd.isna(value):
        return "0,0%"
    return f"{value:.1f}%"


def normalize_currency(series: pd.Series) -> pd.Series:
    cleaned = (
        series.astype(str)
        .str.replace("R$", "", regex=False)
        .str.replace(" ", "", regex=False)
        .str.replace(r"[^\d,.-]", "", regex=True)
        .str.replace(".", "", regex=False)
        .str.replace(",", ".", regex=False)
    )
    return pd.to_numeric(cleaned, errors="coerce")


def format_time_in_stage(hours: Optional[float]) -> str:
    if pd.isna(hours):
        return "N/A"
    total_minutes = int(hours * 60)
    days = total_minutes // (24 * 60)
    remaining_minutes_after_days = total_minutes % (24 * 60)
    hrs = remaining_minutes_after_days // 60
    minutes = remaining_minutes_after_days % 60
    return f"{days} dias, {hrs} horas, {minutes} minutos"

