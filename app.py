import os
import streamlit as st
import pandas as pd
import numpy as np
import plotly.express as px
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import gspread
from datetime import datetime, timedelta
from oauth2client.service_account import ServiceAccountCredentials
import re
from streamlit_autorefresh import st_autorefresh

# --- CONFIGURAÇÃO DA PÁGINA ---
st.set_page_config(
    page_title="Painel Executivo - BI Operacional",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded"
)

# --- ESTILOS CSS PERSONALIZADOS ---
st.markdown("""
<style>
    .main-header {
        font-size: 3rem;
        font-weight: bold;
        background: linear-gradient(90deg, #0066CC, #00CCFF);
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
        text-align: center;
        margin-bottom: 2rem;
    }
    .metric-card {
        background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
        padding: 1.5rem;
        border-radius: 15px;
        color: white;
        box-shadow: 0 4px 15px rgba(0,0,0,0.1);
    }
    .metric-value {
        font-size: 2.5rem;
        font-weight: bold;
        margin: 0.5rem 0;
    }
    .metric-label {
        font-size: 0.9rem;
        opacity: 0.9;
    }
    .positive-trend {
        color: #00FF88;
        font-weight: bold;
    }
    .negative-trend {
        color: #FF4444;
        font-weight: bold;
    }
    .section-header {
        font-size: 1.5rem;
        font-weight: bold;
        color: #2E86AB;
        margin: 2rem 0 1rem 0;
        padding-bottom: 0.5rem;
        border-bottom: 2px solid #2E86AB;
    }
</style>
""", unsafe_allow_html=True)

# --- INICIALIZAÇÃO DE SESSÃO ---
if 'authenticated' not in st.session_state:
    st.session_state.authenticated = False
if 'data_loaded' not in st.session_state:
    st.session_state.data_loaded = False
if 'df' not in st.session_state:
    st.session_state.df = pd.DataFrame()
if 'df_timeline' not in st.session_state:
    st.session_state.df_timeline = pd.DataFrame()

# --- AUTENTICAÇÃO GOOGLE SHEETS ---
@st.cache_resource
def get_gspread_client():
    try:
        creds = st.secrets["connections"]["gsheets"]
        scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
        credentials = ServiceAccountCredentials.from_json_keyfile_dict(creds, scope)
        return gspread.authorize(credentials)
    except Exception as e:
        st.error(f"❌ Erro na autenticação: {e}")
        return None

