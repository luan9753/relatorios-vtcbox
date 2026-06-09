"""Gera painel HTML de temperatura para todos os pedidos (pastas Pedido_*)."""
from __future__ import annotations

import json
import re
import statistics
from datetime import datetime
from pathlib import Path

import fitz

PASTA = Path(__file__).resolve().parent
OUT_HTML = PASTA / "multigrafico_todos.html"
PADRAO_PDF = re.compile(r"^(\d+)_([A-Z][A-Z0-9]+)_([A-Z]{2})(_\d+)?\.pdf$", re.I)
PAT_LOGGER = re.compile(r"Nome do dispositivo:\s*([A-Z][A-Z0-9]+)", re.I)
PAT_MIN = re.compile(r"Temperatura m[ií]nima:\s*([-\d.]+)", re.I)
PAT_MAX = re.compile(r"Temperatura m[aá]xima:\s*([-\d.]+)", re.I)
PAT_MEDIA = re.compile(r"Temperatura m[eé]dia:\s*([-\d.]+)", re.I)

FAIXA_MIN = 2.0
FAIXA_MAX = 8.0
SALTO_MIN_C = 2.0
JANELA_ESTAVEL = 20


def recalcular_metricas(points: list[dict]) -> dict:
    temps = [p["temp"] for p in points]
    return {
        "temp_min": min(temps),
        "temp_max": max(temps),
        "temp_media": round(statistics.mean(temps), 2),
        "pontos": len(points),
        "inicio": points[0]["t"],
        "fim": points[-1]["t"],
    }


def cortar_pos_entrega(points: list[dict]) -> tuple[list[dict], int]:
    """Remove trecho final após salto(s) para cima saindo da faixa de trânsito."""
    if len(points) < 3:
        return points, 0

    n0 = len(points)
    min_idx = max(1, int(n0 * 0.70))  # só considera salto nos últimos 30% da série
    total_cortados = 0

    while len(points) >= 3:
        corte_em = None
        limite = min(min_idx, len(points) - 1)
        for i in range(len(points) - 1, limite - 1, -1):
            delta = points[i]["temp"] - points[i - 1]["temp"]
            if delta < SALTO_MIN_C:
                continue
            if points[i - 1]["temp"] <= FAIXA_MAX:
                corte_em = i
                break

        if corte_em is None:
            break

        pre = points[max(0, corte_em - JANELA_ESTAVEL) : corte_em]
        suffix = points[corte_em:]
        if not pre or not suffix:
            break

        pre_med = statistics.median(p["temp"] for p in pre)
        suf_med = statistics.median(p["temp"] for p in suffix)
        if suf_med < pre_med + 1.0 and max(p["temp"] for p in suffix) <= FAIXA_MAX:
            break

        removidos = len(points) - corte_em
        points = points[:corte_em]
        total_cortados += removidos

    return points, total_cortados


def parse_pdf(pdf: Path, pedido: str, uf: str) -> dict | None:
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
    pontos_originais = len(points)
    points, pontos_cortados = cortar_pos_entrega(points)
    if len(points) < 2:
        return None

    metricas = recalcular_metricas(points)

    return {
        "id": f"{pedido}_{uf}_{logger}",
        "pedido": pedido,
        "uf": uf,
        "logger": logger,
        "arquivo": pdf.name,
        "pasta": pdf.parent.name,
        "pontos": metricas["pontos"],
        "pontos_originais": pontos_originais,
        "pontos_cortados": pontos_cortados,
        "cortado_entrega": pontos_cortados > 0,
        "temp_min": metricas["temp_min"],
        "temp_max": metricas["temp_max"],
        "temp_media": metricas["temp_media"],
        "inicio": metricas["inicio"],
        "fim": metricas["fim"],
        "serie": points,
    }


def coletar_pdfs() -> list[tuple[Path, str, str]]:
    encontrados: list[tuple[Path, str, str]] = []
    vistos: set[Path] = set()

    for pasta in sorted(PASTA.glob("Pedido_*")):
        if not pasta.is_dir():
            continue
        for pdf in sorted(pasta.glob("*.pdf")):
            m = PADRAO_PDF.match(pdf.name)
            if not m:
                continue
            resolved = pdf.resolve()
            if resolved in vistos:
                continue
            vistos.add(resolved)
            encontrados.append((pdf, m.group(1), m.group(3).upper()))

    for pdf in sorted(PASTA.glob("*.pdf")):
        m = PADRAO_PDF.match(pdf.name)
        if not m:
            continue
        resolved = pdf.resolve()
        if resolved in vistos:
            continue
        vistos.add(resolved)
        encontrados.append((pdf, m.group(1), m.group(3).upper()))

    return encontrados


def _prioridade_pdf(item: dict) -> tuple:
    dup = 1 if re.search(r"_\d+\.pdf$", item["arquivo"], re.I) else 0
    return (dup, -item["pontos"])


def carregar_series() -> list[dict]:
    por_id: dict[str, dict] = {}
    for pdf, pedido, uf in coletar_pdfs():
        item = parse_pdf(pdf, pedido, uf)
        if not item:
            continue
        key = item["id"]
        if key not in por_id or _prioridade_pdf(item) < _prioridade_pdf(por_id[key]):
            por_id[key] = item
    series = sorted(por_id.values(), key=lambda s: (s["pedido"], s["uf"], s["logger"]))
    return series


