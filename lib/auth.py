"""Password gate so the dashboard isn't open to anyone with the URL.

One shared password, configured via APP_PASSWORD (Streamlit Cloud secrets or
local .env) — not a per-user login system. Persists per browser session.
"""
from __future__ import annotations

import base64
import hmac
from pathlib import Path

import streamlit as st

from lib import config, style

LOGO_PATH = Path(__file__).parent.parent / "assets" / "logo.png"

# Login screen. Colours come from the CSS variables lib/style.py defines per
# theme, so the screen follows Light / Dark / System like the rest of the app.
_STYLE = """
<style>
@keyframes denriFadeUp { from { opacity: 0; transform: translateY(18px); } to { opacity: 1; transform: translateY(0); } }
@keyframes denriPopIn { from { opacity: 0; transform: scale(0.85) rotate(-4deg); } to { opacity: 1; transform: scale(1) rotate(0); } }
@keyframes denriFloat { 0%, 100% { transform: translateY(0); } 50% { transform: translateY(-8px); } }
@keyframes denriGrowBar { from { height: 0%; } to { height: var(--bar-h); } }
@keyframes denriDrift { 0%, 100% { transform: translate(0, 0) scale(1); } 50% { transform: translate(-6%, 5%) scale(1.1); } }
@keyframes denriShake { 10%, 90% { transform: translateX(-2px); } 20%, 80% { transform: translateX(4px); }
  30%, 50%, 70% { transform: translateX(-7px); } 40%, 60% { transform: translateX(7px); } }

[data-testid="stSidebar"], [data-testid="stSidebarCollapsedControl"], [data-testid="stExpandSidebarButton"] { display: none !important; }
[data-testid="stMainBlockContainer"] { padding-top: 5vh; }

.denri-orb { position: fixed; border-radius: 50%; filter: blur(70px); pointer-events: none; z-index: 0;
  width: 520px; height: 520px; }
.denri-orb-1 { top: -18%; left: -10%; background: var(--denri-glow-1); animation: denriFloat 14s ease-in-out infinite; }
.denri-orb-2 { bottom: -22%; right: -10%; background: var(--denri-glow-2); animation: denriFloat 17s ease-in-out infinite reverse; }
.denri-orb-3 { top: 38%; left: 58%; width: 380px; height: 380px; background: var(--denri-glow-3);
  animation: denriDrift 22s ease-in-out infinite; }

.denri-login-head { position: relative; z-index: 1; text-align: center; }
.denri-logo-card { background: #ffffff; border-radius: 26px; padding: 18px; width: 112px; margin: 0 auto 20px auto;
  box-shadow: 0 16px 36px rgba(20, 20, 40, 0.18); border: 1px solid rgba(23, 23, 28, 0.06);
  animation: denriPopIn 0.7s 0.05s cubic-bezier(.2, .9, .3, 1.2) both; }
.denri-logo-card:hover { animation: denriFloat 2.4s ease-in-out infinite; }
.denri-logo-card img { width: 100%; display: block; }
.denri-hello { display: inline-block; font-size: 0.72rem; font-weight: 700; letter-spacing: 0.12em; text-transform: uppercase;
  color: var(--denri-text-2); background: var(--denri-glass); border: 1px solid var(--denri-glass-edge);
  border-radius: 999px; padding: 6px 14px; margin-bottom: 14px; animation: denriFadeUp 0.6s 0.15s ease both; }
.denri-title { font-size: 2.15rem; font-weight: 800; letter-spacing: -0.03em; color: var(--denri-text);
  line-height: 1.12; margin-bottom: 0.45rem; animation: denriFadeUp 0.6s 0.22s ease both; }
.denri-subtitle { color: var(--denri-muted); font-size: 0.98rem; margin-bottom: 1.4rem;
  animation: denriFadeUp 0.6s 0.3s ease both; }

.denri-chart-row { position: relative; z-index: 1; display: flex; gap: 10px; justify-content: center;
  margin: 0 auto 6px auto; animation: denriFadeUp 0.7s 0.38s ease both; }
.denri-chart-card { flex: 1; border-radius: 18px; padding: 12px 10px 9px 10px; border: 1px solid var(--denri-glass-edge);
  box-shadow: var(--denri-shadow); transition: transform 220ms cubic-bezier(.2, .8, .2, 1), box-shadow 220ms ease; cursor: default; }
.denri-chart-card:hover { transform: translateY(-5px); box-shadow: var(--denri-shadow-hover); }
.denri-chart-card:nth-child(1) { background: var(--denri-tint-1); }
.denri-chart-card:nth-child(2) { background: var(--denri-tint-2); }
.denri-chart-card:nth-child(3) { background: var(--denri-tint-3); }
.denri-chart-label { font-size: 0.64rem; color: var(--denri-text-2); text-align: center; margin-top: 7px;
  letter-spacing: 0.06em; text-transform: uppercase; font-weight: 700; }
.denri-bars { display: flex; align-items: flex-end; gap: 3px; height: 38px; }
.denri-bars span { flex: 1; border-radius: 4px 4px 2px 2px; background: #7c68ee;
  animation: denriGrowBar 0.9s cubic-bezier(.2, .9, .3, 1) both; transition: filter 160ms ease; }
.denri-chart-card:hover .denri-bars span { filter: brightness(1.2); }
.denri-sparkline { width: 100%; height: 38px; display: block; }
.denri-ring { width: 46px; height: 46px; display: block; margin: -4px auto 0 auto; }

/* the sign-in card */
.st-key-denri_login {
  position: relative; z-index: 1; padding: 22px 22px 14px 22px;
  background: var(--denri-glass); border: 1px solid var(--denri-glass-edge); border-radius: 26px;
  box-shadow: var(--denri-shadow-hover); backdrop-filter: blur(18px) saturate(140%); -webkit-backdrop-filter: blur(18px) saturate(140%);
  animation: denriFadeUp 0.6s 0.45s ease both;
}
.st-key-denri_login.denri-wrong { animation: denriShake 0.45s ease both; }
.st-key-denri_login [data-testid="stForm"] { border: none; padding: 0; }
.st-key-denri_login [data-baseweb="input"] { height: 48px; border-radius: 14px; transition: box-shadow 160ms ease; }
.st-key-denri_login [data-baseweb="input"]:focus-within { box-shadow: 0 0 0 4px rgba(165, 148, 249, 0.30); }
.st-key-denri_login [data-testid="stFormSubmitButton"] button { height: 48px; font-size: 1rem; font-weight: 700; }
.st-key-denri_login [data-testid="stFormSubmitButton"] button:hover { transform: translateY(-2px); }
.denri-hint { text-align: center; color: var(--denri-muted); font-size: 0.78rem; }
.denri-hint kbd { font-family: inherit; font-size: 0.72rem; font-weight: 700; padding: 2px 7px; border-radius: 6px;
  border: 1px solid var(--denri-hair); background: var(--denri-field); color: var(--denri-text-2);
  box-shadow: 0 1px 0 var(--denri-hair); }
.denri-footnote { position: relative; z-index: 1; text-align: center; color: var(--denri-muted);
  font-size: 0.78rem; margin-top: 0.4rem; }
</style>

<div class="denri-orb denri-orb-1"></div>
<div class="denri-orb denri-orb-2"></div>
<div class="denri-orb denri-orb-3"></div>
"""

