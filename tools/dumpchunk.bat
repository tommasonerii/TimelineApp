@echo off
setlocal enabledelayedexpansion
set "file=%~1"
set "start=%~2"
set "count=%~3"
if "%file%"=="" set "file=ui\timeline_canvas.py"
if "%start%"=="" set "start=1"
if "%count%"=="" set "count=250"
set /a end=start+count-1
set n=0
for /f "usebackq delims=" %%L in ("%file%") do (
  set /a n+=1
  if !n! geq %start% if !n! leq !end! echo(!n!: %%L
)
endlocal
