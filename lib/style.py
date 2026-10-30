"""App-wide look: soft canvas, floating pill sidebar, glass cards, pill filters.

Streamlit's own Light / Dark / System themes (.streamlit/config.toml) set the
base colours; this layer adds the shapes, translucency and motion on top.
inject() runs from auth.require_login(), which every page calls first.

CSS can't ask Streamlit which theme is showing, so a small script stamps
<html data-denri-theme="light|dark"> from the app background's brightness and
keeps it current when the theme is switched. It also marks bordered
st.container()s with data-denri-card — their markup is otherwise identical to
a plain container — so only those become glass cards.
"""
from __future__ import annotations

import streamlit as st

_CSS = """
<style>
:root, html[data-denri-theme="light"] {
  --denri-ink-rgb: 23, 23, 28;
  --denri-text: #17171c;
  --denri-text-2: #4b4b57;
  --denri-muted: #7b7b88;
  --denri-glass: rgba(255, 255, 255, 0.72);
  --denri-glass-hover: rgba(255, 255, 255, 0.86);
  --denri-glass-edge: rgba(255, 255, 255, 0.95);
  --denri-hair: rgba(23, 23, 28, 0.07);
  --denri-shadow: 0 1px 2px rgba(20, 20, 40, 0.04), 0 10px 28px rgba(20, 20, 40, 0.06);
  --denri-shadow-hover: 0 2px 4px rgba(20, 20, 40, 0.05), 0 18px 40px rgba(20, 20, 40, 0.10);
  --denri-pill-on-bg: #17171c;
  --denri-pill-on-fg: #ffffff;
  --denri-track: rgba(23, 23, 28, 0.05);
  --denri-field: #ffffff;
  --denri-glow-1: rgba(165, 148, 249, 0.30);
  --denri-glow-2: rgba(255, 183, 197, 0.26);
  --denri-glow-3: rgba(156, 220, 196, 0.24);
  --denri-tint-1: #ece8ff;
  --denri-tint-2: #ffe8ee;
  --denri-tint-3: #e3f6ee;
  --denri-tint-4: #e4f0ff;
}
html[data-denri-theme="dark"] {
  --denri-ink-rgb: 255, 255, 255;
  --denri-text: #f2f2f5;
  --denri-text-2: #c4c4cf;
  --denri-muted: #8d8d9a;
  --denri-glass: rgba(255, 255, 255, 0.045);
  --denri-glass-hover: rgba(255, 255, 255, 0.07);
  --denri-glass-edge: rgba(255, 255, 255, 0.09);
  --denri-hair: rgba(255, 255, 255, 0.07);
  --denri-shadow: 0 1px 2px rgba(0, 0, 0, 0.3), 0 12px 32px rgba(0, 0, 0, 0.35);
  --denri-shadow-hover: 0 2px 4px rgba(0, 0, 0, 0.35), 0 20px 44px rgba(0, 0, 0, 0.5);
  --denri-pill-on-bg: #a594f9;
  --denri-pill-on-fg: #0b0b0f;
  --denri-track: rgba(255, 255, 255, 0.05);
  --denri-field: rgba(255, 255, 255, 0.04);
  --denri-glow-1: rgba(124, 104, 238, 0.20);
  --denri-glow-2: rgba(214, 92, 140, 0.12);
  --denri-glow-3: rgba(40, 170, 130, 0.10);
  --denri-tint-1: rgba(165, 148, 249, 0.13);
  --denri-tint-2: rgba(255, 140, 170, 0.10);
  --denri-tint-3: rgba(90, 210, 160, 0.10);
  --denri-tint-4: rgba(90, 160, 250, 0.11);
}

/* ---------- canvas ---------- */
.stApp {
  background-image:
    radial-gradient(38rem 26rem at 8% -6%, var(--denri-glow-1), transparent 70%),
    radial-gradient(34rem 24rem at 100% 8%, var(--denri-glow-2), transparent 70%),
    radial-gradient(40rem 28rem at 60% 110%, var(--denri-glow-3), transparent 70%);
  background-attachment: fixed;
}
[data-testid="stHeader"] {
  background: transparent;
  backdrop-filter: blur(10px);
  -webkit-backdrop-filter: blur(10px);
}
[data-testid="stMainBlockContainer"] { padding-top: 3.2rem; max-width: 1480px; }

/* ---------- headings ---------- */
h1 { font-weight: 800 !important; letter-spacing: -0.025em; }
h2, h3 { font-weight: 700 !important; letter-spacing: -0.015em; }
[data-testid="stCaptionContainer"] { color: var(--denri-muted); }

/* ---------- floating pill sidebar ---------- */
section[data-testid="stSidebar"] {
  background: transparent !important;
  box-shadow: none;
}
section[data-testid="stSidebar"] > div:first-child {
  margin: 12px 0 12px 12px;
  height: calc(100% - 24px);
  border-radius: 26px;
  background: var(--denri-sidebar-bg, #121216);
  border: 1px solid rgba(255, 255, 255, 0.06);
  box-shadow: 0 18px 44px rgba(10, 10, 20, 0.28);
  overflow: hidden;
}
[data-testid="stSidebarContent"] { border-radius: 26px; }
[data-testid="stSidebarNav"] a, [data-testid="stSidebarNavLink"] {
  border-radius: 999px !important;
  margin: 2px 6px;
  transition: background 160ms ease, transform 160ms ease;
}
[data-testid="stSidebarNavLink"]:hover { transform: translateX(2px); }
[data-testid="stSidebarNavLink"][aria-current="page"] {
  background: #c9bffc !important;
}
[data-testid="stSidebarNavLink"][aria-current="page"] span { color: #121216 !important; font-weight: 700; }

/* ---------- glass cards (bordered containers) ---------- */
[data-denri-card] {
  background: var(--denri-glass);
  border-color: var(--denri-glass-edge) !important;
  border-radius: 22px !important;
  box-shadow: var(--denri-shadow);
  backdrop-filter: blur(16px) saturate(140%);
  -webkit-backdrop-filter: blur(16px) saturate(140%);
  transition: transform 220ms cubic-bezier(.2, .8, .2, 1), box-shadow 220ms ease, background 220ms ease;
}
[data-denri-card]:hover {
  transform: translateY(-3px);
  box-shadow: var(--denri-shadow-hover);
  background: var(--denri-glass-hover);
}
[data-denri-card] [data-denri-card] { box-shadow: none; backdrop-filter: none; }
[data-denri-card] [data-denri-card]:hover { transform: none; }

/* ---------- KPI tiles ---------- */
[data-testid="stMetric"] {
  background: var(--denri-glass);
  border: 1px solid var(--denri-glass-edge);
  border-radius: 20px;
  padding: 14px 16px 12px 16px;
  box-shadow: var(--denri-shadow);
  backdrop-filter: blur(14px);
  -webkit-backdrop-filter: blur(14px);
  transition: transform 220ms cubic-bezier(.2, .8, .2, 1), box-shadow 220ms ease;
}
[data-testid="stMetric"]:hover { transform: translateY(-3px); box-shadow: var(--denri-shadow-hover); }
/* KPI rows take the pastel tints in turn, like the reference's cards */
[data-testid="stColumn"]:nth-child(4n+1) [data-testid="stElementContainer"] > [data-testid="stMetric"],
[data-testid="stColumn"]:nth-child(4n+1) [data-denri-card]:has(> [data-testid="stElementContainer"] > [data-testid="stMetric"]) { background: var(--denri-tint-1); }
[data-testid="stColumn"]:nth-child(4n+2) [data-testid="stElementContainer"] > [data-testid="stMetric"],
[data-testid="stColumn"]:nth-child(4n+2) [data-denri-card]:has(> [data-testid="stElementContainer"] > [data-testid="stMetric"]) { background: var(--denri-tint-2); }
[data-testid="stColumn"]:nth-child(4n+3) [data-testid="stElementContainer"] > [data-testid="stMetric"],
[data-testid="stColumn"]:nth-child(4n+3) [data-denri-card]:has(> [data-testid="stElementContainer"] > [data-testid="stMetric"]) { background: var(--denri-tint-3); }
[data-testid="stColumn"]:nth-child(4n) [data-testid="stElementContainer"] > [data-testid="stMetric"],
[data-testid="stColumn"]:nth-child(4n) [data-denri-card]:has(> [data-testid="stElementContainer"] > [data-testid="stMetric"]) { background: var(--denri-tint-4); }
[data-denri-card] [data-testid="stMetric"] {
  background: transparent !important; border-color: transparent; box-shadow: none;
  backdrop-filter: none; padding: 2px 0;
}
[data-denri-card] [data-testid="stMetric"]:hover { transform: none; }
[data-testid="stMetricLabel"] p { color: var(--denri-muted); font-weight: 600; font-size: 0.8rem; }
[data-testid="stMetricValue"] { font-weight: 800; letter-spacing: -0.02em; font-size: clamp(1.25rem, 1.65vw, 2rem); }
/* long figures wrap instead of being cut to "KES 82,3…" */
[data-testid="stMetricValue"] > div { white-space: normal; overflow: visible; text-overflow: clip; line-height: 1.15; }

/* ---------- pill filters: segmented control, pills, tabs ---------- */
[data-testid="stButtonGroup"] > div {
  background: var(--denri-track);
  border-radius: 999px;
  padding: 4px;
  gap: 4px;
  width: fit-content;
  max-width: 100%;
  flex-wrap: wrap;
}
[data-testid="stButtonGroup"] button {
  border-radius: 999px !important;
  border-color: transparent !important;
  background: transparent;
  font-weight: 600;
  transition: background 160ms ease, color 160ms ease;
}
[data-testid="stButtonGroup"] button:hover { background: var(--denri-glass); }
[data-testid="stButtonGroup"] button[aria-checked="true"] {
  background: var(--denri-pill-on-bg) !important;
  color: var(--denri-pill-on-fg) !important;
  box-shadow: 0 4px 12px rgba(20, 20, 40, 0.18);
}
[data-testid="stButtonGroup"] button[aria-checked="true"] * { color: var(--denri-pill-on-fg) !important; }

[data-baseweb="tab-list"] {
  background: var(--denri-track);
  border-radius: 999px;
  padding: 4px;
  gap: 4px;
  width: fit-content;
  max-width: 100%;
}
[data-baseweb="tab-list"] button[role="tab"] {
  border-radius: 999px;
  padding: 6px 16px;
  height: auto;
}
[data-baseweb="tab-list"] button[role="tab"][aria-selected="true"] {
  background: var(--denri-pill-on-bg);
}
[data-baseweb="tab-list"] button[role="tab"][aria-selected="true"] p { color: var(--denri-pill-on-fg); font-weight: 700; }
[data-baseweb="tab-highlight"], [data-baseweb="tab-border"] { display: none; }

/* ---------- buttons & fields ---------- */
.stButton button, .stDownloadButton button, [data-testid="stFormSubmitButton"] button {
  font-weight: 600;
  transition: transform 160ms ease, box-shadow 160ms ease;
}
.stButton button:hover, .stDownloadButton button:hover, [data-testid="stFormSubmitButton"] button:hover {
  transform: translateY(-1px);
  box-shadow: 0 6px 16px rgba(20, 20, 40, 0.14);
}
html[data-denri-theme="dark"] [data-testid^="stBaseButton-primary"],
html[data-denri-theme="dark"] [data-testid^="stBaseButton-primary"] * { color: #0b0b0f !important; }
.stButton button:active, .stDownloadButton button:active { transform: scale(0.98); }
[data-baseweb="select"] > div, [data-baseweb="input"], [data-testid="stDateInput"] [data-baseweb="input"] {
  background: var(--denri-field);
  border-radius: 12px;
}

/* ---------- expanders, tables, charts ---------- */
[data-testid="stExpander"] details {
  background: var(--denri-glass);
  border-color: var(--denri-glass-edge);
  border-radius: 18px;
  box-shadow: var(--denri-shadow);
  backdrop-filter: blur(14px);
  -webkit-backdrop-filter: blur(14px);
}
[data-denri-card] [data-testid="stExpander"] details { box-shadow: none; }
[data-testid="stDataFrame"], [data-testid="stTable"] { border-radius: 14px; overflow: hidden; }
[data-testid="stPlotlyChart"] {
  background: var(--denri-glass);
  border: 1px solid var(--denri-glass-edge);
  border-radius: 20px;
  box-shadow: var(--denri-shadow);
  padding: 6px;
  backdrop-filter: blur(14px);
  -webkit-backdrop-filter: blur(14px);
}
[data-denri-card] [data-testid="stPlotlyChart"] {
  background: transparent; border-color: transparent; box-shadow: none; padding: 0; backdrop-filter: none;
}
[data-testid="stAlert"] > div { border-radius: 16px; }
hr { border-color: var(--denri-hair) !important; }

/* the script element below takes no room */
[data-testid="stElementContainer"]:has(> [data-testid="stHtml"] > script.denri-boot) { display: none; }

@media (prefers-reduced-motion: reduce) {
  *, *::before, *::after { transition: none !important; animation: none !important; }
}
</style>
"""

