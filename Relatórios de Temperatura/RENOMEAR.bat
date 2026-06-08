@echo off
title Renomear relatorios - Pedido_Logger_UF
cd /d "%~dp0"
echo.
echo  Padrao: pedido_logger_uf.pdf
echo  Exemplo: 556160_A0974_SC.pdf
echo.

where py >nul 2>&1 && set PY=py -3
if not defined PY where python >nul 2>&1 && set PY=python
if not defined PY (
  echo Python nao encontrado. Instale Python 3 e execute: pip install pymupdf pyodbc
  pause
  exit /b 1
)

%PY% -c "import fitz" >nul 2>&1 || (
  echo Instalando pymupdf...
  %PY% -m pip install pymupdf --quiet
)

%PY% "%~dp0renomear_pdfs.py"
echo.
pause
