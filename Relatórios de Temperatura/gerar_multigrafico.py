"""Gera painel HTML de temperatura para todos os pedidos (pastas Pedido_*)."""
from __future__ import annotations

import json
import re
import statistics
import sys
from datetime import datetime, timedelta
from pathlib import Path

import fitz
import pandas as pd

PASTA = Path(__file__).resolve().parent
OUT_HTML = PASTA / "multigrafico_todos.html"
XLSX_BASE = PASTA / "Base.xlsx"
MANIFEST_INCLUSAO = PASTA / "_inclusao_manifest.json"
LOG_RENOMEACAO = PASTA / "_renomeacao_log.csv"
PAINEL_TITULO = "Temperatura VTCBOX — Painel Executivo"
PAINEL_BRAND = "VTCBOX · Caixa Nova"
PAINEL_H1 = "Painel de Temperatura"
PADRAO_PDF = re.compile(r"^(\d+)_([A-Z][A-Z0-9]+)_([A-Z]{2})(_\d+)?\.pdf$", re.I)
PAT_LOGGER = re.compile(r"Nome do dispositivo:\s*([A-Z][A-Z0-9]+)", re.I)
PAT_MIN = re.compile(r"Temperatura m[ií]nima:\s*([-\d.]+)", re.I)
PAT_MAX = re.compile(r"Temperatura m[aá]xima:\s*([-\d.]+)", re.I)
PAT_MEDIA = re.compile(r"Temperatura m[eé]dia:\s*([-\d.]+)", re.I)

FAIXA_MIN = 2.0
FAIXA_MAX = 8.0
SALTO_MIN_C = 2.0
JANELA_ESTAVEL = 20
CORTE_INICIO_HORAS = 3.0
CORTE_INICIO_MS: tuple[int, int] | None = None
CLIMATIZADO_MIN = 15.0
CLIMATIZADO_MAX = 30.0
IGNORADOS_CLIMATIZADO: list[dict[str, str]] = []
COLETA_PEDIDO: dict[str, str] = {
    "556135": "2026-06-10 21:31:00",
}


def aplicar_pasta(pasta: Path) -> None:
    global PASTA, OUT_HTML, XLSX_BASE, PAINEL_TITULO, PAINEL_BRAND, PAINEL_H1, CORTE_INICIO_MS
    global MANIFEST_INCLUSAO, LOG_RENOMEACAO
    PASTA = pasta.resolve()
    XLSX_BASE = PASTA / "Base.xlsx"
    MANIFEST_INCLUSAO = PASTA / "_inclusao_manifest.json"
    LOG_RENOMEACAO = PASTA / "_renomeacao_log.csv"
    if "130l" in pasta.name.lower():
        OUT_HTML = PASTA / "multigrafico_130l_normal.html"
        PAINEL_TITULO = "Caixa VTCBOX 130L Normal — Temperatura"
        PAINEL_BRAND = "VTCBOX · 130L Normal"
        PAINEL_H1 = "Painel Caixa 130L Normal"
        CORTE_INICIO_MS = None
    else:
        OUT_HTML = PASTA / "multigrafico_todos.html"
        PAINEL_TITULO = "Temperatura VTCBOX — Painel Executivo"
        PAINEL_BRAND = "VTCBOX · Caixa Nova"
        PAINEL_H1 = "Painel de Temperatura"
        CORTE_INICIO_MS = None


def _col(cols: dict[str, str], *partes: str) -> str | None:
    for parte in partes:
        hit = next((cols[k] for k in cols if parte in k), None)
        if hit:
            return hit
    return None


def _norm_logger(value) -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return ""
    s = str(value).strip().upper()
    return "" if s in {"", "NAN", "NONE"} else s


def _norm_pedido(value) -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return ""
    s = str(value).strip()
    if s.endswith(".0"):
        s = s[:-2]
    return s


def _norm_uf(value) -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return ""
    return str(value).strip().upper()


def _parse_data(value) -> str | None:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%d %H:%M:%S")
    dt = pd.to_datetime(value, dayfirst=True, errors="coerce")
    if pd.isna(dt):
        return None
    return dt.strftime("%Y-%m-%d %H:%M:%S")


