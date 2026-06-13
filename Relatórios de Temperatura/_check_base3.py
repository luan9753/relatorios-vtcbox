"""Compara base3.xlsx com PDFs da pasta principal e gera xlsx de pendentes."""
from __future__ import annotations

import re
from collections import defaultdict
from pathlib import Path

import pandas as pd

PASTA = Path(__file__).resolve().parent
BASE = PASTA / "base3.xlsx"
EXCLUIR = {"Caixa 130L Normal", "Caixa 130L Após 10-05"}
PADRAO = re.compile(r"^(\d+)_([A-Z][A-Z0-9]+)_([A-Z]{2})(_\d+)?\.pdf$", re.I)
OUT = PASTA / "pendentes_base3.xlsx"


def norm_pedido(v) -> str:
    if pd.isna(v):
        return ""
    s = str(v).strip()
    return s[:-2] if s.endswith(".0") else s


def norm_logger(v) -> str:
    if pd.isna(v):
        return ""
    s = str(v).strip().upper()
    return "" if s in {"", "NAN", "NONE"} else s


def norm_uf(v) -> str:
    if pd.isna(v):
        return ""
    return str(v).strip().upper()


def _col(cols: dict[str, str], *partes: str) -> str | None:
    for parte in partes:
        hit = next((cols[k] for k in cols if parte in k), None)
        if hit:
            return hit
    return None


def main() -> None:
    pdfs: set[tuple[str, str, str]] = set()
    for pdf in PASTA.rglob("*.pdf"):
        if any(x in EXCLUIR for x in pdf.parts):
            continue
        m = PADRAO.match(pdf.name)
        if m:
            pdfs.add((norm_pedido(m.group(1)), norm_logger(m.group(2)), norm_uf(m.group(3))))

    df = pd.read_excel(BASE)
    cols = {str(c).strip().lower(): c for c in df.columns}
    pedido_col = _col(cols, "pedido")
    logger_col = _col(cols, "logger")
    uf_col = _col(cols, "uf")
    modal_col = _col(cols, "modal")
    lpn_col = _col(cols, "lpn")
    coleta_col = _col(cols, "coleta")
    entrega_col = _col(cols, "entrega")

    rows = []
    for _, row in df.iterrows():
        pedido = norm_pedido(row.get(pedido_col)) if pedido_col else ""
        logger = norm_logger(row.get(logger_col)) if logger_col else ""
        uf = norm_uf(row.get(uf_col)) if uf_col else ""
        if not pedido or not logger or not uf:
            continue
        modal = "" if not modal_col or pd.isna(row.get(modal_col)) else str(row.get(modal_col)).strip()
        key = (pedido, logger, uf)
        rows.append({"pedido": pedido, "logger": logger, "uf": uf, "modal": modal, "tem_pdf": key in pdfs})

    faltando = [r for r in rows if not r["tem_pdf"]]
    print(f"Arquivo: {BASE.name}")
    print(f"Colunas: {list(df.columns)}")
    print(f"Total na base: {len(rows)}")
    print(f"PDFs encontrados: {len(pdfs)}")
    print(f"Com PDF: {len(rows) - len(faltando)}")
    print(f"FALTANDO PDF: {len(faltando)}")
    print()

    by_group: dict[tuple[str, str], list] = defaultdict(list)
    for r in faltando:
        by_group[(r["pedido"], r["uf"])].append(r)

    for (pedido, uf), items in sorted(by_group.items(), key=lambda x: (x[0][0], x[0][1])):
        loggers = ", ".join(i["logger"] for i in sorted(items, key=lambda x: x["logger"]))
        modal = items[0]["modal"] or "—"
        print(f"Pedido {pedido} / {uf} ({modal}) — {len(items)}: {loggers}")

    if faltando:
        df_out = pd.DataFrame(faltando).drop(columns=["tem_pdf"])
        extra_cols = [c for c in (lpn_col, coleta_col, entrega_col) if c]
        if extra_cols and pedido_col and logger_col and uf_col:
            extra = df[[pedido_col, logger_col, uf_col] + extra_cols].copy()
            extra.columns = ["pedido", "logger", "uf"] + [
                "lpn" if c == lpn_col else "data_coleta" if c == coleta_col else "data_entrega"
                for c in extra_cols
            ]
            extra["pedido"] = extra["pedido"].map(norm_pedido)
            extra["logger"] = extra["logger"].map(norm_logger)
            extra["uf"] = extra["uf"].map(norm_uf)
            df_out = df_out.merge(extra, on=["pedido", "logger", "uf"], how="left")
        df_out = df_out.sort_values(["pedido", "uf", "logger"])
        df_out.to_excel(OUT, index=False)
        print(f"\nArquivo gerado: {OUT}")
    else:
        print("\nNenhum pendente — todos os loggers da base têm PDF.")


if __name__ == "__main__":
    main()
