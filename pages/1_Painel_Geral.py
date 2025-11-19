from __future__ import annotations

from datetime import datetime

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from core.auth import require_auth
from core.data_service import load_datasets
from core.formatters import format_currency, safe_percentage
from core.ui import chart_card, style_fig, style_heatmap

try:
    from streamlit_autorefresh import st_autorefresh
except ImportError:  # pragma: no cover
    st_autorefresh = None


PLOTLY_CONFIG = {
    "displaylogo": False,
    "modeBarButtonsToRemove": ["zoomIn2d", "zoomOut2d", "lasso2d", "select2d"],
    "responsive": True,
}


def sidebar_multiselect(label: str, series: pd.Series):
    options = sorted(series.dropna().unique().tolist())
    if not options:
        return []
    return st.sidebar.multiselect(label, options, default=options)


def get_filters(df: pd.DataFrame):
    st.sidebar.header("Filtros do Painel Geral")

    valid_aberturas = df['Data de abertura'].dropna()
    if not valid_aberturas.empty:
        min_date = valid_aberturas.min().date()
        max_date = valid_aberturas.max().date()
        date_range = st.sidebar.date_input(
            "Período de Abertura",
            value=(min_date, max_date),
            min_value=min_date,
            max_value=max_date,
            format="DD/MM/YYYY",
        )
        if isinstance(date_range, tuple) and len(date_range) == 2:
            start_date, end_date = date_range
        else:
            start_date, end_date = min_date, max_date
    else:
        start_date, end_date = None, None
        date_range = None

    estagios_para_filtrar = sidebar_multiselect("Estágios", df['Estágio'])
    responsaveis_para_filtrar = sidebar_multiselect("Responsáveis", df['Responsável'])
    estados_para_filtrar = sidebar_multiselect("Estados", df['Estado'])

    presentation_step = st.sidebar.radio(
        "Modo Apresentação",
        options=[0, 1, 2],
        format_func=lambda x: ["Desativado", "Destacar Heatmap", "Destacar Tempo Médio"][x],
        index=0,
    )

    selected_oc = st.sidebar.selectbox("Filtrar por Oportunidade (opcional)", [None] + sorted(df['OC_Identifier'].dropna().unique().tolist()))

    filtered_df = df.copy()
    if start_date and end_date:
        filtered_df = filtered_df[
            (filtered_df['Data de abertura'].dt.date >= start_date)
            & (filtered_df['Data de abertura'].dt.date <= end_date)
        ]
    if estagios_para_filtrar:
        filtered_df = filtered_df[filtered_df['Estágio'].isin(estagios_para_filtrar)]
    if responsaveis_para_filtrar:
        filtered_df = filtered_df[filtered_df['Responsável'].isin(responsaveis_para_filtrar)]
    if estados_para_filtrar:
        filtered_df = filtered_df[filtered_df['Estado'].isin(estados_para_filtrar)]
    if selected_oc:
        filtered_df = filtered_df[filtered_df['OC_Identifier'] == selected_oc]

    return filtered_df, start_date, end_date, estagios_para_filtrar, selected_oc, presentation_step


def render_kpis(filtered_df: pd.DataFrame):
    ganha_df = filtered_df[filtered_df['Estado'] == 'Ganha'].copy()
    total_ops = filtered_df['OC_Identifier'].nunique() if not filtered_df.empty else 0
    unique_won = ganha_df['OC_Identifier'].nunique() if not ganha_df.empty else 0
    won_values = ganha_df['Valor rec. fechamento'].where(
        ganha_df['Valor rec. fechamento'].notna(), ganha_df['Valor']
    )
    total_won_value = won_values.sum() if won_values is not None else 0
    win_rate = (unique_won / total_ops * 100) if total_ops else 0
    pipeline_mask = ~filtered_df['Estado'].isin(['Ganha', 'Perdida'])
    valor_pipeline = filtered_df.loc[pipeline_mask, 'Valor'].sum(min_count=1)
    valor_previsto = (
        (filtered_df['Valor'] * (filtered_df['Prob %'] / 100)).sum(min_count=1)
        if 'Prob %' in filtered_df.columns
        else 0
    )
    ticket_medio = total_won_value / unique_won if unique_won else 0

    kpi_data = [
        ("Total Oportunidades Únicas", f"{int(total_ops)}"),
        ("Taxa de Sucesso", safe_percentage(win_rate)),
        ("Valor Total Ganho", format_currency(total_won_value)),
        ("Ticket Médio Ganho", format_currency(ticket_medio)),
        ("Valor em Aberto", format_currency(valor_pipeline)),
        ("Valor Previsto (Prob %)", format_currency(valor_previsto)),
    ]

    with chart_card("Resumo Geral"):
        cols = st.columns(3)
        for idx, (label, value) in enumerate(kpi_data):
            with cols[idx % 3]:
                st.markdown(
                    f"<div class='metric-card'><h3>{label}</h3><p>{value}</p></div>",
                    unsafe_allow_html=True,
                )


