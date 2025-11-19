from __future__ import annotations

import plotly.express as px
import streamlit as st

from core.auth import authenticate, init_auth_state
from core.data_service import get_placeholder_interactions, load_datasets
from core.formatters import format_currency, safe_percentage
from core.ui import chart_card, inject_global_styles, style_fig
from services.logging_service import get_logger

st.set_page_config(page_title="Painel de BI Operacional", layout="wide")


def ensure_datasets():
    if "datasets" not in st.session_state:
        st.session_state["datasets"] = load_datasets()
    return st.session_state["datasets"]


def render_sidebar():
    st.sidebar.title("Status de Acesso")
    if st.session_state.get("authenticated"):
        st.sidebar.success("Usuário autenticado")
        if st.sidebar.button("Sair"):
            st.session_state.clear()
            st.rerun()
    else:
        st.sidebar.info("Realize o login na tela principal.")


def render_login(logger):
    st.title("Central Operacional B2")
    st.markdown(
        "Faça login para liberar os demais módulos do painel (Painel Geral e Relatório de Oportunidade)."
    )

    with st.form("login_form"):
        username = st.text_input("Usuário")
        password = st.text_input("Senha", type="password")
        submit = st.form_submit_button("Entrar")

        if submit:
            if authenticate(username, password):
                st.session_state["authenticated"] = True
                ensure_datasets()
                logger.info("Login bem-sucedido para %s", username)
                st.success("Login realizado! Utilize o menu lateral para navegar.")
                st.rerun()
            else:
                logger.warning("Tentativa de login falhou para %s", username)
                st.error("Credenciais inválidas.")


def render_home():
    df, _ = st.session_state.get("datasets", (None, None))
    placeholder_interactions = get_placeholder_interactions()

    st.markdown(
        """
        <div class="hero">
            <div class="hero-text">
                <p class="eyebrow">BI Operacional</p>
                <h1>Radar Estratégico B2</h1>
                <p>Use as páginas ao lado para navegar entre visão consolidada e análise detalhada.</p>
            </div>
            <div class="hero-stats">
                <div>
                    <span>Versão</span>
                    <strong>2.0</strong>
                    <small>Arquitetura modular</small>
                </div>
                <div>
                    <span>Telas</span>
                    <strong>2 principais</strong>
                    <small>Painel Geral & Relatório</small>
                </div>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    st.subheader("Como navegar?")
    st.markdown(
        """
        1. **Painel Geral**: KPIs consolidados, filtros avançados e Modo Apresentação.
        2. **Relatório de Oportunidade**: consulta individual com IA opcional para insights.
        """
    )

    with chart_card("Interações de Exemplo por Usuário"):
        fig = px.bar(
            placeholder_interactions,
            x="Usuário",
            y="Interações",
            color="Usuário",
            color_discrete_sequence=px.colors.qualitative.Plotly,
        )
        fig.update_layout(xaxis_title="Usuário", yaxis_title="Total de Interações")
        style_fig(fig)
        st.plotly_chart(fig, use_container_width=True, config={"displaylogo": False})

    if df is not None and not df.empty:
        total_ops = df['OC_Identifier'].nunique()
        total_valor = format_currency(df['Valor'].sum(min_count=1))
        win_rate = safe_percentage(
            (df[df['Estado'] == 'Ganha']['OC_Identifier'].nunique() / total_ops * 100)
            if total_ops
            else 0
        )

        st.markdown("### Painel em números (última carga)")
        col1, col2, col3 = st.columns(3)
        for col, label, value in [
            (col1, "Oportunidades Únicas", f"{int(total_ops)}"),
            (col2, "Valor Total", total_valor),
            (col3, "Taxa de Sucesso", win_rate),
        ]:
            with col:
                st.markdown(
                    f"<div class='metric-card'><h3>{label}</h3><p>{value}</p></div>",
                    unsafe_allow_html=True,
                )
    else:
        st.info("Os dados serão carregados automaticamente após o primeiro login.")


def main():
    logger = get_logger()
    inject_global_styles()
    init_auth_state()
    render_sidebar()

    if st.session_state.get("authenticated"):
        ensure_datasets()
        render_home()
    else:
        render_login(logger)


if __name__ == "__main__":
    main()
