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
set "PYTHON=python"
where python >nul 2>&1
if errorlevel 1 set "PYTHON=py"
where %PYTHON% >nul 2>&1
if errorlevel 1 (
    echo  [ОШИБКА] Python не найден.
    echo  Установите Python 3.10+ с https://www.python.org/downloads/
    echo  и обязательно отметьте галочку "Add Python to PATH".
    echo.
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
