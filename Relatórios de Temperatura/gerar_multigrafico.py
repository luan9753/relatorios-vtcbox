"""Gera multigráfico HTML de temperatura a partir dos PDFs renomeados."""
from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path

import fitz

PASTA = Path(__file__).resolve().parent
PEDIDO = "556160"
UF = "SC"
PADRAO_PDF = re.compile(rf"^{PEDIDO}_([A-Z][A-Z0-9]+)_{UF}\.pdf$", re.I)
PAT_LOGGER = re.compile(r"Nome do dispositivo:\s*([A-Z][A-Z0-9]+)", re.I)
PAT_MIN = re.compile(r"Temperatura m[ií]nima:\s*([-\d.]+)", re.I)
PAT_MAX = re.compile(r"Temperatura m[aá]xima:\s*([-\d.]+)", re.I)
PAT_MEDIA = re.compile(r"Temperatura m[eé]dia:\s*([-\d.]+)", re.I)
OUT_HTML = PASTA / f"multigrafico_{PEDIDO}_{UF}.html"

# Faixa de referência (refrigerado 2–8 °C)
FAIXA_MIN = 2.0
FAIXA_MAX = 8.0


def parse_pdf(pdf: Path) -> dict | None:
    doc = fitz.open(pdf)
    try:
        text = "".join(page.get_text() for page in doc)
    finally:
        doc.close()

    m = PAT_LOGGER.search(text)
    if not m:
        return None
    logger = m.group(1).upper()

    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    points: list[dict] = []
    i = 0
    while i < len(lines):
        if re.fullmatch(r"\d{2}/\d{2}/\d{4} \d{2}:\d{2}:\d{2}", lines[i]):
            dt_str = lines[i]
            temp_raw = lines[i + 1] if i + 1 < len(lines) else ""
            temp_m = re.search(r"([\d.]+)", temp_raw)
            if temp_m:
                dt = datetime.strptime(dt_str, "%d/%m/%Y %H:%M:%S")
                points.append(
                    {
                        "t": dt.strftime("%Y-%m-%d %H:%M:%S"),
                        "temp": float(temp_m.group(1)),
                    }
                )
            i += 3
            continue
        i += 1

    if not points:
        return None

    points.sort(key=lambda p: p["t"])
    tmin = PAT_MIN.search(text)
    tmax = PAT_MAX.search(text)
    tmed = PAT_MEDIA.search(text)

    return {
        "logger": logger,
        "arquivo": pdf.name,
        "pontos": len(points),
        "temp_min": float(tmin.group(1)) if tmin else None,
        "temp_max": float(tmax.group(1)) if tmax else None,
        "temp_media": float(tmed.group(1)) if tmed else None,
        "inicio": points[0]["t"],
        "fim": points[-1]["t"],
        "serie": points,
    }


def carregar_series() -> list[dict]:
    series: list[dict] = []
    for pdf in sorted(PASTA.glob("*.pdf")):
        if not PADRAO_PDF.match(pdf.name):
            continue
        item = parse_pdf(pdf)
        if item:
            series.append(item)
    series.sort(key=lambda s: s["logger"])
    return series


