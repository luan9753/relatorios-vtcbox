# Gera indicador.html com dados atualizados do Aura (ODBC AuraVTC)
$ErrorActionPreference = 'Stop'
$embFilter = "ds_tipo ILIKE '%VTCBOX 130L WEDGE SEAL%'"
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$outHtml = Join-Path $here 'indicador.html'

$conn = New-Object System.Data.Odbc.OdbcConnection('DSN=AuraVTC')
$conn.Open()
$cmd = $conn.CreateCommand()
$cmd.CommandText = @"
WITH base AS (
  SELECT nr_pedido, nullif(btrim(cd_uf), '') AS uf, cd_lpn, dt_entregaefetiva,
         dt_coletaefetiva AT TIME ZONE 'America/Sao_Paulo' AS coleta
  FROM vtc_stage.documentos
  WHERE $embFilter AND cd_lpn IS NOT NULL AND btrim(cd_lpn) <> ''
),
por_lpn AS (
  SELECT DISTINCT ON (nr_pedido, cd_lpn)
    nr_pedido, uf, cd_lpn, (dt_entregaefetiva IS NOT NULL) AS entregue, coleta
  FROM base ORDER BY nr_pedido, cd_lpn, dt_entregaefetiva DESC NULLS LAST
),
por_pedido AS (
  SELECT nr_pedido, uf,
    count(*) AS lpns,
    count(*) FILTER (WHERE entregue) AS lpns_entregues,
    count(*) FILTER (WHERE NOT entregue) AS lpns_em_rota,
    min(coleta) AS primeira_coleta,
    max(coleta) AS ultima_coleta,
    CASE WHEN bool_and(entregue) THEN 'ENTREGUE' ELSE 'EM ROTA' END AS status
  FROM por_lpn GROUP BY nr_pedido, uf
)
SELECT * FROM por_pedido ORDER BY uf, lpns DESC, nr_pedido
"@
$r = $cmd.ExecuteReader()
$rows = @()
while ($r.Read()) {
  $rows += [PSCustomObject]@{
    pedido            = [string]$r['nr_pedido']
    uf                = [string]$r['uf']
    lpns              = [int]$r['lpns']
    lpns_entregues    = [int]$r['lpns_entregues']
    lpns_em_rota      = [int]$r['lpns_em_rota']
    status            = [string]$r['status']
    primeira_coleta   = if ($r['primeira_coleta'] -is [DBNull]) { $null } else { $r['primeira_coleta'].ToString('dd/MM/yyyy HH:mm') }
    ultima_coleta     = if ($r['ultima_coleta'] -is [DBNull]) { $null } else { $r['ultima_coleta'].ToString('dd/MM/yyyy HH:mm') }
  }
}
$r.Close()
$conn.Close()

$entregues = @($rows | Where-Object status -eq 'ENTREGUE')
$emRota = @($rows | Where-Object status -eq 'EM ROTA')
$agora = Get-Date -Format 'dd/MM/yyyy HH:mm:ss'

$porUf = $rows | Group-Object uf | Sort-Object Name | ForEach-Object {
  [PSCustomObject]@{
    uf                = $_.Name
    pedidos           = $_.Count
    pedidos_entregues = @($_.Group | Where-Object status -eq 'ENTREGUE').Count
    pedidos_em_rota   = @($_.Group | Where-Object status -eq 'EM ROTA').Count
    lpns              = ($_.Group | Measure-Object -Property lpns -Sum).Sum
  }
}

$payload = [PSCustomObject]@{
  meta = [PSCustomObject]@{
    titulo        = 'Indicador VTCBOX 130L'
    embalagem     = [string][char]0x0043 + 'AIXA VTCBOX 130L WEDGE SEAL COM BER' + [char]0x00C7 + 'O'
    atualizado_em = $agora
    fonte         = 'vtc_stage.documentos (Aura)'
  }
  resumo = [PSCustomObject]@{
    pedidos_total     = $rows.Count
    pedidos_entregues = $entregues.Count
    pedidos_em_rota   = $emRota.Count
    lpns_total        = ($rows | Measure-Object -Property lpns -Sum).Sum
    lpns_entregues    = ($entregues | Measure-Object -Property lpns -Sum).Sum
    lpns_em_rota      = ($emRota | Measure-Object -Property lpns -Sum).Sum
    ufs               = @($rows.uf | Sort-Object -Unique).Count
  }
  por_uf    = $porUf
  entregues = $entregues
  em_rota   = $emRota
}

