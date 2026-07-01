@echo off
cd /d "%~dp0"

:: Kill old EXE
taskkill /F /IM TestCaseGenerator.exe >nul 2>&1
timeout /t 2 /nobreak >nul

:: Build frontend
cd frontend
call npm run build
cd ..

:: Copy to EXE folder
if not exist "dist\frontend\dist" mkdir "dist\frontend\dist"
xcopy /E /Y /I /Q "frontend\dist" "dist\frontend\dist"

:: Launch EXE
start "" "dist\TestCaseGenerator.exe"
timeout /t 3 /nobreak >nul

echo.
echo Done. Browser will open at localhost:8000
echo Press Ctrl+Shift+R in the browser for a hard refresh
echo.
pause
