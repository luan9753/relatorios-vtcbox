@echo off
title Indicador - Caixa 130L Apos 10/05
cd /d "%~dp0"
set PY=%LOCALAPPDATA%\Programs\Python\Python312\python.exe
if not exist "%PY%" set PY=py -3
echo.
echo  Gerando painel Caixa 130L Apos 10/05...
"%PY%" "%~dp0..\gerar_multigrafico.py" "%~dp0"
if %ERRORLEVEL% NEQ 0 pause & exit /b 1
echo.
echo  Abrindo no navegador...
start "" "%~dp0multigrafico_130l_apos_1005.html"
pause