def render_html(series: list[dict], gerado_em: str) -> str:
    data_json = json.dumps(series, ensure_ascii=False)
    loggers_json = json.dumps([s["logger"] for s in series], ensure_ascii=False)

    return f"""<!doctype html>
<html lang="pt-BR">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Multigráfico — Pedido {PEDIDO} ({UF})</title>
  <script src="https://cdn.plot.ly/plotly-2.35.2.min.js"></script>
  <style>
    :root {{
      --bg: #0b0f14;
      --card: #141b24;
      --ink: #e8eef5;
      --muted: #8fa3bc;
      --line: #243044;
      --accent: #60a5fa;
      --ok: #4ade80;
      --warn: #fb923c;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      font-family: "Segoe UI", system-ui, sans-serif;
      background: var(--bg);
      color: var(--ink);
    }}
    .wrap {{ max-width: 1600px; margin: 0 auto; padding: 18px; }}
    .hero {{
      background: linear-gradient(135deg, #0f2744, #1e3a5f);
      border: 1px solid var(--line);
      border-radius: 16px;
      padding: 22px 24px;
      margin-bottom: 16px;
    }}
    .hero h1 {{ margin: 0 0 6px; font-size: 1.5rem; }}
    .hero p {{ margin: 4px 0; color: #bfdbfe; font-size: 0.92rem; }}
    .tabs {{
      display: flex;
      gap: 8px;
      flex-wrap: wrap;
      margin-bottom: 14px;
    }}
    .tab {{
      background: var(--card);
      border: 1px solid var(--line);
      color: var(--ink);
      padding: 10px 16px;
      border-radius: 10px;
      cursor: pointer;
      font-weight: 600;
    }}
    .tab.active {{ background: #1e3a5f; border-color: var(--accent); color: #fff; }}
    .panel {{
      display: none;
      background: var(--card);
      border: 1px solid var(--line);
      border-radius: 14px;
      padding: 14px;
      margin-bottom: 16px;
    }}
    .panel.active {{ display: block; }}
    .toolbar {{
      display: flex;
      flex-wrap: wrap;
      gap: 10px;
      align-items: center;
      margin-bottom: 12px;
    }}
    .toolbar input, .toolbar select {{
      background: #0f172a;
      border: 1px solid var(--line);
      color: var(--ink);
      border-radius: 8px;
      padding: 8px 12px;
      min-width: 220px;
    }}
    .btn {{
      background: var(--accent);
      color: #0f172a;
      border: none;
      border-radius: 8px;
      padding: 8px 14px;
      font-weight: 700;
      cursor: pointer;
    }}
    .grid {{
      display: grid;
      grid-template-columns: repeat(auto-fill, minmax(320px, 1fr));
      gap: 12px;
    }}
    .mini {{
      background: #0f172a;
      border: 1px solid var(--line);
      border-radius: 12px;
      padding: 8px;
      cursor: pointer;
      transition: border-color .15s;
    }}
    .mini:hover, .mini.focused {{ border-color: var(--accent); }}
    .mini h3 {{
      margin: 0 0 4px;
      font-size: 0.95rem;
      display: flex;
      justify-content: space-between;
      gap: 8px;
    }}
    .mini .meta {{ font-size: 0.75rem; color: var(--muted); margin-bottom: 4px; }}
    .mini-chart {{ height: 180px; }}
    .badge {{
      font-size: 0.7rem;
      padding: 2px 8px;
      border-radius: 999px;
      font-weight: 700;
    }}
    .badge.ok {{ background: #14532d; color: #bbf7d0; }}
    .badge.warn {{ background: #7c2d12; color: #fed7aa; }}
    #chart-detalhe, #chart-comparativo, #chart-todos {{ width: 100%; min-height: 520px; }}
    .logger-list {{
      max-height: 280px;
      overflow: auto;
      display: grid;
      grid-template-columns: repeat(auto-fill, minmax(120px, 1fr));
      gap: 6px;
      background: #0f172a;
      border: 1px solid var(--line);
      border-radius: 10px;
      padding: 10px;
    }}
    .logger-list label {{
      font-size: 0.82rem;
      display: flex;
      gap: 6px;
      align-items: center;
      cursor: pointer;
    }}
    .footer {{ color: var(--muted); font-size: 0.8rem; text-align: center; padding: 12px; }}
  </style>
</head>
<body>
  <div class="wrap">
    <header class="hero">
      <h1>Multigráfico de Temperatura — Pedido {PEDIDO} ({UF})</h1>
      <p>Loggers com PDF disponível: <strong id="n-loggers">{len(series)}</strong></p>
      <p>Faixa de referência: <strong>{FAIXA_MIN}°C a {FAIXA_MAX}°C</strong> · Gerado em {gerado_em}</p>
    </header>

    <div class="tabs">
      <button class="tab active" data-tab="individual">Individual (1 gráfico por logger)</button>
      <button class="tab" data-tab="detalhe">Detalhe (logger selecionado)</button>
      <button class="tab" data-tab="comparativo">Comparativo (até 6 loggers)</button>
    </div>

    <section id="panel-individual" class="panel active">
      <div class="toolbar">
        <input type="search" id="busca-grid" placeholder="Filtrar logger..." />
        <button class="btn" id="btn-mostrar-todos">Mostrar todos</button>
      </div>
      <div class="grid" id="grid-mini"></div>
    </section>

    <section id="panel-detalhe" class="panel">
      <div class="toolbar">
        <select id="sel-detalhe"></select>
      </div>
      <div id="chart-detalhe"></div>
    </section>

    <section id="panel-comparativo" class="panel">
      <div class="toolbar">
        <button class="btn" id="btn-limpar">Limpar seleção</button>
        <span style="color:var(--muted);font-size:0.85rem">Selecione até 6 loggers:</span>
      </div>
      <div class="logger-list" id="lista-comp"></div>
      <div id="chart-comparativo" style="margin-top:12px"></div>
    </section>

    <div class="footer">Clique em um mini-gráfico para abrir o detalhe · Dados extraídos dos PDFs de temperatura</div>
  </div>

  <script>
    const DATA = {data_json};
    const LOGGERS = {loggers_json};
    const FAIXA = [{FAIXA_MIN}, {FAIXA_MAX}];
    const COLORS = [
      "#60a5fa","#4ade80","#fb923c","#f472b6","#a78bfa","#facc15",
      "#22d3ee","#f87171","#34d399","#c084fc","#fdba74","#86efac"
    ];

    const layoutBase = {{
      paper_bgcolor: "#0f172a",
      plot_bgcolor: "#0f172a",
      font: {{ color: "#e8eef5", size: 11 }},
      margin: {{ l: 42, r: 12, t: 28, b: 36 }},
      xaxis: {{
        gridcolor: "#243044",
        tickcolor: "#243044",
        linecolor: "#243044",
        tickformat: "%d/%m %H:%M",
      }},
      yaxis: {{
        gridcolor: "#243044",
        tickcolor: "#243044",
        linecolor: "#243044",
        title: "°C",
      }},
      showlegend: false,
    }};

    function faixaShapes() {{
      return [
        {{
          type: "rect", xref: "paper", x0: 0, x1: 1,
          y0: FAIXA[0], y1: FAIXA[1],
          fillcolor: "rgba(74,222,128,0.12)",
          line: {{ width: 0 }},
          layer: "below",
        }},
        {{
          type: "line", xref: "paper", x0: 0, x1: 1,
          y0: FAIXA[0], y1: FAIXA[0],
          line: {{ color: "#4ade80", width: 1, dash: "dot" }},
        }},
        {{
          type: "line", xref: "paper", x0: 0, x1: 1,
          y0: FAIXA[1], y1: FAIXA[1],
          line: {{ color: "#4ade80", width: 1, dash: "dot" }},
        }},
      ];
    }}

    function conforme(s) {{
      if (s.temp_min == null || s.temp_max == null) return false;
      return s.temp_min >= FAIXA[0] && s.temp_max <= FAIXA[1];
    }}

    function traceTemp(s, color) {{
      return {{
        x: s.serie.map(p => p.t),
        y: s.serie.map(p => p.temp),
        type: "scatter",
        mode: "lines",
        name: s.logger,
        line: {{ color, width: 2 }},
        hovertemplate: "%{{x}}<br>%{{y:.2f}}°C<extra>" + s.logger + "</extra>",
      }};
    }}

    function miniLayout(title) {{
      return {{
        ...layoutBase,
        title: {{ text: title, font: {{ size: 12 }} }},
        margin: {{ l: 36, r: 8, t: 30, b: 30 }},
        shapes: faixaShapes(),
      }};
    }}

    function detalheLayout(s) {{
      return {{
        ...layoutBase,
        title: `Logger ${{s.logger}} — min ${{s.temp_min ?? "?"}}°C / max ${{s.temp_max ?? "?"}}°C / média ${{s.temp_media ?? "?"}}°C`,
        margin: {{ l: 50, r: 20, t: 50, b: 50 }},
        shapes: faixaShapes(),
        showlegend: false,
      }};
    }}

    function renderGrid(filtro = "") {{
      const grid = document.getElementById("grid-mini");
      grid.innerHTML = "";
      const q = filtro.trim().toUpperCase();
      DATA.filter(s => !q || s.logger.includes(q)).forEach((s, idx) => {{
        const ok = conforme(s);
        const card = document.createElement("div");
        card.className = "mini";
        card.dataset.logger = s.logger;
        card.innerHTML = `
          <h3>${{s.logger}} <span class="badge ${{ok ? "ok" : "warn"}}">${{ok ? "OK" : "FORA"}}</span></h3>
          <div class="meta">${{s.pontos}} pts · ${{s.inicio.slice(5,16)}} → ${{s.fim.slice(5,16)}}</div>
          <div class="mini-chart" id="mini-${{s.logger}}"></div>
        `;
        card.addEventListener("click", () => openDetalhe(s.logger));
        grid.appendChild(card);
        Plotly.newPlot(
          `mini-${{s.logger}}`,
          [traceTemp(s, COLORS[idx % COLORS.length])],
          miniLayout(s.logger),
          {{ responsive: true, displayModeBar: false }}
        );
      }});
    }}

    function openDetalhe(logger) {{
      document.querySelectorAll(".tab").forEach(t => t.classList.toggle("active", t.dataset.tab === "detalhe"));
      document.querySelectorAll(".panel").forEach(p => p.classList.remove("active"));
      document.getElementById("panel-detalhe").classList.add("active");
      document.getElementById("sel-detalhe").value = logger;
      renderDetalhe(logger);
    }}

    function renderDetalhe(logger) {{
      const s = DATA.find(d => d.logger === logger);
      if (!s) return;
      Plotly.newPlot("chart-detalhe", [traceTemp(s, "#60a5fa")], detalheLayout(s), {{ responsive: true }});
    }}

    function renderComparativo() {{
      const picked = [...document.querySelectorAll("#lista-comp input:checked")].map(el => el.value).slice(0, 6);
      const traces = picked.map((lg, i) => {{
        const s = DATA.find(d => d.logger === lg);
        return traceTemp(s, COLORS[i % COLORS.length]);
      }});
      const layout = {{
        ...layoutBase,
        title: "Comparativo de loggers selecionados",
        margin: {{ l: 50, r: 20, t: 50, b: 50 }},
        shapes: faixaShapes(),
        showlegend: true,
        legend: {{ orientation: "h", y: 1.12 }},
      }};
      Plotly.newPlot("chart-comparativo", traces, layout, {{ responsive: true }});
    }}

    // Tabs
    document.querySelectorAll(".tab").forEach(btn => {{
      btn.addEventListener("click", () => {{
        document.querySelectorAll(".tab").forEach(t => t.classList.toggle("active", t === btn));
        document.querySelectorAll(".panel").forEach(p => p.classList.remove("active"));
        document.getElementById("panel-" + btn.dataset.tab).classList.add("active");
      }});
    }});

    document.getElementById("busca-grid").addEventListener("input", e => renderGrid(e.target.value));
    document.getElementById("btn-mostrar-todos").addEventListener("click", () => {{
      document.getElementById("busca-grid").value = "";
      renderGrid();
    }});

    const sel = document.getElementById("sel-detalhe");
    LOGGERS.forEach(lg => {{
      const opt = document.createElement("option");
      opt.value = lg; opt.textContent = lg;
      sel.appendChild(opt);
    }});
    sel.addEventListener("change", () => renderDetalhe(sel.value));

    const lista = document.getElementById("lista-comp");
    LOGGERS.forEach(lg => {{
      const lbl = document.createElement("label");
      lbl.innerHTML = `<input type="checkbox" value="${{lg}}"> ${{lg}}`;
      lbl.querySelector("input").addEventListener("change", () => {{
        const n = document.querySelectorAll("#lista-comp input:checked").length;
        if (n > 6) {{
          lbl.querySelector("input").checked = false;
          alert("Máximo de 6 loggers no comparativo.");
          return;
        }}
        renderComparativo();
      }});
      lista.appendChild(lbl);
    }});
    document.getElementById("btn-limpar").addEventListener("click", () => {{
      document.querySelectorAll("#lista-comp input").forEach(c => c.checked = false);
      Plotly.purge("chart-comparativo");
    }});

    renderGrid();
    if (LOGGERS.length) {{
      sel.value = LOGGERS[0];
      renderDetalhe(LOGGERS[0]);
    }}
  </script>
</body>
</html>
"""


def main() -> int:
    series = carregar_series()
    if not series:
        print(f"Nenhum PDF encontrado no padrao {PEDIDO}_LOGGER_{UF}.pdf em {PASTA}")
        return 1

    gerado_em = datetime.now().strftime("%d/%m/%Y %H:%M:%S")
    html = render_html(series, gerado_em)
    OUT_HTML.write_text(html, encoding="utf-8")

    print(f"Loggers: {len(series)}")
    print(f"Arquivo: {OUT_HTML}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
