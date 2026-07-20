"""Password gate so the dashboard isn't open to anyone with the URL.

One shared password, configured via APP_PASSWORD (Streamlit Cloud secrets or
local .env) — not a per-user login system. Persists per browser session.
"""
from __future__ import annotations

import base64
import hmac
from pathlib import Path

import streamlit as st

from lib import config, theme

LOGO_PATH = Path(__file__).parent.parent / "assets" / "logo.png"

_ACCENT = theme.CATEGORICAL[0]  # brand blue — every decorative visual uses this one hue

_STYLE = f"""
<style>
@keyframes denriDrift1 {{ 0%, 100% {{ transform: translate(0, 0) scale(1); }} 50% {{ transform: translate(6%, 8%) scale(1.12); }} }}
@keyframes denriDrift2 {{ 0%, 100% {{ transform: translate(0, 0) scale(1); }} 50% {{ transform: translate(-6%, -8%) scale(1.08); }} }}
@keyframes denriFadeUp {{ from {{ opacity: 0; transform: translateY(18px); }} to {{ opacity: 1; transform: translateY(0); }} }}
@keyframes denriPopIn {{ from {{ opacity: 0; transform: scale(0.85); }} to {{ opacity: 1; transform: scale(1); }} }}
@keyframes denriGrowBar {{ from {{ height: 0%; }} to {{ height: var(--bar-h); }} }}
@keyframes denriGlow {{ 0%, 100% {{ filter: drop-shadow(0 0 2px {_ACCENT}40); }} 50% {{ filter: drop-shadow(0 0 6px {_ACCENT}90); }} }}
@keyframes denriDraw {{ to {{ stroke-dashoffset: 0; }} }}
@keyframes denriFillRing {{ from {{ stroke-dashoffset: 100; }} to {{ stroke-dashoffset: 22; }} }}
@keyframes denriDot {{ 0%, 100% {{ r: 2.2; opacity: 1; }} 50% {{ r: 3.4; opacity: 0.6; }} }}

.denri-blob {{ position: fixed; border-radius: 50%; filter: blur(64px); pointer-events: none; z-index: 0; }}
.denri-blob-1 {{ top: -14%; left: -8%; width: 460px; height: 460px;
  background: radial-gradient(circle at 30% 30%, {_ACCENT}52, transparent 70%);
  animation: denriDrift1 20s ease-in-out infinite; }}
.denri-blob-2 {{ bottom: -16%; right: -8%; width: 500px; height: 500px;
  background: radial-gradient(circle at 60% 60%, #9085e948, transparent 70%);
  animation: denriDrift2 24s ease-in-out infinite; }}

.denri-chart-row {{ position: relative; z-index: 1; display: flex; gap: 12px; justify-content: center;
  max-width: 420px; margin: 0 auto 24px auto; animation: denriFadeUp 0.7s ease both; }}
.denri-chart-card {{ flex: 1; background: rgba(255,255,255,0.045); border: 1px solid rgba(255,255,255,0.09);
  border-radius: 14px; padding: 12px 10px 9px 10px; backdrop-filter: blur(8px); }}
.denri-chart-label {{ font-size: 0.62rem; color: {theme.TEXT_MUTED}; text-align: center; margin-top: 7px;
  letter-spacing: 0.04em; text-transform: uppercase; font-family: {theme.FONT_FAMILY}; }}

.denri-bars {{ display: flex; align-items: flex-end; gap: 3px; height: 38px; }}
.denri-bars span {{ flex: 1; border-radius: 3px 3px 1px 1px; background: {_ACCENT};
  animation: denriGrowBar 0.9s cubic-bezier(.2,.9,.3,1) both, denriGlow 3.2s ease-in-out infinite;
  transform-origin: bottom; }}

.denri-sparkline {{ width: 100%; height: 38px; overflow: visible; }}
.denri-sparkline polyline {{ fill: none; stroke: {_ACCENT}; stroke-width: 2.4; stroke-linecap: round; stroke-linejoin: round;
  stroke-dasharray: 105; stroke-dashoffset: 105;
  animation: denriDraw 1.1s ease-out both, denriGlow 3.2s ease-in-out infinite; }}
.denri-sparkline circle {{ fill: {_ACCENT}; animation: denriDot 1.8s ease-in-out infinite; }}

.denri-ring {{ width: 56px; height: 56px; display: block; margin: 0 auto; transform: rotate(-90deg); }}
.denri-ring-track {{ fill: none; stroke: rgba(255,255,255,0.1); stroke-width: 3; }}
.denri-ring-fill {{ fill: none; stroke: {_ACCENT}; stroke-width: 3; stroke-linecap: round; stroke-dasharray: 100;
  animation: denriFillRing 1.2s 0.2s ease-out both, denriGlow 3.2s ease-in-out infinite; }}

.denri-logo-card {{ position: relative; z-index: 1; background: #ffffff; border-radius: 24px; padding: 22px;
  width: 150px; margin: 6vh auto 28px auto; box-shadow: 0 12px 32px rgba(0,0,0,0.4);
  animation: denriPopIn 0.6s 0.1s cubic-bezier(.2,.9,.3,1) both; }}
.denri-logo-card img {{ width: 100%; display: block; }}
.denri-title {{ position: relative; z-index: 1; text-align: center; font-family: {theme.FONT_FAMILY};
  font-size: 1.75rem; font-weight: 700; color: {theme.TEXT_PRIMARY}; margin-bottom: 0.3rem;
  letter-spacing: 0.01em; animation: denriFadeUp 0.6s 0.25s ease both; }}
.denri-subtitle {{ position: relative; z-index: 1; text-align: center; font-family: {theme.FONT_FAMILY};
  color: {theme.TEXT_MUTED}; font-size: 0.95rem; margin-bottom: 1.6rem;
  animation: denriFadeUp 0.6s 0.35s ease both; }}
.denri-footnote {{ text-align: center; font-family: {theme.FONT_FAMILY}; color: {theme.TEXT_MUTED};
  font-size: 0.8rem; margin-top: 1rem; }}
</style>

<div class="denri-blob denri-blob-1"></div>
<div class="denri-blob denri-blob-2"></div>
"""

