"""Renomeia PDFs: {pedido}_{logger}_{uf}.pdf"""
from __future__ import annotations

import csv
import re
import sys
from datetime import datetime
from pathlib import Path

import fitz

PASTA = Path(__file__).resolve().parent
LOG = PASTA / "_renomeacao_log.csv"
PAT_LOGGER = re.compile(r"Nome do dispositivo:\s*([A-Z][A-Z0-9]+)", re.I)
PAT_JA = re.compile(r"^\d+_[A-Z][A-Z0-9]+_[A-Z]{2}(_\d+)?\.pdf$", re.I)

# Pedido SC VTCBOX (banco em 08/06/2026)
PEDIDO_PADRAO = "556160"
UF_PADRAO = "SC"
LOGGER_PEDIDO_UF: dict[str, tuple[str, str]] = {}


def carregar_lookup_odbc() -> None:
    try:
        import pyodbc
    except ImportError:
        return

    sql = """
    SELECT DISTINCT nullif(btrim(cd_referencia), '') AS logger, nr_pedido, cd_uf
    FROM vtc_stage.documentos
    WHERE nr_pedido = ?
      AND cd_referencia IS NOT NULL
      AND btrim(cd_referencia) <> ''
    """
    try:
        with pyodbc.connect("DSN=AuraVTC", timeout=30) as conn:
            cur = conn.cursor()
            cur.execute(sql, (PEDIDO_PADRAO,))
            for logger, pedido, uf in cur.fetchall():
                if logger:
                    LOGGER_PEDIDO_UF[str(logger).strip().upper()] = (
                        str(pedido).strip(),
                        str(uf).strip().upper(),
                    )
    except Exception as exc:
        print(f"Aviso: lookup ODBC falhou ({exc}). Usando pedido/UF padrao.")


def extrair_logger(pdf: Path) -> str:
    doc = fitz.open(pdf)
    try:
        text = "".join(page.get_text() for page in doc)
    finally:
        doc.close()
    m = PAT_LOGGER.search(text)
    return m.group(1).upper() if m else ""


def nome_destino(pedido: str, logger: str, uf: str, reservados: set[str]) -> str:
    logger_part = logger or "SEM_LOGGER"
    base = f"{pedido}_{logger_part}_{uf}.pdf"
    if base not in reservados:
        reservados.add(base)
        return base
    n = 2
    while True:
        cand = f"{pedido}_{logger_part}_{uf}_{n}.pdf"
        if cand not in reservados:
            reservados.add(cand)
            return cand
        n += 1


def main() -> int:
    carregar_lookup_odbc()

    pdfs = sorted(
        p
        for p in PASTA.glob("*.pdf")
        if not p.name.startswith("_") and not PAT_JA.match(p.name)
    )
    if not pdfs:
        print("Nenhum PDF pendente para renomear.")
        return 0

    reservados = {p.name for p in PASTA.glob("*.pdf")}
    rows: list[dict] = []
    agora = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    print(f"Pasta: {PASTA}")
    print(f"PDFs pendentes: {len(pdfs)}\n")

    for pdf in pdfs:
        original = pdf.name
        logger = extrair_logger(pdf)
        if logger and logger in LOGGER_PEDIDO_UF:
            pedido, uf = LOGGER_PEDIDO_UF[logger]
        elif logger:
            pedido, uf = PEDIDO_PADRAO, UF_PADRAO
        else:
            pedido, uf = PEDIDO_PADRAO, "SEM_LOGGER" if not logger else UF_PADRAO

        dest_name = nome_destino(pedido, logger, uf, reservados)
        dest = PASTA / dest_name

        if dest.exists() and dest.resolve() != pdf.resolve():
            status = "erro_destino_existe"
        elif pdf.name == dest_name:
            status = "ja_nomeado"
        else:
            pdf.rename(dest)
            status = "renomeado"

        rows.append(
            {
                "executado_em": agora,
                "arquivo_original": original,
                "arquivo_novo": dest_name,
                "logger": logger,
                "pedido": pedido,
                "uf": uf,
                "status": status,
            }
        )
        print(f"{original} -> {dest_name} [{status}]")

    if rows:
        write_header = not LOG.exists()
        with LOG.open("a", newline="", encoding="utf-8-sig") as f:
            w = csv.DictWriter(f, fieldnames=list(rows[0].keys()), delimiter=";")
            if write_header:
                w.writeheader()
            w.writerows(rows)

    renomeados = sum(1 for r in rows if r["status"] == "renomeado")
    print(f"\nRenomeados: {renomeados}/{len(rows)}")
    print(f"Log: {LOG}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
