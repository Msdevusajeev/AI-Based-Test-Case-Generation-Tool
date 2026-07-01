@echo off
title Test Case Generator -- EXE Builder
color 0A

echo.
echo  =====================================================
echo   Test Case Generator  --  EXE Build Script
echo  =====================================================
echo.

set "PROJECT_ROOT=%~dp0"
if "%PROJECT_ROOT:~-1%"=="\" set "PROJECT_ROOT=%PROJECT_ROOT:~0,-1%"
echo  Project root: %PROJECT_ROOT%
echo.

if not exist "%PROJECT_ROOT%\TestCaseGenerator.spec" (
    echo ERROR: TestCaseGenerator.spec not found & pause & exit /b 1
)

echo  What did you change?
echo.
echo  [1] Backend only  (Python files)
echo  [2] Frontend only (React/JSX files)
echo  [3] Both
echo  [4] Full clean rebuild
echo.
set /p CHOICE="Enter choice (1/2/3/4): "
echo.

set DO_FRONTEND=0
set DO_BACKEND=0

if "%CHOICE%"=="1" ( set DO_BACKEND=1 )
if "%CHOICE%"=="2" ( set DO_FRONTEND=1 )
if "%CHOICE%"=="3" ( set DO_FRONTEND=1 & set DO_BACKEND=1 )
if "%CHOICE%"=="4" (
    set DO_FRONTEND=1 & set DO_BACKEND=1
    for %%F in (build dist) do (
        if exist "%PROJECT_ROOT%\%%F\" rd /s /q "%PROJECT_ROOT%\%%F"
    )
)

if "%DO_FRONTEND%"=="0" if "%DO_BACKEND%"=="0" (
    echo Invalid choice. & pause & exit /b 1
)

:: ── AUTO-PATCH ResultsTable.jsx ──────────────────────────────────────────────
if "%DO_FRONTEND%"=="1" (
    echo [AUTO-PATCH]  Fixing ResultsTable.jsx...
    python "%PROJECT_ROOT%\_patch_frontend.py"
    echo.
)

:: ── Frontend build ────────────────────────────────────────────────────────────
if "%DO_FRONTEND%"=="1" (
    echo [STEP: Frontend]  Building React...
    if exist "%PROJECT_ROOT%\frontend\dist\" rd /s /q "%PROJECT_ROOT%\frontend\dist"
    if exist "%PROJECT_ROOT%\frontend\node_modules\.vite\" rd /s /q "%PROJECT_ROOT%\frontend\node_modules\.vite"
    cd /d "%PROJECT_ROOT%\frontend"
    call npm install
    if %errorlevel% neq 0 ( echo ERROR: npm install failed & cd /d "%PROJECT_ROOT%" & pause & exit /b 1 )
    call npm run build
    if %errorlevel% neq 0 ( echo ERROR: npm build failed & cd /d "%PROJECT_ROOT%" & pause & exit /b 1 )
    cd /d "%PROJECT_ROOT%"
    if not exist "%PROJECT_ROOT%\frontend\dist\index.html" (
        echo ERROR: Build output missing & pause & exit /b 1
    )
    echo  React build complete.
    echo.
)

:: ── PyInstaller ───────────────────────────────────────────────────────────────
echo [STEP: Build]  Running PyInstaller...
cd /d "%PROJECT_ROOT%"
python -m PyInstaller "%PROJECT_ROOT%\TestCaseGenerator.spec" --noconfirm ^
    --distpath "%PROJECT_ROOT%\dist" ^
    --workpath "%PROJECT_ROOT%\build"
if %errorlevel% neq 0 ( echo ERROR: PyInstaller failed & pause & exit /b 1 )

echo.
echo  =====================================================
echo   OUTPUT:  %PROJECT_ROOT%\dist\TestCaseGenerator.exe
echo  =====================================================
echo.
pause
