@echo off
chcp 65001 >nul
setlocal
title GameZone — запуск магазина
cd /d "%~dp0"

rem ---------------------------------------------------------------
rem  GameZone: запуск магазина в один клик.
rem  Батник сам находит Python, готовит окружение, ставит зависимости,
rem  применяет миграции, добавляет демо-товары, предлагает создать
rem  администратора и запускает сервер, открыв магазин в браузере.
rem
rem  Порт можно задать аргументом:   run.bat 8080
rem ---------------------------------------------------------------

set "PORT=%~1"
if not defined PORT set "PORT=8000"

rem Проверяем, что аргумент похож на номер порта.
set "PORT_CHECK=%PORT%"
for /f "delims=0123456789" %%i in ("%PORT%") do set "PORT_CHECK=bad"
if not "%PORT_CHECK%"=="bad" goto port_ok
echo  [ВНИМАНИЕ] "%PORT%" не похоже на номер порта — беру 8000.
set "PORT=8000"
:port_ok

echo.
echo  ==============================================
echo   GameZone — интернет-магазин игровых товаров
echo   Учебный проект на Python и Django
echo  ==============================================
echo.

rem ---------- 1. Ищем готовое окружение ----------
rem Порядок: .venv в папке проекта, затем .venv уровнем выше — так батник
rem не создаёт второе окружение, если проект открыт в PyCharm.
set "VPY=.venv\Scripts\python.exe"
if exist "%VPY%" goto env_project
set "VPY=..\.venv\Scripts\python.exe"
if exist "%VPY%" goto env_parent
goto find_python

:env_project
rem Окружение есть, но проверяем, что его Python действительно запускается:
rem .venv ломается, если системный Python удалили или обновили.
"%VPY%" --version >nul 2>&1
if errorlevel 1 goto venv_broken
echo  Окружение: .venv (в папке проекта)
goto env_ready

:venv_broken
echo  [ВНИМАНИЕ] Окружение .venv не работает (например, Python был удалён
echo  или обновлён) — пересоздаю его.
echo.
goto find_python

:env_parent
"%VPY%" --version >nul 2>&1
if errorlevel 1 goto find_python
echo  Окружение: ..\.venv (рядом с проектом — например, из PyCharm)
echo  Второе создавать не нужно, использую его.
goto env_ready

rem ---------- 2. Ищем системный Python ----------
rem Проверяем именно запуск команды, а не where: подставла Microsoft Store
rem (WindowsApps\python.exe) есть в PATH, но настоящим Python не является.
:find_python
set "PYTHON=py"
%PYTHON% --version >nul 2>&1
if not errorlevel 1 goto have_python
set "PYTHON=python"
%PYTHON% --version >nul 2>&1
if not errorlevel 1 goto have_python

echo  [ОШИБКА] Python не найден или не запускается.
echo  Установите Python 3.12+ с https://www.python.org/downloads/
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
if errorlevel 1 goto old_python

echo  [1/5] Создаю виртуальное окружение .venv ...
%PYTHON% -m venv .venv
if errorlevel 1 goto venv_failed
set "VPY=.venv\Scripts\python.exe"
goto env_ready

:old_python
echo  [ОШИБКА] Нужен Python 3.12 или новее — текущая версия слишком старая.
echo  Установите свежий Python с https://www.python.org/downloads/
echo  и перезапустите run.bat.
echo.
pause
exit /b 1

:venv_failed
echo  [ОШИБКА] Не удалось создать виртуальное окружение.
pause
exit /b 1

:env_ready
echo.

rem ---------- 3. Зависимости ----------
rem Быстрая проверка: если Django и Pillow уже установлены, а requirements.txt
rem не менялся с прошлой установки, pip не запускаем вовсе — повторный старт
rem занимает секунды, а не минуты.
"%VPY%" -c "import django, PIL" >nul 2>&1
if errorlevel 1 goto need_deps
if not exist ".requirements.lock" goto need_deps
fc /b requirements.txt .requirements.lock >nul 2>&1
if errorlevel 1 goto need_deps
echo  [2/5] Зависимости уже установлены — пропускаю установку.
goto deps_done

:need_deps
echo  [2/5] Устанавливаю зависимости (Django, Pillow) ...
"%VPY%" -m pip install --disable-pip-version-check -q -r requirements.txt
if errorlevel 1 goto deps_failed
copy /y requirements.txt .requirements.lock >nul
goto deps_done

