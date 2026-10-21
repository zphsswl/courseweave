@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"

if defined COURSEWEAVE_PYTHON (
  "%COURSEWEAVE_PYTHON%" -c "import sys" >nul 2>nul
  if not errorlevel 1 goto explicit_python
)
"%~dp0.venv\Scripts\python.exe" -c "import sys" >nul 2>nul
if not errorlevel 1 goto project_python
py -3 -c "import sys" >nul 2>nul
if not errorlevel 1 goto system_launcher
python -c "import sys" >nul 2>nul
if not errorlevel 1 goto system_python
echo 未找到可用的 Python。复制的 .venv 可能仍引用原电脑的安装路径。
echo 请安装 Python 3.12，然后运行 py -3.12 -m venv .venv-local
echo 再运行 .venv-local\Scripts\python.exe -m pip install -r requirements.txt
echo 设置 COURSEWEAVE_PYTHON 为新环境的 python.exe 后重试。
pause
exit /b 1

:explicit_python
"%COURSEWEAVE_PYTHON%" "%~dp0scripts\start_local.py" %*
goto finished
:project_python
"%~dp0.venv\Scripts\python.exe" "%~dp0scripts\start_local.py" %*
goto finished
:system_launcher
py -3 "%~dp0scripts\start_local.py" %*
goto finished
:system_python
python "%~dp0scripts\start_local.py" %*
:finished
set "courseweave_exit_code=%errorlevel%"
if not "%courseweave_exit_code%"=="0" pause
exit /b %courseweave_exit_code%
