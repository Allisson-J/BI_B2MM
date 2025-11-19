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
    
    # Botão para atualizar dados
    if st.sidebar.button("🔄 Atualizar Dados do Google Sheets", use_container_width=True, type="primary"):
        st.cache_data.clear()
        st.cache_resource.clear()
        st.success("Cache limpo! Os dados serão recarregados.")
        st.rerun()
    
    st.sidebar.divider()

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
            start_date = end_date = date_range
        if start_date > end_date:
            st.sidebar.warning("A data inicial era maior que a final e foi ajustada automaticamente.")
            start_date, end_date = end_date, start_date
        start_datetime = pd.to_datetime(start_date)
        end_datetime = pd.to_datetime(end_date) + pd.Timedelta(days=1) - pd.Timedelta(seconds=1)
        filtered_df = df[
            (df['Data de abertura'] >= start_datetime)
            & (df['Data de abertura'] <= end_datetime)
        ].copy()
    else:
        start_datetime = pd.Timestamp("1970-01-01")
        end_datetime = pd.Timestamp("2100-01-01")
        filtered_df = df.copy()

    estados = sidebar_multiselect("Selecionar Estado", filtered_df['Estado'])
    if estados:
        filtered_df = filtered_df[filtered_df['Estado'].isin(estados)]

    responsaveis = sidebar_multiselect("Selecionar Responsável", filtered_df['Responsável'])
    if responsaveis:
        filtered_df = filtered_df[filtered_df['Responsável'].isin(responsaveis)]

    estagios = sidebar_multiselect("Selecionar Estágio", filtered_df['Estágio'])
    if estagios:
        filtered_df = filtered_df[filtered_df['Estágio'].isin(estagios)]
        estagios_para_filtrar = estagios
    else:
        estagios_para_filtrar = filtered_df['Estágio'].dropna().unique().tolist()

    opportunity_identifiers = filtered_df['OC_Identifier'].dropna().unique()
    selected_oc = st.sidebar.selectbox(
        "Filtrar por Oportunidade (OC ou CTE)",
        ["Todos"] + list(opportunity_identifiers),
    )
    if selected_oc != "Todos":
        filtered_df = filtered_df[filtered_df['OC_Identifier'] == selected_oc].copy()

    presentation_mode = st.sidebar.toggle("Modo Apresentação", value=False)
    presentation_step = 0
    if presentation_mode and st_autorefresh:
        counter = st_autorefresh(interval=15000, limit=None, key="presentation_refresh")
        presentation_step = counter % 3

    return (
        filtered_df,
        start_datetime,
        end_datetime,
        estagios_para_filtrar,
        selected_oc,
        presentation_step,
    )


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
                    barmode='group',
                    color_discrete_sequence=px.colors.qualitative.Pastel,
                )
                fig2.update_layout(xaxis_title="Mês/Ano", yaxis_title="Total de Oportunidades Únicas")
                style_fig(fig2)
                st.plotly_chart(fig2, use_container_width=True, config=PLOTLY_CONFIG)
            else:
                st.info("Sem dados por estado e mês para os filtros atuais.")

    with chart_card("Heatmap: Oportunidades por Etapa e Hora de Abertura"):
        if df_timeline.empty:
            st.info("Timeline indisponível.")
        else:
            df_timeline_filtered = df_timeline[
                (df_timeline['Data de abertura'] >= start_dt)
                & (df_timeline['Data de abertura'] <= end_dt)
            ].copy()
            if estagios_para_filtrar:
                df_timeline_filtered = df_timeline_filtered[
                    df_timeline_filtered['Estágio'].isin(estagios_para_filtrar)
                ].copy()
            if selected_oc != "Todos":
                df_timeline_filtered = df_timeline_filtered[
                    df_timeline_filtered['OC_Identifier'] == selected_oc
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
        if stage_counts.empty:
            st.info("Sem dados de estágio para os filtros atuais.")
        else:
            fig4 = px.bar(
                stage_counts,
                x='Estágio',
                y='Quantidade',
                color='Estágio',
                color_discrete_sequence=px.colors.qualitative.Set3,
            )
            fig4.update_layout(xaxis_title="Estágio", yaxis_title="Quantidade")
            style_fig(fig4)
            st.plotly_chart(fig4, use_container_width=True, config=PLOTLY_CONFIG)

    with chart_card("Análise de Tempo Médio por Estágio (Filtrado)"):
        if df_timeline.empty:
            st.info("Timeline indisponível.")
        else:
            df_timeline_avg = df_timeline[
                (df_timeline['Data de abertura'] >= start_dt)
                & (df_timeline['Data de abertura'] <= end_dt)
            ].copy()
            if estagios_para_filtrar:
                df_timeline_avg = df_timeline_avg[df_timeline_avg['Estágio'].isin(estagios_para_filtrar)].copy()
            if selected_oc != "Todos":
                df_timeline_avg = df_timeline_avg[
                    df_timeline_avg['OC_Identifier'] == selected_oc
                ].copy()

            if df_timeline_avg.empty:
                st.info("Sem dados para cálculo de tempo médio.")
            else:
                df_agg_time = df_timeline_avg.groupby('Estágio')['Time_in_Stage'].mean().reset_index()
                df_agg_time = df_agg_time.sort_values(by='Time_in_Stage', ascending=False)
                df_agg_time['Tempo Médio no Estágio'] = df_agg_time['Time_in_Stage'].apply(
                    lambda hours: "N/A"
                    if pd.isna(hours)
                    else f"{int(hours // 24)} dias, {int(hours % 24)} horas"
                )

                st.dataframe(df_agg_time[['Estágio', 'Tempo Médio no Estágio']])
                fig5 = px.bar(
                    df_agg_time,
                    x='Estágio',
                    y='Time_in_Stage',
                    color='Estágio',
                    color_discrete_sequence=px.colors.qualitative.Vivid,
                )
                fig5.update_layout(xaxis_title='Estágio', yaxis_title='Tempo Médio (horas)')
                style_fig(fig5)
                st.plotly_chart(fig5, use_container_width=True, config=PLOTLY_CONFIG)

    if presentation_step == 1:
        st.success("Modo apresentação: destacando o Heatmap.")
    elif presentation_step == 2:
        st.success("Modo apresentação: destacando a Análise de Tempo Médio.")


if __name__ == "__main__":
    main()
