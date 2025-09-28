import os
import streamlit as st
from oauth2client.service_account import ServiceAccountCredentials
import gspread
from datetime import datetime
import pandas as pd
import re
import plotly.express as px
import plotly.graph_objects as go
from streamlit_plotly_events import plotly_events
import base64
from fpdf import FPDF

# --- Google Sheets ---
try:
    creds = st.secrets["connections"]["gsheets"]
    
    scope = ["https://spreadsheets.google.com/feeds",
             "https://www.googleapis.com/auth/drive"]
    
    credentials = ServiceAccountCredentials.from_json_keyfile_dict(creds, scope)
    gc = gspread.authorize(credentials)
    
    spreadsheet = gc.open_by_url(creds["spreadsheet"])
    worksheet = spreadsheet.get_worksheet(0)

except Exception as e:
    st.error(f"Erro na autenticação do Google Sheets: {e}")
    gc = None

# --- Configuração da página ---
st.set_page_config(layout="wide", page_title="Painel de BI Operacional")

# --- OpenAI ---
openai_api_key = os.getenv("OPENAI_API_KEY") or st.secrets["openai"]["api_key"]

if openai_api_key:
    from openai import OpenAI
    client = OpenAI(api_key=openai_api_key)
else:
    st.warning("⚠️ OpenAI API key not found. OpenAI features will be disabled.")
    client = None

@st.cache_data
def load_data(_gspread_client):
    if _gspread_client is None:
        st.warning("Cliente gspread não disponível. Não foi possível carregar os dados.")
        return pd.DataFrame(), pd.DataFrame()

    try:
        B2sheet = _gspread_client.open('BI_B2')
        page = B2sheet.sheet1
        all_data = page.get_all_values()
        df = pd.DataFrame(all_data[1:], columns=all_data[0])

        value_cols = ['Valor', 'Valor Rec.', 'Valor fechamento', 'Valor rec. fechamento']
        for col in value_cols:
            df[col] = df[col].astype(str).str.replace('R$', '', regex=False).str.replace(',', '', regex=False).str.strip()
            df[col] = pd.to_numeric(df[col], errors='coerce')

        date_cols = ['Data de abertura', 'Data fechamento']
        for col in date_cols:
            df[col] = pd.to_datetime(df[col], errors='coerce', format='%d/%m/%Y %H:%M:%S')

        def extract_oc_identifier(title):
            if isinstance(title, str):
                match = re.search(r'(OC\s*\d+)', title, re.IGNORECASE)
                if match:
                    return match.group(1).replace(" ", "")
                else:
                    match_cte = re.search(r'(CTE\s*\d+)', title, re.IGNORECASE)
                    if match_cte:
                         return match_cte.group(1).replace(" ", "")
            return None

        df['OC_Identifier'] = df['Título'].apply(extract_oc_identifier)

        df['Mes de Abertura'] = df['Data de abertura'].dt.month.fillna(0).astype(int) if pd.api.types.is_datetime64_any_dtype(df['Data de abertura']) else 0
        df['Ano de Abertura'] = df['Data de abertura'].dt.year.fillna(0).astype(int) if pd.api.types.is_datetime64_any_dtype(df['Data de abertura']) else 0
        df['Mes de Fechamento'] = df['Data fechamento'].dt.month.fillna(0).astype(int) if pd.api.types.is_datetime64_any_dtype(df['Data fechamento']) else 0
        df['Ano de Fechamento'] = df['Data fechamento'].dt.year.fillna(0).astype(int) if pd.api.types.is_datetime64_any_dtype(df['Data fechamento']) else 0

        df['MonthYear_Abertura'] = df['Data de abertura'].dt.to_period('M') if pd.api.types.is_datetime64_any_dtype(df['Data de abertura']) else None
        df['MonthYear_Fechamento'] = df['Data fechamento'].dt.to_period('M') if pd.api.types.is_datetime64_any_dtype(df['Data fechamento']) else None

        df['Hour_of_Day_Abertura'] = df['Data de abertura'].apply(lambda x: x.hour if pd.notna(x) else -1).astype(int)

        df_timeline = df[['OC_Identifier', 'Estágio', 'Data de abertura', 'Data fechamento']].copy()
        df_timeline.dropna(subset=['OC_Identifier', 'Data de abertura'], inplace=True)
        df_timeline = df_timeline.sort_values(by=['OC_Identifier', 'Data de abertura'])

        current_time = pd.to_datetime('now')
        df_timeline['Time_in_Stage'] = (df_timeline['Data fechamento'] - df_timeline['Data de abertura']).dt.total_seconds() / 3600

        df_timeline['Time_in_Stage'] = df_timeline.apply(
            lambda row: (current_time - row['Data de abertura']).total_seconds() / 3600 if pd.isna(row['Data fechamento']) else row['Time_in_Stage'],
            axis=1
        )

        def format_time_in_stage(hours):
            if pd.isna(hours):
                return "N/A"
            total_minutes = int(hours * 60)
            days = total_minutes // (24 * 60)
            remaining_minutes_after_days = total_minutes % (24 * 60)
            hours = remaining_minutes_after_days // 60
            minutes = remaining_minutes_after_days % 60
            return f"{days}d {hours}h {minutes}m"

        df_timeline['Time_in_Stage_Formatted'] = df_timeline['Time_in_Stage'].apply(format_time_in_stage)

        return df, df_timeline

    except Exception as e:
        st.error(f"Erro ao carregar dados do Google Sheet: {e}")
        return pd.DataFrame(), pd.DataFrame()

