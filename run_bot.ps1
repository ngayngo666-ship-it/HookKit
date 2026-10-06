# Chạy lại bot két trên Windows (chỉ 1 process main.py).
# Dùng khi đã sửa xong handler/parse — báo user gửi lại tin.
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

Get-CimInstance Win32_Process -Filter "Name = 'python.exe' OR Name = 'python3.exe'" |
  Where-Object { $_.CommandLine -match 'main\.py' } |
  ForEach-Object {
    Write-Host "Dừng PID $($_.ProcessId)"
    Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
  }

Start-Sleep -Seconds 1
if (Test-Path .\.venv\Scripts\python.exe) {
  & .\.venv\Scripts\python.exe main.py
} else {
  python main.py
}