# Runs in the page itself (st.html with JavaScript), once per browser tab.
_SCRIPT = """
<script class="denri-boot">
(() => {
  if (window.__denriStyle) { window.__denriStyle(); return; }
  const root = document.documentElement;
  const lum = (rgb) => {
    const m = (rgb || "").match(/\\d+(\\.\\d+)?/g);
    if (!m) return 1;
    return (0.2126 * m[0] + 0.7152 * m[1] + 0.0722 * m[2]) / 255;
  };
  const sync = () => {
    const app = document.querySelector(".stApp");
    if (app) {
      const mode = lum(getComputedStyle(app).backgroundColor) < 0.5 ? "dark" : "light";
      if (root.dataset.denriTheme !== mode) root.dataset.denriTheme = mode;
    }
    const side = document.querySelector('section[data-testid="stSidebar"]');
    if (side) {
      const inner = side.querySelector('[data-testid="stSidebarContent"]');
      if (inner) {
        const bg = getComputedStyle(inner).backgroundColor;
        if (bg && bg !== "rgba(0, 0, 0, 0)") root.style.setProperty("--denri-sidebar-bg", bg);
      }
    }
    document.querySelectorAll('[data-testid="stVerticalBlock"][data-test-scroll-behavior]:not([data-denri-seen])')
      .forEach((el) => {
        el.dataset.denriSeen = "1";
        const cs = getComputedStyle(el);
        if (parseFloat(cs.borderTopWidth) > 0 && cs.borderTopStyle !== "none") el.dataset.denriCard = "1";
      });
  };
  let queued = false;
  const schedule = () => {
    if (queued) return;
    queued = true;
    requestAnimationFrame(() => { queued = false; sync(); });
  };
  new MutationObserver(schedule).observe(document.body, { childList: true, subtree: true });
  new MutationObserver(schedule).observe(document.head, { childList: true, subtree: true, characterData: true });
  window.matchMedia("(prefers-color-scheme: dark)").addEventListener("change", schedule);
  window.__denriStyle = schedule;
  sync();
})();
</script>
"""


def inject() -> None:
    """Add the global stylesheet and theme script to the current page."""
    mode = getattr(getattr(st.context, "theme", None), "type", None) or "dark"
    # The first paint uses the theme the browser reported, so nothing flashes
    # the wrong way before the script takes over.
    st.html(_CSS.replace(':root, html[data-denri-theme="light"]',
                         ':root, html[data-denri-theme="light"]' if mode == "light" else
                         'html[data-denri-theme="light"]', 1)
            .replace('html[data-denri-theme="dark"] {',
                     ':root, html[data-denri-theme="dark"] {' if mode != "light" else
                     'html[data-denri-theme="dark"] {', 1))
    st.html(_SCRIPT, unsafe_allow_javascript=True)