# Load data
df, df_timeline = load_data(gc)

# --- Placeholder Interaction Data ---
interaction_data = {
    'User': ['User A', 'User B', 'User C', 'User A', 'User B', 'User D', 'User A'],
    'Interactions': [10, 15, 8, 12, 18, 5, 11]
}
df_interaction = pd.DataFrame(interaction_data)
df_agg_interaction = df_interaction.groupby('User')['Interactions'].sum().reset_index()

# --- Authentication Logic ---
if 'authenticated' not in st.session_state:
    st.session_state['authenticated'] = False

VALID_USERNAME = st.secrets.get("login", {}).get("username") or os.getenv("VALID_USERNAME")
VALID_PASSWORD = st.secrets.get("login", {}).get("password") or os.getenv("VALID_PASSWORD")

def authenticate(username, password):
    return username == VALID_USERNAME and password == VALID_PASSWORD

# --- Multi-page Navigation ---
st.sidebar.title("Navegação")

if st.session_state['authenticated']:
    if 'page' not in st.session_state:
        st.session_state['page'] = "Página Inicial"

    page = st.sidebar.radio("Ir para:", ["Página Inicial", "Painel Geral", "Relatório de Oportunidade"], index=["Página Inicial", "Painel Geral", "Relatório de Oportunidade"].index(st.session_state['page']))
    st.session_state['page'] = page

    if st.sidebar.button("Logout"):
        st.session_state['authenticated'] = False
        st.session_state['page'] = "Login"
        st.rerun()
else:
    page = "Login"
    st.session_state['page'] = "Login"

# --- Refresh Button ---
if st.session_state['authenticated']:
    if st.sidebar.button("Atualizar Dados"):
        st.cache_data.clear()
        st.rerun()

