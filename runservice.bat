@echo off
REM PurifierGraph startup script
REM   Neo4j  : Docker container (purifiergraph-neo4j)
REM   Backend: conda graphrag + uvicorn on :8000
REM   Frontend: npm run dev (Vite) on :5173
REM Close the popup cmd windows to stop each service.

chcp 65001 >nul
cd /d "%~dp0"

echo.
echo ======================================================
echo  PurifierGraph Launcher
echo  Project: %CD%
echo ======================================================
echo.

set "BDIR=%CD%\backend"
set "FDIR=%CD%\frontend"
set "PY=C:\Users\danid\anaconda3\envs\graphrag\python.exe"

REM --- Set env vars BEFORE start (inherited by child cmd windows) ---
set "PYTHONPATH=%BDIR%"
set "SEED_ON_STARTUP=false"

REM --- 1. Neo4j ---
echo [1/3] Checking Neo4j container...
docker ps --filter name=purifiergraph-neo4j --filter status=running --format {{.Names}} | findstr purifiergraph >nul
if errorlevel 1 (
  echo       Not running. Starting...
  docker compose up -d neo4j
  if errorlevel 1 (
    echo       [FAIL] Neo4j start failed. Is Docker Desktop running?
    pause
    exit /b 1
  )
  echo       Waiting for Neo4j healthy...
  timeout /t 10 /nobreak >nul
) else (
  echo       Already running.
)
echo.

REM --- 2. Backend ---
echo [2/3] Starting backend on http://127.0.0.1:8000
if not exist "%PY%" (
  echo       [FAIL] Python not found: %PY%
  echo       Make sure conda env graphrag exists.
  pause
  exit /b 1
)
start "PurifierGraph Backend" /d "%BDIR%" cmd /k ""%PY%" -m uvicorn app.main:app --host 127.0.0.1 --port 8000"
echo       Backend window opened.
echo.

REM --- 3. Frontend ---
echo [3/3] Starting frontend on http://localhost:5173
if not exist "%FDIR%\node_modules" (
  echo       First run - installing deps...
  cd /d "%FDIR%"
  call npm install
)
start "PurifierGraph Frontend" /d "%FDIR%" cmd /k call npm run dev
echo       Frontend window opened.
echo.

echo ======================================================
echo  All services launched!
echo  - Frontend : http://localhost:5173
echo  - Backend  : http://127.0.0.1:8000/api/health
echo  - Neo4j    : http://localhost:7474  (neo4j / purifier123)
echo.
echo  Close the popup cmd windows to stop backend/frontend.
echo  To stop Neo4j: docker compose stop neo4j
echo ======================================================
echo.
pause
