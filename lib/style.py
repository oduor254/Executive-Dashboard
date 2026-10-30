"""App-wide look: soft canvas, floating pill sidebar, glass cards, pill filters.

Streamlit's own Light / Dark / System themes (.streamlit/config.toml) set the
base colours; this layer adds the shapes, translucency and motion on top.
inject() runs from auth.require_login(), which every page calls first.

CSS can't ask Streamlit which theme is showing, so a small script stamps
<html data-denri-theme="light|dark"> from the app background's brightness and
keeps it current when the theme is switched. The same script runs the
sidebar's glass lens and its refraction filters. It also marks bordered
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
  --denri-text-2: #3a3a44;
  --denri-muted: #5f5f6b;
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
  /* sidebar liquid glass */
  --denri-side-glass: linear-gradient(160deg, rgba(255, 255, 255, 0.62), rgba(255, 255, 255, 0.30) 55%, rgba(255, 255, 255, 0.46));
  --denri-side-edge: rgba(255, 255, 255, 0.85);
  --denri-side-ink: #17171c;
  --denri-side-muted: #5b5b68;
  --denri-side-hover: rgba(255, 255, 255, 0.55);
  --denri-side-on-bg: rgba(255, 255, 255, 0.92);
  --denri-side-on-fg: #17171c;
  --denri-side-on-icon: #6d5ce8;
  --denri-side-shadow: 0 24px 60px rgba(60, 50, 120, 0.16), 0 2px 6px rgba(60, 50, 120, 0.08);
  --denri-lens: rgba(255, 255, 255, 0.22);
  --denri-orb-a: rgba(140, 120, 250, 0.55);
  --denri-orb-b: rgba(255, 150, 190, 0.45);
  --denri-orb-c: rgba(110, 200, 255, 0.40);
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
  --denri-side-glass: linear-gradient(160deg, rgba(255, 255, 255, 0.10), rgba(255, 255, 255, 0.03) 55%, rgba(255, 255, 255, 0.07));
  --denri-side-edge: rgba(255, 255, 255, 0.22);
  --denri-side-ink: #ececf1;
  --denri-side-muted: #a3a3b2;
  --denri-side-hover: rgba(255, 255, 255, 0.07);
  --denri-side-on-bg: #c9bffc;
  --denri-side-on-fg: #121216;
  --denri-side-on-icon: #121216;
  --denri-side-shadow: 0 24px 60px rgba(0, 0, 0, 0.55), 0 2px 6px rgba(0, 0, 0, 0.3);
  --denri-lens: rgba(255, 255, 255, 0.06);
  --denri-orb-a: rgba(124, 104, 238, 0.36);
  --denri-orb-b: rgba(214, 92, 140, 0.22);
  --denri-orb-c: rgba(60, 140, 230, 0.22);
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

/* ---------- liquid-glass sidebar ----------
   Light glass in Light mode, smoked glass in Dark. Colour orbs drift behind
   it so the glass has something to bend; in Chromium browsers an SVG
   displacement filter adds the refraction, elsewhere it stays frosted. */
section[data-testid="stSidebar"] {
  background: transparent !important;
  box-shadow: none;
  transition: width 320ms cubic-bezier(.2, .8, .2, 1), min-width 320ms cubic-bezier(.2, .8, .2, 1),
              transform 320ms cubic-bezier(.2, .8, .2, 1) !important;
}
section[data-testid="stSidebar"]::before {
  content: ""; position: fixed; left: -60px; top: 6vh; width: 340px; height: 88vh; z-index: -1;
  pointer-events: none; filter: blur(30px);
  background:
    radial-gradient(150px 150px at 30% 18%, var(--denri-orb-a), transparent 70%),
    radial-gradient(170px 170px at 75% 55%, var(--denri-orb-b), transparent 70%),
    radial-gradient(150px 150px at 25% 88%, var(--denri-orb-c), transparent 70%);
  animation: denriOrbs 18s ease-in-out infinite alternate;
}
@keyframes denriOrbs {
  0% { transform: translate(0, 0) rotate(0deg); }
  50% { transform: translate(18px, -24px) rotate(8deg); }
  100% { transform: translate(-10px, 20px) rotate(-6deg); }
}
section[data-testid="stSidebar"] > div:first-child {
  position: relative;
  margin: 12px 0 12px 12px;
  height: calc(100% - 24px);
  border-radius: 28px;
  /* the glass, plus a specular rim: bright at the top-left, fading round the edge */
  border: 1.2px solid transparent;
  background:
    var(--denri-side-glass) padding-box,
    linear-gradient(145deg, rgba(255, 255, 255, 0.95), rgba(255, 255, 255, 0.12) 32%,
                    rgba(255, 255, 255, 0.04) 62%, rgba(255, 255, 255, 0.55)) border-box;
  backdrop-filter: blur(22px) saturate(185%) brightness(1.04);
  -webkit-backdrop-filter: blur(22px) saturate(185%) brightness(1.04);
  box-shadow:
    var(--denri-side-shadow),
    inset 1.5px 1.5px 0 var(--denri-side-edge),
    inset -1px -1px 0 rgba(255, 255, 255, 0.18),
    inset 0 0 26px rgba(255, 255, 255, 0.10);
  overflow: hidden;
}
html[data-denri-liquid] section[data-testid="stSidebar"] > div:first-child {
  backdrop-filter: blur(16px) url(#denri-refract) saturate(185%) brightness(1.04);
}
/* a soft glare band across the top */
section[data-testid="stSidebar"] > div:first-child::after {
  content: ""; position: absolute; left: -20%; top: -12%; width: 140%; height: 34%; pointer-events: none; z-index: 1;
  background: radial-gradient(ellipse at 40% 0%, rgba(255, 255, 255, 0.35), transparent 65%);
  opacity: 0.55;
}
[data-testid="stSidebarContent"] { border-radius: 28px; background: transparent !important; position: relative; z-index: 3; }
[data-testid="stSidebarContent"] * { color: var(--denri-side-ink); }

[data-testid="stSidebarNavItems"] { position: relative; }
[data-testid="stSidebarNavLink"] {
  position: relative; z-index: 1;
  border-radius: 999px !important;
  margin: 2px 6px;
  gap: 10px;
  background: transparent !important;
  transition: background 200ms ease;
}
[data-testid="stSidebarNavLink"] > span {
  transform-origin: 0% 50%;
  transition: transform 340ms cubic-bezier(.3, 1.5, .5, 1), letter-spacing 340ms ease;
}
[data-testid="stSidebarNavLink"][aria-current="page"] {
  background: var(--denri-side-on-bg) !important;
  box-shadow: 0 6px 18px rgba(60, 50, 120, 0.14), inset 1px 1px 0 rgba(255, 255, 255, 0.9);
}
[data-testid="stSidebarNavLink"][aria-current="page"] span,
[data-testid="stSidebarNavLink"][aria-current="page"] p { color: var(--denri-side-on-fg) !important; font-weight: 700; }

/* the lens: a drop of glass that glides to whichever page is under the
   pointer and magnifies it as it passes, like the iOS tab bar */
.denri-lens {
  position: absolute; left: 6px; right: 6px; top: 0; height: 36px; z-index: 2; pointer-events: none;
  border-radius: 999px; opacity: 0;
  background: var(--denri-lens);
  backdrop-filter: blur(1.5px) saturate(170%) brightness(1.06);
  -webkit-backdrop-filter: blur(1.5px) saturate(170%) brightness(1.06);
  box-shadow:
    inset 1.5px 1.5px 0 rgba(255, 255, 255, 0.85),
    inset -1px -1px 0 rgba(255, 255, 255, 0.25),
    inset 0 -6px 14px rgba(255, 255, 255, 0.18),
    0 10px 24px rgba(40, 30, 90, 0.18);
  transition: transform 460ms cubic-bezier(.3, 1.35, .45, 1), opacity 220ms ease,
              height 300ms ease, left 300ms ease, right 300ms ease;
}
html[data-denri-liquid] .denri-lens {
  backdrop-filter: url(#denri-lens-refract) saturate(170%) brightness(1.06);
}
.denri-lens.on { opacity: 1; }
.denri-lens.moving { animation: denriSquash 460ms cubic-bezier(.3, 1.35, .45, 1); }
@keyframes denriSquash { 0% { scale: 1 1; } 35% { scale: 1.04 0.86; } 70% { scale: 0.99 1.05; } 100% { scale: 1 1; } }
[data-denri-lensed] > span { transform: scale(1.16); letter-spacing: 0.01em; }
[data-denri-lensed]::before { transform: scale(1.28) !important; }

/* every page gets an icon (Material Symbols, already loaded by Streamlit) */
[data-testid="stSidebarNavLink"]::before {
  content: var(--denri-icon, "radio_button_unchecked");
  font-family: "Material Symbols Rounded";
  font-size: 20px; line-height: 1; font-weight: 400;
  font-feature-settings: "liga"; -webkit-font-feature-settings: "liga";
  flex-shrink: 0; width: 22px; text-align: center;
  color: var(--denri-side-muted);
  transition: transform 340ms cubic-bezier(.3, 1.6, .5, 1), color 160ms ease;
}
[data-testid="stSidebarNavLink"]:hover::before { color: var(--denri-side-ink); }
[data-testid="stSidebarNavLink"][aria-current="page"]::before { color: var(--denri-side-on-icon); }
[data-denri-home] { --denri-icon: "home"; }
[data-testid="stSidebarNavLink"][href$="/Sales"] { --denri-icon: "payments"; }
[data-testid="stSidebarNavLink"][href$="/Product_Sales"] { --denri-icon: "shopping_bag"; }
[data-testid="stSidebarNavLink"][href$="/Customers"] { --denri-icon: "groups"; }
[data-testid="stSidebarNavLink"][href$="/Production"] { --denri-icon: "precision_manufacturing"; }
[data-testid="stSidebarNavLink"][href$="/Dispatch_Tracking"] { --denri-icon: "local_shipping"; }
[data-testid="stSidebarNavLink"][href$="/Stock_Levels"] { --denri-icon: "inventory_2"; }
[data-testid="stSidebarNavLink"][href$="/WhatsApp_and_Social_DMs"] { --denri-icon: "forum"; }
[data-testid="stSidebarNavLink"][href$="/Shop_Attendants"] { --denri-icon: "badge"; }
[data-testid="stSidebarNavLink"][href$="/Shop_Performance"] { --denri-icon: "storefront"; }
[data-testid="stSidebarNavLink"][href$="/Footfall_Traffic"] { --denri-icon: "directions_walk"; }
[data-testid="stSidebarNavLink"][href$="/Reports"] { --denri-icon: "description"; }
/* pages that bring their own icon (sales_operations_app.py) keep it */
[data-testid="stSidebarNavLink"]:has([data-testid^="stIcon"])::before { display: none; }
/* the entry page is called "app" after its file; show it as Home */
[data-denri-home] p { font-size: 0; }
[data-denri-home] p::after {
  content: "Home"; font-size: 0.875rem;
}

/* collapsed: a slim icon rail instead of vanishing */
section[data-testid="stSidebar"][aria-expanded="false"] {
  transform: none !important;
  width: 88px !important; min-width: 88px !important; max-width: 88px !important;
}
section[data-testid="stSidebar"][aria-expanded="false"] [data-testid="stSidebarUserContent"],
section[data-testid="stSidebar"][aria-expanded="false"] [data-testid="stSidebarHeader"] > :not([data-testid="stSidebarCollapseButton"]),
section[data-testid="stSidebar"][aria-expanded="false"] [data-testid="stSidebarNavSeparator"],
section[data-testid="stSidebar"][aria-expanded="false"] [data-testid="stSidebarNavViewButton"] { display: none !important; }
section[data-testid="stSidebar"][aria-expanded="false"] [data-testid="stSidebarNav"] { padding-top: 40px; }
section[data-testid="stSidebar"][aria-expanded="false"] [data-testid="stSidebarNavLink"] {
  width: 44px; height: 44px; min-height: 0; padding: 0 !important; margin: 3px auto; justify-content: center;
  animation: denriRailIn 420ms cubic-bezier(.3, 1.4, .5, 1) both;
}
section[data-testid="stSidebar"][aria-expanded="false"] [data-testid="stSidebarNavLink"] > span { display: none; }
section[data-testid="stSidebar"][aria-expanded="false"] [data-testid="stSidebarNavLink"]::before { font-size: 22px; }
section[data-testid="stSidebar"][aria-expanded="false"] .denri-lens { left: 50%; right: auto; width: 44px; margin-left: -22px; height: 44px; }
section[data-testid="stSidebar"][aria-expanded="false"] [data-testid="stSidebarNavLink"][aria-current="page"] {
  box-shadow: 0 0 0 4px rgba(165, 148, 249, 0.18), 0 8px 18px rgba(124, 104, 238, 0.30), inset 1px 1px 0 rgba(255, 255, 255, 0.9);
}
section[data-testid="stSidebar"][aria-expanded="false"] li:nth-child(1) [data-testid="stSidebarNavLink"] { animation-delay: 30ms; }
section[data-testid="stSidebar"][aria-expanded="false"] li:nth-child(2) [data-testid="stSidebarNavLink"] { animation-delay: 60ms; }
section[data-testid="stSidebar"][aria-expanded="false"] li:nth-child(3) [data-testid="stSidebarNavLink"] { animation-delay: 90ms; }
section[data-testid="stSidebar"][aria-expanded="false"] li:nth-child(4) [data-testid="stSidebarNavLink"] { animation-delay: 120ms; }
section[data-testid="stSidebar"][aria-expanded="false"] li:nth-child(5) [data-testid="stSidebarNavLink"] { animation-delay: 150ms; }
section[data-testid="stSidebar"][aria-expanded="false"] li:nth-child(6) [data-testid="stSidebarNavLink"] { animation-delay: 180ms; }
section[data-testid="stSidebar"][aria-expanded="false"] li:nth-child(7) [data-testid="stSidebarNavLink"] { animation-delay: 210ms; }
section[data-testid="stSidebar"][aria-expanded="false"] li:nth-child(8) [data-testid="stSidebarNavLink"] { animation-delay: 240ms; }
section[data-testid="stSidebar"][aria-expanded="false"] li:nth-child(9) [data-testid="stSidebarNavLink"] { animation-delay: 270ms; }
section[data-testid="stSidebar"][aria-expanded="false"] li:nth-child(10) [data-testid="stSidebarNavLink"] { animation-delay: 300ms; }
section[data-testid="stSidebar"][aria-expanded="false"] li:nth-child(11) [data-testid="stSidebarNavLink"] { animation-delay: 330ms; }
section[data-testid="stSidebar"][aria-expanded="false"] li:nth-child(12) [data-testid="stSidebarNavLink"] { animation-delay: 360ms; }
section[data-testid="stSidebar"][aria-expanded="false"] li:nth-child(13) [data-testid="stSidebarNavLink"] { animation-delay: 390ms; }
section[data-testid="stSidebar"][aria-expanded="false"] li:nth-child(14) [data-testid="stSidebarNavLink"] { animation-delay: 420ms; }
section[data-testid="stSidebar"][aria-expanded="true"] [data-testid="stSidebarNavLink"] > span {
  animation: denriLabelIn 360ms ease both;
}
@keyframes denriRailIn { from { opacity: 0; transform: translateX(-14px) scale(0.6); } to { opacity: 1; transform: none; } }
@keyframes denriLabelIn { from { opacity: 0; transform: translateX(-8px); } to { opacity: 1; transform: none; } }
/* the » button beside the rail reopens the full sidebar */
[data-testid="stExpandSidebarButton"] { transition: transform 200ms ease; }
[data-testid="stExpandSidebarButton"]:hover { transform: translateX(3px) scale(1.12); }

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
/* Figures are never cut short ("KES 81,0…"). The script below fits each value
   to its own tile: short ones stay full size, long ones shrink just enough to
   show in full at any zoom or column width, and wrap only as a last resort.
   Labels and delta tags wrap instead of being clipped. */
[data-testid="stMetricLabel"] p { color: var(--denri-muted); font-weight: 600; font-size: 0.8rem; }
[data-testid="stMetricValue"] { font-weight: 800; letter-spacing: -0.02em; line-height: 1.12; font-size: 2rem; }
[data-testid="stMetricValue"] p { font-size: inherit; line-height: inherit; margin: 0; }
[data-testid="stMetricValue"], [data-testid="stMetricValue"] > div, [data-testid="stMetricValue"] p {
  overflow: visible !important;
  text-overflow: clip !important;
}
[data-testid="stMetric"] label, [data-testid="stMetric"] label *,
[data-testid="stMetricDelta"], [data-testid="stMetricDelta"] * {
  white-space: normal !important;
  overflow: visible !important;
  text-overflow: clip !important;
}
[data-testid="stMetricDelta"] { height: auto !important; align-items: flex-start; max-width: 100%; }
[data-testid="stMetricDelta"] svg { flex-shrink: 0; margin-top: 2px; }
[data-testid="stMetricDelta"] p { font-size: 0.78rem; line-height: 1.3; }

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
      const was = root.dataset.denriTheme;
      if (was !== mode) {
        root.dataset.denriTheme = mode;
        // Charts are coloured on the server from the theme it last saw, and
        // switching themes doesn't rerun the app, so ask for a rerun.
        const rerun = was && document.querySelector(".st-key-denri_theme_sync button");
        if (rerun) rerun.click();
      }
    }
    lens();
    document.querySelectorAll('[data-testid="stSidebarNavLink"]:not([title])').forEach((a) => {
      const span = a.querySelector("span[label]");
      const label = span ? span.getAttribute("label") : a.textContent.trim();
      if (label === "app") a.dataset.denriHome = "1";
      a.title = label === "app" ? "Home" : label;  // the rail's hover label
    });
    document.querySelectorAll('[data-testid="stVerticalBlock"][data-test-scroll-behavior]:not([data-denri-seen])')
      .forEach((el) => {
        el.dataset.denriSeen = "1";
        const cs = getComputedStyle(el);
        if (parseFloat(cs.borderTopWidth) > 0 && cs.borderTopStyle !== "none") el.dataset.denriCard = "1";
      });
  };
  // Refraction needs SVG filters inside backdrop-filter, which only Chromium
  // draws; other browsers keep the plain frosted glass.
  const brands = (navigator.userAgentData && navigator.userAgentData.brands) || [];
  if (brands.some((b) => /Chromium/.test(b.brand))) root.dataset.denriLiquid = "1";
  if (!document.getElementById("denri-glass-filters")) {
    const ns = "http://www.w3.org/2000/svg";
    const holder = document.createElementNS(ns, "svg");
    holder.id = "denri-glass-filters";
    holder.setAttribute("width", "0"); holder.setAttribute("height", "0");
    holder.style.position = "absolute";
    // Built node by node: markup inside this script would be stripped.
    const el = (parent, tag, attrs) => {
      const node = document.createElementNS(ns, tag);
      Object.entries(attrs).forEach(([k, v]) => node.setAttribute(k, v));
      parent.appendChild(node);
      return node;
    };
    const box = { x: "0", y: "0", width: "100%", height: "100%" };
    const panel = el(holder, "filter", { id: "denri-refract", ...box });
    el(panel, "feTurbulence", { type: "fractalNoise", baseFrequency: "0.006 0.009", numOctaves: "2", seed: "7", result: "n" });
    el(panel, "feGaussianBlur", { in: "n", stdDeviation: "8", result: "nb" });
    el(panel, "feDisplacementMap", { in: "SourceGraphic", in2: "nb", scale: "16", xChannelSelector: "R", yChannelSelector: "G" });
    const drop = el(holder, "filter", { id: "denri-lens-refract", ...box });
    el(drop, "feTurbulence", { type: "fractalNoise", baseFrequency: "0.02 0.05", numOctaves: "1", seed: "3", result: "n" });
    el(drop, "feDisplacementMap", { in: "SourceGraphic", in2: "n", scale: "6", xChannelSelector: "R", yChannelSelector: "G" });
    document.body.appendChild(holder);
  }

  // The sidebar lens: follows the pointer down the page list, springs back to
  // the open page when the pointer leaves, and magnifies whatever it covers.
  let lensFor = null;
  const place = (lensEl, link, list, magnify = true) => {
    if (!link) { lensEl.classList.remove("on"); return; }
    const top = link.getBoundingClientRect().top - list.getBoundingClientRect().top;
    if (lensEl.dataset.y !== String(top)) {
      lensEl.classList.remove("moving"); void lensEl.offsetWidth; lensEl.classList.add("moving");
    }
    lensEl.dataset.y = String(top);
    lensEl.style.height = link.offsetHeight + "px";
    lensEl.style.transform = `translateY(${top}px)`;
    lensEl.classList.add("on");
    list.querySelectorAll("[data-denri-lensed]").forEach((l) => { if (l !== link) delete l.dataset.denriLensed; });
    if (magnify) link.dataset.denriLensed = "1";
    clearTimeout(lensEl.fade);
  };
  const lens = () => {
    const list = document.querySelector('[data-testid="stSidebarNavItems"]');
    if (!list) return;
    let lensEl = list.querySelector(":scope > .denri-lens");
    if (!lensEl) {
      lensEl = document.createElement("div");
      lensEl.className = "denri-lens";
      list.appendChild(lensEl);
    }
    if (lensFor !== list) {
      lensFor = list;
      // On leaving, the lens glides back onto the open page and dissolves into it.
      const home = () => {
        place(lensEl, list.querySelector('[data-testid="stSidebarNavLink"][aria-current="page"]'), list, false);
        lensEl.fade = setTimeout(() => lensEl.classList.remove("on"), 420);
      };
      list.addEventListener("pointerover", (e) => {
        const link = e.target.closest('[data-testid="stSidebarNavLink"]');
        if (link) place(lensEl, link, list);
      });
      list.addEventListener("pointerleave", () => {
        list.querySelectorAll("[data-denri-lensed]").forEach((l) => delete l.dataset.denriLensed);
        home();
      });
    }
  };

  // Fit every KPI figure to its tile (see the stMetricValue CSS).
  const fit = () => {
    document.querySelectorAll('[data-testid="stMetricValue"]').forEach((v) => {
      const p = v.querySelector("p") || v;
      const tile = v.closest('[data-testid="stMetric"]') || v.parentElement;
      const cs = getComputedStyle(tile);
      const room = tile.clientWidth - parseFloat(cs.paddingLeft) - parseFloat(cs.paddingRight);
      if (room <= 0) return;
      const key = room + "|" + p.textContent;
      if (p.dataset.denriFit === key) return;
      p.style.fontSize = "";
      p.style.whiteSpace = "nowrap";
      let size = parseFloat(getComputedStyle(p).fontSize);
      if (p.scrollWidth > room) {
        size = Math.max(15, Math.floor(size * room / p.scrollWidth));
        p.style.fontSize = size + "px";
        while (p.scrollWidth > room && size > 15) { size -= 1; p.style.fontSize = size + "px"; }
      }
      p.style.whiteSpace = p.scrollWidth > room ? "normal" : "nowrap";
      p.dataset.denriFit = key;
    });
  };
  let queued = false;
  const schedule = () => {
    if (queued) return;
    queued = true;
    requestAnimationFrame(() => { queued = false; sync(); fit(); });
  };
  new MutationObserver(schedule).observe(document.body, { childList: true, subtree: true });
  new MutationObserver(schedule).observe(document.head, { childList: true, subtree: true, characterData: true });
  window.matchMedia("(prefers-color-scheme: dark)").addEventListener("change", schedule);
  window.addEventListener("resize", schedule);  // browser zoom fires this too
  window.__denriStyle = schedule;
  sync();
  fit();
  // Re-measure once the web font arrives; it is wider than the fallback.
  if (document.fonts) document.fonts.ready.then(() => {
    document.querySelectorAll("[data-denri-fit]").forEach((p) => delete p.dataset.denriFit);
    fit();
  });
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
    # Hidden; the script clicks it after a theme switch to redraw the charts.
    st.html("<style>.st-key-denri_theme_sync { display: none !important; }</style>")
    st.button("Sync theme", key="denri_theme_sync")
