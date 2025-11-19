from __future__ import annotations

from contextlib import contextmanager
from typing import Optional

import streamlit as st


def inject_global_styles() -> None:
    st.markdown(
        """
        <style>
            @import url('https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@400;500;600;700&display=swap');

            :root {
                --bg-primary: #030712;
                --bg-card: rgba(7, 11, 24, 0.8);
                --border-color: rgba(148, 163, 184, 0.2);
                --text-primary: #e2e8f0;
                --text-muted: #94a3b8;
                --accent: #38bdf8;
                --accent-strong: #6366f1;
            }

            html, body, [data-testid="block-container"] {
                background: radial-gradient(circle at top left, rgba(56,189,248,0.12), transparent 35%),
                            radial-gradient(circle at 20% 20%, rgba(239,68,68,0.08), transparent 45%),
                            var(--bg-primary);
                color: var(--text-primary);
                font-family: 'Space Grotesk', sans-serif;
            }

            [data-testid="block-container"] {
                padding-top: 1.2rem;
                padding-left: 2.2rem;
                padding-right: 2.2rem;
            }

            [data-testid="stSidebar"] {
                background: linear-gradient(180deg, #050b1b 0%, #0f172a 100%);
                color: var(--text-primary);
            }

            [data-testid="stSidebar"] * {
                color: var(--text-primary) !important;
            }

            .hero {
                background: linear-gradient(125deg, rgba(56,189,248,0.35), rgba(99,102,241,0.4));
                border: 1px solid rgba(148,163,184,0.25);
                border-radius: 28px;
                padding: 28px 36px;
                display: flex;
                gap: 2rem;
                align-items: center;
                box-shadow: 0 30px 80px rgba(2,6,23,0.55);
                margin-bottom: 2rem;
            }

            .hero h1 {
                margin: 0;
                font-size: 2.4rem;
                color: #f8fafc;
            }

            .hero p {
                margin-top: 0.4rem;
                color: rgba(248,250,252,0.85);
            }

            .hero .eyebrow {
                letter-spacing: 0.3em;
                font-size: 0.75rem;
                text-transform: uppercase;
                color: rgba(248,250,252,0.65);
            }

            .hero-stats {
                display: flex;
                gap: 1.5rem;
                flex-wrap: wrap;
            }

            .hero-stats div {
                background: rgba(15,23,42,0.35);
                padding: 16px 20px;
                border-radius: 18px;
                border: 1px solid rgba(248,250,252,0.12);
                min-width: 170px;
            }

            .hero-stats strong {
                display: block;
                font-size: 1.4rem;
                color: #f8fafc;
            }

            .hero-stats small, .hero-stats span {
                font-size: 0.75rem;
                color: rgba(248,250,252,0.65);
                letter-spacing: 0.08em;
            }

            .stButton button {
                background: linear-gradient(135deg, #38bdf8, #6366f1);
                color: #f8fafc;
                border: 0;
                border-radius: 999px;
                font-weight: 600;
            }

            .stButton button:hover {
                filter: brightness(1.1);
            }

            .metric-card {
                background: linear-gradient(135deg, rgba(56,189,248,0.12), rgba(99,102,241,0.15));
                color: #f8fafc;
                padding: 18px;
                border-radius: 18px;
                border: 1px solid var(--border-color);
                text-align: left;
                backdrop-filter: blur(12px);
                box-shadow: 0 18px 40px rgba(2,6,23,0.45);
            }

            .metric-card h3 {
                margin-bottom: 4px;
                font-size: 0.85rem;
                font-weight: 500;
                color: var(--text-muted);
                letter-spacing: 0.08em;
            }

            .metric-card p {
                font-size: 1.6rem;
                margin: 0;
                font-weight: 600;
            }

            .chart-card {
                background: var(--bg-card);
                padding: 1.4rem 1.6rem 1.6rem;
                border-radius: 24px;
                border: 1px solid var(--border-color);
                box-shadow: inset 0 1px 0 rgba(255,255,255,0.05), 0 25px 40px rgba(2,6,23,0.55);
                margin-bottom: 1.5rem;
                backdrop-filter: blur(16px);
            }

            .section-title {
                margin-top: 0;
                color: #f1f5f9;
                letter-spacing: 0.05em;
            }
        </style>
        """,
        unsafe_allow_html=True,
    )


@contextmanager
def chart_card(title: Optional[str] = None, subtitle: Optional[str] = None):
    st.markdown("<div class='chart-card'>", unsafe_allow_html=True)
    if title:
        st.markdown(f"<h4 class='section-title'>{title}</h4>", unsafe_allow_html=True)
    if subtitle:
        st.markdown(
            f"<p style='color:#94a3b8;margin-top:-0.35rem;'>{subtitle}</p>",
            unsafe_allow_html=True,
        )
    yield
    st.markdown("</div>", unsafe_allow_html=True)


def style_fig(fig, height: Optional[int] = None):
    fig.update_layout(
        template="plotly_dark",
        plot_bgcolor="rgba(5,10,25,0.6)",
        paper_bgcolor="rgba(5,10,25,0.6)",
        font=dict(family="Space Grotesk", color="#f8fafc"),
        margin=dict(t=50, b=40, l=40, r=24),
    )
    fig.update_xaxes(gridcolor="rgba(148,163,184,0.3)")
    fig.update_yaxes(gridcolor="rgba(148,163,184,0.2)")
    if height:
        fig.update_layout(height=height)
    return fig


def style_heatmap(fig, height: Optional[int] = None):
    fig.update_layout(
        template="plotly_dark",
        plot_bgcolor="rgba(5,10,25,0.35)",
        paper_bgcolor="rgba(5,10,25,0.35)",
        font=dict(family="Space Grotesk", color="#f8fafc"),
        margin=dict(t=60, b=50, l=80, r=60),
    )
    fig.update_xaxes(
        gridcolor="rgba(148,163,184,0.25)",
        zerolinecolor="rgba(148,163,184,0.25)",
        title_font=dict(color="#f8fafc"),
        tickfont=dict(color="#cbd5f5"),
    )
    fig.update_yaxes(
        gridcolor="rgba(148,163,184,0.1)",
        zerolinecolor="rgba(148,163,184,0.1)",
        title_font=dict(color="#f8fafc"),
        tickfont=dict(color="#cbd5f5"),
    )
    if height:
        fig.update_layout(height=height)
    return fig

