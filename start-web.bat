@echo off
echo Starting SearchPro Web on http://127.0.0.1:8765 ...
start "" python "%~dp0web.py"
timeout /t 2 >nul
start "" http://127.0.0.1:8765
echo Open http://127.0.0.1:8765 in your browser
pause
