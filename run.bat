@echo off
chcp 65001 >nul
setlocal
title GameZone — запуск магазина
cd /d "%~dp0"

echo.
echo  ==============================================
echo   GameZone — интернет-магазин игровых товаров
echo   Учебный проект на Python и Django
echo  ==============================================
echo.

rem ---------- 1. Проверка Python ----------
rem Сначала пробуем лаунчер py, затем python.
rem Проверяем именно запуск команды, а не where: подставла Microsoft Store
rem (WindowsApps\python.exe) находится в PATH, но не является настоящим Python.
set "PYTHON=py"
%PYTHON% --version >nul 2>&1
if not errorlevel 1 goto have_python
set "PYTHON=python"
%PYTHON% --version >nul 2>&1
if not errorlevel 1 goto have_python

echo  [ОШИБКА] Python не найден или не запускается.
echo  Установите Python 3.10+ с https://www.python.org/downloads/
echo  и отметьте галочку "Add Python to PATH".
echo  Если была ошибка про WindowsApps\python.exe — это подставла
echo  Microsoft Store, а не настоящий Python: нужен python.org.
echo.
pause
exit /b 1

:have_python
echo  Найден Python-лаунчер: %PYTHON%
%PYTHON% --version
echo.

rem Django 6.1 требует Python 3.12 или новее.
%PYTHON% -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 12) else 1)" >nul 2>&1
if errorlevel 1 (
    echo  [ОШИБКА] Нужен Python 3.12 или новее — текущая версия слишком старая.
    echo  Установите свежий Python с https://www.python.org/downloads/
    echo  и перезапустите run.bat.
    pause
    exit /b 1
)

rem ---------- 2. Виртуальное окружение ----------
if not exist ".venv\Scripts\python.exe" (
    echo  [1/5] Создаю виртуальное окружение .venv ...
    %PYTHON% -m venv .venv
    if errorlevel 1 (
        echo  [ОШИБКА] Не удалось создать виртуальное окружение.
        pause
        exit /b 1
    )
)
set "VPY=.venv\Scripts\python.exe"

rem ---------- 3. Зависимости ----------
echo  [2/5] Устанавливаю зависимости (Django, Pillow) ...
"%VPY%" -m pip install --disable-pip-version-check -q -r requirements.txt
if errorlevel 1 (
    echo  [ОШИБКА] Не удалось установить зависимости из requirements.txt.
    pause
    exit /b 1
)

rem ---------- 4. База данных ----------
echo  [3/5] Применяю миграции базы данных ...
"%VPY%" manage.py migrate
if errorlevel 1 (
    echo  [ОШИБКА] Не удалось применить миграции.
    pause
    exit /b 1
)

echo  [4/5] Проверяю демо-данные ...
"%VPY%" manage.py seed_data --if-empty

rem ---------- 5. Запуск сервера ----------
echo  [5/5] Запускаю сервер ...
echo.
echo  ----------------------------------------------
echo   Магазин:       http://127.0.0.1:8000/
echo   Админ-панель:  http://127.0.0.1:8000/admin/
echo  ----------------------------------------------
echo   Чтобы создать администратора — запустите
echo   create_admin.bat (или см. README.md).
echo   Чтобы остановить сервер — нажмите Ctrl+C
echo   или закройте это окно.
echo  ----------------------------------------------
echo.

start "" "http://127.0.0.1:8000/"
"%VPY%" manage.py runserver

echo.
echo  Сервер остановлен. Нажмите любую клавишу для выхода.
pause >nul
endlocal
exit /b 0
