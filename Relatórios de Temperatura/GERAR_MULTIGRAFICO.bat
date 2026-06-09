@echo off
title Multigrafico - Todos os Pedidos
cd /d "%~dp0"
set PY=%LOCALAPPDATA%\Programs\Python\Python312\python.exe
if not exist "%PY%" set PY=py -3
echo.
echo  Gerando painel de temperatura (todos os pedidos)...
"%PY%" "%~dp0gerar_multigrafico.py"
if %ERRORLEVEL% NEQ 0 pause & exit /b 1
echo.
echo  Abrindo no navegador...
start "" "%~dp0multigrafico_todos.html"
