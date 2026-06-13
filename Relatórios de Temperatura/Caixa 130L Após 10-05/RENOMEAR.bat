@echo off
title Renomear PDFs - Caixa 130L Apos 10/05
cd /d "%~dp0"
set PY=%LOCALAPPDATA%\Programs\Python\Python312\python.exe
if not exist "%PY%" set PY=py -3
echo.
echo  Renomeando PDFs...
"%PY%" "%~dp0..\renomear_pdfs.py" "%~dp0"
if %ERRORLEVEL% NEQ 0 pause & exit /b 1
pause