def _norm_modal(value) -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return "Sem modal"
    s = str(value).strip()
    return s if s and s.upper() not in {"NAN", "NONE"} else "Sem modal"


def carregar_dataframe_base() -> pd.DataFrame | None:
    candidatos: list[Path] = []
    for nome in ("base3.xlsx", "base2.xlsx", "Base.xlsx", "Base.csv"):
        p = PASTA / nome
        if p.is_file():
            candidatos.append(p)
    if not candidatos:
        return None
    arquivo = max(candidatos, key=lambda p: p.stat().st_mtime)
    if arquivo.suffix.lower() == ".csv":
        for sep, enc in ((";", "latin-1"), (";", "utf-8-sig"), (",", "utf-8-sig")):
            try:
                return pd.read_csv(arquivo, sep=sep, encoding=enc)
            except Exception:
                continue
        return pd.read_csv(arquivo, sep=None, engine="python", encoding="latin-1")
    return pd.read_excel(arquivo)


def carregar_metadados_base() -> dict[tuple[str, str, str], dict[str, str | None]]:
    df = carregar_dataframe_base()
    if df is None:
        return {}
    cols = {str(c).strip().lower(): c for c in df.columns}
    pedido_col = _col(cols, "pedido")
    logger_col = _col(cols, "logger")
    uf_col = _col(cols, "uf")
    coleta_col = _col(cols, "coleta")
    entrega_col = _col(cols, "entrega")
    modal_col = _col(cols, "modal")
    lookup: dict[tuple[str, str, str], dict[str, str | None]] = {}
    for _, row in df.iterrows():
        pedido = _norm_pedido(row.get(pedido_col)) if pedido_col else ""
        logger = _norm_logger(row.get(logger_col)) if logger_col else ""
        uf = _norm_uf(row.get(uf_col)) if uf_col else ""
        if not pedido or not logger or not uf:
            continue
        lookup[(pedido, logger, uf)] = {
            "data_coleta": _parse_data(row.get(coleta_col)) if coleta_col else None,
            "data_entrega": _parse_data(row.get(entrega_col)) if entrega_col else None,
            "modal": _norm_modal(row.get(modal_col)) if modal_col else "Sem modal",
        }
    return lookup


