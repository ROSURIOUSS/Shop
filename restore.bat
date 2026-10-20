@echo off
chcp 65001 >nul
setlocal
title GameZone — восстановление данных из копии
cd /d "%~dp0"

echo.
echo  ==============================================
echo   GameZone — восстановление данных из копии
echo  ==============================================
echo.
echo  Возвращает пользователей, заказы и товары из резервной копии.
echo  Можно перетащить файл копии на этот батник или просто запустить его —
echo  тогда возьмётся самая свежая копия из папки backups.
echo.

rem ---------- Определяем Python ----------
rem Приоритет: интерпретатор, который уже выбрал run.bat, затем окружение
rem .venv, затем лаунчер py, затем python.
set "VPY=.venv\Scripts\python.exe"
if defined GAMEZONE_PYTHON set "VPY=%GAMEZONE_PYTHON%"
if exist "%VPY%" goto have_python
set "VPY=py"
%VPY% --version >nul 2>&1
if not errorlevel 1 goto have_python
set "VPY=python"
%VPY% --version >nul 2>&1
if not errorlevel 1 goto have_python

echo  [ОШИБКА] Python не найден или не запускается.
echo  Сначала один раз запустите run.bat — он всё подготовит.
echo.
pause
exit /b 1

:have_python
set "TARGET=%~1"

if not defined TARGET (
    for /f "delims=" %%f in ('dir /b /a-d /o-n "backups\*.json" 2^>nul') do (
        if not defined TARGET set "TARGET=backups\%%f"
    )
)

if not defined TARGET (
    echo  [ОШИБКА] В папке backups нет ни одной копии.
    echo  Сначала запустите backup.bat или перетащите сюда файл копии.
    echo.
    pause
    exit /b 1
)

echo  Копия: %TARGET%
echo.
"%VPY%" manage.py restore_data "%TARGET%" --show
echo.

set "ANSWER="
set /p ANSWER=Восстановить эти данные в базу? (y/n): 
if /i not "%ANSWER%"=="y" (
    echo  Отменено — база не изменена.
    echo.
    pause
    exit /b 0
)

"%VPY%" manage.py restore_data "%TARGET%"
if errorlevel 1 (
    echo.
    echo  [ОШИБКА] Не удалось восстановить данные.
    pause
    exit /b 1
)

echo.
echo  Готово. Данные из копии снова в базе.
echo.
pause
endlocal
exit /b 0