def contar_ok(series: list[dict]) -> int:
    return sum(
        1
        for s in series
        if s["temp_min"] is not None
        and s["temp_max"] is not None
        and s["temp_min"] >= FAIXA_MIN
        and s["temp_max"] <= FAIXA_MAX
    )


def render_html(series: list[dict], gerado_em: str) -> str:
    data_json = json.dumps(series, ensure_ascii=False)
    pedidos = sorted({s["pedido"] for s in series})
    ufs = sorted({s["uf"] for s in series})
    pedidos_json = json.dumps(pedidos, ensure_ascii=False)
    ufs_json = json.dumps(ufs, ensure_ascii=False)
    n_pedidos = len(pedidos)
    n_ufs = len(ufs)
    n_loggers = len(series)
    n_ok = contar_ok(series)
    n_fora = n_loggers - n_ok
    pct_ok = round(100 * n_ok / n_loggers) if n_loggers else 0

    return f"""<!doctype html>
<html lang="pt-BR">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover" />
  <meta name="theme-color" content="#0b0f14" />
  <meta name="apple-mobile-web-app-capable" content="yes" />
  <title>Temperatura VTCBOX — Painel Executivo</title>
  <script src="https://cdn.plot.ly/plotly-2.35.2.min.js"></script>
  <style>
    :root {{
      --bg: #0b0f14;
      --surface: #141b24;
      --ink: #e8eef5;
      --muted: #8fa3bc;
      --line: #243044;
      --navy: #0f2744;
      --navy-soft: #1e3a5f;
      --accent: #60a5fa;
      --ok: #4ade80;
      --ok-bg: rgba(74,222,128,.1);
      --ok-border: rgba(74,222,128,.35);
      --warn: #fb923c;
      --warn-bg: rgba(251,146,60,.1);
      --warn-border: rgba(251,146,60,.35);
      --chart-bg: #0f172a;
      --radius: 16px;
      --shadow: 0 4px 24px rgba(0,0,0,.35);
      --safe-b: env(safe-area-inset-bottom, 0px);
      --safe-t: env(safe-area-inset-top, 0px);
    }}
    * {{ box-sizing: border-box; -webkit-tap-highlight-color: transparent; }}
    html {{ scroll-behavior: smooth; }}
    body {{
      margin: 0;
      font-family: "Segoe UI", system-ui, -apple-system, sans-serif;
      background: var(--bg);
      color: var(--ink);
      line-height: 1.45;
      padding-bottom: calc(72px + var(--safe-b));
    }}
    .topbar {{
      position: sticky;
      top: 0;
      z-index: 100;
      background: linear-gradient(135deg, #0f2744, #1e3a5f);
      color: #fff;
      padding: calc(12px + var(--safe-t)) 16px 12px;
      box-shadow: 0 2px 16px rgba(0,0,0,.4);
      border-bottom: 1px solid var(--line);
    }}
    .topbar-inner {{ max-width: 1200px; margin: 0 auto; }}
    .topbar .brand {{ font-size: .72rem; text-transform: uppercase; letter-spacing: .12em; opacity: .75; }}
    .topbar h1 {{ margin: 2px 0 0; font-size: 1.15rem; font-weight: 700; }}
    .topbar .sub {{ margin: 4px 0 0; font-size: .78rem; opacity: .85; }}
    .wrap {{ max-width: 1200px; margin: 0 auto; padding: 14px 14px 0; }}
    .legenda {{
      background: var(--surface);
      border: 1px solid var(--line);
      border-radius: var(--radius);
      padding: 12px 14px;
      margin-bottom: 14px;
      font-size: .84rem;
      color: var(--muted);
      box-shadow: var(--shadow);
    }}
    .legenda strong {{ color: var(--ink); }}
    .legenda .faixa {{
      display: inline-flex;
      align-items: center;
      gap: 6px;
      margin-top: 6px;
      padding: 4px 10px;
      background: var(--ok-bg);
      border: 1px solid var(--ok-border);
      border-radius: 999px;
      color: var(--ok);
      font-weight: 600;
      font-size: .8rem;
    }}
    .hero-kpis {{
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 10px;
      margin-bottom: 10px;
    }}
    .hero-kpi {{
      border-radius: var(--radius);
      padding: 18px 16px;
      box-shadow: var(--shadow);
      border: 2px solid transparent;
    }}
    .hero-kpi {{ background: var(--surface); border: 1px solid var(--line); }}
    .hero-kpi.ok {{ background: var(--ok-bg); border-color: var(--ok-border); }}
    .hero-kpi.warn {{ background: var(--warn-bg); border-color: var(--warn-border); }}
    .hero-kpi .num {{ font-size: 2.4rem; font-weight: 800; line-height: 1; }}
    .hero-kpi.ok .num {{ color: var(--ok); }}
    .hero-kpi.warn .num {{ color: var(--warn); }}
    .hero-kpi .lbl {{ font-size: .95rem; font-weight: 700; margin-top: 4px; color: var(--ink); }}
    .hero-kpi .hint {{ font-size: .75rem; color: var(--muted); margin-top: 2px; }}
    .conformidade {{
      background: var(--surface);
      border: 1px solid var(--line);
      border-radius: var(--radius);
      padding: 14px 16px;
      margin-bottom: 14px;
      box-shadow: var(--shadow);
    }}
    .conformidade .row {{
      display: flex;
      justify-content: space-between;
      align-items: center;
      font-size: .88rem;
      font-weight: 600;
      margin-bottom: 8px;
    }}
    .bar-track {{
      height: 10px;
      background: #1e293b;
      border-radius: 999px;
      overflow: hidden;
    }}
    .bar-fill {{
      height: 100%;
      background: linear-gradient(90deg, var(--ok), #22d3ee);
      border-radius: 999px;
      transition: width .4s ease;
    }}
    .kpis-sec {{
      display: grid;
      grid-template-columns: repeat(3, 1fr);
      gap: 8px;
      margin-bottom: 14px;
    }}
    .kpi-sec {{
      background: var(--surface);
      border: 1px solid var(--line);
      border-radius: 12px;
      padding: 12px 8px;
      text-align: center;
      box-shadow: var(--shadow);
    }}
    .kpi-sec .val {{ font-size: 1.35rem; font-weight: 800; color: var(--accent); }}
    .kpi-sec .lbl {{ font-size: .68rem; color: var(--muted); text-transform: uppercase; letter-spacing: .05em; margin-top: 2px; }}
    .nav-tabs {{
      position: sticky;
      top: calc(56px + var(--safe-t));
      z-index: 90;
      background: var(--bg);
      padding: 8px 0 10px;
      margin: 0 -14px;
      padding-left: 14px;
      padding-right: 14px;
      overflow-x: auto;
      -webkit-overflow-scrolling: touch;
      scrollbar-width: none;
      display: flex;
      gap: 8px;
    }}
    .nav-tabs::-webkit-scrollbar {{ display: none; }}
    .tab {{
      flex: 0 0 auto;
      min-height: 44px;
      padding: 10px 18px;
      border: 1px solid var(--line);
      border-radius: 999px;
      background: var(--surface);
      color: var(--muted);
      font-size: .88rem;
      font-weight: 600;
      cursor: pointer;
      white-space: nowrap;
      transition: all .15s;
    }}
    .tab.active {{
      background: var(--navy-soft);
      border-color: var(--accent);
      color: #fff;
      box-shadow: 0 4px 12px rgba(0,0,0,.3);
    }}
    .panel {{ display: none; }}
    .panel.active {{ display: block; }}
    .panel-card {{
      background: var(--surface);
      border: 1px solid var(--line);
      border-radius: var(--radius);
      padding: 14px;
      margin-bottom: 14px;
      box-shadow: var(--shadow);
    }}
    .filtros-toggle {{
      width: 100%;
      min-height: 48px;
      display: flex;
      align-items: center;
      justify-content: space-between;
      background: var(--bg);
      border: 1px solid var(--line);
      border-radius: 12px;
      padding: 12px 14px;
      font-size: .92rem;
      font-weight: 600;
      color: var(--ink);
      cursor: pointer;
      margin-bottom: 10px;
    }}
    .filtros-toggle .chev {{ transition: transform .2s; }}
    .filtros-toggle.open .chev {{ transform: rotate(180deg); }}
    .filtros-body {{ display: none; }}
    .filtros-body.open {{ display: block; }}
    .chips {{
      display: flex;
      gap: 8px;
      margin-bottom: 12px;
      overflow-x: auto;
      -webkit-overflow-scrolling: touch;
      padding-bottom: 2px;
    }}
    .chip {{
      flex: 0 0 auto;
      min-height: 40px;
      padding: 8px 16px;
      border-radius: 999px;
      border: 1px solid var(--line);
      background: var(--surface);
      font-size: .85rem;
      font-weight: 600;
      color: var(--muted);
      cursor: pointer;
    }}
    .chip.active {{ background: var(--navy-soft); color: #fff; border-color: var(--accent); }}
    .chip.ok.active {{ background: var(--ok); border-color: var(--ok); }}
    .chip.warn.active {{ background: var(--warn); border-color: var(--warn); }}
    .field {{ margin-bottom: 10px; }}
    .field label {{
      display: block;
      font-size: .72rem;
      font-weight: 700;
      text-transform: uppercase;
      letter-spacing: .06em;
      color: var(--muted);
      margin-bottom: 4px;
    }}
    .field input, .field select {{
      width: 100%;
      min-height: 48px;
      font-size: 16px;
      padding: 10px 14px;
      border: 1px solid var(--line);
      border-radius: 12px;
      background: var(--bg);
      color: var(--ink);
      appearance: none;
    }}
    .btn {{
      width: 100%;
      min-height: 48px;
      border: none;
      border-radius: 12px;
      background: var(--accent);
      color: #0f172a;
      font-size: .92rem;
      font-weight: 700;
      cursor: pointer;
      margin-top: 4px;
    }}
    .btn-ghost {{
      background: transparent;
      border: 1px solid var(--line);
      color: var(--muted);
    }}
    .grid {{
      display: grid;
      grid-template-columns: 1fr;
      gap: 12px;
    }}
    .card {{
      background: var(--surface);
      border: 1px solid var(--line);
      border-radius: var(--radius);
      overflow: hidden;
      box-shadow: var(--shadow);
      cursor: pointer;
      transition: transform .12s, box-shadow .12s;
    }}
    .card:active {{ transform: scale(.98); }}
    .card-head {{
      padding: 14px 14px 10px;
      display: flex;
      justify-content: space-between;
      align-items: flex-start;
      gap: 10px;
      border-bottom: 1px solid var(--line);
    }}
    .card-head.ok-head {{ background: linear-gradient(180deg, var(--ok-bg), var(--surface)); }}
    .card-head.warn-head {{ background: linear-gradient(180deg, var(--warn-bg), var(--surface)); }}
    .card-pedido {{ font-size: .78rem; color: var(--muted); font-weight: 600; }}
    .card-uf {{
      display: inline-block;
      background: var(--navy-soft);
      color: #bfdbfe;
      font-size: .7rem;
      font-weight: 700;
      padding: 2px 8px;
      border-radius: 6px;
      margin-left: 6px;
      border: 1px solid var(--line);
    }}
    .card-logger {{ font-size: 1.2rem; font-weight: 800; color: var(--ink); margin-top: 2px; }}
    .card-temps {{ font-size: .78rem; color: var(--muted); margin-top: 4px; }}
    .badge {{
      flex-shrink: 0;
      min-width: 56px;
      text-align: center;
      font-size: .75rem;
      font-weight: 800;
      padding: 6px 10px;
      border-radius: 10px;
      letter-spacing: .04em;
    }}
    .badge.ok {{ background: #14532d; color: #bbf7d0; }}
    .badge.warn {{ background: #7c2d12; color: #fed7aa; }}
    .card-meta {{
      padding: 8px 14px;
      font-size: .75rem;
      color: var(--muted);
      display: flex;
      justify-content: space-between;
    }}
    .chart-box {{
      position: relative;
      height: 160px;
      background: var(--chart-bg);
    }}
    .chart-loading {{
      position: absolute;
      inset: 0;
      display: flex;
      align-items: center;
      justify-content: center;
      color: var(--muted);
      font-size: .8rem;
      z-index: 2;
      pointer-events: none;
      transition: opacity .2s;
    }}
    .chart-loading.done {{
      opacity: 0;
      visibility: hidden;
    }}
    .mini-chart {{ height: 160px; width: 100%; }}
    #chart-detalhe, #chart-comparativo {{ width: 100%; min-height: 340px; }}
    .detalhe-info {{
      display: grid;
      grid-template-columns: repeat(3, 1fr);
      gap: 8px;
      margin-bottom: 12px;
    }}
    .det-box {{
      background: var(--bg);
      border-radius: 10px;
      padding: 10px 8px;
      text-align: center;
    }}
    .det-box .v {{ font-size: 1.1rem; font-weight: 800; color: var(--ink); }}
    .det-box .l {{ font-size: .65rem; color: var(--muted); text-transform: uppercase; margin-top: 2px; }}
    .logger-list {{
      max-height: 50vh;
      overflow: auto;
      -webkit-overflow-scrolling: touch;
      display: flex;
      flex-direction: column;
      gap: 6px;
    }}
    .logger-item {{
      display: flex;
      align-items: center;
      gap: 12px;
      min-height: 48px;
      padding: 10px 12px;
      background: var(--bg);
      border: 1px solid var(--line);
      border-radius: 12px;
      font-size: .85rem;
      cursor: pointer;
    }}
    .logger-item input {{ width: 20px; height: 20px; flex-shrink: 0; }}
    .logger-item .st {{ margin-left: auto; font-size: .7rem; font-weight: 700; padding: 3px 8px; border-radius: 6px; }}
    .logger-item .st.ok {{ background: var(--ok-bg); color: var(--ok); }}
    .logger-item .st.warn {{ background: var(--warn-bg); color: var(--warn); }}
    .empty {{
      text-align: center;
      padding: 40px 20px;
      color: var(--muted);
      font-size: .92rem;
    }}
    .footer {{
      text-align: center;
      font-size: .75rem;
      color: var(--muted);
      padding: 16px 14px 8px;
    }}
    .bottom-nav {{
      position: fixed;
      bottom: 0;
      left: 0;
      right: 0;
      z-index: 100;
      background: var(--surface);
      border-top: 1px solid var(--line);
      padding: 8px 8px calc(8px + var(--safe-b));
      display: flex;
      gap: 6px;
      box-shadow: 0 -4px 20px rgba(0,0,0,.4);
    }}
    .bottom-nav button {{
      flex: 1;
      min-height: 48px;
      border: none;
      border-radius: 12px;
      background: transparent;
      color: var(--muted);
      font-size: .72rem;
      font-weight: 600;
      cursor: pointer;
      display: flex;
      flex-direction: column;
      align-items: center;
      justify-content: center;
      gap: 2px;
    }}
    .bottom-nav button .ico {{ font-size: 1.2rem; line-height: 1; }}
    .bottom-nav button.active {{ background: var(--navy-soft); color: #fff; border: 1px solid var(--accent); }}
    @media (min-width: 640px) {{
      .wrap {{ padding: 20px 20px 0; }}
      .topbar h1 {{ font-size: 1.35rem; }}
      .hero-kpis {{ grid-template-columns: 1fr 1fr; gap: 14px; }}
      .hero-kpi .num {{ font-size: 3rem; }}
      .grid {{ grid-template-columns: repeat(2, 1fr); }}
      .filtros-body.open {{ display: grid; grid-template-columns: 1fr 1fr; gap: 10px; }}
      .filtros-body.open .btn {{ grid-column: 1 / -1; }}
      .filtros-toggle {{ display: none; }}
      .filtros-body {{ display: grid !important; grid-template-columns: 1fr 1fr 1fr; gap: 10px; }}
      .filtros-body .btn {{ grid-column: 1 / -1; max-width: 240px; }}
      .bottom-nav {{ display: none; }}
      body {{ padding-bottom: 20px; }}
      #chart-detalhe, #chart-comparativo {{ min-height: 480px; }}
    }}
    @media (min-width: 1024px) {{
      .grid {{ grid-template-columns: repeat(3, 1fr); }}
      .hero-kpis {{ max-width: 560px; }}
    }}
  </style>
</head>
<body>
  <header class="topbar">
    <div class="topbar-inner">
      <div class="brand">VTCBOX · Caixa Nova</div>
      <h1>Painel de Temperatura</h1>
      <div class="sub">Atualizado em {gerado_em}</div>
    </div>
  </header>

  <div class="wrap">
    <div class="legenda">
      <strong>Como ler:</strong> cada card é um logger de temperatura de um pedido.
      <strong>OK</strong> = mínima e máxima dentro da faixa refrigerada.
      <strong>Fora</strong> = algum valor saiu da faixa.
      <div class="faixa">Faixa aceita: {FAIXA_MIN}°C a {FAIXA_MAX}°C</div>
    </div>

    <div class="hero-kpis">
      <div class="hero-kpi ok">
        <div class="num" id="kpi-ok">{n_ok}</div>
        <div class="lbl">Dentro da faixa</div>
        <div class="hint">Loggers OK</div>
      </div>
      <div class="hero-kpi warn">
        <div class="num" id="kpi-fora">{n_fora}</div>
        <div class="lbl">Fora da faixa</div>
        <div class="hint">Requer atenção</div>
      </div>
    </div>

    <div class="conformidade">
      <div class="row">
        <span>Taxa de conformidade</span>
        <span id="kpi-pct">{pct_ok}%</span>
      </div>
      <div class="bar-track"><div class="bar-fill" id="bar-ok" style="width:{pct_ok}%"></div></div>
    </div>

    <div class="kpis-sec">
      <div class="kpi-sec"><div class="val" id="kpi-visiveis">{n_loggers}</div><div class="lbl">Loggers</div></div>
      <div class="kpi-sec"><div class="val" id="kpi-pedidos">{n_pedidos}</div><div class="lbl">Pedidos</div></div>
      <div class="kpi-sec"><div class="val" id="kpi-ufs">{n_ufs}</div><div class="lbl">UFs</div></div>
    </div>

    <div class="nav-tabs" id="nav-tabs">
      <button class="tab active" data-tab="individual">Visão geral</button>
      <button class="tab" data-tab="detalhe">Detalhe</button>
      <button class="tab" data-tab="comparativo">Comparar</button>
    </div>

    <section id="panel-individual" class="panel active">
      <div class="panel-card">
        <div class="chips" id="chips-status">
          <button class="chip active" data-status="">Todos</button>
          <button class="chip ok" data-status="ok">Só OK</button>
          <button class="chip warn" data-status="fora">Só Fora</button>
        </div>
        <button class="filtros-toggle" id="btn-filtros" type="button">
          <span>Filtros avançados</span>
          <span class="chev">▼</span>
        </button>
        <div class="filtros-body" id="filtros-body">
          <div class="field">
            <label>Pedido</label>
            <select id="filtro-pedido"><option value="">Todos os pedidos</option></select>
          </div>
          <div class="field">
            <label>UF</label>
            <select id="filtro-uf"><option value="">Todas as UFs</option></select>
          </div>
          <div class="field">
            <label>Buscar</label>
            <input type="search" id="busca-grid" placeholder="Pedido, UF ou logger..." enterkeyhint="search" />
          </div>
          <button class="btn btn-ghost" id="btn-limpar-filtros" type="button">Limpar filtros</button>
        </div>
      </div>
      <div class="grid" id="grid-mini"></div>
    </section>

    <section id="panel-detalhe" class="panel">
      <div class="panel-card">
        <div class="field">
          <label>Selecione o logger</label>
          <select id="sel-detalhe"></select>
        </div>
        <div class="detalhe-info" id="detalhe-info"></div>
      </div>
      <div class="panel-card" style="padding:8px">
        <div id="chart-detalhe"></div>
      </div>
    </section>

    <section id="panel-comparativo" class="panel">
      <div class="panel-card">
        <p style="margin:0 0 10px;font-size:.88rem;color:var(--muted)">Marque até <strong>6 loggers</strong> para comparar no mesmo gráfico.</p>
        <div class="logger-list" id="lista-comp"></div>
        <button class="btn btn-ghost" id="btn-limpar" type="button" style="margin-top:10px">Limpar seleção</button>
      </div>
      <div class="panel-card" style="padding:8px">
        <div id="chart-comparativo"></div>
      </div>
    </section>

    <div class="footer">Toque em um card para ver o gráfico completo · Ordenado por Pedido → UF → Logger</div>
  </div>

  <nav class="bottom-nav" id="bottom-nav">
    <button class="active" data-tab="individual" type="button"><span class="ico">▦</span>Visão</button>
    <button data-tab="detalhe" type="button"><span class="ico">📈</span>Detalhe</button>
    <button data-tab="comparativo" type="button"><span class="ico">⚖</span>Comparar</button>
  </nav>

  <script>
    const DATA = {data_json};
    const PEDIDOS = {pedidos_json};
    const UFS = {ufs_json};
    const FAIXA = [{FAIXA_MIN}, {FAIXA_MAX}];
    const IS_MOBILE = window.matchMedia("(max-width: 639px)").matches;
    const COLORS = [
      "#60a5fa","#4ade80","#fb923c","#f472b6","#a78bfa","#facc15",
      "#22d3ee","#f87171","#34d399","#c084fc","#fdba74","#86efac"
    ];
    const chartsRendered = new Set();
    let statusChip = "";
    let chartObserver = null;

    const layoutBase = {{
      paper_bgcolor: "#0f172a",
      plot_bgcolor: "#0f172a",
      font: {{ color: "#e8eef5", size: IS_MOBILE ? 10 : 11 }},
      margin: {{ l: IS_MOBILE ? 36 : 44, r: IS_MOBILE ? 8 : 14, t: IS_MOBILE ? 24 : 32, b: IS_MOBILE ? 28 : 36 }},
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
        title: {{ text: "°C", font: {{ size: 11 }} }},
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

    function labelItem(s) {{
      return `Pedido ${{s.pedido}} · ${{s.uf}} · ${{s.logger}}`;
    }}

    function fmtTemp(v) {{
      return v == null ? "—" : v.toFixed(1) + "°C";
    }}

    function getFiltros() {{
      return {{
        pedido: document.getElementById("filtro-pedido").value,
        uf: document.getElementById("filtro-uf").value,
        status: statusChip,
        busca: document.getElementById("busca-grid").value.trim().toUpperCase(),
      }};
    }}

    function filtrarDados() {{
      const f = getFiltros();
      return DATA.filter(s => {{
        if (f.pedido && s.pedido !== f.pedido) return false;
        if (f.uf && s.uf !== f.uf) return false;
        if (f.status === "ok" && !conforme(s)) return false;
        if (f.status === "fora" && conforme(s)) return false;
        if (f.busca) {{
          const hay = `${{s.pedido}} ${{s.uf}} ${{s.logger}}`.toUpperCase();
          if (!hay.includes(f.busca)) return false;
        }}
        return true;
      }});
    }}

    function atualizarKpis(lista) {{
      const ok = lista.filter(conforme).length;
      const fora = lista.length - ok;
      const pct = lista.length ? Math.round(100 * ok / lista.length) : 0;
      const pedidos = new Set(lista.map(s => s.pedido)).size;
      const ufs = new Set(lista.map(s => s.uf)).size;
      document.getElementById("kpi-visiveis").textContent = lista.length;
      document.getElementById("kpi-ok").textContent = ok;
      document.getElementById("kpi-fora").textContent = fora;
      document.getElementById("kpi-pedidos").textContent = pedidos;
      document.getElementById("kpi-ufs").textContent = ufs;
      document.getElementById("kpi-pct").textContent = pct + "%";
      document.getElementById("bar-ok").style.width = pct + "%";
    }}

    function traceTemp(s, color) {{
      return {{
        x: s.serie.map(p => p.t),
        y: s.serie.map(p => p.temp),
        type: "scatter",
        mode: "lines",
        name: labelItem(s),
        line: {{ color, width: IS_MOBILE ? 1.8 : 2.2 }},
        hovertemplate: "%{{x}}<br>%{{y:.1f}}°C<extra></extra>",
      }};
    }}

    function miniLayout() {{
      return {{
        ...layoutBase,
        margin: {{ l: 32, r: 6, t: 8, b: 24 }},
        shapes: faixaShapes(),
      }};
    }}

    function detalheLayout(s) {{
      return {{
        ...layoutBase,
        title: {{
          text: `${{s.logger}} (${{s.pedido}} / ${{s.uf}})`,
          font: {{ size: IS_MOBILE ? 13 : 15 }},
        }},
        margin: {{ l: IS_MOBILE ? 40 : 50, r: 12, t: IS_MOBILE ? 40 : 48, b: IS_MOBILE ? 36 : 44 }},
        shapes: faixaShapes(),
      }};
    }}

    function chartId(s) {{
      return "mini-" + s.id.replace(/[^a-zA-Z0-9_-]/g, "_");
    }}

    function renderMiniChart(s) {{
      const cid = chartId(s);
      if (chartsRendered.has(cid)) return;
      const el = document.getElementById(cid);
      if (!el || el.dataset.loaded) return;
      el.dataset.loaded = "1";
      chartsRendered.add(cid);
      const loading = document.getElementById("load-" + cid);
      Plotly.newPlot(
        cid,
        [traceTemp(s, conforme(s) ? "#4ade80" : "#fb923c")],
        miniLayout(),
        {{ responsive: true, displayModeBar: false, staticPlot: IS_MOBILE }}
      ).then(() => {{
        if (loading) loading.classList.add("done");
      }});
    }}

    function setupLazyCharts(lista) {{
      if (chartObserver) chartObserver.disconnect();
      chartObserver = new IntersectionObserver(entries => {{
        entries.forEach(entry => {{
          if (!entry.isIntersecting) return;
          const card = entry.target;
          const id = card.dataset.id;
          const s = lista.find(d => d.id === id);
          if (s) renderMiniChart(s);
          chartObserver.unobserve(card);
        }});
      }}, {{ rootMargin: "120px" }});
      document.querySelectorAll(".card[data-id]").forEach(card => chartObserver.observe(card));
    }}

    function renderGrid() {{
      chartsRendered.clear();
      const lista = filtrarDados();
      atualizarKpis(lista);
      const grid = document.getElementById("grid-mini");
      grid.innerHTML = "";
      if (!lista.length) {{
        grid.innerHTML = '<div class="empty panel-card">Nenhum logger encontrado.<br>Tente outro filtro ou limpe a busca.</div>';
        return;
      }}
      lista.forEach(s => {{
        const ok = conforme(s);
        const cid = chartId(s);
        const card = document.createElement("article");
        card.className = "card";
        card.dataset.id = s.id;
        card.innerHTML = `
          <div class="card-head ${{ok ? "ok-head" : "warn-head"}}">
            <div>
              <div class="card-pedido">Pedido ${{s.pedido}}<span class="card-uf">${{s.uf}}</span></div>
              <div class="card-logger">${{s.logger}}</div>
              <div class="card-temps">Mín ${{fmtTemp(s.temp_min)}} · Máx ${{fmtTemp(s.temp_max)}}</div>
            </div>
            <span class="badge ${{ok ? "ok" : "warn"}}">${{ok ? "OK" : "FORA"}}</span>
          </div>
          <div class="card-meta">
            <span>${{s.pontos}} leituras${{s.cortado_entrega ? " · pós-entrega cortado" : ""}}</span>
            <span>${{s.inicio.slice(8,10)}}/${{s.inicio.slice(5,7)}} → ${{s.fim.slice(8,10)}}/${{s.fim.slice(5,7)}}</span>
          </div>
          <div class="chart-box">
            <div class="chart-loading" id="load-${{cid}}">Carregando gráfico…</div>
            <div class="mini-chart" id="${{cid}}"></div>
          </div>
        `;
        card.addEventListener("click", () => openDetalhe(s.id));
        grid.appendChild(card);
      }});
      setupLazyCharts(lista);
      lista.slice(0, IS_MOBILE ? 4 : 8).forEach(s => renderMiniChart(s));
    }}

    function switchTab(tab) {{
      document.querySelectorAll(".tab").forEach(t => t.classList.toggle("active", t.dataset.tab === tab));
      document.querySelectorAll(".bottom-nav button").forEach(b => b.classList.toggle("active", b.dataset.tab === tab));
      document.querySelectorAll(".panel").forEach(p => p.classList.remove("active"));
      document.getElementById("panel-" + tab).classList.add("active");
      window.scrollTo({{ top: 0, behavior: "smooth" }});
      if (tab === "detalhe") setTimeout(() => Plotly.Plots.resize("chart-detalhe"), 200);
      if (tab === "comparativo") setTimeout(() => Plotly.Plots.resize("chart-comparativo"), 200);
    }}

    function openDetalhe(id) {{
      switchTab("detalhe");
      document.getElementById("sel-detalhe").value = id;
      renderDetalhe(id);
    }}

    function renderDetalheInfo(s) {{
      const ok = conforme(s);
      document.getElementById("detalhe-info").innerHTML = `
        <div class="det-box"><div class="v">${{fmtTemp(s.temp_min)}}</div><div class="l">Mínima</div></div>
        <div class="det-box"><div class="v">${{fmtTemp(s.temp_max)}}</div><div class="l">Máxima</div></div>
        <div class="det-box"><div class="v" style="color:${{ok ? "var(--ok)" : "var(--warn)"}}">${{ok ? "OK" : "FORA"}}</div><div class="l">Status</div></div>
      `;
    }}

    function renderDetalhe(id) {{
      const s = DATA.find(d => d.id === id);
      if (!s) return;
      renderDetalheInfo(s);
      Plotly.newPlot(
        "chart-detalhe",
        [traceTemp(s, conforme(s) ? "#4ade80" : "#fb923c")],
        detalheLayout(s),
        {{ responsive: true, displayModeBar: !IS_MOBILE }}
      );
    }}

    function renderComparativo() {{
      const picked = [...document.querySelectorAll("#lista-comp input:checked")].map(el => el.value).slice(0, 6);
      if (!picked.length) {{
        Plotly.purge("chart-comparativo");
        return;
      }}
      const traces = picked.map((id, i) => {{
        const s = DATA.find(d => d.id === id);
        return traceTemp(s, COLORS[i % COLORS.length]);
      }});
      Plotly.newPlot("chart-comparativo", traces, {{
        ...layoutBase,
        title: {{ text: "Comparativo", font: {{ size: 14 }} }},
        margin: {{ l: IS_MOBILE ? 40 : 50, r: 12, t: 44, b: 40 }},
        shapes: faixaShapes(),
        showlegend: true,
        legend: {{ orientation: "h", y: IS_MOBILE ? -0.35 : 1.1, font: {{ size: 10 }} }},
      }}, {{ responsive: true, displayModeBar: !IS_MOBILE }});
    }}

    function popularFiltros() {{
      PEDIDOS.forEach(p => {{
        const opt = document.createElement("option");
        opt.value = p; opt.textContent = "Pedido " + p;
        document.getElementById("filtro-pedido").appendChild(opt);
      }});
      UFS.forEach(u => {{
        const opt = document.createElement("option");
        opt.value = u; opt.textContent = u;
        document.getElementById("filtro-uf").appendChild(opt);
      }});
    }}

    function popularDetalhe() {{
      const sel = document.getElementById("sel-detalhe");
      DATA.forEach(s => {{
        const opt = document.createElement("option");
        opt.value = s.id; opt.textContent = labelItem(s);
        sel.appendChild(opt);
      }});
      sel.addEventListener("change", () => renderDetalhe(sel.value));
    }}

    function popularComparativo() {{
      const lista = document.getElementById("lista-comp");
      DATA.forEach(s => {{
        const ok = conforme(s);
        const row = document.createElement("label");
        row.className = "logger-item";
        row.innerHTML = `
          <input type="checkbox" value="${{s.id}}">
          <span><strong>${{s.logger}}</strong><br><small style="color:var(--muted)">Pedido ${{s.pedido}} · ${{s.uf}}</small></span>
          <span class="st ${{ok ? "ok" : "warn"}}">${{ok ? "OK" : "FORA"}}</span>
        `;
        row.querySelector("input").addEventListener("change", ev => {{
          const n = document.querySelectorAll("#lista-comp input:checked").length;
          if (n > 6) {{
            ev.target.checked = false;
            alert("Selecione no máximo 6 loggers.");
            return;
          }}
          renderComparativo();
        }});
        lista.appendChild(row);
      }});
    }}

    document.querySelectorAll(".tab, .bottom-nav button").forEach(btn => {{
      btn.addEventListener("click", () => switchTab(btn.dataset.tab));
    }});

    document.querySelectorAll("#chips-status .chip").forEach(chip => {{
      chip.addEventListener("click", () => {{
        statusChip = chip.dataset.status;
        document.querySelectorAll("#chips-status .chip").forEach(c => c.classList.toggle("active", c === chip));
        renderGrid();
      }});
    }});

    document.getElementById("btn-filtros").addEventListener("click", () => {{
      const btn = document.getElementById("btn-filtros");
      const body = document.getElementById("filtros-body");
      btn.classList.toggle("open");
      body.classList.toggle("open");
    }});

    ["filtro-pedido", "filtro-uf"].forEach(id => {{
      document.getElementById(id).addEventListener("change", renderGrid);
    }});
    document.getElementById("busca-grid").addEventListener("input", renderGrid);
    document.getElementById("btn-limpar-filtros").addEventListener("click", () => {{
      document.getElementById("filtro-pedido").value = "";
      document.getElementById("filtro-uf").value = "";
      document.getElementById("busca-grid").value = "";
      statusChip = "";
      document.querySelectorAll("#chips-status .chip").forEach((c, i) => c.classList.toggle("active", i === 0));
      renderGrid();
    }});
    document.getElementById("btn-limpar").addEventListener("click", () => {{
      document.querySelectorAll("#lista-comp input").forEach(c => c.checked = false);
      Plotly.purge("chart-comparativo");
    }});

    popularFiltros();
    popularDetalhe();
    popularComparativo();
    renderGrid();
    if (DATA.length) renderDetalhe(DATA[0].id);
  </script>
</body>
</html>
"""


def main() -> int:
    series = carregar_series()
    if not series:
        print(f"Nenhum PDF encontrado em pastas Pedido_* em {PASTA}")
        return 1

    gerado_em = datetime.now().strftime("%d/%m/%Y %H:%M:%S")
    html = render_html(series, gerado_em)
    OUT_HTML.write_text(html, encoding="utf-8")

    pedidos = sorted({s["pedido"] for s in series})
    ok = contar_ok(series)
    cortados = [s for s in series if s.get("cortado_entrega")]
    print(f"Loggers: {len(series)}")
    print(f"Pedidos: {len(pedidos)} ({', '.join(pedidos)})")
    print(f"OK: {ok} | Fora: {len(series) - ok}")
    if cortados:
        print(f"Cortados pos-entrega: {len(cortados)}")
        for s in cortados:
            print(f"  {s['pedido']}/{s['uf']}/{s['logger']}: -{s['pontos_cortados']} pts (fim {s['fim']})")
    print(f"Arquivo: {OUT_HTML}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