:deps_failed
rem Нет интернета — не беда, если пакеты уже стоят.
"%VPY%" -c "import django, PIL" >nul 2>&1
if errorlevel 1 goto deps_fatal
echo  [ВНИМАНИЕ] pip завершился с ошибкой (возможно, нет интернета),
echo             но Django уже установлен — продолжаю с тем, что есть.
goto deps_done

:deps_fatal
echo  [ОШИБКА] Не удалось установить зависимости из requirements.txt.
echo  Проверьте подключение к интернету и запустите run.bat ещё раз.
pause
exit /b 1

:migrate_failed
echo  [ОШИБКА] Не удалось применить миграции базы данных.
echo  Возможно, db.sqlite3 открыт другой программой или повреждён —
echo  закройте её и запустите run.bat ещё раз.
pause
exit /b 1

:deps_done
echo.

rem ---------- 4. База данных ----------
echo  [3/5] Применяю миграции базы данных ...
"%VPY%" manage.py migrate --no-input
if errorlevel 1 goto migrate_failed
echo.
echo  [4/5] Проверяю демо-данные ...
"%VPY%" manage.py seed_data --if-empty
echo.

rem ---------- 5. Администратор (по желанию) ----------
rem Спрашиваем у самой базы, есть ли уже суперпользователь,
rem чтобы не предлагать создание администратора при каждом запуске.
del /q .admin-check >nul 2>&1
"%VPY%" -c "import os, django; os.environ.setdefault('DJANGO_SETTINGS_MODULE','gamezone.settings'); django.setup(); from django.contrib.auth import get_user_model; open('.admin-check','w').write('1' if get_user_model().objects.filter(is_superuser=True).exists() else '0')" >nul 2>&1
set "HAS_ADMIN=0"
if not exist .admin-check goto ask_admin
set /p HAS_ADMIN=<.admin-check
del /q .admin-check >nul 2>&1
if "%HAS_ADMIN%"=="1" goto port_check

:ask_admin
echo  Администратор ещё не создан — без него не войти в /admin/.
echo  Создать его прямо сейчас? Логин и пароль набираются видимым текстом.
echo.
set "MAKE_ADMIN=n"
set /p MAKE_ADMIN=Создать администратора? (y — да, Enter — пропустить): 
if /i not "%MAKE_ADMIN%"=="y" goto port_check
echo.
rem Передаём выбранный интерпретатор, чтобы create_admin.bat не искал его заново.
set "GAMEZONE_PYTHON=%VPY%"
call create_admin.bat
echo.

rem ---------- 6. Проверяем, свободен ли порт ----------
:port_check
netstat -ano | findstr "LISTENING" | findstr /c:":%PORT% " >nul 2>&1
if errorlevel 1 goto port_free

echo  [ВНИМАНИЕ] Порт %PORT% уже занят — скорее всего, сервер уже
echo  запущен из PyCharm или вторым окном run.bat.
echo.
echo    1 — открыть магазин в браузере и выйти (сервер уже работает)
echo    2 — запустить на другом порту
echo.
set "CHOICE=1"
set /p CHOICE=Ваш выбор (1 или 2, по умолчанию 1): 
if "%CHOICE%"=="2" goto ask_port
echo.
start "" "http://127.0.0.1:%PORT%/"
echo  Открыл http://127.0.0.1:%PORT%/ — там уже работает ваш сервер.
echo.
pause
endlocal
exit /b 0

:ask_port
set "PORT="
set /p PORT=Введите свободный порт (например 8001): 
if not defined PORT set "PORT=8001"
echo.
goto port_check

rem ---------- 7. Запуск сервера ----------
:port_free
echo  [5/5] Запускаю сервер на порту %PORT% ...
echo.
echo  ----------------------------------------------
echo   Магазин:       http://127.0.0.1:%PORT%/
echo   Админ-панель:  http://127.0.0.1:%PORT%/admin/
echo  ----------------------------------------------
echo   Браузер откроется сам, когда сервер запустится.
echo   Остановить сервер — Ctrl+C или закрыть окно.
echo  ----------------------------------------------
echo.

rem Браузер открываем с небольшой задержкой в отдельном окне:
rem к этому моменту сервер уже успевает начать слушать порт,
rem и страница не показывает ошибку подключения.
start "GameZone" /min cmd /c "ping -n 4 127.0.0.1 >nul & start http://127.0.0.1:%PORT%/"
"%VPY%" manage.py runserver %PORT%

echo.
echo  Сервер остановлен. Нажмите любую клавишу для выхода.
pause >nul
endlocal
exit /b 0
