@echo off
title Indicador VTCBOX - Atualizar
cd /d "%~dp0"
echo.
echo  Atualizando indicador VTCBOX do banco Aura (ODBC AuraVTC)...
echo.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0gerar_indicador.ps1"
if %ERRORLEVEL% NEQ 0 (
  echo.
  echo  ERRO ao gerar. Verifique se o ODBC AuraVTC esta configurado.
  pause
  exit /b 1
)
echo.
echo  Abrindo indicador no navegador...
start "" "%~dp0indicador.html"
