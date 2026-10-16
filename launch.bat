@echo off
setlocal
cd /d "%~dp0"
where py >nul 2>nul
if errorlevel 1 goto try_python
py -3 -c "import sys" >nul 2>nul
if errorlevel 1 goto try_python
py -3 app.py %*
set "APP_EXIT_CODE=%ERRORLEVEL%"
goto finished

:try_python
where python >nul 2>nul
if errorlevel 1 goto no_python
python app.py %*
set "APP_EXIT_CODE=%ERRORLEVEL%"
goto finished

:no_python
echo Python 3 was not found. Install Python with Tcl/Tk and add it to PATH.
set "APP_EXIT_CODE=1"

:finished
if not "%APP_EXIT_CODE%"=="0" pause
exit /b %APP_EXIT_CODE%
