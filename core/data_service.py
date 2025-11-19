from __future__ import annotations

import re
from datetime import datetime
from typing import Tuple

import gspread
import pandas as pd
import streamlit as st
from oauth2client.service_account import ServiceAccountCredentials

from core.formatters import format_time_in_stage, normalize_currency


@st.cache_resource
def get_gspread_client():
    try:
        creds = st.secrets["connections"]["gsheets"]
        scope = [
            "https://spreadsheets.google.com/feeds",
            "https://www.googleapis.com/auth/drive",
        ]
        credentials = ServiceAccountCredentials.from_json_keyfile_dict(creds, scope)
        return gspread.authorize(credentials)
    except Exception as exc:  # pragma: no cover - streamlit UI handles display
        st.error(f"Erro na autenticação do Google Sheets: {exc}")
        return None


def _extract_oc_identifier(title: str | None) -> str | None:
    if not isinstance(title, str):
        return None
    match = re.search(r'(OC\s*\d+)', title, re.IGNORECASE)
    if match:
        return match.group(1).replace(" ", "")
    match_cte = re.search(r'(CTE\s*\d+)', title, re.IGNORECASE)
    if match_cte:
        return match_cte.group(1).replace(" ", "")
    return None


@st.cache_data(ttl=900)
def load_datasets() -> Tuple[pd.DataFrame, pd.DataFrame]:
    client = get_gspread_client()
    if client is None:
        return pd.DataFrame(), pd.DataFrame()

    try:
        sheet = client.open("BI_B2").sheet1
        all_data = sheet.get_all_values()
        df = pd.DataFrame(all_data[1:], columns=all_data[0])

        value_cols = ['Valor', 'Valor Rec.', 'Valor fechamento', 'Valor rec. fechamento']
        for col in value_cols:
            if col in df.columns:
                df[col] = normalize_currency(df[col])

        if 'Prob %' in df.columns:
            df['Prob %'] = (
                df['Prob %']
                .astype(str)
                .str.replace('%', '', regex=False)
                .str.replace(',', '.', regex=False)
                .str.replace(' ', '', regex=False)
            )
            df['Prob %'] = pd.to_numeric(df['Prob %'], errors='coerce')

        date_cols = ['Data de abertura', 'Data fechamento']
        for col in date_cols:
            df[col] = pd.to_datetime(df[col], errors='coerce', format='%d/%m/%Y %H:%M:%S')

        df['OC_Identifier'] = df['Título'].apply(_extract_oc_identifier)

        for col, attr in [('Data de abertura', 'MonthYear_Abertura'), ('Data fechamento', 'MonthYear_Fechamento')]:
            df[attr] = df[col].dt.to_period('M') if pd.api.types.is_datetime64_any_dtype(df[col]) else None

        df['Hour_of_Day_Abertura'] = df['Data de abertura'].apply(lambda x: x.hour if pd.notna(x) else -1).astype(int)

        df_timeline = df[['OC_Identifier', 'Estágio', 'Data de abertura', 'Data fechamento']].copy()
        df_timeline.dropna(subset=['OC_Identifier', 'Data de abertura'], inplace=True)
        df_timeline = df_timeline.sort_values(by=['OC_Identifier', 'Data de abertura'])

        current_time = pd.to_datetime('now')
        df_timeline['Time_in_Stage'] = (
            df_timeline['Data fechamento'] - df_timeline['Data de abertura']
        ).dt.total_seconds() / 3600
        df_timeline['Time_in_Stage'] = df_timeline.apply(
            lambda row: (current_time - row['Data de abertura']).total_seconds() / 3600
            if pd.isna(row['Data fechamento'])
            else row['Time_in_Stage'],
            axis=1,
        )
        df_timeline['Tempo no Estágio'] = df_timeline['Time_in_Stage'].apply(format_time_in_stage)

        return df, df_timeline
    except Exception as exc:  # pragma: no cover
        st.error(f"Erro ao carregar dados do Google Sheet: {exc}")
        return pd.DataFrame(), pd.DataFrame()


def get_placeholder_interactions() -> pd.DataFrame:
    data = {
        'Usuário': ['User A', 'User B', 'User C', 'User A', 'User B', 'User D', 'User A'],
        'Interações': [10, 15, 8, 12, 18, 5, 11],
    }
    return pd.DataFrame(data)

