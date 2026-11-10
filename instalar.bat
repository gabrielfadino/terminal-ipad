@echo off
chcp 65001 >nul
title Terminal iPad - instalacao
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0instalar.ps1"