# --- CARREGAMENTO E TRATAMENTO DE DADOS ---
@st.cache_data(ttl=300)
def load_and_process_data(_gc):
    try:
        spreadsheet = _gc.open('BI_B2')
        worksheet = spreadsheet.sheet1
        records = worksheet.get_all_records()
        
        if not records:
            return pd.DataFrame(), pd.DataFrame()
            
        df = pd.DataFrame(records)
        
        # --- LIMPEZA E TRATAMENTO ---
        # Remover duplicatas baseado em ID ou título
        df = df.drop_duplicates(subset=['ID', 'Título'], keep='last')
        
        # Converter valores monetários
        monetary_cols = ['Valor', 'Valor Rec.', 'Valor fechamento', 'Valor rec. fechamento']
        for col in monetary_cols:
            if col in df.columns:
                df[col] = (
                    df[col].astype(str)
                    .str.replace('R\$', '', regex=False)
                    .str.replace('.', '', regex=False)
                    .str.replace(',', '.', regex=False)
                    .str.strip()
                )
                df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0)
        
        # Converter datas
        date_cols = ['Data de abertura', 'Data fechamento']
        for col in date_cols:
            if col in df.columns:
                df[col] = pd.to_datetime(df[col], errors='coerce', dayfirst=True)
        
        # Extrair identificador único da oportunidade
        def extract_opportunity_id(title):
            if isinstance(title, str):
                patterns = [
                    r'OC\s*(\d+)',
                    r'CTE\s*(\d+)',
                    r'OP\s*(\d+)',
                    r'(\d{4,})'  # Números com 4+ dígitos
                ]
                for pattern in patterns:
                    match = re.search(pattern, title, re.IGNORECASE)
                    if match:
                        return f"OC_{match.group(1)}"
            return f"UNK_{hash(str(title)) % 10000:04d}"
        
        df['OPPORTUNITY_ID'] = df['Título'].apply(extract_opportunity_id)
        
        # Engenharia de features para BI
        df['MES_ABERTURA'] = df['Data de abertura'].dt.to_period('M')
        df['ANO_ABERTURA'] = df['Data de abertura'].dt.year
        df['DIA_SEMANA'] = df['Data de abertura'].dt.day_name()
        df['HORA_ABERTURA'] = df['Data de abertura'].dt.hour
        
        # Classificar estágios
        df['ESTAGIO_GRUPO'] = df['Estágio'].apply(
            lambda x: 'INICIAL' if any(word in str(x).upper() for word in ['QUALIFIC', 'PROSPEC']) 
            else 'NEGOCIACAO' if any(word in str(x).upper() for word in ['NEGOC', 'PROPOSTA'])
            else 'FECHAMENTO' if any(word in str(x).upper() for word in ['FECH', 'GANH', 'PERDID'])
            else 'OUTROS'
        )
        
        # Criar timeline para análise de tempo
        df_timeline = df[['OPPORTUNITY_ID', 'Estágio', 'Data de abertura', 'Data fechamento', 'Estado']].copy()
        df_timeline = df_timeline.dropna(subset=['Data de abertura'])
        
        if not df_timeline.empty:
            current_time = pd.Timestamp.now()
            df_timeline['TEMPO_ESTAGIO_HORAS'] = (
                df_timeline['Data fechamento'].fillna(current_time) - df_timeline['Data de abertura']
            ).dt.total_seconds() / 3600
            
            df_timeline['TEMPO_ESTAGIO_DIAS'] = df_timeline['TEMPO_ESTAGIO_HORAS'] / 24
        
        return df, df_timeline
        
    except Exception as e:
        st.error(f"❌ Erro no carregamento: {e}")
        return pd.DataFrame(), pd.DataFrame()

# --- KPI CALCULATIONS ---
def calculate_kpis(df):
    if df.empty:
        return {}
    
    kpis = {}
    
    # Oportunidades únicas
    kpis['total_oportunidades'] = df['OPPORTUNITY_ID'].nunique()
    
    # Valor total
    kpis['valor_total_aberto'] = df[df['Estado'].isin(['Aberta', 'Em andamento'])]['Valor'].sum()
    kpis['valor_total_ganho'] = df[df['Estado'] == 'Ganha']['Valor fechamento'].sum()
    
    # Taxa de conversão
    oportunidades_ganhas = df[df['Estado'] == 'Ganha']['OPPORTUNITY_ID'].nunique()
    kpis['taxa_conversao'] = (oportunidades_ganhas / kpis['total_oportunidades'] * 100) if kpis['total_oportunidades'] > 0 else 0
    
    # Tempo médio de fechamento
    oportunidades_fechadas = df[df['Estado'].isin(['Ganha', 'Perdida'])]
    if not oportunidades_fechadas.empty:
        tempo_medio = (oportunidades_fechadas['Data fechamento'] - oportunidades_fechadas['Data de abertura']).dt.days.mean()
        kpis['tempo_medio_fechamento'] = tempo_medio
    else:
        kpis['tempo_medio_fechamento'] = 0
    
    # Eficiência por responsável
    if 'Responsável' in df.columns:
        resp_stats = df.groupby('Responsável').agg({
            'OPPORTUNITY_ID': 'nunique',
            'Valor': 'sum',
            'Estado': lambda x: (x == 'Ganha').sum()
        }).round(2)
        kpis['top_responsavel'] = resp_stats.nlargest(1, 'OPPORTUNITY_ID').iloc[0] if not resp_stats.empty else None
    
    # Pipeline por estágio
    pipeline_estagio = df.groupby('Estágio').agg({
        'OPPORTUNITY_ID': 'nunique',
        'Valor': 'sum'
    }).round(2)
    kpis['pipeline_estagio'] = pipeline_estagio
    
    return kpis

