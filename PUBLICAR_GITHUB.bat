@echo off
title Publicar no GitHub
cd /d "%~dp0"
set "PATH=C:\Program Files\Git\cmd;C:\Program Files\GitHub CLI;%PATH%"

echo.
echo  === Publicar relatorios-vtcbox no GitHub ===
echo.

gh auth status >nul 2>&1
if %ERRORLEVEL% NEQ 0 (
  echo  Voce precisa entrar no GitHub primeiro.
  echo  Abrindo login...
  gh auth login -p https -w
  if %ERRORLEVEL% NEQ 0 (
    echo  Login falhou. Rode manualmente: gh auth login
    pause
    exit /b 1
  )
)

git status >nul 2>&1
if %ERRORLEVEL% NEQ 0 (
  echo  Git nao inicializado nesta pasta.
  pause
  exit /b 1
)

git remote get-url origin >nul 2>&1
if %ERRORLEVEL% NEQ 0 (
  echo  Criando repositorio publico relatorios-vtcbox ...
  gh repo create relatorios-vtcbox --public --source=. --remote=origin --description "Indicador e multigrafico VTCBOX 130L"
  if %ERRORLEVEL% NEQ 0 pause & exit /b 1
)

echo  Enviando codigo...
git push -u origin main
if %ERRORLEVEL% NEQ 0 (
  echo  Push falhou.
  pause
  exit /b 1
)

echo.
echo  Ativando GitHub Pages (pasta docs/)...
gh api repos/{owner}/relatorios-vtcbox/pages -X POST -f build_type=legacy -f source[branch]=main -f source[path]=/docs 2>nul
if %ERRORLEVEL% NEQ 0 (
  echo  Pages: configure manualmente em Settings ^> Pages ^> Branch main ^> folder docs
) else (
  echo  Pages solicitado com sucesso.
)

for /f "delims=" %%U in ('gh repo view --json url -q .url 2^>nul') do set REPO=%%U
echo.
echo  Repositorio: %REPO%
echo  Multigrafico online em alguns minutos:
echo  %REPO%/tree/main/docs  ^(ou URL do Pages^)
echo.
pause