def carregar_manifest_inclusao() -> dict[str, str]:
    if not MANIFEST_INCLUSAO.is_file():
        return {}
    try:
        return json.loads(MANIFEST_INCLUSAO.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def salvar_manifest_inclusao(manifest: dict[str, str]) -> None:
    MANIFEST_INCLUSAO.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def carregar_datas_renomeacao() -> dict[tuple[str, str, str], str]:
    if not LOG_RENOMEACAO.is_file():
        return {}
    try:
        df = pd.read_csv(LOG_RENOMEACAO, sep=";", encoding="utf-8-sig")
    except Exception:
        return {}
    cols = {str(c).strip().lower(): c for c in df.columns}
    pedido_col = _col(cols, "pedido")
    logger_col = _col(cols, "logger")
    uf_col = _col(cols, "uf")
    quando_col = _col(cols, "executado")
    status_col = _col(cols, "status")
    if not all([pedido_col, logger_col, uf_col, quando_col]):
        return {}
    datas: dict[tuple[str, str, str], str] = {}
    for _, row in df.iterrows():
        if status_col and str(row.get(status_col, "")).strip().lower() not in {"", "renomeado"}:
            continue
        pedido = _norm_pedido(row.get(pedido_col))
        logger = _norm_logger(row.get(logger_col))
        uf = _norm_uf(row.get(uf_col))
        quando = row.get(quando_col)
        if not pedido or not logger or not uf or pd.isna(quando):
            continue
        ts = _parse_data(quando) or str(quando).strip()
        chave = (pedido, logger, uf)
        if chave not in datas or ts < datas[chave]:
            datas[chave] = ts
    return datas


def data_candidata_inclusao(
    pdf: Path, pedido: str, logger: str, uf: str, log_datas: dict[tuple[str, str, str], str]
) -> str:
    ts = log_datas.get((pedido, logger, uf))
    if ts:
        return ts
    try:
        return datetime.fromtimestamp(pdf.stat().st_mtime).strftime("%Y-%m-%d %H:%M:%S")
    except OSError:
        return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def aplicar_manifest_inclusao(series: list[dict], candidatos: dict[str, str]) -> None:
    manifest = carregar_manifest_inclusao()
    agora = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    primeiro_manifest = not manifest

    for item in series:
        cid = item["id"]
        if primeiro_manifest:
            manifest[cid] = candidatos.get(cid, agora)
        elif cid not in manifest:
            manifest[cid] = agora
        item["data_inclusao"] = manifest[cid]

    salvar_manifest_inclusao(manifest)


def _chave_recente(item: dict) -> str:
    return item.get("data_coleta") or item.get("data_entrega") or item["fim"]


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


def cortar_inicio_horas(points: list[dict], horas: float = CORTE_INICIO_HORAS) -> tuple[list[dict], int]:
    """Descarta as primeiras horas do trajeto."""
    if not points or horas <= 0:
        return points, 0
    t0 = datetime.strptime(points[0]["t"], "%Y-%m-%d %H:%M:%S")
    limite = t0 + timedelta(hours=horas)
    filtrados = [
        p for p in points if datetime.strptime(p["t"], "%Y-%m-%d %H:%M:%S") >= limite
    ]
    return filtrados, len(points) - len(filtrados)


def cortar_inicio_desde_coleta(
    points: list[dict], coleta: str, horas: float = CORTE_INICIO_HORAS
) -> tuple[list[dict], int]:
    """Descarta leituras anteriores à coleta + horas de estabilização."""
    if not points or not coleta or horas <= 0:
        return points, 0
    inicio = datetime.strptime(coleta, "%Y-%m-%d %H:%M:%S")
    limite = inicio + timedelta(hours=horas)
    filtrados = [
        p for p in points if datetime.strptime(p["t"], "%Y-%m-%d %H:%M:%S") >= limite
    ]
    return filtrados, len(points) - len(filtrados)


def totalmente_climatizado(points: list[dict]) -> bool:
    """True se 100% das leituras ficaram na faixa ambiente/climatizada."""
    if not points:
        return False
    return all(CLIMATIZADO_MIN <= p["temp"] <= CLIMATIZADO_MAX for p in points)


def cortar_inicio_apos_horario(
    points: list[dict], hora: int, minuto: int
) -> tuple[list[dict], int]:
    """Descarta leituras anteriores ao horário no primeiro dia da série."""
    if not points:
        return points, 0
    primeiro = datetime.strptime(points[0]["t"], "%Y-%m-%d %H:%M:%S")
    limite = primeiro.replace(hour=hora, minute=minuto, second=0, microsecond=0)
    filtrados = [
        p for p in points if datetime.strptime(p["t"], "%Y-%m-%d %H:%M:%S") >= limite
    ]
    return filtrados, len(points) - len(filtrados)


def parse_pdf(
    pdf: Path, pedido: str, uf: str, coleta: str | None = None
) -> dict | None:
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
    if coleta:
        points, pontos_cortados_inicio = cortar_inicio_desde_coleta(points, coleta)
    else:
        points, pontos_cortados_inicio = cortar_inicio_horas(points)
    if len(points) < 2:
        return None

    points, pontos_cortados = cortar_pos_entrega(points)
    if len(points) < 2:
        return None

    if totalmente_climatizado(points):
        IGNORADOS_CLIMATIZADO.append(
            {"pedido": pedido, "uf": uf, "logger": logger, "arquivo": pdf.name}
        )
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
        "pontos_cortados_inicio": pontos_cortados_inicio,
        "cortado_entrega": pontos_cortados > 0,
        "cortado_inicio": pontos_cortados_inicio > 0,
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
    IGNORADOS_CLIMATIZADO.clear()
    metadados = carregar_metadados_base()
    log_datas = carregar_datas_renomeacao()
    candidatos: dict[str, str] = {}
    por_id: dict[str, dict] = {}
    for pdf, pedido, uf in coletar_pdfs():
        coleta_ref = COLETA_PEDIDO.get(pedido)
        item = parse_pdf(pdf, pedido, uf, coleta=coleta_ref)
        if not item:
            continue
        extra = metadados.get((pedido, item["logger"], uf), {})
        item["data_coleta"] = COLETA_PEDIDO.get(pedido) or extra.get("data_coleta")
        item["data_entrega"] = extra.get("data_entrega")
        item["modal"] = extra.get("modal") or "Sem modal"
        candidatos[item["id"]] = data_candidata_inclusao(
            pdf, pedido, item["logger"], uf, log_datas
        )
        key = item["id"]
        if key not in por_id or _prioridade_pdf(item) < _prioridade_pdf(por_id[key]):
            por_id[key] = item
    series = sorted(por_id.values(), key=_chave_recente, reverse=True)
    aplicar_manifest_inclusao(series, candidatos)
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
    pedidos = sorted(
        {s["pedido"] for s in series},
        key=lambda p: max(_chave_recente(s) for s in series if s["pedido"] == p),
        reverse=True,
    )
    ufs = sorted({s["uf"] for s in series})
    modais = sorted({s.get("modal") or "Sem modal" for s in series})
    pedidos_json = json.dumps(pedidos, ensure_ascii=False)
    ufs_json = json.dumps(ufs, ensure_ascii=False)
    modais_json = json.dumps(modais, ensure_ascii=False)
    n_pedidos = len(pedidos)
    n_ufs = len(ufs)
    n_loggers = len(series)
    n_ok = contar_ok(series)
    n_fora = n_loggers - n_ok
    pct_ok = round(100 * n_ok / n_loggers) if n_loggers else 0
    datas_coleta = sorted({s["data_coleta"][:10] for s in series if s.get("data_coleta")})
    coleta_min = datas_coleta[0] if datas_coleta else ""
    coleta_max = datas_coleta[-1] if datas_coleta else ""
    nota_corte = (
        f'<div class="faixa">Análise inicia após as {int(CORTE_INICIO_HORAS)} '
        f'primeiras horas do trajeto.</div>'
        f'<div class="faixa">Relatórios 100% climatizados ({CLIMATIZADO_MIN:g}°C a '
        f'{CLIMATIZADO_MAX:g}°C) são ignorados.</div>'
        f'<div class="faixa">Data de inclusão = primeira vez que o logger entrou no painel.</div>'
    )
    nota_ms = ""
    if CORTE_INICIO_MS:
        h, mi = CORTE_INICIO_MS
        nota_ms = (
            f'<div class="faixa">Pedidos MS: análise inicia após '
            f'{h:02d}:{mi:02d} do primeiro dia.</div>'
        )
    if COLETA_PEDIDO:
        pedidos_coleta = ", ".join(sorted(COLETA_PEDIDO))
        nota_ms += (
            f'<div class="faixa">Pedidos {pedidos_coleta}: análise inicia '
            f'{int(CORTE_INICIO_HORAS)}h após a data de coleta informada.</div>'
        )

    return f"""<!doctype html>
<html lang="pt-BR">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover" />
  <meta name="theme-color" content="#0b0f14" />
  <meta name="apple-mobile-web-app-capable" content="yes" />
  <title>{PAINEL_TITULO}</title>
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
    .modal-section {{
      background: var(--surface);
      border: 1px solid var(--line);
      border-radius: var(--radius);
      padding: 16px;
      margin-bottom: 14px;
      box-shadow: var(--shadow);
    }}
    .modal-section h2 {{
      margin: 0;
      font-size: .95rem;
      font-weight: 700;
    }}
    .modal-section-sub {{
      margin: 4px 0 16px;
      font-size: .75rem;
      color: var(--muted);
    }}
    .donut-grid {{
      display: flex;
      flex-wrap: wrap;
      gap: 14px;
      justify-content: center;
    }}
    .donut-empty {{
      width: 100%;
      color: var(--muted);
      font-size: .85rem;
      padding: 12px;
      text-align: center;
    }}
    .donut-card {{
      flex: 1 1 220px;
      max-width: 300px;
      background: linear-gradient(180deg, #131c2e 0%, var(--chart-bg) 100%);
      border: 1px solid var(--line);
      border-radius: 16px;
      padding: 18px 16px 14px;
      text-align: center;
      cursor: pointer;
      transition: transform .15s ease, border-color .15s ease, box-shadow .15s ease;
    }}
    .donut-card:hover {{
      transform: translateY(-2px);
      border-color: #334155;
    }}
    .donut-card.highlight {{
      border-color: var(--accent);
      box-shadow: 0 0 0 1px var(--accent), 0 10px 28px rgba(56, 189, 248, .14);
    }}
    .donut-card h4 {{
      margin: 0 0 14px;
      font-size: .88rem;
      font-weight: 700;
      color: var(--ink);
      line-height: 1.25;
      min-height: auto;
      letter-spacing: .02em;
    }}
    .donut-wrap {{
      display: flex;
      justify-content: center;
      margin-bottom: 14px;
    }}
    .donut-ring {{
      --pct: 0;
      --ok: #34d399;
      --fora: #fb923c;
      --track: #243044;
      width: 148px;
      height: 148px;
      border-radius: 50%;
      background: conic-gradient(
        var(--ok) 0deg calc(var(--pct) * 3.6deg),
        var(--fora) calc(var(--pct) * 3.6deg) 360deg
      );
      display: grid;
      place-items: center;
      box-shadow: 0 4px 18px rgba(0, 0, 0, .28), inset 0 0 0 1px rgba(255, 255, 255, .05);
      transition: background .35s ease;
    }}
    .donut-ring.empty {{
      background: var(--track);
    }}
    .donut-ring.perfect {{
      background: var(--ok);
    }}
    .donut-ring.zero {{
      background: var(--fora);
    }}
    .donut-hole {{
      width: 92px;
      height: 92px;
      border-radius: 50%;
      background: #0b1220;
      border: 1px solid rgba(255, 255, 255, .07);
      display: flex;
      flex-direction: column;
      align-items: center;
      justify-content: center;
      gap: 3px;
    }}
    .donut-pct {{
      font-size: 1.65rem;
      font-weight: 800;
      line-height: 1;
      color: var(--ink);
    }}
    .donut-pct small {{
      font-size: .82rem;
      font-weight: 700;
      opacity: .75;
    }}
    .donut-lbl {{
      font-size: .62rem;
      text-transform: uppercase;
      letter-spacing: .09em;
      color: var(--muted);
    }}
    .donut-stats {{
      display: flex;
      justify-content: center;
      gap: 18px;
      font-size: .8rem;
    }}
    .donut-stat {{
      display: inline-flex;
      align-items: center;
      gap: 7px;
      color: var(--muted);
    }}
    .donut-stat strong {{
      color: var(--ink);
      font-weight: 700;
    }}
    .dot {{
      width: 9px;
      height: 9px;
      border-radius: 50%;
      flex-shrink: 0;
    }}
    .dot.ok {{ background: #34d399; box-shadow: 0 0 8px rgba(52, 211, 153, .45); }}
    .dot.fora {{ background: #fb923c; box-shadow: 0 0 8px rgba(251, 146, 60, .4); }}
    .donut-total {{
      margin-top: 10px;
      font-size: .68rem;
      color: var(--muted);
    }}
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
    .field-full {{ grid-column: 1 / -1; }}
    .chips-excluir {{
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
      max-height: 160px;
      overflow-y: auto;
      padding: 2px 0;
    }}
    .chip-excluir {{
      min-height: 36px;
      padding: 6px 12px;
      border-radius: 999px;
      border: 1px solid var(--line);
      background: var(--surface);
      font-size: .8rem;
      font-weight: 600;
      color: var(--muted);
      cursor: pointer;
      transition: all .15s;
    }}
    .chip-excluir.active {{
      background: rgba(248, 113, 113, .15);
      border-color: #f87171;
      color: #fca5a5;
      text-decoration: line-through;
    }}
    .field label .hint {{
      font-weight: 500;
      text-transform: none;
      letter-spacing: 0;
      opacity: .85;
    }}
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
      grid-template-columns: repeat(auto-fit, minmax(120px, 1fr));
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
      .filtros-body {{ display: grid !important; grid-template-columns: repeat(3, 1fr); gap: 10px; }}
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
      <div class="brand">{PAINEL_BRAND}</div>
      <h1>{PAINEL_H1}</h1>
      <div class="sub">Atualizado em {gerado_em}</div>
    </div>
  </header>

  <div class="wrap">
    <div class="legenda">
      <strong>Como ler:</strong> cada card é um logger de temperatura de um pedido.
      <strong>OK</strong> = mínima e máxima dentro da faixa refrigerada.
      <strong>Fora</strong> = algum valor saiu da faixa.
      <div class="faixa">Faixa aceita: {FAIXA_MIN}°C a {FAIXA_MAX}°C</div>
      {nota_corte}
      {nota_ms}
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

    <div class="modal-section">
      <h2>Conformidade por modal</h2>
      <p class="modal-section-sub">Clique em um card para filtrar os loggers</p>
      <div class="donut-grid" id="donut-grid"></div>
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
            <label>Modal</label>
            <select id="filtro-modal"><option value="">Todos os modais</option></select>
          </div>
          <div class="field">
            <label>Coleta de</label>
            <input type="date" id="filtro-coleta-ini" min="{coleta_min}" max="{coleta_max}" />
          </div>
          <div class="field">
            <label>Coleta até</label>
            <input type="date" id="filtro-coleta-fim" min="{coleta_min}" max="{coleta_max}" />
          </div>
          <div class="field">
            <label>Buscar</label>
            <input type="search" id="busca-grid" placeholder="Pedido, UF ou logger..." enterkeyhint="search" />
          </div>
          <div class="field field-full">
            <label>Ignorar pedidos <span class="hint">(clique para ocultar do painel)</span></label>
            <div class="chips-excluir" id="chips-excluir-pedidos"></div>
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

    <div class="footer">Toque em um card para ver o gráfico completo · Ordenado do mais recente ao mais antigo</div>
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
    const MODAIS = {modais_json};
    const FAIXA = [{FAIXA_MIN}, {FAIXA_MAX}];
    const IS_MOBILE = window.matchMedia("(max-width: 639px)").matches;
    const COLORS = [
      "#60a5fa","#4ade80","#fb923c","#f472b6","#a78bfa","#facc15",
      "#22d3ee","#f87171","#34d399","#c084fc","#fdba74","#86efac"
    ];
    const chartsRendered = new Set();
    let statusChip = "";
    let chartObserver = null;
    const pedidosIgnorados = new Set();

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

    function diaColeta(s) {{
      if (!s.data_coleta) return "";
      return String(s.data_coleta).slice(0, 10);
    }}

    function fmtDataColeta(s) {{
      if (!s.data_coleta) return "—";
      const raw = String(s.data_coleta).trim();
      const [data, hora] = raw.split(/[ T]/);
      if (!data) return "—";
      const [y, m, day] = data.split("-");
      if (hora && hora.slice(0, 5) !== "00:00") {{
        return `${{day}}/${{m}}/${{y}} ${{hora.slice(0, 5)}}`;
      }}
      return `${{day}}/${{m}}/${{y}}`;
    }}

    function fmtDataInclusao(s) {{
      if (!s.data_inclusao) return "—";
      const raw = String(s.data_inclusao).replace(" ", "T");
      const dt = new Date(raw);
      if (Number.isNaN(dt.getTime())) return s.data_inclusao;
      return dt.toLocaleString("pt-BR", {{
        day: "2-digit", month: "2-digit", year: "numeric",
        hour: "2-digit", minute: "2-digit",
      }});
    }}

    function getFiltros() {{
      return {{
        pedido: document.getElementById("filtro-pedido").value,
        uf: document.getElementById("filtro-uf").value,
        modal: document.getElementById("filtro-modal").value,
        coletaIni: document.getElementById("filtro-coleta-ini").value,
        coletaFim: document.getElementById("filtro-coleta-fim").value,
        status: statusChip,
        busca: document.getElementById("busca-grid").value.trim().toUpperCase(),
      }};
    }}

    function chaveRecente(s) {{
      return s.data_coleta || s.data_entrega || s.fim;
    }}

    function filtrarDados() {{
      const f = getFiltros();
      return DATA.filter(s => {{
        if (pedidosIgnorados.has(s.pedido)) return false;
        if (f.pedido && s.pedido !== f.pedido) return false;
        if (f.uf && s.uf !== f.uf) return false;
        if (f.modal && (s.modal || "Sem modal") !== f.modal) return false;
        if (f.coletaIni || f.coletaFim) {{
          const dia = diaColeta(s);
          if (!dia) return false;
          if (f.coletaIni && dia < f.coletaIni) return false;
          if (f.coletaFim && dia > f.coletaFim) return false;
        }}
        if (f.status === "ok" && !conforme(s)) return false;
        if (f.status === "fora" && conforme(s)) return false;
        if (f.busca) {{
          const hay = `${{s.pedido}} ${{s.uf}} ${{s.logger}}`.toUpperCase();
          if (!hay.includes(f.busca)) return false;
        }}
        return true;
      }}).sort((a, b) => chaveRecente(b).localeCompare(chaveRecente(a)));
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

    function renderDonutsModal(lista) {{
      const grid = document.getElementById("donut-grid");
      const filtroModal = document.getElementById("filtro-modal").value;
      const porModal = new Map();
      lista.forEach(s => {{
        const m = s.modal || "Sem modal";
        if (!porModal.has(m)) porModal.set(m, {{ ok: 0, fora: 0 }});
        const bucket = porModal.get(m);
        if (conforme(s)) bucket.ok++; else bucket.fora++;
      }});
      const modais = [...porModal.keys()].sort((a, b) => a.localeCompare(b, "pt-BR"));
      grid.innerHTML = "";
      if (!modais.length) {{
        grid.innerHTML = '<div class="donut-empty">Sem dados para exibir.</div>';
        return;
      }}
      modais.forEach(modal => {{
        const {{ ok, fora }} = porModal.get(modal);
        const total = ok + fora;
        const pct = total ? Math.round(100 * ok / total) : 0;
        const ringClass = !total ? " empty" : pct >= 100 ? " perfect" : pct <= 0 ? " zero" : "";
        const card = document.createElement("div");
        card.className = "donut-card" + (filtroModal === modal ? " highlight" : "");
        card.title = "Filtrar por " + modal;
        card.innerHTML = `
          <h4>${{modal}}</h4>
          <div class="donut-wrap">
            <div class="donut-ring${{ringClass}}" style="--pct:${{pct}}">
              <div class="donut-hole">
                <div class="donut-pct">${{total ? pct : "—"}}${{total ? "<small>%</small>" : ""}}</div>
                <div class="donut-lbl">conformidade</div>
              </div>
            </div>
          </div>
          <div class="donut-stats">
            <span class="donut-stat"><span class="dot ok"></span><strong>${{ok}}</strong> OK</span>
            <span class="donut-stat"><span class="dot fora"></span><strong>${{fora}}</strong> Fora</span>
          </div>
          <div class="donut-total">${{total}} logger${{total !== 1 ? "s" : ""}}</div>
        `;
        card.addEventListener("click", () => {{
          document.getElementById("filtro-modal").value = filtroModal === modal ? "" : modal;
          renderGrid();
        }});
        grid.appendChild(card);
      }});
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
      renderDonutsModal(lista);
      atualizarDetalheSelect(lista);
      atualizarComparativoVisivel();
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
              <div class="card-temps">${{s.modal || "Sem modal"}} · Coleta ${{fmtDataColeta(s)}} · Incluído ${{fmtDataInclusao(s)}}</div>
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
        <div class="det-box"><div class="v" style="font-size:1rem">${{fmtDataInclusao(s)}}</div><div class="l">Incluído no painel</div></div>
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
      MODAIS.forEach(m => {{
        const opt = document.createElement("option");
        opt.value = m; opt.textContent = m;
        document.getElementById("filtro-modal").appendChild(opt);
      }});
      const box = document.getElementById("chips-excluir-pedidos");
      PEDIDOS.forEach(p => {{
        const btn = document.createElement("button");
        btn.type = "button";
        btn.className = "chip-excluir";
        btn.dataset.pedido = p;
        btn.textContent = p;
        btn.title = "Ignorar pedido " + p;
        btn.addEventListener("click", () => {{
          if (pedidosIgnorados.has(p)) {{
            pedidosIgnorados.delete(p);
            btn.classList.remove("active");
          }} else {{
            pedidosIgnorados.add(p);
            btn.classList.add("active");
          }}
          renderGrid();
        }});
        box.appendChild(btn);
      }});
    }}

    function atualizarDetalheSelect(lista) {{
      const sel = document.getElementById("sel-detalhe");
      const atual = sel.value;
      sel.innerHTML = "";
      lista.forEach(s => {{
        const opt = document.createElement("option");
        opt.value = s.id;
        opt.textContent = labelItem(s);
        sel.appendChild(opt);
      }});
      if (lista.some(s => s.id === atual)) {{
        sel.value = atual;
      }} else if (lista.length) {{
        sel.value = lista[0].id;
        renderDetalhe(lista[0].id);
      }} else {{
        Plotly.purge("chart-detalhe");
        document.getElementById("detalhe-info").innerHTML = "";
      }}
    }}

    function popularDetalhe() {{
      const sel = document.getElementById("sel-detalhe");
      sel.addEventListener("change", () => renderDetalhe(sel.value));
    }}

    function popularComparativo() {{
      const lista = document.getElementById("lista-comp");
      DATA.forEach(s => {{
        const ok = conforme(s);
        const row = document.createElement("label");
        row.className = "logger-item";
        row.dataset.pedido = s.pedido;
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

    function atualizarComparativoVisivel() {{
      document.querySelectorAll("#lista-comp .logger-item").forEach(row => {{
        const hide = pedidosIgnorados.has(row.dataset.pedido);
        row.style.display = hide ? "none" : "";
        if (hide) row.querySelector("input").checked = false;
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

    ["filtro-pedido", "filtro-uf", "filtro-modal", "filtro-coleta-ini", "filtro-coleta-fim"].forEach(id => {{
      document.getElementById(id).addEventListener("change", renderGrid);
    }});
    document.getElementById("busca-grid").addEventListener("input", renderGrid);
    document.getElementById("btn-limpar-filtros").addEventListener("click", () => {{
      document.getElementById("filtro-pedido").value = "";
      document.getElementById("filtro-uf").value = "";
      document.getElementById("filtro-modal").value = "";
      document.getElementById("filtro-coleta-ini").value = "";
      document.getElementById("filtro-coleta-fim").value = "";
      document.getElementById("busca-grid").value = "";
      pedidosIgnorados.clear();
      document.querySelectorAll(".chip-excluir").forEach(c => c.classList.remove("active"));
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
    if (filtrarDados().length) renderDetalhe(filtrarDados()[0].id);
  </script>
</body>
</html>
"""


def main() -> int:
    for arg in sys.argv[1:]:
        p = Path(arg)
        if p.is_dir():
            aplicar_pasta(p)
            break

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
    cortados_inicio = [s for s in series if s.get("cortado_inicio")]
    print(f"Loggers: {len(series)}")
    print(f"Pedidos: {len(pedidos)} ({', '.join(pedidos)})")
    print(f"OK: {ok} | Fora: {len(series) - ok}")
    if cortados_inicio:
        print(f"Cortados inicio ({int(CORTE_INICIO_HORAS)}h): {len(cortados_inicio)}")
    if IGNORADOS_CLIMATIZADO:
        print(f"Ignorados 100% climatizados ({CLIMATIZADO_MIN:g}-{CLIMATIZADO_MAX:g}C): {len(IGNORADOS_CLIMATIZADO)}")
        for s in IGNORADOS_CLIMATIZADO:
            print(f"  {s['pedido']}/{s['uf']}/{s['logger']}")
    if cortados:
        print(f"Cortados pos-entrega: {len(cortados)}")
        for s in cortados:
            print(f"  {s['pedido']}/{s['uf']}/{s['logger']}: -{s['pontos_cortados']} pts (fim {s['fim']})")
    print(f"Arquivo: {OUT_HTML}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