_CHART_ROW = """
<div class="denri-chart-row">
  <div class="denri-chart-card">
    <div class="denri-bars">
      <span style="--bar-h:38%; animation-delay:.05s;"></span>
      <span style="--bar-h:58%; animation-delay:.12s;"></span>
      <span style="--bar-h:46%; animation-delay:.19s;"></span>
      <span style="--bar-h:72%; animation-delay:.26s;"></span>
      <span style="--bar-h:62%; animation-delay:.33s;"></span>
      <span style="--bar-h:92%; animation-delay:.40s;"></span>
    </div>
    <div class="denri-chart-label">Sales</div>
  </div>
  <div class="denri-chart-card">
    <svg class="denri-sparkline" viewBox="0 0 90 40">
      <polyline points="0,32 18,24 36,28 54,14 72,18 90,4"></polyline>
      <circle cx="90" cy="4" r="2.6"></circle>
    </svg>
    <div class="denri-chart-label">Trend</div>
  </div>
  <div class="denri-chart-card">
    <svg class="denri-ring" viewBox="0 0 36 36">
      <circle class="denri-ring-track" cx="18" cy="18" r="15.9155"></circle>
      <circle class="denri-ring-fill" cx="18" cy="18" r="15.9155"></circle>
    </svg>
    <div class="denri-chart-label">Growth</div>
  </div>
</div>
"""


def _logo_data_uri() -> str | None:
    if not LOGO_PATH.exists():
        return None
    encoded = base64.b64encode(LOGO_PATH.read_bytes()).decode()
    return f"data:image/png;base64,{encoded}"


def require_login() -> None:
    """Block the rest of the page until the correct password is entered."""
    if st.session_state.get("authenticated"):
        return

    expected = config.get("APP_PASSWORD")
    if not expected:
        st.error(
            "APP_PASSWORD is not configured. Set it in .env (local) or in "
            "the Streamlit Cloud app's Settings -> Secrets (production)."
        )
        st.stop()

    st.markdown(_STYLE, unsafe_allow_html=True)

    _, col, _ = st.columns([1, 1.2, 1])
    with col:
        st.markdown(_CHART_ROW, unsafe_allow_html=True)

        logo_uri = _logo_data_uri()
        if logo_uri:
            st.markdown(f'<div class="denri-logo-card"><img src="{logo_uri}" alt="Denri logo"></div>', unsafe_allow_html=True)
        st.markdown('<div class="denri-title">Denri Executive Dashboard</div>', unsafe_allow_html=True)
        st.markdown(
            '<div class="denri-subtitle">Sign in to view live sales, production &amp; dispatch data</div>',
            unsafe_allow_html=True,
        )

        with st.container(border=True):
            password = st.text_input(
                "Password", type="password", key="login_password",
                label_visibility="collapsed", placeholder="Dashboard password",
            )
            if st.button("Log in", key="login_submit", type="primary", width="stretch"):
                if hmac.compare_digest(password, expected):
                    st.session_state.authenticated = True
                    st.rerun()
                else:
                    st.error("Incorrect password.", icon="🚫")

        st.markdown('<div class="denri-footnote">Authorized personnel only</div>', unsafe_allow_html=True)

    st.stop()
