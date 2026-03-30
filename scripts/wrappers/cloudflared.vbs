Set objShell = CreateObject("WScript.Shell")
objShell.CurrentDirectory = "C:\bitman_marketfloww"
objShell.Run """C:\bitman_marketfloww\cloudflared.exe"" tunnel --config ""C:\Users\dynas\.cloudflared\config.yml"" run bitman-api", 0, True
