@echo off
chcp 65001 >nul
setlocal
title GameZone — резервная копия данных
cd /d "%~dp0"

echo.
echo  ==============================================
echo   GameZone — резервная копия данных
echo  ==============================================
echo.
echo  Сохраняются пользователи, профили, заказы, товары и обращения.
echo  Файл появится в папке backups рядом с проектом.
echo  Журнал посещений добавляется параметром: backup.bat --with-logs
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
"%VPY%" manage.py backup_data %*
if errorlevel 1 (
    echo.
    echo  [ОШИБКА] Не удалось создать резервную копию.
    pause
    exit /b 1
)

echo.
echo  Готово. Папка с копиями: backups
echo  Восстановить копию можно файлом restore.bat
echo.
pause
endlocal
exit /b 0
