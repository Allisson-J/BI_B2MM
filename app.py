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
import time

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
        font-size: 2.5rem;
        font-weight: bold;
        background: linear-gradient(90deg, #0066CC, #00CCFF);
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
        text-align: center;
        margin-bottom: 1rem;
        padding: 1rem;
    }
    .metric-card {
        background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
        padding: 1.5rem;
        border-radius: 15px;
        color: white;
        box-shadow: 0 4px 15px rgba(0,0,0,0.1);
        border: 1px solid rgba(255,255,255,0.2);
        transition: transform 0.3s ease;
    }
    .metric-card:hover {
        transform: translateY(-5px);
    }
    .metric-value {
        font-size: 2.2rem;
        font-weight: bold;
        margin: 0.5rem 0;
        text-shadow: 1px 1px 2px rgba(0,0,0,0.3);
    }
    .metric-label {
        font-size: 0.9rem;
        opacity: 0.9;
        font-weight: 500;
    }
    .positive-trend {
        color: #00FF88;
        font-weight: bold;
        font-size: 0.8rem;
    }
    .negative-trend {
        color: #FF4444;
        font-weight: bold;
        font-size: 0.8rem;
    }
    .section-header {
        font-size: 1.4rem;
        font-weight: bold;
        color: #2E86AB;
        margin: 1.5rem 0 1rem 0;
        padding-bottom: 0.5rem;
        border-bottom: 2px solid #2E86AB;
    }
    .stAlert {
        border-radius: 10px;
    }
    .sidebar .sidebar-content {
        background: linear-gradient(180deg, #2E86AB 0%, #1B4F72 100%);
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
if 'last_refresh' not in st.session_state:
    st.session_state.last_refresh = None

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
            st.warning("⚠️ Nenhum dado encontrado na planilha.")
            return pd.DataFrame(), pd.DataFrame()
            
        df = pd.DataFrame(records)
        
        # --- LIMPEZA E TRATAMENTO AVANÇADO ---
        # Remover duplicatas baseado em múltiplos critérios
        df = df.drop_duplicates(subset=['ID', 'Título', 'Data de abertura'], keep='last')
        
        # Converter valores monetários com tratamento robusto
        monetary_cols = ['Valor', 'Valor Rec.', 'Valor fechamento', 'Valor rec. fechamento']
        for col in monetary_cols:
            if col in df.columns:
                df[col] = (
                    df[col].astype(str)
                    .str.replace('R\$', '', regex=False)
                    .str.replace('.', '', regex=False)
                    .str.replace(',', '.', regex=False)
                    .str.replace(' ', '', regex=False)
                    .str.strip()
                )
                # Converter para numérico, tratando valores inválidos
                df[col] = pd.to_numeric(df[col], errors='coerce')
                df[col] = df[col].fillna(0)
        
        # Converter datas com múltiplos formatos
        date_cols = ['Data de abertura', 'Data fechamento']
        for col in date_cols:
            if col in df.columns:
                # Tentar diferentes formatos de data
                df[col] = pd.to_datetime(df[col], errors='coerce', dayfirst=True)
        
        # Extrair identificador único da oportunidade
        def extract_opportunity_id(title):
            if pd.isna(title):
                return f"UNK_{np.random.randint(10000, 99999)}"
            
            title_str = str(title).upper()
            patterns = [
                (r'OC\s*(\d+)', 'OC'),
                (r'CTE\s*(\d+)', 'CTE'),
                (r'OP\s*(\d+)', 'OP'),
                (r'OPORTUNIDADE\s*(\d+)', 'OP'),
                (r'(\d{5,})', 'REF')  # Números com 5+ dígitos
            ]
            
            for pattern, prefix in patterns:
                match = re.search(pattern, title_str)
                if match:
                    return f"{prefix}_{match.group(1)}"
            
            return f"UNK_{hash(title_str) % 100000:05d}"

        df['OPPORTUNITY_ID'] = df['Título'].apply(extract_opportunity_id)
        
        # Engenharia de features para BI executivo
        df['MES_ABERTURA'] = df['Data de abertura'].dt.to_period('M')
        df['ANO_ABERTURA'] = df['Data de abertura'].dt.year
        df['TRIMESTRE'] = df['Data de abertura'].dt.quarter
        df['DIA_SEMANA'] = df['Data de abertura'].dt.day_name()
        df['HORA_ABERTURA'] = df['Data de abertura'].dt.hour
        
        # Classificar estágios para análise executiva
        def classify_stage(estagio):
            if pd.isna(estagio):
                return 'NÃO INFORMADO'
            
            estagio_str = str(estagio).upper()
            if any(word in estagio_str for word in ['QUALIFIC', 'PROSPEC', 'CONTATO']):
                return 'QUALIFICAÇÃO'
            elif any(word in estagio_str for word in ['NEGOC', 'PROPOSTA', 'APRESENTA']):
                return 'NEGOCIAÇÃO'
            elif any(word in estagio_str for word in ['FECH', 'CONTRAT', 'FINALIZ']):
                return 'FECHAMENTO'
            elif any(word in estagio_str for word in ['GANH', 'CONCLUÍD', 'VENCID']):
                return 'GANHA'
            elif any(word in estagio_str for word in ['PERDID', 'CANCELAD', 'DESIST']):
                return 'PERDIDA'
            else:
                return 'EM ANDAMENTO'
        
        df['ESTAGIO_GRUPO'] = df['Estágio'].apply(classify_stage)
        
        # Calcular idade da oportunidade
        current_time = pd.Timestamp.now()
        df['IDADE_DIAS'] = (current_time - df['Data de abertura']).dt.days
        
        # Criar timeline para análise de tempo
        df_timeline = df[['OPPORTUNITY_ID', 'Estágio', 'ESTAGIO_GRUPO', 'Data de abertura', 'Data fechamento', 'Estado', 'Valor']].copy()
        df_timeline = df_timeline.dropna(subset=['Data de abertura'])
        
        if not df_timeline.empty:
            df_timeline['TEMPO_ESTAGIO_HORAS'] = (
                df_timeline['Data fechamento'].fillna(current_time) - df_timeline['Data de abertura']
            ).dt.total_seconds() / 3600
            
            df_timeline['TEMPO_ESTAGIO_DIAS'] = df_timeline['TEMPO_ESTAGIO_HORAS'] / 24
        
        return df, df_timeline
        
    except Exception as e:
        st.error(f"❌ Erro no carregamento de dados: {str(e)}")
        return pd.DataFrame(), pd.DataFrame()

# --- KPI CALCULATIONS ---
def calculate_kpis(df):
    if df.empty:
        return {}
    
    kpis = {}
    
    try:
        # Oportunidades únicas
        kpis['total_oportunidades'] = df['OPPORTUNITY_ID'].nunique()
        
        # Valor total
        kpis['valor_total_aberto'] = df[df['Estado'].isin(['Aberta', 'Em andamento'])]['Valor'].sum()
        kpis['valor_total_ganho'] = df[df['Estado'] == 'Ganha']['Valor fechamento'].sum()
        kpis['valor_total_pipeline'] = df[~df['Estado'].isin(['Ganha', 'Perdida'])]['Valor'].sum()
        
        # Taxa de conversão
        oportunidades_ganhas = df[df['Estado'] == 'Ganha']['OPPORTUNITY_ID'].nunique()
        oportunidades_fechadas = df[df['Estado'].isin(['Ganha', 'Perdida'])]['OPPORTUNITY_ID'].nunique()
        
        kpis['taxa_conversao'] = (oportunidades_ganhas / kpis['total_oportunidades'] * 100) if kpis['total_oportunidades'] > 0 else 0
        kpis['taxa_sucesso_fechadas'] = (oportunidades_ganhas / oportunidades_fechadas * 100) if oportunidades_fechadas > 0 else 0
        
        # Tempo médio de fechamento
        oportunidades_fechadas_df = df[df['Estado'].isin(['Ganha', 'Perdida'])]
        if not oportunidades_fechadas_df.empty:
            tempo_medio = (oportunidades_fechadas_df['Data fechamento'] - oportunidades_fechadas_df['Data de abertura']).dt.days.mean()
            kpis['tempo_medio_fechamento'] = tempo_medio
        else:
            kpis['tempo_medio_fechamento'] = 0
        
        # Valor médio por oportunidade
        kpis['valor_medio_ganho'] = kpis['valor_total_ganho'] / oportunidades_ganhas if oportunidades_ganhas > 0 else 0
        kpis['valor_medio_aberto'] = kpis['valor_total_aberto'] / kpis['total_oportunidades'] if kpis['total_oportunidades'] > 0 else 0
        
        # Distribuição por estágio
        kpis['dist_estagio'] = df['ESTAGIO_GRUPO'].value_counts().to_dict()
        
        # Eficiência por responsável
        if 'Responsável' in df.columns:
            resp_stats = df.groupby('Responsável').agg({
                'OPPORTUNITY_ID': 'nunique',
                'Valor': 'sum',
                'Estado': lambda x: (x == 'Ganha').sum()
            }).round(2)
            kpis['top_responsavel'] = resp_stats.nlargest(1, 'OPPORTUNITY_ID').iloc[0] if not resp_stats.empty else None
        
        # Pipeline por estágio
        pipeline_estagio = df.groupby('ESTAGIO_GRUPO').agg({
            'OPPORTUNITY_ID': 'nunique',
            'Valor': 'sum'
        }).round(2)
        kpis['pipeline_estagio'] = pipeline_estagio
        
        # Tendência mensal
        tendencia_mensal = df.groupby(df['Data de abertura'].dt.to_period('M')).agg({
            'OPPORTUNITY_ID': 'nunique',
            'Valor': 'sum'
        }).tail(6)  # Últimos 6 meses
        kpis['tendencia_mensal'] = tendencia_mensal
        
    except Exception as e:
        st.error(f"❌ Erro no cálculo de KPIs: {str(e)}")
    
    return kpis

# --- COMPONENTES VISUAIS ---
def create_metric_card(title, value, change=None, format_func=None, subtitle=""):
    if format_func:
        value_str = format_func(value)
    else:
        value_str = str(value)
    
    change_html = ""
    if change is not None:
        change_class = "positive-trend" if change >= 0 else "negative-trend"
        change_symbol = "↗" if change >= 0 else "↘"
        change_html = f'<div class="{change_class}">{change_symbol} {abs(change):.1f}%</div>'
    
    subtitle_html = f'<div style="font-size: 0.7rem; opacity: 0.8; margin-top: 0.2rem;">{subtitle}</div>' if subtitle else ""
    
    return f"""
    <div class="metric-card">
        <div class="metric-label">{title}</div>
        <div class="metric-value">{value_str}</div>
        {change_html}
        {subtitle_html}
    </div>
    """

def format_currency(value):
    if value >= 1_000_000:
        return f"R$ {value/1_000_000:.1f}M"
    elif value >= 1_000:
        return f"R$ {value/1_000:.1f}K"
    else:
        return f"R$ {value:,.0f}".replace(",", ".")

def format_percentage(value):
    return f"{value:.1f}%"

def format_number(value):
    return f"{value:,.0f}".replace(",", ".")

# --- PÁGINA DE LOGIN ---
def login_page():
    col1, col2, col3 = st.columns([1, 2, 1])
    with col2:
        st.markdown('<div class="main-header">🔐 PAINEL EXECUTIVO</div>', unsafe_allow_html=True)
        
        with st.container():
            st.markdown("### Acesso Restrito")
            st.markdown("Entre com suas credenciais para acessar o painel de BI")
            
            with st.form("login_form"):
                username = st.text_input("👤 Usuário", placeholder="Digite seu usuário")
                password = st.text_input("🔒 Senha", type="password", placeholder="Digite sua senha")
                
                if st.form_submit_button("🚀 ACESSAR PAINEL", use_container_width=True):
                    valid_user = st.secrets.get("login", {}).get("username", "admin")
                    valid_pass = st.secrets.get("login", {}).get("password", "admin123")
                    
                    if username == valid_user and password == valid_pass:
                        st.session_state.authenticated = True
                        st.session_state.data_loaded = False
                        st.success("✅ Login realizado com sucesso!")
                        time.sleep(1)
                        st.rerun()
                    else:
                        st.error("❌ Credenciais inválidas. Tente novamente.")

# --- PAINEL PRINCIPAL ---
def main_dashboard():
    # Header
    col1, col2, col3 = st.columns([3, 1, 1])
    with col1:
        st.markdown('<div class="main-header">📊 PAINEL EXECUTIVO - BI OPERACIONAL</div>', unsafe_allow_html=True)
    with col3:
        if st.button("🔄 ATUALIZAR DADOS", use_container_width=True):
            st.cache_data.clear()
            st.session_state.data_loaded = False
            st.session_state.last_refresh = datetime.now()
            st.rerun()
    
    # Status de atualização
    if st.session_state.last_refresh:
        st.caption(f"📅 Última atualização: {st.session_state.last_refresh.strftime('%d/%m/%Y %H:%M:%S')}")
    
    # Carregar dados se necessário
    if not st.session_state.data_loaded:
        with st.spinner("📥 Carregando dados do Google Sheets..."):
            gc = get_gspread_client()
            if gc:
                df, df_timeline = load_and_process_data(gc)
                st.session_state.df = df
                st.session_state.df_timeline = df_timeline
                st.session_state.data_loaded = True
                st.session_state.last_refresh = datetime.now()
                st.rerun()
            else:
                st.error("❌ Não foi possível conectar ao Google Sheets")
                return
    
    if st.session_state.df.empty:
        st.warning("⚠️ Nenhum dado disponível para análise. Verifique a conexão com a planilha.")
        return
    
    # KPIs PRINCIPAIS
    kpis = calculate_kpis(st.session_state.df)
    
    st.markdown('<div class="section-header">🎯 MÉTRICAS EXECUTIVAS PRINCIPAIS</div>', unsafe_allow_html=True)
    
    # Linha 1 de KPIs
    col1, col2, col3, col4 = st.columns(4)
    
    with col1:
        st.markdown(create_metric_card(
            "TOTAL OPORTUNIDADES", 
            kpis.get('total_oportunidades', 0),
            format_func=format_number,
            subtitle="Oportunidades únicas no sistema"
        ), unsafe_allow_html=True)
    
    with col2:
        st.markdown(create_metric_card(
            "VALOR EM PIPELINE",
            kpis.get('valor_total_pipeline', 0),
            format_func=format_currency,
            subtitle="Valor total em oportunidades abertas"
        ), unsafe_allow_html=True)
    
    with col3:
        st.markdown(create_metric_card(
            "VALOR GANHO",
            kpis.get('valor_total_ganho', 0),
            format_func=format_currency,
            subtitle="Valor total em oportunidades ganhas"
        ), unsafe_allow_html=True)
    
    with col4:
        st.markdown(create_metric_card(
            "TAXA DE CONVERSÃO",
            kpis.get('taxa_conversao', 0),
            format_func=format_percentage,
            subtitle="Eficiência no fechamento"
        ), unsafe_allow_html=True)
    
    # Linha 2 de KPIs
    col5, col6, col7, col8 = st.columns(4)
    
    with col5:
        st.markdown(create_metric_card(
            "TEMPO MÉDIO",
            kpis.get('tempo_medio_fechamento', 0),
            format_func=lambda x: f"{x:.0f} dias",
            subtitle="Dias para fechamento"
        ), unsafe_allow_html=True)
    
    with col6:
        st.markdown(create_metric_card(
            "VALOR MÉDIO GANHO",
            kpis.get('valor_medio_ganho', 0),
            format_func=format_currency,
            subtitle="Por oportunidade ganha"
        ), unsafe_allow_html=True)
    
    with col7:
        st.markdown(create_metric_card(
            "TAXA DE SUCESSO",
            kpis.get('taxa_sucesso_fechadas', 0),
            format_func=format_percentage,
            subtitle="Em oportunidades fechadas"
        ), unsafe_allow_html=True)
    
    with col8:
        oportunidades_ganhas = st.session_state.df[st.session_state.df['Estado'] == 'Ganha']['OPPORTUNITY_ID'].nunique()
        st.markdown(create_metric_card(
            "OPORTUNIDADES GANHAS",
            oportunidades_ganhas,
            format_func=format_number,
            subtitle="Total convertido"
        ), unsafe_allow_html=True)
    
    # VISUALIZAÇÕES PRINCIPAIS
    st.markdown('<div class="section-header">📈 ANÁLISE ESTRATÉGICA DO PIPELINE</div>', unsafe_allow_html=True)
    
    col1, col2 = st.columns(2)
    
    with col1:
        # Funil de vendas
        st.subheader("🎯 FUNIL DE VENDAS - VALOR POR ESTÁGIO")
        
        if not kpis.get('pipeline_estagio', pd.DataFrame()).empty:
            pipeline_data = kpis['pipeline_estagio'].reset_index()
            pipeline_data = pipeline_data.sort_values('Valor', ascending=False)
            
            fig = px.funnel(
                pipeline_data, 
                x='Valor', 
                y='ESTAGIO_GRUPO',
                title="",
                color='ESTAGIO_GRUPO',
                height=400
            )
            fig.update_layout(
                showlegend=True,
                plot_bgcolor='rgba(0,0,0,0)',
                paper_bgcolor='rgba(0,0,0,0)',
            )
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("📊 Aguardando dados do pipeline...")
    
    with col2:
        # Evolução mensal
        st.subheader("📅 EVOLUÇÃO MENSAL - OPORTUNIDADES E VALOR")
        
        evolucao_mensal = st.session_state.df.groupby(
            st.session_state.df['Data de abertura'].dt.to_period('M')
        ).agg({
            'OPPORTUNITY_ID': 'nunique',
            'Valor': 'sum'
        }).reset_index()
        
        if not evolucao_mensal.empty:
            evolucao_mensal['Data de abertura'] = evolucao_mensal['Data de abertura'].astype(str)
            
            fig = make_subplots(specs=[[{"secondary_y": True}]])
            
            fig.add_trace(
                go.Scatter(
                    x=evolucao_mensal['Data de abertura'],
                    y=evolucao_mensal['OPPORTUNITY_ID'],
                    name='Oportunidades',
                    line=dict(color='#00CCFF', width=4),
                    marker=dict(size=8)
                ),
                secondary_y=False,
            )
            
            fig.add_trace(
                go.Bar(
                    x=evolucao_mensal['Data de abertura'],
                    y=evolucao_mensal['Valor'],
                    name='Valor (R$)',
                    opacity=0.6,
                    marker_color='#FF6B6B'
                ),
                secondary_y=True,
            )
            
            fig.update_layout(
                xaxis_title="Mês",
                yaxis_title="Quantidade de Oportunidades",
                yaxis2_title="Valor (R$)",
                height=400,
                showlegend=True,
                plot_bgcolor='rgba(0,0,0,0)',
            )
            
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("📈 Aguardando dados de evolução...")
    
    # ANÁLISE DE PERFORMANCE
    st.markdown('<div class="section-header">🏆 ANÁLISE DE PERFORMANCE E EFICIÊNCIA</div>', unsafe_allow_html=True)
    
    col1, col2 = st.columns(2)
    
    with col1:
        # Distribuição por estágio
        st.subheader("📊 DISTRIBUIÇÃO POR ESTÁGIO ATUAL")
        
        dist_estagio = st.session_state.df['ESTAGIO_GRUPO'].value_counts().reset_index()
        dist_estagio.columns = ['Estágio', 'Quantidade']
        
        fig = px.pie(
            dist_estagio, 
            values='Quantidade', 
            names='Estágio',
            hole=0.5,
            color_discrete_sequence=px.colors.sequential.Blues_r
        )
        fig.update_traces(
            textposition='inside', 
            textinfo='percent+label',
            pull=[0.1 if i == 0 else 0 for i in range(len(dist_estagio))]
        )
        fig.update_layout(height=400)
        st.plotly_chart(fig, use_container_width=True)
    
    with col2:
        # Tempo médio por estágio
        st.subheader("⏰ TEMPO MÉDIO POR ESTÁGIO (DIAS)")
        
        if not st.session_state.df_timeline.empty:
            tempo_estagio = st.session_state.df_timeline.groupby('ESTAGIO_GRUPO')['TEMPO_ESTAGIO_DIAS'].mean().sort_values(ascending=True)
            
            fig = px.bar(
                tempo_estagio.reset_index(),
                x='TEMPO_ESTAGIO_DIAS',
                y='ESTAGIO_GRUPO',
                orientation='h',
                title="",
                color='TEMPO_ESTAGIO_DIAS',
                color_continuous_scale='Reds'
            )
            fig.update_layout(
                height=400,
                xaxis_title="Tempo Médio (Dias)",
                yaxis_title="",
                showlegend=False
            )
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("⏱️ Aguardando dados de timeline...")
    
    # TOP PERFORMERS E ANÁLISE DETALHADA
    st.markdown('<div class="section-header">👥 DESEMPENHO POR RESPONSÁVEL</div>', unsafe_allow_html=True)
    
    if 'Responsável' in st.session_state.df.columns:
        # Top 10 responsáveis
        top_responsaveis = st.session_state.df.groupby('Responsável').agg({
            'OPPORTUNITY_ID': 'nunique',
            'Valor': 'sum',
            'Estado': lambda x: (x == 'Ganha').sum()
        }).round(2).nlargest(10, 'OPPORTUNITY_ID')
        
        col1, col2 = st.columns(2)
        
        with col1:
            st.subheader("🏅 TOP 10 - VOLUME DE OPORTUNIDADES")
            fig = px.bar(
                top_responsaveis.reset_index(),
                x='OPPORTUNITY_ID',
                y='Responsável',
                orientation='h',
                title="",
                color='OPPORTUNITY_ID',
                color_continuous_scale='Viridis'
            )
            fig.update_layout(height=400, showlegend=False)
            st.plotly_chart(fig, use_container_width=True)
        
        with col2:
            st.subheader("💰 TOP 10 - VALOR EM PIPELINE")
            top_valor = st.session_state.df.groupby('Responsável')['Valor'].sum().nlargest(10)
            fig = px.bar(
                top_valor.reset_index(),
                x='Valor',
                y='Responsável',
                orientation='h',
                title="",
                color='Valor',
                color_continuous_scale='Plasma'
            )
            fig.update_layout(height=400, showlegend=False)
            st.plotly_chart(fig, use_container_width=True)
    else:
        st.info("👥 Coluna 'Responsável' não encontrada nos dados")

    # ANÁLISE TEMPORAL DETALHADA
    st.markdown('<div class="section-header">📅 ANÁLISE TEMPORAL DETALHADA</div>', unsafe_allow_html=True)
    
    col1, col2 = st.columns(2)
    
    with col1:
        # Heatmap de atividades
        st.subheader("🏢 ATIVIDADE POR HORA E DIA DA SEMANA")
        
        if not st.session_state.df.empty and 'HORA_ABERTURA' in st.session_state.df.columns:
            heatmap_data = st.session_state.df.pivot_table(
                index='DIA_SEMANA',
                columns='HORA_ABERTURA',
                values='OPPORTUNITY_ID',
                aggfunc='count',
                fill_value=0
            )
            
            # Ordenar dias da semana
            dias_ordenados = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']
            dias_portugues = ['Segunda', 'Terça', 'Quarta', 'Quinta', 'Sexta', 'Sábado', 'Domingo']
            heatmap_data = heatmap_data.reindex(dias_ordenados)
            heatmap_data.index = dias_portugues
            
            fig = px.imshow(
                heatmap_data,
                title="",
                color_continuous_scale='Blues',
                aspect="auto",
                labels=dict(x="Hora do Dia", y="Dia da Semana", color="Oportunidades")
            )
            fig.update_layout(height=400)
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("🏢 Aguardando dados para heatmap...")
    
    with col2:
        # Eficiência do pipeline
        st.subheader("📈 EFICIÊNCIA DO PIPELINE")
        
        if not st.session_state.df_timeline.empty:
            eficiencia = st.session_state.df_timeline.groupby('ESTAGIO_GRUPO').agg({
                'OPPORTUNITY_ID': 'nunique',
                'TEMPO_ESTAGIO_DIAS': 'mean',
                'Valor': 'sum'
            }).round(2)
            
            fig = make_subplots(specs=[[{"secondary_y": True}]])
            
            fig.add_trace(
                go.Bar(
                    name='Quantidade',
                    x=eficiencia.index,
                    y=eficiencia['OPPORTUNITY_ID'],
                    marker_color='#36A2EB'
                ),
                secondary_y=False,
            )
            
            fig.add_trace(
                go.Scatter(
                    name='Tempo Médio (Dias)',
                    x=eficiencia.index,
                    y=eficiencia['TEMPO_ESTAGIO_DIAS'],
                    line=dict(color='#FF6384', width=3),
                    marker=dict(size=8)
                ),
                secondary_y=True,
            )
            
            fig.update_layout(
                xaxis_title="Estágio",
                yaxis_title="Quantidade",
                yaxis2_title="Tempo Médio (Dias)",
                height=400,
                showlegend=True
            )
            
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("📈 Aguardando dados de eficiência...")

# --- SIDEBAR ---
def render_sidebar():
    with st.sidebar:
        st.markdown("""
            <div style="text-align: center; padding: 1rem;">
                <h2>🎯 PAINEL EXECUTIVO</h2>
                <p style="font-size: 0.9rem; opacity: 0.8;">BI Operacional</p>
            </div>
        """, unsafe_allow_html=True)
        
        st.markdown("---")
        
        if st.button("🚪 SAIR", use_container_width=True):
            st.session_state.authenticated = False
            st.session_state.data_loaded = False
            st.rerun()
        
        st.markdown("---")
        
        if st.session_state.data_loaded and not st.session_state.df.empty:
            st.markdown("### 🔍 FILTROS")
            
            # Filtro por período
            min_date = st.session_state.df['Data de abertura'].min().date()
            max_date = st.session_state.df['Data de abertura'].max().date()
            
            st.date_input(
                "📅 Período de Análise",
                value=(min_date, max_date),
                min_value=min_date,
                max_value=max_date,
                key="date_filter"
            )
            
            # Filtro por estágio
            estagios = st.session_state.df['ESTAGIO_GRUPO'].unique()
            st.multiselect(
                "📊 Estágios",
                options=estagios,
                default=estagios,
                key="stage_filter"
            )
            
            # Filtro por responsável
            if 'Responsável' in st.session_state.df.columns:
                responsaveis = st.session_state.df['Responsável'].unique()
                st.multiselect(
                    "👥 Responsáveis",
                    options=responsaveis,
                    default=responsaveis,
                    key="responsible_filter"
                )

# --- APLICAÇÃO PRINCIPAL ---
def main():
    if not st.session_state.authenticated:
        login_page()
    else:
        render_sidebar()
        main_dashboard()

if __name__ == "__main__":
    main()
