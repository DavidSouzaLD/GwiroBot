
@echo off
chcp 65001 >nul
set PYTHONIOENCODING=utf-8

cd /d "%~dp0"

echo ==================================
echo Instalando dependencias...
echo ==================================

python -m pip install --upgrade pip
python -m pip install playwright beautifulsoup4

echo.
echo Instalando navegadores do Playwright...
python -m playwright install chromium

echo.
echo Iniciando servidor...
echo ==================================

python server.py

pause
