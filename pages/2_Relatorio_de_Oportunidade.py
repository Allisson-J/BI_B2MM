from __future__ import annotations

import os
from datetime import datetime

import pandas as pd
import streamlit as st

from core.auth import require_auth
from core.data_service import load_datasets
from core.formatters import format_currency
from core.ui import chart_card


def get_openai_client():
    api_key = os.getenv("OPENAI_API_KEY") or st.secrets.get("openai", {}).get("api_key")
    if not api_key:
        return None
    import openai

    openai.api_key = api_key
    return openai.OpenAI(api_key=api_key)


def main():
    require_auth()
    
    # Botão para atualizar dados
    st.sidebar.header("Ações")
    if st.sidebar.button("🔄 Atualizar Dados do Google Sheets", use_container_width=True, type="primary"):
        st.cache_data.clear()
        st.cache_resource.clear()
        st.success("Cache limpo! Os dados serão recarregados.")
        st.rerun()
    st.sidebar.divider()
    
    df, df_timeline = load_datasets()

    if df.empty or df_timeline.empty:
        st.warning("Dados indisponíveis para gerar o relatório. Atualize a página inicial.")
        return

    st.title("Relatório de Oportunidade")
    oc_list = df['OC_Identifier'].dropna().unique()
    if len(oc_list) == 0:
        st.info("Nenhum identificador único encontrado nos dados.")
        return

    selected_oc = st.selectbox("Selecione uma Oportunidade", oc_list)
    df_op = df[df['OC_Identifier'] == selected_oc]
    if df_op.empty:
        st.warning("Não foi possível localizar detalhes desta oportunidade.")
        return

    opportunity = df_op.iloc[0]

    col1, col2 = st.columns(2)
    with col1:
        st.write("**ID:**", opportunity.get('ID', 'N/A'))
        st.write("**Título:**", opportunity.get('Título', 'N/A'))
        st.write("**Responsável:**", opportunity.get('Responsável', 'N/A'))
        st.write("**Estado:**", opportunity.get('Estado', 'N/A'))
        st.write("**Estágio Atual:**", opportunity.get('Estágio', 'N/A'))
    with col2:
        st.write("**Valor:**", format_currency(opportunity.get('Valor')))
        st.write("**Origem:**", opportunity.get('Origem', 'N/A'))
        st.write("**Prob %:**", opportunity.get('Prob %', 'N/A'))
        st.write("**OC:**", opportunity.get('OC', 'N/A'))

    col_dates1, col_dates2 = st.columns(2)
    with col_dates1:
        abertura = opportunity.get('Data de abertura')
        abertura_str = abertura.strftime('%d/%m/%Y %H:%M:%S') if pd.notna(abertura) else "N/A"
        st.write("**Data de Abertura:**", abertura_str)
    with col_dates2:
        fechamento = opportunity.get('Data fechamento')
        fechamento_str = fechamento.strftime('%d/%m/%Y %H:%M:%S') if pd.notna(fechamento) else "N/A"
        st.write("**Data de Fechamento:**", fechamento_str)

    if pd.notna(opportunity.get('Data fechamento')):
        with st.expander("Detalhes de Fechamento"):
            st.write("**Valor Fechamento:**", format_currency(opportunity.get('Valor fechamento')))
            st.write("**Valor Rec. Fechamento:**", format_currency(opportunity.get('Valor rec. fechamento')))
            st.write("**Razão de Fechamento:**", opportunity.get('Razão de fechamento', 'N/A'))
            st.write("**Observação de Fechamento:**", opportunity.get('Observação de fechamento', 'N/A'))

    with chart_card("Linha do Tempo da Oportunidade"):
        opportunity_timeline = df_timeline[df_timeline['OC_Identifier'] == selected_oc].copy()
        if opportunity_timeline.empty:
            st.info("Nenhum dado de timeline encontrado para esta oportunidade.")
        else:
            display_cols = ['Estágio', 'Data de abertura', 'Data fechamento', 'Tempo no Estágio']
            st.dataframe(opportunity_timeline[display_cols], use_container_width=True)

    st.subheader("Assistente de IA")
    client = get_openai_client()
    if not client:
        st.info("Configure a chave da API da OpenAI para ativar o assistente.")
        return

    user_query = st.text_area("Pergunte algo sobre esta oportunidade:", height=120)
    if st.button("Obter Resposta da IA"):
        if not user_query:
            st.warning("Digite uma pergunta.")
        else:
            with st.spinner("Analisando com IA..."):
                prompt = f"""
                Você é um analista de BI. Use os dados abaixo para responder em português.
                Detalhes:
                - ID: {opportunity.get('ID', 'N/A')}
                - Título: {opportunity.get('Título', 'N/A')}
                - Responsável: {opportunity.get('Responsável', 'N/A')}
                - Estado: {opportunity.get('Estado', 'N/A')}
                - Estágio: {opportunity.get('Estágio', 'N/A')}
                - Valor: {format_currency(opportunity.get('Valor'))}
                - Origem: {opportunity.get('Origem', 'N/A')}
                - Prob %: {opportunity.get('Prob %', 'N/A')}
                - OC: {opportunity.get('OC', 'N/A')}
                - Data de Abertura: {abertura_str}
                - Data de Fechamento: {fechamento_str}
                Linha do tempo:
                {opportunity_timeline[['Estágio', 'Data de abertura', 'Data fechamento', 'Tempo no Estágio']].to_string(index=False)}

                Pergunta do usuário: {user_query}
                """
                response = client.chat.completions.create(
                    model="gpt-4o-mini",
                    messages=[
                        {"role": "system", "content": "Você é um assistente de BI conciso e direto."},
                        {"role": "user", "content": prompt},
                    ],
                    max_tokens=300,
                )
                st.success(response.choices[0].message.content)


if __name__ == "__main__":
    main()