# --- COMPONENTES VISUAIS ---
def create_metric_card(title, value, change=None, format_func=None):
    if format_func:
        value_str = format_func(value)
    else:
        value_str = str(value)
    
    change_html = ""
    if change is not None:
        change_class = "positive-trend" if change >= 0 else "negative-trend"
        change_symbol = "↗" if change >= 0 else "↘"
        change_html = f'<div class="{change_class}">{change_symbol} {abs(change):.1f}%</div>'
    
    return f"""
    <div class="metric-card">
        <div class="metric-label">{title}</div>
        <div class="metric-value">{value_str}</div>
        {change_html}
    </div>
    """

def format_currency(value):
    return f"R$ {value:,.0f}".replace(",", ".")

def format_percentage(value):
    return f"{value:.1f}%"

# --- PÁGINA DE LOGIN ---
def login_page():
    st.markdown('<div class="main-header">🔐 Painel Executivo</div>', unsafe_allow_html=True)
    
    with st.container():
        col1, col2, col3 = st.columns([1,2,1])
        with col2:
            with st.form("login_form"):
                st.subheader("Acesso Restrito")
                username = st.text_input("Usuário")
                password = st.text_input("Senha", type="password")
                
                if st.form_submit_button("🚀 Acessar Painel", use_container_width=True):
                    valid_user = st.secrets.get("login", {}).get("username")
                    valid_pass = st.secrets.get("login", {}).get("password")
                    
                    if username == valid_user and password == valid_pass:
                        st.session_state.authenticated = True
                        st.session_state.data_loaded = False
                        st.rerun()
                    else:
                        st.error("Credenciais inválidas")