# Main app logic
try:
    if page == "Login":
        st.title("Login")
        st.markdown("Por favor, insira suas credenciais para acessar o painel.")

        with st.form("login_form"):
            username = st.text_input("Nome de Usuário")
            password = st.text_input("Senha", type="password")
            login_button = st.form_submit_button("Login")

            if login_button:
                if authenticate(username, password):
                    st.session_state['authenticated'] = True
                    st.success("Login bem-sucedido!")
                    st.session_state['page'] = "Página Inicial"
                    st.rerun()
                else:
                    st.error("Nome de usuário ou senha inválidos.")

    elif st.session_state['authenticated']:
        if page == "Página Inicial":
            st.title("Bem-vindo ao Painel de BI Operacional")

            st.markdown("""
                Este painel interativo oferece insights valiosos sobre suas oportunidades de negócios.
                Navegue pelas seções usando o menu ao lado para explorar:

                *   **Painel Geral**: Uma visão abrangente das métricas e distribuições de oportunidades.
                *   **Relatório de Oportunidade Individual**: Análise detalhada da linha do tempo e informações de oportunidades específicas.

                Utilize os filtros em cada página para personalizar sua análise.
            """)

            st.subheader("Visão Geral Rápida")
            col_intro1, col_intro2 = st.columns(2)

            with col_intro1:
                st.info("Clique no 'Painel Geral' para começar a explorar os dados agregados.")

            with col_intro2:
                st.info("Clique em 'Relatório de Oportunidade' para analisar oportunidades específicas.")

            st.markdown("---")

            st.subheader("Interação do Site por Usuário (Dados de Exemplo)")
            if not df_agg_interaction.empty:
                fig_interaction = px.bar(df_agg_interaction, x='User', y='Interactions',
                                         title='Total de Interações do Site por Usuário (Dados de Exemplo)',
                                         template='plotly_white',
                                         color='User',
                                         color_discrete_sequence=px.colors.qualitative.Plotly)

                fig_interaction.update_layout(xaxis_title="Usuário", yaxis_title="Número Total de Interações")
                st.plotly_chart(fig_interaction, use_container_width=True)
            else:
                st.info("Nenhum dado de interação de usuário disponível para exibir.")

            st.markdown("---")

            st.subheader("Sobre o Projeto")
            st.markdown("""
                Este projeto de Business Intelligence foi desenvolvido para fornecer uma visão clara e acionável
                sobre o desempenho das oportunidades de negócios, identificar gargalos no processo e facilitar a tomada de decisão.

                **Idealizador e Supervisor de Projetos:**
                Allisson Silva

                **Contato:**
                *   Telefone: +55 81 9760-0051
                *   Gmail: allisson.silva.modal@gmail.com
                *   Outlook: Allisson.silva@logmultimodal.com.br

                Sinta-se à vontade para entrar em contato para feedback, sugestões ou colaboração.
            """)

        elif page == "Painel Geral":
            st.title("Painel de BI Operacional - Geral")

            st.markdown("""
            Este painel apresenta insights gerais sobre os dados operacionais,
            permitindo acompanhar o desempenho e a distribuição dos negócios.
            """)

            if not df.empty:
                st.sidebar.subheader("Filtros do Painel Geral")

                if not df['Data de abertura'].empty:
                    min_date_abertura = df['Data de abertura'].min().date()
                    max_date_abertura = df['Data de abertura'].max().date()

                    start_date = st.sidebar.date_input("Data de Abertura (Início)", min_value=min_date_abertura, max_value=max_date_abertura, value=min_date_abertura)
                    end_date = st.sidebar.date_input("Data de Abertura (Fim)", min_value=min_date_abertura, max_value=max_date_abertura, value=max_date_abertura)

                    start_datetime = pd.to_datetime(start_date)
                    end_datetime = pd.to_datetime(end_date)

                    filtered_df = df[(df['Data de abertura'] >= start_datetime) & (df['Data de abertura'] <= end_datetime)].copy()
                else:
                    filtered_df = df.copy()

                selected_estados = st.sidebar.multiselect("Selecionar Estado:", filtered_df['Estado'].unique(), filtered_df['Estado'].unique())
                filtered_df = filtered_df[filtered_df['Estado'].isin(selected_estados)]

                selected_responsaveis_sidebar = st.sidebar.multiselect("Selecionar Responsável:", filtered_df['Responsável'].unique(), filtered_df['Responsável'].unique())
                filtered_df = filtered_df[filtered_df['Responsável'].isin(selected_responsaveis_sidebar)]

                selected_estagios = st.sidebar.multiselect("Selecionar Estágio:", filtered_df['Estágio'].unique(), filtered_df['Estágio'].unique())
                filtered_df = filtered_df[filtered_df['Estágio'].isin(selected_estagios)]

                opportunity_identifiers = filtered_df['OC_Identifier'].dropna().unique()
                selected_opportunity_identifier_general = st.sidebar.selectbox(
                    "Filtrar por Oportunidade:",
                    ['Todos'] + list(opportunity_identifiers)
                )

                if selected_opportunity_identifier_general != 'Todos':
                     filtered_df = filtered_df[filtered_df['OC_Identifier'] == selected_opportunity_identifier_general].copy()

                df_agg_responsavel_count = filtered_df.groupby('Responsável')['OC_Identifier'].nunique().reset_index()
                df_agg_responsavel_count.rename(columns={'OC_Identifier': 'Unique Opportunity Count'}, inplace=True)

                df_agg_estado_mes_count = filtered_df.groupby(['Estado', 'MonthYear_Abertura'])['OC_Identifier'].nunique().reset_index()
                df_agg_estado_mes_count.rename(columns={'OC_Identifier': 'Unique Opportunity Count'}, inplace=True)
                df_agg_estado_mes_count['MonthYear_Abertura'] = df_agg_estado_mes_count['MonthYear_Abertura'].astype(str)

                ganha_df_filtered = filtered_df[filtered_df['Estado'] == 'Ganha'].copy()

                st.subheader("Resumo Geral")
                col_kpi1, col_kpi2, col_kpi3 = st.columns(3)

                total_opportunities = filtered_df['OC_Identifier'].nunique() if not filtered_df.empty else 0
                total_won_value = ganha_df_filtered['Valor'].sum() if not ganha_df_filtered.empty else 0
                win_rate = (len(ganha_df_filtered) / total_opportunities * 100) if total_opportunities > 0 else 0

                col_kpi1.metric("Total Oportunidades Únicas", total_opportunities)
                col_kpi2.metric("Valor Total Ganho", f"R$ {total_won_value:,.2f}")
                col_kpi3.metric("Taxa de Sucesso", f"{win_rate:.2f}%")

                st.subheader("Análise de Oportunidades e Valor")
                col1, col2 = st.columns(2)

                with col1:
                    st.subheader("Quantidade de Oportunidades Únicas por Responsável")
                    if not df_agg_responsavel_count.empty:
                        fig1 = px.bar(df_agg_responsavel_count, x='Responsável', y='Unique Opportunity Count',
                                      title='Quantidade de Oportunidades Únicas por Responsável',
                                      color='Responsável',
                                      template='plotly_white',
                                      color_discrete_sequence=px.colors.qualitative.Set2)

                        fig1.update_layout(xaxis_title="Responsável", yaxis_title="Contagem Única de Oportunidades")
                        selected_points = plotly_events(fig1, select_event=True)

                        if selected_points:
                            selected_responsaveis_chart = [p['x'] for p in selected_points]
                            filtered_df_chart_selection = filtered_df[filtered_df['Responsável'].isin(selected_responsaveis_chart)].copy()
                        else:
                            filtered_df_chart_selection = filtered_df.copy()
                    else:
                        st.info("Nenhum dado disponível para 'Quantidade de Oportunidades Únicas por Responsável' com os filtros selecionados.")
                        filtered_df_chart_selection = filtered_df.copy()

                with col2:
                    df_agg_estado_mes_count_filtered = filtered_df_chart_selection.groupby(['Estado', 'MonthYear_Abertura'])['OC_Identifier'].nunique().reset_index()
                    df_agg_estado_mes_count_filtered.rename(columns={'OC_Identifier': 'Unique Opportunity Count'}, inplace=True)
                    df_agg_estado_mes_count_filtered['MonthYear_Abertura'] = df_agg_estado_mes_count_filtered['MonthYear_Abertura'].astype(str)

                    st.subheader("Quantidade de Negócios Únicos por Estado e Mês de Abertura")
                    if not df_agg_estado_mes_count_filtered.empty:
                        fig2 = px.bar(df_agg_estado_mes_count_filtered, x='MonthYear_Abertura', y='Unique Opportunity Count', color='Estado',
                                      title='Quantidade de Negócios Únicos por Estado e Mês de Abertura',
                                      barmode='group',
                                      template='plotly_white',
                                      color_discrete_sequence=px.colors.qualitative.Pastel)

                        fig2.update_layout(xaxis_title="Mês/Ano de Abertura", yaxis_title="Quantidade de Oportunidades Únicas")
                        st.plotly_chart(fig2, use_container_width=True)
                    else:
                        st.info("Nenhum dado disponível para 'Quantidade de Negócios Únicos por Estado e Mês de Abertura' com os filtros selecionados.")

                st.subheader("Heatmap: Oportunidades por Etapa e Hora de Abertura")
                if not df_timeline.empty:
                    df_timeline_filtered_for_heatmap = df_timeline[(df_timeline['Data de abertura'] >= start_datetime) & (df_timeline['Data de abertura'] <= end_datetime)].copy()

                    if selected_points:
                         selected_oc_identifiers_chart = filtered_df_chart_selection['OC_Identifier'].unique()
                         df_timeline_filtered_for_heatmap = df_timeline_filtered_for_heatmap[df_timeline_filtered_for_heatmap['OC_Identifier'].isin(selected_oc_identifiers_chart)].copy()
                    df_timeline_filtered_for_heatmap = df_timeline_filtered_for_heatmap[df_timeline_filtered_for_heatmap['Estágio'].isin(selected_estagios)].copy()

                    if selected_opportunity_identifier_general != 'Todos':
                         df_timeline_filtered_for_heatmap = df_timeline_filtered_for_heatmap[df_timeline_filtered_for_heatmap['OC_Identifier'] == selected_opportunity_identifier_general].copy()

                    df_timeline_filtered_for_heatmap['Hour_of_Day_Abertura'] = df_timeline_filtered_for_heatmap['Data de abertura'].dt.hour

                    if not df_timeline_filtered_for_heatmap.empty:
                         heatmap_data = df_timeline_filtered_for_heatmap.groupby(['Estágio', 'Hour_of_Day_Abertura'])['OC_Identifier'].nunique().unstack(fill_value=0)

                         if not heatmap_data.empty:
                            fig_heatmap = go.Figure(data=go.Heatmap(
                                   z=heatmap_data.values,
                                   x=heatmap_data.columns,
                                   y=heatmap_data.index,
                                   colorscale='Portland'))

                            fig_heatmap.update_layout(title='Oportunidades por Etapa e Hora de Abertura',
                                                      xaxis_title='Hora do Dia',
                                                      yaxis_title='Etapa',
                                                      template='plotly_white')

                            st.plotly_chart(fig_heatmap, use_container_width=True)
                         else:
                            st.info("Nenhum dado agregado disponível para o Heatmap com os filtros selecionados.")
                    else:
                         st.info("Nenhum dado de timeline disponível para o Heatmap com os filtros selecionados.")
                else:
                    st.info("Dados de timeline não disponíveis para o Heatmap.")

                st.subheader("Análise de Estágios")
                col5, = st.columns(1)

                with col5:
                    if not filtered_df_chart_selection.empty:
                        st.subheader("Distribuição de Todos os Estágios")
                        stage_counts = filtered_df_chart_selection['Estágio'].value_counts().reset_index()
                        stage_counts.columns = ['Estágio', 'Count']
                        fig4 = px.bar(stage_counts, x='Estágio', y='Count',
                                      title='Distribuição de Todos os Estágios',
                                      color='Estágio',
                                      template='plotly_white',
                                      color_discrete_sequence=px.colors.qualitative.Set3)
                        fig4.update_layout(xaxis_title="Estágio", yaxis_title="Contagem")
                        st.plotly_chart(fig4, use_container_width=True)
                    else:
                        st.info("Nenhum dado disponível para 'Distribuição de Todos os Estágios' com os filtros selecionados.")

                st.subheader("Análise de Tempo Médio por Estágio")
                if not df_timeline.empty:
                    df_timeline_filtered = df_timeline[(df_timeline['Data de abertura'] >= start_datetime) & (df_timeline['Data de abertura'] <= end_datetime)].copy()

                    if selected_points:
                         selected_oc_identifiers_chart = filtered_df_chart_selection['OC_Identifier'].unique()
                         df_timeline_filtered = df_timeline_filtered[df_timeline_filtered['OC_Identifier'].isin(selected_oc_identifiers_chart)].copy()
                    df_timeline_filtered = df_timeline_filtered[df_timeline_filtered['Estágio'].isin(selected_estagios)].copy()

                    if selected_opportunity_identifier_general != 'Todos':
                         df_timeline_filtered = df_timeline_filtered[df_timeline_filtered['OC_Identifier'] == selected_opportunity_identifier_general].copy()

                    if not df_timeline_filtered.empty:
                        df_agg_time_per_stage_avg = df_timeline_filtered.groupby('Estágio')['Time_in_Stage'].mean().reset_index()
                        df_agg_time_per_stage_avg = df_agg_time_per_stage_avg.sort_values(by='Time_in_Stage', ascending=False)

                        def format_time_in_stage(hours):
                            if pd.isna(hours):
                                return "N/A"
                            total_minutes = int(hours * 60)
                            days = total_minutes // (24 * 60)
                            remaining_minutes_after_days = total_minutes % (24 * 60)
                            hours = remaining_minutes_after_days // 60
                            minutes = remaining_minutes_after_days % 60
                            return f"{days} days, {hours} hours, {minutes} minutes"

                        df_agg_time_per_stage_avg['Average Time in Stage'] = df_agg_time_per_stage_avg['Time_in_Stage'].apply(format_time_in_stage)

                        st.write("Tempo Médio em Cada Estágio:")
                        st.dataframe(df_agg_time_per_stage_avg[['Estágio', 'Average Time in Stage']])

                        st.subheader("Tempo Médio por Estágio Visualização")
                        fig5 = px.bar(df_agg_time_per_stage_avg, x='Estágio', y='Time_in_Stage',
                                      title='Tempo Médio por Estágio',
                                      color='Estágio',
                                      template='plotly_white',
                                      color_discrete_sequence=px.colors.qualitative.Vivid)
                        fig5.update_layout(xaxis_title='Estágio', yaxis_title='Tempo Médio (horas)')
                        st.plotly_chart(fig5, use_container_width=True)
                    else:
                         st.info("Nenhum dado disponível para Análise de Tempo Médio por Estágio com os filtros selecionados.")
                else:
                    st.info("Dados de timeline não disponíveis.")

        elif page == "Relatório de Oportunidade":
            st.title("Relatório de Oportunidade Individual")

            st.markdown("""
            Selecione um identificador de Oportunidade (OC + Número ou CTE + Número)
            para visualizar sua linha do tempo e detalhes.
            """)

            if df.empty or df_timeline.empty:
                st.warning("Dados de oportunidade ou linha do tempo não disponíveis. Por favor, verifique a conexão com o Google Sheet.")
            else:
                try:
                    opportunity_identifiers = df['OC_Identifier'].dropna().unique()

                    if len(opportunity_identifiers) == 0:
                        st.info("Nenhum identificador de oportunidade único encontrado nos dados.")
                    else:
                        selected_opportunity_identifier = st.selectbox("Selecionar Oportunidade (OC + Número ou CTE + Número):", opportunity_identifiers)

                        st.subheader(f"Detalhes e Linha do Tempo para: {selected_opportunity_identifier}")

                        try:
                            opportunity_details_df = df[df['OC_Identifier'] == selected_opportunity_identifier]

                            if opportunity_details_df.empty:
                                st.warning(f"Nenhum detalhe encontrado para: {selected_opportunity_identifier} no DataFrame principal.")
                            else:
                                opportunity_details = opportunity_details_df.iloc[0]

                                col_info1, col_info2 = st.columns(2)

                                with col_info1:
                                    st.write("**ID:**", opportunity_details.get('ID', 'N/A'))
                                    st.write("**Título:**", opportunity_details.get('Título', 'N/A'))
                                    st.write("**Responsável:**", opportunity_details.get('Responsável', 'N/A'))
                                    st.write("**Estado:**", opportunity_details.get('Estado', 'N/A'))
                                    st.write("**Estágio Atual:**", opportunity_details.get('Estágio', 'N/A'))

                                with col_info2:
                                    valor_display = "N/A"
                                    if pd.notna(opportunity_details.get('Valor')) and pd.api.types.is_numeric_dtype(opportunity_details.get('Valor')):
                                        valor_display = f"R$ {opportunity_details['Valor']:,.2f}"
                                    st.write("**Valor:**", valor_display)

                                    st.write("**Origem:**", opportunity_details.get('Origem', 'N/A'))
                                    st.write("**Prob %:**", opportunity_details.get('Prob %', 'N/A'))
                                    st.write("**OC:**", opportunity_details.get('OC', 'N/A'))

                                st.subheader("Datas Principais")
                                col_dates1, col_dates2 = st.columns(2)
                                with col_dates1:
                                    st.write("**Data de Abertura:**", opportunity_details['Data de abertura'].strftime('%d/%m/%Y %H:%M:%S') if pd.notna(opportunity_details['Data de abertura']) else "N/A")
                                with col_dates2:
                                    st.write("**Data de Fechamento:**", opportunity_details['Data fechamento'].strftime('%d/%m/%Y %H:%M:%S') if pd.notna(opportunity_details['Data fechamento']) else "N/A")

                                if pd.notna(opportunity_details.get('Data fechamento')):
                                    with st.expander("Detalhes de Fechamento"):
                                        valor_fechamento_display = "N/A"
                                        if pd.notna(opportunity_details.get('Valor fechamento')) and pd.api.types.is_numeric_dtype(opportunity_details.get('Valor fechamento')):
                                            valor_fechamento_display = f"R$ {opportunity_details['Valor fechamento']:,.2f}"
                                        st.write("**Valor Fechamento:**", valor_fechamento_display)

                                        valor_rec_fechamento_display = "N/A"
                                        if pd.notna(opportunity_details.get('Valor rec. fechamento')) and pd.api.types.is_numeric_dtype(opportunity_details.get('Valor rec. fechamento')):
                                            valor_rec_fechamento_display = f"R$ {opportunity_details['Valor rec. fechamento']:,.2f}"
                                        st.write("**Valor Rec. Fechamento:**", valor_rec_fechamento_display)

                                        st.write("**Razão de Fechamento:**", opportunity_details.get('Razão de fechamento', 'N/A'))
                                        st.write("**Observação de Fechamento:**", opportunity_details.get('Observação de fechamento', 'N/A'))

                                try:
                                    opportunity_timeline = df_timeline[df_timeline['OC_Identifier'] == selected_opportunity_identifier].copy()

                                    if not opportunity_timeline.empty:
                                        st.subheader("Linha do Tempo da Oportunidade")

                                        # Visualização Gráfica da Linha do Tempo
                                        st.markdown("#### 📊 Visualização Gráfica da Linha do Tempo")
                                        
                                        gantt_data = opportunity_timeline.copy()
                                        gantt_data['Start'] = gantt_data['Data de abertura']
                                        gantt_data['Finish'] = gantt_data['Data fechamento'].fillna(pd.Timestamp.now())
                                        gantt_data['Task'] = gantt_data['Estágio']
                                        
                                        fig_gantt = px.timeline(
                                            gantt_data, 
                                            x_start="Start", 
                                            x_end="Finish", 
                                            y="Task",
                                            title=f"Linha do Tempo - {selected_opportunity_identifier}",
                                            color="Task",
                                            color_discrete_sequence=px.colors.qualitative.Set3
                                        )
                                        
                                        fig_gantt.update_layout(
                                            xaxis_title="Data",
                                            yaxis_title="Estágio",
                                            height=400
                                        )
                                        
                                        st.plotly_chart(fig_gantt, use_container_width=True)

                                        # Gráfico de Barras do Tempo
                                        st.markdown("#### ⏱️ Tempo Gasto em Cada Estágio")
                                        
                                        gantt_data['Tempo_Horas'] = (gantt_data['Finish'] - gantt_data['Start']).dt.total_seconds() / 3600
                                        
                                        fig_tempo = px.bar(
                                            gantt_data,
                                            x='Tempo_Horas',
                                            y='Task',
                                            orientation='h',
                                            title="Tempo Gasto por Estágio (Horas)",
                                            color='Task',
                                            color_discrete_sequence=px.colors.qualitative.Pastel
                                        )
                                        
                                        fig_tempo.update_layout(
                                            xaxis_title="Tempo (Horas)",
                                            yaxis_title="Estágio",
                                            height=300
                                        )
                                        
                                        st.plotly_chart(fig_tempo, use_container_width=True)

                                        # Tabela de detalhes
                                        st.markdown("#### 📋 Detalhes da Linha do Tempo")
                                        display_timeline_cols = ['Estágio', 'Data de abertura', 'Data fechamento', 'Time_in_Stage_Formatted']
                                        st.dataframe(opportunity_timeline[display_timeline_cols])
                                        
                                    else:
                                        st.info(f"Nenhum dado de linha do tempo encontrado para: {selected_opportunity_identifier}")

                                except Exception as e:
                                    st.error(f"Erro ao processar ou exibir dados de linha do tempo para {selected_opportunity_identifier}: {e}")

                                # --- AI Agent Interaction Section ---
                                st.subheader("Assistente de IA para Oportunidade")
                                
                                if st.session_state.get('ai_response') is None:
                                    st.session_state['ai_response'] = ""

                                if client:
                                    user_query = st.text_area(f"Faça uma pergunta sobre a oportunidade {selected_opportunity_identifier}:", height=100, key='user_query')
                                    col_ai_button1, col_ai_button2, col_ai_button3 = st.columns(3)

                                    with col_ai_button1:
                                        if st.button("Obter Resposta da IA", use_container_width=True):
                                            if user_query:
                                                with st.spinner("Obtendo resposta da IA..."):
                                                    try:
                                                        prompt = f"""
                                                        Você é um assistente de BI focado em analisar dados de oportunidades de negócios.
                                                        Sua tarefa é responder a perguntas sobre uma oportunidade específica com base nos dados fornecidos.
                                                        Seja conciso e útil, focando em insights de BI e na progressão da oportunidade.
                                                        **Use APENAS os dados fornecidos abaixo.**
                                                        Se a pergunta do usuário não puder ser respondida com os dados disponíveis, diga isso de forma educada.

                                                        Dados da Oportunidade com identificador {selected_opportunity_identifier}:

                                                        Detalhes Principais:
                                                        - ID: {opportunity_details.get('ID', 'N/A')}
                                                        - Título: {opportunity_details.get('Título', 'N/A')}
                                                        - Responsável: {opportunity_details.get('Responsável', 'N/A')}
                                                        - Estado: {opportunity_details.get('Estado', 'N/A')}
                                                        - Estágio Atual: {opportunity_details.get('Estágio', 'N/A')}
                                                        - Valor: R$ {opportunity_details.get('Valor', 'N/A')}
                                                        - Origem: {opportunity_details.get('Origem', 'N/A')}
                                                        - Prob %: {opportunity_details.get('Prob %', 'N/A')}
                                                        - OC: {opportunity_details.get('OC', 'N/A')}
                                                        - Data de Abertura: {opportunity_details.get('Data de abertura', 'N/A')}
                                                        - Data de Fechamento: {opportunity_details.get('Data fechamento', 'N/A')}

                                                        Detalhes de Fechamento (se aplicável):
                                                        - Valor Fechamento: R$ {opportunity_details.get('Valor fechamento', 'N/A')}
                                                        - Valor Rec. Fechamento: R$ {opportunity_details.get('Valor rec. fechamento', 'N/A')}
                                                        - Razão de Fechamento: {opportunity_details.get('Razão de fechamento', 'N/A')}
                                                        - Observação de Fechamento: {opportunity_details.get('Observação de fechamento', 'N/A')}

                                                        Linha do Tempo (Estágios e Tempos):
                                                        {opportunity_timeline[['Estágio', 'Data de abertura', 'Data fechamento', 'Time_in_Stage_Formatted']].to_string(index=False)}

                                                        Pergunta do Usuário: {user_query}

                                                        Responda em Português do Brasil.
                                                        """

                                                        response = client.chat.completions.create(
                                                            model="gpt-4o-mini",
                                                            messages=[
                                                                {"role": "system", "content": "Você é um assistente de BI útil e conciso."},
                                                                {"role": "user", "content": prompt}
                                                            ],
                                                            max_tokens=300
                                                        )
                                                        st.session_state['ai_response'] = response.choices[0].message.content
                                                    except Exception as e:
                                                        st.session_state['ai_response'] = f"Erro ao comunicar com a API da OpenAI: {e}"
                                            else:
                                                st.session_state['ai_response'] = "Por favor, digite sua pergunta sobre a oportunidade."

                                    with col_ai_button2:
                                        if st.button("Limpar Resposta da IA", use_container_width=True):
                                            st.session_state['ai_response'] = ""

                                    with col_ai_button3:
                                        if st.button("📄 Exportar Relatório PDF", use_container_width=True):
                                            try:
                                                # Criar PDF
                                                pdf = FPDF()
                                                pdf.add_page()
                                                
                                                # Configurar fonte
                                                pdf.set_font("Arial", size=12)
                                                
                                                # Título
                                                pdf.set_font("Arial", 'B', 16)
                                                pdf.cell(200, 10, f"Relatorio: {selected_opportunity_identifier}", ln=True, align='C')
                                                pdf.ln(10)
                                                
                                                # Detalhes da Oportunidade
                                                pdf.set_font("Arial", 'B', 14)
                                                pdf.cell(200, 10, "Detalhes da Oportunidade:", ln=True)
                                                pdf.set_font("Arial", size=10)
                                                
                                                details = [
                                                    f"ID: {opportunity_details.get('ID', 'N/A')}",
                                                    f"Titulo: {opportunity_details.get('Titulo', 'N/A')}",
                                                    f"Responsavel: {opportunity_details.get('Responsavel', 'N/A')}",
                                                    f"Estado: {opportunity_details.get('Estado', 'N/A')}",
                                                    f"Estagio Atual: {opportunity_details.get('Estagio', 'N/A')}",
                                                    f"Valor: {valor_display}",
                                                    f"Origem: {opportunity_details.get('Origem', 'N/A')}",
                                                    f"Probabilidade: {opportunity_details.get('Prob %', 'N/A')}%",
                                                    f"Data de Abertura: {opportunity_details['Data de abertura'].strftime('%d/%m/%Y %H:%M:%S') if pd.notna(opportunity_details['Data de abertura']) else 'N/A'}",
                                                    f"Data de Fechamento: {opportunity_details['Data fechamento'].strftime('%d/%m/%Y %H:%M:%S') if pd.notna(opportunity_details['Data fechamento']) else 'N/A'}"
                                                ]
                                                
                                                for detail in details:
                                                    pdf.cell(200, 8, detail, ln=True)
                                                
                                                pdf.ln(8)
                                                
                                                # Linha do Tempo
                                                if not opportunity_timeline.empty:
                                                    pdf.set_font("Arial", 'B', 14)
                                                    pdf.cell(200, 10, "Linha do Tempo:", ln=True)
                                                    pdf.set_font("Arial", size=8)
                                                    
                                                    # Cabeçalho da tabela
                                                    pdf.cell(50, 8, "Estagio", border=1)
                                                    pdf.cell(40, 8, "Data Abertura", border=1)
                                                    pdf.cell(40, 8, "Data Fechamento", border=1)
                                                    pdf.cell(60, 8, "Tempo", border=1)
                                                    pdf.ln()
                                                    
                                                    # Dados da tabela
                                                    for _, row in opportunity_timeline.iterrows():
                                                        pdf.cell(50, 8, str(row['Estagio'])[:20], border=1)
                                                        pdf.cell(40, 8, row['Data de abertura'].strftime('%d/%m/%Y') if pd.notna(row['Data de abertura']) else 'N/A', border=1)
                                                        pdf.cell(40, 8, row['Data fechamento'].strftime('%d/%m/%Y') if pd.notna(row['Data fechamento']) else 'Em andamento', border=1)
                                                        pdf.cell(60, 8, str(row['Time_in_Stage_Formatted'])[:25], border=1)
                                                        pdf.ln()
                                                
                                                pdf.ln(8)
                                                
                                                # Resposta da IA
                                                if st.session_state.get('ai_response') and st.session_state['ai_response'] != "":
                                                    pdf.set_font("Arial", 'B', 14)
                                                    pdf.cell(200, 10, "Analise da IA:", ln=True)
                                                    pdf.set_font("Arial", size=9)
                                                    
                                                    ai_response = st.session_state['ai_response']
                                                    pdf.multi_cell(0, 5, ai_response)
                                                
                                                # Data de geração
                                                pdf.ln(10)
                                                pdf.set_font("Arial", 'I', 8)
                                                pdf.cell(200, 8, f"Relatorio gerado em: {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}", ln=True)
                                                
                                                # Salvar PDF
                                                pdf_output = f"relatorio_{selected_opportunity_identifier}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf"
                                                pdf.output(pdf_output)
                                                
                                                # Criar link de download
                                                with open(pdf_output, "rb") as f:
                                                    pdf_bytes = f.read()
                                                
                                                b64 = base64.b64encode(pdf_bytes).decode()
                                                href = f'<a href="data:application/octet-stream;base64,{b64}" download="{pdf_output}">📥 Clique aqui para baixar o PDF</a>'
                                                st.markdown(href, unsafe_allow_html=True)
                                                st.success("PDF gerado com sucesso!")
                                                
                                            except Exception as e:
                                                st.error(f"Erro ao gerar PDF: {e}")

                                    # Display AI response
                                    if st.session_state.get('ai_response'):
                                        st.text_area("Resposta da IA:", value=st.session_state['ai_response'], height=200, disabled=True, key='ai_response_display')
                                else:
                                    st.info("O assistente de IA está desabilitado porque a chave da API da OpenAI não foi configurada.")

                        except Exception as e:
                            st.error(f"Erro ao carregar detalhes da oportunidade {selected_opportunity_identifier}: {e}")

                except Exception as e:
                    st.error(f"Erro ao processar identificadores de oportunidade: {e}")

except Exception as e:
    st.error(f"Ocorreu um erro geral na aplicação: {e}")
    st.stop()
