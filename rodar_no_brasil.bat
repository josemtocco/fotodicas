@echo off
chcp 65001 >nul
setlocal enabledelayedexpansion
title Atualizar lista M3U - Fotodicas
cd /d "%~dp0"

echo ============================================================
echo   ATUALIZAR LISTA M3U  -  FOTODICAS
echo   (rode este arquivo no Brasil, com sua internet normal)
echo ============================================================
echo.

REM --- ffmpeg portatil em C:\ffmpeg (nao mexe em nenhum outro programa) ---
if exist "C:\ffmpeg\bin\ffprobe.exe" (
    set "PATH=C:\ffmpeg\bin;%PATH%"
    echo [OK] ffmpeg encontrado em C:\ffmpeg\bin
) else (
    echo [AVISO] ffmpeg nao encontrado em C:\ffmpeg\bin
    echo         O teste de reproducao vai ficar incompleto.
    echo         Veja no LEIA-ME como instalar em 2 minutos.
)
echo.

REM --- python ---
where python >nul 2>nul
if errorlevel 1 (
    echo [ERRO] Python nao encontrado.
    echo        Instale em https://www.python.org/downloads/windows/
    echo        e marque a opcao "Add python.exe to PATH".
    pause
    exit /b 1
)
for /f "delims=" %%v in ('python -c "import sys;print(sys.version.split()[0])" 2^>nul') do set "PYVER=%%v"
echo [OK] Python !PYVER!
echo.

echo Iniciando a coleta e o teste dos canais...
echo Isso leva de 3 a 6 minutos. Pode deixar rodando.
echo.
python atualizar_m3u.py
if errorlevel 1 (
    echo.
    echo [ERRO] O script terminou com falha. Veja a mensagem acima.
    pause
    exit /b 1
)

echo.
echo ============================================================
echo   PRONTO!
echo   Arquivos gerados nesta pasta:
echo     - fotodicas.m3u        (a lista para o SS IPTV / VLC)
echo     - estado_canais.json   (memoria das 6 atualizacoes)
echo     - relatorio_teste.csv  (o que tocou e o que nao tocou)
echo ============================================================
echo.
pause
