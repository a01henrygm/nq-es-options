"""The Q DATA loading window shown while the app starts its server and data collection."""
from __future__ import annotations
import base64

from backend.config import ROOT


def splash_html(version: str) -> str:
    p = ROOT / "assets" / "icon_256.png"
    img = f'<img src="data:image/png;base64,{base64.b64encode(p.read_bytes()).decode()}" alt="">' if p.exists() else ""
    return """<!DOCTYPE html><html><head><meta charset="utf-8"><style>
html,body{margin:0;height:100%;background:#05070b;overflow:hidden;font-family:"Segoe UI",system-ui,sans-serif;color:#e8ecf4;user-select:none}
.wrap{height:100%;display:flex;flex-direction:column;align-items:center;justify-content:center;gap:18px;
  background:radial-gradient(circle at 50% 38%,rgba(66,110,255,.20),transparent 60%)}
img{width:118px;height:118px;filter:drop-shadow(0 0 22px rgba(64,140,255,.55));animation:glow 2.4s ease-in-out infinite}
@keyframes glow{50%{filter:drop-shadow(0 0 34px rgba(150,90,255,.75));transform:scale(1.025)}}
h1{margin:0;font-size:44px;font-weight:800;letter-spacing:.32em;padding-left:.32em;
  background:linear-gradient(90deg,#3fb6ff,#5b7bff 50%,#a35bff);-webkit-background-clip:text;background-clip:text;color:transparent}
.bar{width:220px;height:3px;border-radius:3px;background:#141a26;overflow:hidden}
.bar i{display:block;width:40%;height:100%;border-radius:3px;background:linear-gradient(90deg,#3fb6ff,#a35bff);animation:run 1.3s ease-in-out infinite}
@keyframes run{0%{transform:translateX(-110%)}100%{transform:translateX(280%)}}
#st{font-size:12.5px;color:#8792a6;min-height:16px}
.v{position:fixed;bottom:10px;right:14px;font-size:11px;color:#4a5466}
</style></head><body><div class="wrap">""" + img + """<h1>Q DATA</h1><div class="bar"><i></i></div><div id="st">Starting...</div></div>
<div class="v">v""" + version + """</div>
<script>function setStatus(t){document.getElementById('st').textContent=t}</script></body></html>"""