_CHART_ROW = """
<div class="denri-chart-row">
  <div class="denri-chart-card">
    <div class="denri-bars">
      <span style="--bar-h:38%; animation-delay:.45s;"></span>
      <span style="--bar-h:58%; animation-delay:.52s;"></span>
      <span style="--bar-h:46%; animation-delay:.59s;"></span>
      <span style="--bar-h:72%; animation-delay:.66s;"></span>
      <span style="--bar-h:62%; animation-delay:.73s;"></span>
      <span style="--bar-h:92%; animation-delay:.80s;"></span>
    </div>
    <div class="denri-chart-label">Sales</div>
  </div>
  <div class="denri-chart-card">
    <img class="denri-sparkline" alt="" src="__SPARK__">
    <div class="denri-chart-label">Trend</div>
  </div>
  <div class="denri-chart-card">
    <img class="denri-ring" alt="" src="__RING__">
    <div class="denri-chart-label">Growth</div>
  </div>
</div>
"""

# Streamlit strips inline <svg>, so the two animated charts travel as images;
# their animation lives inside the SVG itself.
_SPARK_SVG = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="-3 -3 96 46"><style>
polyline{fill:none;stroke:#d6517f;stroke-width:2.6;stroke-linecap:round;stroke-linejoin:round;
stroke-dasharray:105;stroke-dashoffset:105;animation:d 1.2s .5s ease-out forwards}
circle{fill:#d6517f;opacity:0;animation:o .3s 1.6s forwards}
@keyframes d{to{stroke-dashoffset:0}}@keyframes o{to{opacity:1}}</style>
<polyline points="0,32 18,24 36,28 54,14 72,18 90,4"/>
<circle cx="90" cy="4" r="2.8"/></svg>"""
_RING_SVG = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 36 36"><style>
circle{fill:none;stroke-width:3.2}
.f{stroke:#199e70;stroke-linecap:round;stroke-dasharray:100;stroke-dashoffset:100;animation:r 1.3s .5s ease-out forwards}
@keyframes r{to{stroke-dashoffset:26}}</style>
<g transform="rotate(-90 18 18)"><circle cx="18" cy="18" r="15.9155" stroke="rgba(128,128,140,0.25)"/>
<circle class="f" cx="18" cy="18" r="15.9155"/></g></svg>"""


def _svg_uri(svg: str) -> str:
    return "data:image/svg+xml;base64," + base64.b64encode(svg.encode()).decode()


_CHART_ROW = _CHART_ROW.replace("__SPARK__", _svg_uri(_SPARK_SVG)).replace("__RING__", _svg_uri(_RING_SVG))

# Shakes the card once after a wrong password.
_SHAKE = """
<script class="denri-boot">
(() => { const c = document.querySelector('.st-key-denri_login'); if (!c) return;
  c.classList.remove('denri-wrong'); void c.offsetWidth; c.classList.add('denri-wrong'); })();
</script>
"""


def _logo_data_uri() -> str | None:
    if not LOGO_PATH.exists():
        return None
    encoded = base64.b64encode(LOGO_PATH.read_bytes()).decode()
    return f"data:image/png;base64,{encoded}"


DEFAULT_APP_NAME = "Denri Executive Dashboard"


def open_access(app_name: str) -> None:
    """Let this session through require_login() without a password.

    Called by entrypoints that are meant to be open (sales_operations_app.py),
    so the shared pages/ files can keep calling require_login() unchanged.
    Session-scoped: the executive dashboard's own sessions still hit the gate.
    """
    st.session_state["login_disabled"] = True
    st.session_state["app_name"] = app_name


def page_title(section: str) -> str:
    """Browser-tab title for a page, named after whichever app is hosting it."""
    return f"{section} · {st.session_state.get('app_name', DEFAULT_APP_NAME)}"


def require_login() -> None:
    """Block the rest of the page until the correct password is entered.

    Every page calls this first, so it is also where the app-wide styling
    (lib/style.py) goes in.
    """
    style.inject()
    if st.session_state.get("authenticated") or st.session_state.get("login_disabled"):
        return

    expected = config.get("APP_PASSWORD")
    if not expected:
        st.error(
            "APP_PASSWORD is not configured. Set it in .env (local) or in "
            "the Streamlit Cloud app's Settings -> Secrets (production)."
        )
        st.stop()

    st.html(_STYLE)

    _, col, _ = st.columns([1, 1.15, 1])
    with col:
        logo_uri = _logo_data_uri()
        logo = (f'<div class="denri-logo-card"><img src="{logo_uri}" alt="Denri logo"></div>'
                if logo_uri else "")
        st.html(
            f'<div class="denri-login-head">{logo}'
            '<div class="denri-hello">Welcome back</div>'
            '<div class="denri-title">Denri Executive<br>Dashboard</div>'
            '<div class="denri-subtitle">Live sales, production &amp; dispatch, all in one place</div>'
            '</div>'
        )
        # st.markdown, not st.html: st.html strips the inline SVG charts.
        st.markdown(_CHART_ROW, unsafe_allow_html=True)

        with st.container(key="denri_login"):
            # A form, so pressing Enter in the password box signs in.
            with st.form("login_form", border=False, enter_to_submit=True):
                password = st.text_input(
                    "Password", type="password", key="login_password",
                    label_visibility="collapsed", placeholder="Enter dashboard password",
                    icon=":material/lock:",
                )
                submitted = st.form_submit_button(
                    "Sign in", type="primary", width="stretch",
                    icon=":material/arrow_forward:", icon_position="right",
                )
            if submitted:
                if password and hmac.compare_digest(password, expected):
                    st.session_state.authenticated = True
                    st.rerun()
                elif not password:
                    st.warning("Type the password first.", icon=":material/keyboard:")
                else:
                    st.error("That password didn't match. Try again.", icon=":material/lock:")
                    st.html(_SHAKE, unsafe_allow_javascript=True)
            st.html('<div class="denri-hint">Press <kbd>Enter ↵</kbd> to sign in</div>')

        st.html('<div class="denri-footnote">🔒 Authorized personnel only</div>')

    st.stop()