def main():
    require_auth()
    df, df_timeline = load_datasets()

    if df.empty:
        st.warning("Dados indisponíveis. Verifique a conexão com o Google Sheets.")
        return

    filtered_df, start_dt, end_dt, estagios_para_filtrar, selected_oc, presentation_step = get_filters(df)
    if filtered_df.empty:
        st.warning("Sem dados para os filtros aplicados.")
        return

    render_kpis(filtered_df)

    st.subheader("Análise de Oportunidades e Valor")
    col1, col2 = st.columns(2)

    df_agg_responsavel = filtered_df.groupby('Responsável')['OC_Identifier'].nunique().reset_index()
    df_agg_responsavel.rename(columns={'OC_Identifier': 'Total Oportunidades Únicas'}, inplace=True)

    df_agg_estado_mes = (
        filtered_df.groupby(['Estado', 'MonthYear_Abertura'])['OC_Identifier']
        .nunique()
        .reset_index()
    )
    df_agg_estado_mes.rename(columns={'OC_Identifier': 'Total Oportunidades Únicas'}, inplace=True)
    df_agg_estado_mes['MonthYear_Abertura'] = df_agg_estado_mes['MonthYear_Abertura'].astype(str)

    with col1:
        with chart_card("Responsáveis com mais Oportunidades"):
            if not df_agg_responsavel.empty:
                fig1 = px.bar(
                    df_agg_responsavel,
                    x='Responsável',
                    y='Total Oportunidades Únicas',
                    color='Responsável',
                    color_discrete_sequence=px.colors.qualitative.Set2,
                )
                fig1.update_layout(xaxis_title="Responsável", yaxis_title="Total de Oportunidades Únicas")
                style_fig(fig1)
                st.plotly_chart(fig1, use_container_width=True, config=PLOTLY_CONFIG)
            else:
                st.info("Sem dados para responsáveis dentro dos filtros atuais.")

    with col2:
        with chart_card("Oportunidades por Estado e Mês"):
            if not df_agg_estado_mes.empty:
                fig2 = px.bar(
                    df_agg_estado_mes,
                    x='MonthYear_Abertura',
                    y='Total Oportunidades Únicas',
                    color='Estado',
                    color_discrete_sequence=px.colors.qualitative.Plotly,
                )
                fig2.update_layout(xaxis_title="Mês de Abertura", yaxis_title="Total de Oportunidades Únicas")
                style_fig(fig2)
                st.plotly_chart(fig2, use_container_width=True, config=PLOTLY_CONFIG)
            else:
                st.info("Sem dados para estados/meses dentro dos filtros atuais.")

    with chart_card("Heatmap: Oportunidades por Etapa e Hora de Abertura"):
        if df_timeline.empty:
            st.info("Sem timeline disponível para gerar o heatmap.")
        else:
            df_timeline_filtered = df_timeline[
                df_timeline['OC_Identifier'].isin(filtered_df['OC_Identifier'].unique())
            ].copy()

            if df_timeline_filtered.empty:
                st.info("Sem timeline para os filtros atuais.")
            else:
                df_timeline_filtered['Hour_of_Day_Abertura'] = df_timeline_filtered['Data de abertura'].dt.hour
                heatmap_data = (
                    df_timeline_filtered.groupby(['Estágio', 'Hour_of_Day_Abertura'])['OC_Identifier']
                    .nunique()
                    .unstack(fill_value=0)
                )
                if heatmap_data.empty:
                    st.info("Sem dados suficientes para o heatmap.")
                else:
                    fig_heatmap = go.Figure(
                        data=go.Heatmap(
                            z=heatmap_data.values,
                            x=heatmap_data.columns,
                            y=heatmap_data.index,
                            colorscale='Portland',
                            zsmooth='best',
                            colorbar=dict(
                                title=dict(text='Qtd. de Oportunidades', font=dict(color='#f8fafc')),
                                thickness=12,
                                tickcolor='#f8fafc',
                                tickfont=dict(color='#f8fafc'),
                            ),
                            hovertemplate="Etapa: %{y}<br>Hora: %{x}h<br>Total: %{z}<extra></extra>",
                        )
                    )
                    fig_heatmap.update_layout(
                        title='Oportunidades por Etapa e Hora de Abertura',
                        xaxis_title='Hora do Dia',
                        yaxis_title='Etapa',
                    )
                    style_heatmap(fig_heatmap)
                    st.plotly_chart(fig_heatmap, use_container_width=True, config=PLOTLY_CONFIG)

    st.subheader("Análise de Estágios")
    with chart_card("Distribuição de Todos os Estágios (Filtrado)"):
        stage_counts = filtered_df['Estágio'].value_counts().reset_index()
        stage_counts.columns = ['Estágio', 'Quantidade']
        if not stage_counts.empty:
            fig3 = px.pie(
                stage_counts,
                values='Quantidade',
                names='Estágio',
                color_discrete_sequence=px.colors.qualitative.Plotly,
            )
            fig3.update_traces(textposition='inside', textinfo='percent+label')
            style_fig(fig3)
            st.plotly_chart(fig3, use_container_width=True, config=PLOTLY_CONFIG)
        else:
            st.info("Sem dados de estágios para os filtros atuais.")

    with chart_card("Análise de Tempo Médio por Estágio (Filtrado)"):
        if df_timeline.empty:
            st.info("Sem timeline disponível para análise de tempo.")
        else:
            df_timeline_filtered = df_timeline[
                df_timeline['OC_Identifier'].isin(filtered_df['OC_Identifier'].unique())
            ].copy()
            if df_timeline_filtered.empty:
                st.info("Sem timeline para os filtros atuais.")
            else:
                df_agg_time_per_stage_avg = (
                    df_timeline_filtered.groupby('Estágio')['Time_in_Stage']
                    .mean()
                    .reset_index()
                )
                df_agg_time_per_stage_avg['Tempo no Estágio'] = df_agg_time_per_stage_avg['Time_in_Stage'].apply(
                    lambda x: f"{int(x // 24)} dias, {int(x % 24)} horas"
                )
                st.dataframe(
                    df_agg_time_per_stage_avg[['Estágio', 'Tempo no Estágio']],
                    use_container_width=True,
                    hide_index=True,
                )

    with chart_card("Tempo Médio por Estágio Visualização (Filtrado)"):
        if df_timeline.empty:
            st.info("Sem timeline disponível para visualização.")
        else:
            df_timeline_filtered = df_timeline[
                df_timeline['OC_Identifier'].isin(filtered_df['OC_Identifier'].unique())
            ].copy()
            if df_timeline_filtered.empty:
                st.info("Sem timeline para os filtros atuais.")
            else:
                df_agg_time_per_stage_avg = (
                    df_timeline_filtered.groupby('Estágio')['Time_in_Stage']
                    .mean()
                    .reset_index()
                )
                fig5 = px.bar(
                    df_agg_time_per_stage_avg,
                    x='Estágio',
                    y='Time_in_Stage',
                    color='Estágio',
                    color_discrete_sequence=px.colors.qualitative.Plotly,
                )
                fig5.update_layout(
                    xaxis_title="Estágio",
                    yaxis_title="Tempo Médio (horas)",
                )
                style_fig(fig5)
                st.plotly_chart(fig5, use_container_width=True, config=PLOTLY_CONFIG)

    if presentation_step == 1:
        st.success("Modo apresentação: destacando o Heatmap.")
    elif presentation_step == 2:
        st.success("Modo apresentação: destacando a Análise de Tempo Médio.")


if __name__ == "__main__":
    main()
