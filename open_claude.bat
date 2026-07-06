@echo off
:: Bring Claude Desktop to front using AppActivate on process name "claude"
:: If not running, launch it via AppX
powershell -NoProfile -WindowStyle Hidden -Command ^
  "$proc = Get-Process -Name 'claude' -ErrorAction SilentlyContinue | Where-Object {$_.MainWindowTitle -eq 'Claude'} | Select-Object -First 1;" ^
  "if ($proc) {" ^
    "$wshell = New-Object -ComObject WScript.Shell;" ^
    "$wshell.AppActivate($proc.Id);" ^
    "Start-Sleep -Milliseconds 500;" ^
    "$wshell.SendKeys('^n');" ^
  "} else {" ^
    "explorer.exe 'shell:AppsFolder\Claude_pzs8sxrjxfjjc!Claude';" ^
  "}"
exit /b 0
