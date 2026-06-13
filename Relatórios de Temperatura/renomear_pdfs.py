"""Renomeia PDFs soltos: {pedido}_{logger}_{uf}.pdf em Pedido_{pedido}_{uf}/"""
from __future__ import annotations

import csv
import re
import sys
from datetime import datetime
from pathlib import Path

import fitz
import pandas as pd


def _resolve_pasta() -> Path:
    for arg in sys.argv[1:]:
        p = Path(arg)
        if p.is_dir():
            return p.resolve()
    return Path(__file__).resolve().parent


PASTA = _resolve_pasta()
XLSX_PADRAO = PASTA / "Base.xlsx"
LOG = PASTA / "_renomeacao_log.csv"
PAT_LOGGER = re.compile(r"Nome do dispositivo:\s*([A-Z][A-Z0-9]+)", re.I)
PAT_JA = re.compile(r"^\d+_[A-Z][A-Z0-9]+_[A-Z]{2}(_\d+)?\.pdf$", re.I)


def norm_logger(value) -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return ""
    s = str(value).strip().upper()
    return "" if s in {"", "NAN", "NONE"} else s


def find_xlsx() -> Path | None:
    for arg in sys.argv[1:]:
        p = Path(arg)
        if p.is_file() and p.suffix.lower() in {".xlsx", ".csv"}:
            return p
    candidatos = [
        PASTA / nome
        for nome in ("base3.xlsx", "base2.xlsx", "Base.xlsx", "base.xlsx", "Base.csv")
        if (PASTA / nome).is_file()
    ]
    if not candidatos:
        return None
    return max(candidatos, key=lambda p: p.stat().st_mtime)


def _ler_base(base: Path) -> pd.DataFrame:
    if base.suffix.lower() == ".csv":
        for sep, enc in ((";", "latin-1"), (";", "utf-8-sig"), (",", "utf-8-sig")):
            try:
                return pd.read_csv(base, sep=sep, encoding=enc)
            except Exception:
                continue
        return pd.read_csv(base, sep=None, engine="python", encoding="latin-1")
    xl = pd.ExcelFile(base)
    sheet = "com_lpn" if "com_lpn" in xl.sheet_names else xl.sheet_names[0]
    return pd.read_excel(base, sheet_name=sheet)


def load_lookup(xlsx: Path) -> dict[str, tuple[str, str]]:
    df = _ler_base(xlsx)
    cols = {str(c).strip().lower(): c for c in df.columns}
    pedido_col = next((cols[k] for k in cols if "pedido" in k), cols.get("pedido"))
    logger_col = next(
        (cols[k] for k in cols if "logger" in k or "referencia" in k),
        cols.get("logger"),
    )
    uf_col = next((cols[k] for k in cols if k == "uf" or k.endswith("_uf")), cols.get("uf"))

    lookup: dict[str, tuple[str, str]] = {}
    for _, row in df.iterrows():
        logger = norm_logger(row.get(logger_col, ""))
        if not logger or logger in lookup:
            continue
        pedido = str(row.get(pedido_col, "")).strip()
        if pedido.endswith(".0"):
            pedido = pedido[:-2]
        uf = str(row.get(uf_col, "")).strip().upper()
        lookup[logger] = (pedido, uf)
    return lookup


def pasta_pedido(pedido: str, uf: str) -> Path:
    dest = PASTA / f"Pedido_{pedido}_{uf}"
    dest.mkdir(parents=True, exist_ok=True)
    return dest


def extrair_logger(pdf: Path) -> str:
    doc = fitz.open(pdf)
    try:
        text = "".join(page.get_text() for page in doc)
    finally:
        doc.close()
    m = PAT_LOGGER.search(text)
    return m.group(1).upper() if m else ""


def nomes_reservados() -> set[str]:
    reservados: set[str] = set()
    for pdf in PASTA.rglob("*.pdf"):
        reservados.add(pdf.name)
    return reservados


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


def pdfs_pendentes() -> list[Path]:
    return sorted(
        p
        for p in PASTA.glob("*.pdf")
        if not p.name.startswith("_") and not PAT_JA.match(p.name)
    )


def main() -> int:
    xlsx = find_xlsx()
    if not xlsx:
        print(f"Coloque o Excel em: {XLSX_PADRAO}")
        return 1

    lookup = load_lookup(xlsx)
    pdfs = pdfs_pendentes()
    if not pdfs:
        print("Nenhum PDF solto pendente para renomear.")
        print(f"XLSX: {xlsx.name} ({len(lookup)} loggers)")
        return 0

    reservados = nomes_reservados()
    rows: list[dict] = []
    agora = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    pastas_criadas: set[str] = set()

    print(f"Pasta: {PASTA}")
    print(f"XLSX:  {xlsx.name}")
    print(f"Loggers no Excel: {len(lookup)}")
    print(f"PDFs pendentes: {len(pdfs)}\n")

    for pdf in pdfs:
        original = pdf.name
        logger = extrair_logger(pdf)
        if logger and logger in lookup:
            pedido, uf = lookup[logger]
        else:
            pedido, uf = "SEM_PEDIDO", "SEM_UF"

        pasta = pasta_pedido(pedido, uf)
        pastas_criadas.add(pasta.name)

        dest_name = nome_destino(pedido, logger, uf, reservados)
        dest = pasta / dest_name

        if dest.exists() and dest.resolve() != pdf.resolve():
            status = "erro_destino_existe"
        elif pdf.name == dest_name and pdf.parent == pasta:
            status = "ja_nomeado"
        else:
            pdf.rename(dest)
            status = "renomeado"

        rows.append(
            {
                "executado_em": agora,
                "xlsx_usado": xlsx.name,
                "arquivo_original": original,
                "arquivo_novo": f"{pasta.name}/{dest_name}",
                "logger": logger,
                "pedido": pedido,
                "uf": uf,
                "status": status,
            }
        )
        print(f"{original} -> {pasta.name}/{dest_name} [{status}]")

    if rows:
        write_header = not LOG.exists()
        with LOG.open("a", newline="", encoding="utf-8-sig") as f:
            w = csv.DictWriter(f, fieldnames=list(rows[0].keys()), delimiter=";")
            if write_header:
                w.writeheader()
            w.writerows(rows)

    renomeados = sum(1 for r in rows if r["status"] == "renomeado")
    sem_match = sum(1 for r in rows if r["pedido"] == "SEM_PEDIDO")
    print(f"\nRenomeados: {renomeados}/{len(rows)}")
    if sem_match:
        print(f"Sem match no Excel: {sem_match}")
    print(f"Pastas: {', '.join(sorted(pastas_criadas))}")
    print(f"Log: {LOG}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
