@echo off
chcp 65001 >nul
setlocal
title GameZone — создание администратора
cd /d "%~dp0"

echo.
echo  ==============================================
echo   GameZone — создание администратора
echo  ==============================================
echo.
echo  Логин и пароль вводятся как обычный текст —
echo  символы видны на экране (для учебного проекта это нормально).
echo.

rem ---------- Определяем Python ----------
rem Приоритет: интерпретатор, который уже выбрал run.bat, затем окружение
rem .venv, затем лаунчер py, затем python.
rem Проверяем именно запуск команды, а не where: подставла Microsoft Store
rem (WindowsApps\python.exe) находится в PATH, но не является настоящим Python.
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
rem ---------- Миграции ----------
rem Защита от ошибки "no such table: auth_user": без миграций
rem ни админка, ни создание администратора работать не будут.
echo  Применяю миграции базы данных ...
"%VPY%" manage.py migrate
if errorlevel 1 (
    echo  [ОШИБКА] Не удалось применить миграции.
    pause
    exit /b 1
)
echo.

set "ADMUSER="
set "ADMPASS="
set /p ADMUSER=Введите логин: 
if not defined ADMUSER (
    echo  [ОШИБКА] Логин не может быть пустым.
    pause
    exit /b 1
)
set /p ADMPASS=Введите пароль: 
if not defined ADMPASS (
    echo  [ОШИБКА] Пароль не может быть пустым.
    pause
    exit /b 1
)

rem createsuperuser --noinput берёт данные из переменных окружения,
rem поэтому обходится без проблемного запроса пароля в консоли.
set "DJANGO_SUPERUSER_USERNAME=%ADMUSER%"
set "DJANGO_SUPERUSER_EMAIL=%ADMUSER%@gamezone.local"
set "DJANGO_SUPERUSER_PASSWORD=%ADMPASS%"

"%VPY%" manage.py createsuperuser --noinput
if errorlevel 1 (
    echo.
    echo  [ОШИБКА] Не удалось создать администратора.
    echo  Возможно, пользователь с таким логином уже существует —
    echo  попробуйте другой логин.
    pause
    exit /b 1
)

echo.
echo  Готово! Администратор "%ADMUSER%" создан.
echo  Войти в админ-панель: http://127.0.0.1:8000/admin/
echo  (сначала должен работать сервер: run.bat или PyCharm).
echo  Повторно создавать администратора run.bat больше не предложит.
echo.
pause
endlocal
exit /b 0
