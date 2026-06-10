@echo off
title Renomear PDFs - Caixa 130L Normal
cd /d "%~dp0"
set PY=%LOCALAPPDATA%\Programs\Python\Python312\python.exe
if not exist "%PY%" set PY=py -3
echo.
echo  Caixa 130L Normal - renomear para pedido_logger_uf.pdf
echo.
"%PY%" "%~dp0..\renomear_pdfs.py" "%~dp0"
echo.
pause
