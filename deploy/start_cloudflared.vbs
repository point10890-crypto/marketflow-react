Option Explicit
Dim objShell
Set objShell = CreateObject("WScript.Shell")
objShell.Run """C:\Users\dynas\AppData\Local\Microsoft\WinGet\Links\cloudflared.exe"" tunnel --config ""C:\Users\dynas\.cloudflared\config.yml"" run 678e9c60-9f8d-4f49-9fba-a49400ef4ca0", 0, False
