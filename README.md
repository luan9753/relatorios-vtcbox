# Relatórios VTCBOX — Caixa Nova

Ferramentas para operação da embalagem **CAIXA VTCBOX 130L WEDGE SEAL COM BERÇO**:

- **Indicador HTML** — painel de pedidos entregues / em rota (banco Aura via ODBC)
- **Multigráfico de temperatura** — 1 gráfico por logger, extraído dos PDFs
- **Renomeação de PDFs** — padrão `pedido_logger_uf.pdf`

## Pastas

| Pasta | Conteúdo |
|-------|----------|
| `Indicador-VTCBOX/` | Indicador visual + atualização do banco |
| `Relatórios de Temperatura/` | PDFs, renomeação e multigráfico |

## Requisitos

- Windows com ODBC **AuraVTC** configurado (indicador)
- Python 3.12+ (`pip install pymupdf`)
- PowerShell

## Uso rápido

### Indicador VTCBOX
```
Indicador-VTCBOX\ATUALIZAR_INDICADOR.bat
```

### Renomear PDFs de temperatura
Coloque os PDFs em `Relatórios de Temperatura/` e execute:
```
Relatórios de Temperatura\RENOMEAR.bat
```
Padrão: `556160_A0974_SC.pdf`

### Multigráfico de temperatura
Com os PDFs renomeados:
```
Relatórios de Temperatura\GERAR_MULTIGRAFICO.bat
```
Gera `multigrafico_556160_SC.html` e abre no navegador.

## GitHub Pages

O arquivo `Relatórios de Temperatura/multigrafico_556160_SC.html` é autocontido (dados embutidos) e pode ser publicado via Pages apontando para essa pasta ou movendo o HTML para `docs/`.

## Fonte de dados

- Banco Aura (Supabase): `vtc_stage.documentos`
- PDFs de temperatura/umidade exportados do sistema
