@echo off
title Multigrafico Pedido 556160
cd /d "%~dp0"
set PY=%LOCALAPPDATA%\Programs\Python\Python312\python.exe
if not exist "%PY%" set PY=py -3
echo.
echo  Gerando multigrafico de temperatura...
"%PY%" "%~dp0gerar_multigrafico.py"
if %ERRORLEVEL% NEQ 0 pause & exit /b 1
echo.
echo  Abrindo no navegador...
start "" "%~dp0multigrafico_556160_SC.html"