# --- PAINEL PRINCIPAL ---
def main_dashboard():
    # Header
    col1, col2, col3 = st.columns([2,1,1])
    with col1:
        st.markdown('<div class="main-header">📊 Painel Executivo - BI Operacional</div>', unsafe_allow_html=True)
    with col3:
        if st.button("🔄 Atualizar Dados", use_container_width=True):
            st.cache_data.clear()
            st.session_state.data_loaded = False
            st.rerun()
    
    # Carregar dados se necessário
    if not st.session_state.data_loaded:
        with st.spinner("📥 Carregando dados..."):
            gc = get_gspread_client()
            if gc:
                df, df_timeline = load_and_process_data(gc)
                st.session_state.df = df
                st.session_state.df_timeline = df_timeline
                st.session_state.data_loaded = True
                st.rerun()
    
    if st.session_state.df.empty:
        st.warning("⚠️ Nenhum dado disponível. Verifique a conexão com a planilha.")
        return
    
    # KPIs PRINCIPAIS
    kpis = calculate_kpis(st.session_state.df)
    
    st.markdown('<div class="section-header">📈 MÉTRICAS EXECUTIVAS</div>', unsafe_allow_html=True)
    
    col1, col2, col3, col4 = st.columns(4)
    
    with col1:
        st.markdown(create_metric_card(
            "OPORTUNIDADES", 
            kpis.get('total_oportunidades', 0),
            format_func=lambda x: f"{x:,.0f}".replace(",", ".")
        ), unsafe_allow_html=True)
    
    with col2:
        st.markdown(create_metric_card(
            "VALOR EM PIPELINE",
            kpis.get('valor_total_aberto', 0),
            format_func=format_currency
        ), unsafe_allow_html=True)
    
    with col3:
        st.markdown(create_metric_card(
            "VALOR GANHO",
            kpis.get('valor_total_ganho', 0),
            format_func=format_currency
        ), unsafe_allow_html=True)
    
    with col4:
        st.markdown(create_metric_card(
            "TAXA DE SUCESSO",
            kpis.get('taxa_conversao', 0),
            format_func=format_percentage
        ), unsafe_allow_html=True)
    
    # VISUALIZAÇÕES PRINCIPAIS
    col1, col2 = st.columns(2)
    
    with col1:
        st.markdown('<div class="section-header">📊 PIPELINE POR ESTÁGIO</div>', unsafe_allow_html=True)
        
        if not kpis.get('pipeline_estagio', pd.DataFrame()).empty:
            pipeline_data = kpis['pipeline_estagio'].reset_index()
            fig = px.funnel(
                pipeline_data, 
                x='Valor', 
                y='Estágio',
                title="Valor em Pipeline por Estágio",
                color='Estágio',
                height=400
            )
            fig.update_layout(showlegend=False)
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("Sem dados de pipeline disponíveis")
    
    with col2:
        st.markdown('<div class="section-header">📈 EVOLUÇÃO MENSAL</div>', unsafe_allow_html=True)
        
        evolucao_mensal = st.session_state.df.groupby(
            st.session_state.df['Data de abertura'].dt.to_period('M')
        ).agg({
            'OPPORTUNITY_ID': 'nunique',
            'Valor': 'sum'
        }).reset_index()
        
        evolucao_mensal['Data de abertura'] = evolucao_mensal['Data de abertura'].astype(str)
        
        fig = go.Figure()
        fig.add_trace(go.Scatter(
            x=evolucao_mensal['Data de abertura'],
            y=evolucao_mensal['OPPORTUNITY_ID'],
            name='Oportunidades',
            line=dict(color='#00CCFF', width=3)
        ))
        fig.add_trace(go.Bar(
            x=evolucao_mensal['Data de abertura'],
            y=evolucao_mensal['Valor'],
            name='Valor (R$)',
            yaxis='y2',
            opacity=0.6
        ))
        
        fig.update_layout(
            xaxis_title="Mês",
            yaxis_title="Quantidade de Oportunidades",
            yaxis2=dict(
                title="Valor (R$)",
                overlaying='y',
                side='right'
            ),
            height=400,
            showlegend=True
        )
        st.plotly_chart(fig, use_container_width=True)
    
    # ANÁLISE DE PERFORMANCE
    st.markdown('<div class="section-header">🎯 ANÁLISE DE PERFORMANCE</div>', unsafe_allow_html=True)
    
    col1, col2 = st.columns(2)
    
    with col1:
        # Heatmap de atividades por hora e dia
        st.subheader("🏢 Atividade por Hora do Dia")
        
        if not st.session_state.df.empty:
            heatmap_data = st.session_state.df.pivot_table(
                index='DIA_SEMANA',
                columns='HORA_ABERTURA',
                values='OPPORTUNITY_ID',
                aggfunc='count',
                fill_value=0
            )
            
            # Ordenar dias da semana
            dias_ordenados = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']
            heatmap_data = heatmap_data.reindex(dias_ordenados)
            
            fig = px.imshow(
                heatmap_data,
                title="Oportunidades por Dia e Hora",
                color_continuous_scale='Blues',
                aspect="auto"
            )
            st.plotly_chart(fig, use_container_width=True)
    
    with col2:
        # Distribuição por estágio
        st.subheader("📋 Distribuição por Estágio")
        
        dist_estagio = st.session_state.df['Estágio'].value_counts().reset_index()
        dist_estagio.columns = ['Estágio', 'Quantidade']
        
        fig = px.pie(
            dist_estagio, 
            values='Quantidade', 
            names='Estágio',
            hole=0.4,
            color_discrete_sequence=px.colors.sequential.Blues_r
        )
        fig.update_traces(textposition='inside', textinfo='percent+label')
        st.plotly_chart(fig, use_container_width=True)
    
    # TOP PERFORMERS
    st.markdown('<div class="section-header">🏆 TOP PERFORMERS</div>', unsafe_allow_html=True)
    
    if 'Responsável' in st.session_state.df.columns:
        top_responsaveis = st.session_state.df.groupby('Responsável').agg({
            'OPPORTUNITY_ID': 'nunique',
            'Valor': 'sum',
            'Estado': lambda x: (x == 'Ganha').sum()
        }).round(2).nlargest(10, 'OPPORTUNITY_ID')
        
        col1, col2 = st.columns(2)
        
        with col1:
            st.subheader("Top 10 por Volume")
            fig = px.bar(
                top_responsaveis.reset_index(),
                x='Responsável',
                y='OPPORTUNITY_ID',
                title="Oportunidades por Responsável",
                color='OPPORTUNITY_ID',
                color_continuous_scale='Viridis'
            )
            st.plotly_chart(fig, use_container_width=True)
        
        with col2:
            st.subheader("Top 10 por Valor")
            top_valor = st.session_state.df.groupby('Responsável')['Valor'].sum().nlargest(10)
            fig = px.bar(
                top_valor.reset_index(),
                x='Responsável',
                y='Valor',
                title="Valor por Responsável",
                color='Valor',
                color_continuous_scale='Plasma'
            )
            st.plotly_chart(fig, use_container_width=True)
    
    # ANÁLISE TEMPORAL DETALHADA
    st.markdown('<div class="section-header">⏰ ANÁLISE TEMPORAL</div>', unsafe_allow_html=True)
    
    if not st.session_state.df_timeline.empty:
        col1, col2 = st.columns(2)
        
        with col1:
            # Tempo médio por estágio
            tempo_estagio = st.session_state.df_timeline.groupby('Estágio')['TEMPO_ESTAGIO_DIAS'].mean().sort_values()
            
            fig = px.bar(
                tempo_estagio.reset_index(),
                x='TEMPO_ESTAGIO_DIAS',
                y='Estágio',
                orientation='h',
                title="Tempo Médio por Estágio (Dias)",
                color='TEMPO_ESTAGIO_DIAS',
                color_continuous_scale='Reds'
            )
            st.plotly_chart(fig, use_container_width=True)
        
        with col2:
            # Eficiência do pipeline
            st.subheader("📈 Eficiência do Pipeline")
            
            eficiencia = st.session_state.df_timeline.groupby('Estágio').agg({
                'OPPORTUNITY_ID': 'nunique',
                'TEMPO_ESTAGIO_DIAS': 'mean'
            }).round(2)
            
            fig = go.Figure(data=[
                go.Bar(name='Quantidade', x=eficiencia.index, y=eficiencia['OPPORTUNITY_ID'], yaxis='y1'),
                go.Scatter(name='Tempo Médio (Dias)', x=eficiencia.index, y=eficiencia['TEMPO_ESTAGIO_DIAS'], yaxis='y2')
            ])
            
            fig.update_layout(
                xaxis_title="Estágio",
                yaxis=dict(title="Quantidade", side='left'),
                yaxis2=dict(title="Tempo Médio (Dias)", side='right', overlaying='y'),
                showlegend=True
            )
            st.plotly_chart(fig, use_container_width=True)

