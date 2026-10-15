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

if not exist ".venv\Scripts\python.exe" (
    echo  [ОШИБКА] Виртуальное окружение не найдено.
    echo  Сначала один раз запустите run.bat — он всё подготовит.
    echo.
    pause
    exit /b 1
)

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

".venv\Scripts\python.exe" manage.py createsuperuser --noinput
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
echo  (сначала должен работать run.bat).
echo.
pause
endlocal
exit /b 0
