@echo off
chcp 65001 >nul
title TokenRhythm Balance Checker (TUI)
cd /d "%~dp0"
python jyld_tui.py %*
pause