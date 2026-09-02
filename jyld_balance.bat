@echo off
chcp 65001 >nul
title TokenRhythm Balance Checker
cd /d "%~dp0"
python jyld_balance.py
pause
