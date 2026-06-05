import os
import sys
import json
from pathlib import Path

# MarketFlow 패키지 경로를 path에 추가하여 hermes_bridge 임포트 보장
sys.path.append(str(Path(__file__).resolve().parents[1]))
try:
    from app.services.mirofish.hermes_bridge import build_hermes_mcp_manifest
    manifest = build_hermes_mcp_manifest()
    mcp_config = manifest.get("hermes_config_yaml", {}).get("mcp_servers", {}).get("marketflow_mirofish", {})
    print("Loaded configuration from hermes_bridge successfully.")
except Exception as e:
    print(f"Error loading hermes_bridge: {e}")
    # Fallback config
    mcp_config = {
        "command": "C:/bitman_marketfloww/.venv/Scripts/python.exe",
        "args": ["C:/bitman_marketfloww/mirofish_mcp_server.py", "--transport", "stdio"],
        "env": {"PYTHONIOENCODING": "utf-8", "HOME_SERVER": "1"},
        "timeout": 60,
        "connect_timeout": 20,
        "supports_parallel_tool_calls": False,
        "tools": {"resources": True, "prompts": False}
    }

# config.yaml 경로 설정 (Windows 기준)
user_home = Path.home()
hermes_dir = user_home / ".hermes"
config_path = hermes_dir / "config.yaml"

# .hermes 디렉토리가 없으면 생성
hermes_dir.mkdir(parents=True, exist_ok=True)

# yaml 모듈 사용 시도
has_yaml = False
try:
    import yaml
    has_yaml = True
except ImportError:
    print("PyYAML not found, using raw text matching for injection.")

if has_yaml:
    config_data = {}
    if config_path.exists():
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                config_data = yaml.safe_load(f) or {}
        except Exception as e:
            print(f"Error reading existing config.yaml: {e}")
            config_data = {}
    
    if "mcp_servers" not in config_data:
        config_data["mcp_servers"] = {}
    
    # 설정 병합 및 주입
    config_data["mcp_servers"]["marketflow_mirofish"] = mcp_config
    
    try:
        with open(config_path, "w", encoding="utf-8") as f:
            yaml.safe_dump(config_data, f, default_flow_style=False, allow_unicode=True)
        print(f"Successfully integrated MarketFlow MCP to {config_path} using PyYAML.")
    except Exception as e:
        print(f"Error writing config.yaml: {e}")
else:
    # PyYAML이 없는 경우 문자열 파싱/추가
    if not config_path.exists():
        content = "mcp_servers:\n"
    else:
        with open(config_path, "r", encoding="utf-8") as f:
            content = f.read()
            
    if "marketflow_mirofish" in content:
        print("marketflow_mirofish config already exists in config.yaml. Verification required.")
    else:
        # 텍스트 블록 빌드
        mcp_block = f"\n  marketflow_mirofish:\n"
        mcp_block += f"    command: \"{mcp_config['command'].replace('\\\\', '/')}\"\n"
        mcp_block += f"    args:\n"
        for arg in mcp_config['args']:
            mcp_block += f"      - \"{arg.replace('\\\\', '/')}\"\n"
        mcp_block += f"    env:\n"
        for k, v in mcp_config['env'].items():
            mcp_block += f"      {k}: \"{v}\"\n"
        mcp_block += f"    timeout: {mcp_config.get('timeout', 60)}\n"
        mcp_block += f"    connect_timeout: {mcp_config.get('connect_timeout', 20)}\n"
        mcp_block += f"    supports_parallel_tool_calls: false\n"
        mcp_block += f"    tools:\n"
        mcp_block += f"      resources: true\n"
        mcp_block += f"      prompts: false\n"
        
        if "mcp_servers:" not in content:
            content += "mcp_servers:\n"
            
        parts = content.split("mcp_servers:\n")
        new_content = parts[0] + "mcp_servers:\n" + mcp_block + parts[1]
        
        with open(config_path, "w", encoding="utf-8") as f:
            f.write(new_content)
        print(f"Successfully integrated MarketFlow MCP to {config_path} using text replacement.")
