@echo off
setlocal

set "ROOT=%~dp0.."
cd /d "%ROOT%"

set "PYTHONIOENCODING=utf-8"
if "%MIROFISH_MCP_HOST%"=="" set "MIROFISH_MCP_HOST=127.0.0.1"
if "%MIROFISH_MCP_PORT%"=="" set "MIROFISH_MCP_PORT=8766"
if "%MIROFISH_MCP_PATH%"=="" set "MIROFISH_MCP_PATH=/mcp"
if "%MIROFISH_MCP_TRANSPORT%"=="" set "MIROFISH_MCP_TRANSPORT=streamable-http"

".venv\Scripts\python.exe" mirofish_mcp_server.py ^
  --transport "%MIROFISH_MCP_TRANSPORT%" ^
  --host "%MIROFISH_MCP_HOST%" ^
  --port "%MIROFISH_MCP_PORT%" ^
  --path "%MIROFISH_MCP_PATH%"