$dataJson = ($payload | ConvertTo-Json -Depth 6 -Compress) -replace '</', '<\/'

$html = @"
<!doctype html>
<html lang="pt-BR">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Indicador VTCBOX 130L</title>
  <style>
    :root {
      --bg: #0b0f14;
      --card: #141b24;
      --card-hover: #1a2430;
      --ink: #e8eef5;
      --muted: #8fa3bc;
      --line: #243044;
      --blue: #60a5fa;
      --green: #4ade80;
      --green-bg: #14532d;
      --green-head: #166534;
      --orange: #fb923c;
      --orange-bg: #7c2d12;
      --orange-head: #9a3412;
      --shadow: 0 12px 40px rgba(0, 0, 0, 0.45);
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      font-family: "Segoe UI", system-ui, sans-serif;
      background: var(--bg);
      color: var(--ink);
      line-height: 1.45;
    }
    .wrap { max-width: 1280px; margin: 0 auto; padding: 20px; }
    .hero {
      background: linear-gradient(135deg, #0f2744 0%, #1e3a5f 45%, #0c4a6e 100%);
      color: #fff;
      border-radius: 18px;
      padding: 28px 30px;
      box-shadow: var(--shadow);
      border: 1px solid #2d4a6f;
      margin-bottom: 22px;
    }
    .hero h1 { margin: 0 0 8px; font-size: 2rem; font-weight: 800; letter-spacing: -0.02em; }
    .hero .sub { opacity: 0.92; font-size: 1rem; }
    .hero .meta { margin-top: 14px; font-size: 0.9rem; opacity: 0.85; }
    .kpis {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
      gap: 16px;
      margin-bottom: 22px;
    }
    .kpi {
      background: var(--card);
      border-radius: 16px;
      padding: 22px 20px;
      box-shadow: var(--shadow);
      border: 1px solid var(--line);
    }
    .kpi .lbl {
      font-size: 0.78rem;
      font-weight: 700;
      text-transform: uppercase;
      letter-spacing: 0.06em;
      color: var(--muted);
    }
    .kpi .val {
      font-size: 2.6rem;
      font-weight: 800;
      line-height: 1.1;
      margin-top: 8px;
      letter-spacing: -0.03em;
    }
    .kpi .hint { font-size: 0.88rem; color: var(--muted); margin-top: 6px; }
    .kpi.ok .val { color: var(--green); }
    .kpi.warn .val { color: var(--orange); }
    .kpi.blue .val { color: var(--blue); }
    .progress-block {
      background: var(--card);
      border-radius: 16px;
      padding: 22px 24px;
      box-shadow: var(--shadow);
      border: 1px solid var(--line);
      margin-bottom: 22px;
    }
    .progress-block h2 { margin: 0 0 16px; font-size: 1.1rem; color: var(--ink); }
    .bar-row { margin-bottom: 14px; }
    .bar-label {
      display: flex;
      justify-content: space-between;
      font-size: 0.92rem;
      font-weight: 600;
      margin-bottom: 6px;
    }
    .bar-track {
      height: 22px;
      background: #1e293b;
      border-radius: 999px;
      overflow: hidden;
      display: flex;
      border: 1px solid var(--line);
    }
    .bar-fill-green { background: var(--green); height: 100%; }
    .bar-fill-orange { background: var(--orange); height: 100%; }
    .split {
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 18px;
      margin-bottom: 22px;
    }
    @media (max-width: 900px) { .split { grid-template-columns: 1fr; } }
    .panel {
      background: var(--card);
      border-radius: 16px;
      box-shadow: var(--shadow);
      border: 1px solid var(--line);
      overflow: hidden;
    }
    .panel-head {
      padding: 16px 20px;
      font-size: 1.15rem;
      font-weight: 800;
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 10px;
    }
    .panel-head.ok { background: var(--green-head); color: #dcfce7; }
    .panel-head.warn { background: var(--orange-head); color: #ffedd5; }
    .panel-head.uf { background: #1e3a5f; color: #bfdbfe; }
    .badge {
      font-size: 0.85rem;
      font-weight: 700;
      padding: 4px 12px;
      border-radius: 999px;
      background: rgba(0,0,0,0.35);
      color: #fff;
    }
    table { width: 100%; border-collapse: collapse; font-size: 0.92rem; }
    th, td { padding: 11px 16px; text-align: left; border-bottom: 1px solid var(--line); }
    th {
      background: #0f172a;
      font-size: 0.75rem;
      text-transform: uppercase;
      letter-spacing: 0.05em;
      color: var(--muted);
      position: sticky;
      top: 0;
    }
    tr:hover td { background: var(--card-hover); }
    .table-wrap { max-height: 480px; overflow: auto; }
    .uf-grid {
      display: grid;
      grid-template-columns: repeat(auto-fill, minmax(140px, 1fr));
      gap: 12px;
      padding: 16px;
    }
    .uf-card {
      border: 1px solid var(--line);
      border-radius: 12px;
      padding: 14px;
      text-align: center;
      background: #0f172a;
    }
    .uf-card .uf { font-size: 1.4rem; font-weight: 800; color: var(--ink); }
    .uf-card .nums { font-size: 0.82rem; color: var(--muted); margin-top: 6px; }
    .uf-card .nums strong { color: var(--ink); }
    .uf-card .ent { color: var(--green); }
    .uf-card .rota { color: var(--orange); }
    .toolbar {
      display: flex;
      flex-wrap: wrap;
      gap: 10px;
      margin-bottom: 18px;
    }
    .toolbar input {
      flex: 1;
      min-width: 220px;
      padding: 12px 16px;
      border: 1px solid var(--line);
      border-radius: 10px;
      font-size: 1rem;
      background: var(--card);
      color: var(--ink);
    }
    .toolbar input::placeholder { color: var(--muted); }
    .footer { text-align: center; color: var(--muted); font-size: 0.82rem; padding: 20px 0 8px; }
  </style>
</head>
<body>
  <div class="wrap">
    <header class="hero">
      <h1 id="titulo">Indicador VTCBOX 130L</h1>
      <div class="sub" id="embalagem"></div>
      <div class="meta">Atualizado: <strong id="atualizado"></strong> · Fonte: <span id="fonte"></span></div>
    </header>

    <section class="kpis" id="kpis"></section>

    <section class="progress-block">
      <h2>Progresso geral</h2>
      <div class="bar-row">
        <div class="bar-label"><span>Pedidos entregues</span><span id="pct-ped"></span></div>
        <div class="bar-track"><div class="bar-fill-green" id="bar-ped-ok"></div><div class="bar-fill-orange" id="bar-ped-rota"></div></div>
      </div>
      <div class="bar-row">
        <div class="bar-label"><span>LPNs entregues</span><span id="pct-lpn"></span></div>
        <div class="bar-track"><div class="bar-fill-green" id="bar-lpn-ok"></div><div class="bar-fill-orange" id="bar-lpn-rota"></div></div>
      </div>
    </section>

    <section class="panel" style="margin-bottom:22px">
      <div class="panel-head uf">Resumo por UF</div>
      <div class="uf-grid" id="uf-grid"></div>
    </section>

    <div class="toolbar">
      <input type="search" id="busca" placeholder="Buscar pedido ou UF..." />
    </div>

    <section class="split">
      <div class="panel">
        <div class="panel-head ok">ENTREGUES <span class="badge" id="cnt-ent"></span></div>
        <div class="table-wrap">
          <table>
            <thead><tr><th>UF</th><th>Pedido</th><th>LPNs</th><th>Coleta</th></tr></thead>
            <tbody id="tb-ent"></tbody>
          </table>
        </div>
      </div>
      <div class="panel">
        <div class="panel-head warn">EM ROTA <span class="badge" id="cnt-rota"></span></div>
        <div class="table-wrap">
          <table>
            <thead><tr><th>UF</th><th>Pedido</th><th>LPNs</th><th>Coleta</th></tr></thead>
            <tbody id="tb-rota"></tbody>
          </table>
        </div>
      </div>
    </section>

    <div class="footer">1 volume = 1 LPN distinta · Entregue = data de entrega preenchida</div>
  </div>
  <script>
    const DATA = $dataJson;

    function pct(a, b) { return b ? Math.round((a / b) * 100) : 0; }

    function renderRow(r) {
      return '<tr data-q="' + (r.uf + ' ' + r.pedido).toLowerCase() + '">' +
        '<td><strong>' + r.uf + '</strong></td>' +
        '<td>' + r.pedido + '</td>' +
        '<td><strong>' + r.lpns + '</strong></td>' +
        '<td>' + (r.primeira_coleta || '—') + '</td></tr>';
    }

    function render() {
      const m = DATA.meta, s = DATA.resumo;
      document.getElementById('titulo').textContent = m.titulo;
      document.getElementById('embalagem').textContent = m.embalagem;
      document.getElementById('atualizado').textContent = m.atualizado_em;
      document.getElementById('fonte').textContent = m.fonte;

      document.getElementById('kpis').innerHTML = [
        { cls: 'blue', lbl: 'Total de pedidos', val: s.pedidos_total, hint: s.ufs + ' UFs' },
        { cls: 'ok', lbl: 'Pedidos entregues', val: s.pedidos_entregues, hint: s.lpns_entregues + ' LPNs' },
        { cls: 'warn', lbl: 'Pedidos em rota', val: s.pedidos_em_rota, hint: s.lpns_em_rota + ' LPNs' },
        { cls: 'blue', lbl: 'Total de LPNs', val: s.lpns_total, hint: 'volumes distintos' },
      ].map(k => '<div class="kpi ' + k.cls + '"><div class="lbl">' + k.lbl + '</div><div class="val">' + k.val + '</div><div class="hint">' + k.hint + '</div></div>').join('');

      const pp = pct(s.pedidos_entregues, s.pedidos_total);
      const pl = pct(s.lpns_entregues, s.lpns_total);
      document.getElementById('pct-ped').textContent = s.pedidos_entregues + ' de ' + s.pedidos_total + ' (' + pp + '%)';
      document.getElementById('pct-lpn').textContent = s.lpns_entregues + ' de ' + s.lpns_total + ' (' + pl + '%)';
      document.getElementById('bar-ped-ok').style.width = pp + '%';
      document.getElementById('bar-ped-rota').style.width = (100 - pp) + '%';
      document.getElementById('bar-lpn-ok').style.width = pl + '%';
      document.getElementById('bar-lpn-rota').style.width = (100 - pl) + '%';

      document.getElementById('uf-grid').innerHTML = DATA.por_uf.map(u =>
        '<div class="uf-card"><div class="uf">' + u.uf + '</div><div class="nums">' +
        '<strong>' + u.pedidos + '</strong> pedidos<br>' +
        '<span class="ent">' + u.pedidos_entregues + ' ent</span> · ' +
        '<span class="rota">' + u.pedidos_em_rota + ' rota</span><br>' +
        u.lpns + ' LPNs</div></div>'
      ).join('');

      document.getElementById('cnt-ent').textContent = DATA.entregues.length + ' pedidos';
      document.getElementById('cnt-rota').textContent = DATA.em_rota.length + ' pedidos';
      document.getElementById('tb-ent').innerHTML = DATA.entregues.map(renderRow).join('');
      document.getElementById('tb-rota').innerHTML = DATA.em_rota.map(renderRow).join('');
    }

    document.getElementById('busca').addEventListener('input', function () {
      const q = this.value.trim().toLowerCase();
      document.querySelectorAll('#tb-ent tr, #tb-rota tr').forEach(tr => {
        tr.style.display = !q || tr.dataset.q.includes(q) ? '' : 'none';
      });
    });

    render();
  </script>
</body>
</html>
"@

[System.IO.File]::WriteAllText($outHtml, $html, [System.Text.UTF8Encoding]::new($false))
Write-Host "Gerado: $outHtml"
Write-Host "Pedidos: $($rows.Count) | Entregues: $($entregues.Count) | Em rota: $($emRota.Count)"
