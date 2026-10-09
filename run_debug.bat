@echo off
cd /d "%~dp0"
echo Closing any running KeyDeck...
taskkill /im KeyDeck.exe /f >nul 2>&1
echo Starting KeyDeck in debug mode. Leave this window open.
echo If KeyDeck closes, the reason will be printed below.
echo.
set KEYDECK_DEBUG=1
python keydeck.py
echo.
echo ---- KeyDeck stopped. Copy everything above and send it to Claude. ----
pause
