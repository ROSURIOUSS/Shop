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
echo  Пароль придумайте сами и запишите его —
echo  в исходном коде никаких паролей нет.
echo.

if not exist ".venv\Scripts\python.exe" (
    echo  [ОШИБКА] Виртуальное окружение не найдено.
    echo  Сначала один раз запустите run.bat — он всё подготовит.
    echo.
    pause
    exit /b 1
)

".venv\Scripts\python.exe" manage.py createsuperuser

echo.
echo  Готово. Войти в админ-панель можно на
echo  http://127.0.0.1:8000/admin/ (при запущенном run.bat).
echo.
pause
endlocal