# --- APLICAÇÃO PRINCIPAL ---
def main():
    if not st.session_state.authenticated:
        login_page()
    else:
        # Sidebar
        with st.sidebar:
            st.title("🎯 Navegação")
            st.markdown("---")
            
            if st.button("🚪 Logout", use_container_width=True):
                st.session_state.authenticated = False
                st.session_state.data_loaded = False
                st.rerun()
            
            st.markdown("---")
            st.markdown("### 📊 Filtros")
            
            # Filtros dinâmicos quando dados carregados
            if st.session_state.data_loaded and not st.session_state.df.empty:
                # Filtro por período
                min_date = st.session_state.df['Data de abertura'].min().date()
                max_date = st.session_state.df['Data de abertura'].max().date()
                
                date_range = st.date_input(
                    "Período de Análise",
                    value=(min_date, max_date),
                    min_value=min_date,
                    max_value=max_date
                )
                
                # Filtro por estágio
                estagios = st.session_state.df['Estágio'].unique()
                selected_estagios = st.multiselect(
                    "Estágios",
                    options=estagios,
                    default=estagios
                )
                
                # Filtro por responsável
                if 'Responsável' in st.session_state.df.columns:
                    responsaveis = st.session_state.df['Responsável'].unique()
                    selected_responsaveis = st.multiselect(
                        "Responsáveis",
                        options=responsaveis,
                        default=responsaveis
                    )
        
        main_dashboard()

if __name__ == "__main__":
    main()
