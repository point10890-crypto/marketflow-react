Option Explicit
Dim objShell
Set objShell = CreateObject("WScript.Shell")
objShell.Environment("Process")("PYTHONIOENCODING") = "utf-8"
objShell.Environment("Process")("HOME_SERVER") = "1"
objShell.Environment("Process")("MIROFISH_MCP_TRANSPORT") = "streamable-http"
objShell.Environment("Process")("MIROFISH_MCP_HOST") = "127.0.0.1"
objShell.Environment("Process")("MIROFISH_MCP_PORT") = "8765"
objShell.Environment("Process")("MIROFISH_MCP_PATH") = "/mcp"
objShell.CurrentDirectory = "C:\bitman_marketfloww"
objShell.Run "cmd /c .venv\Scripts\python.exe mirofish_mcp_server.py --transport streamable-http --host 127.0.0.1 --port 8765 --path /mcp > logs\mirofish_mcp.out 2> logs\mirofish_mcp.err", 0, False
