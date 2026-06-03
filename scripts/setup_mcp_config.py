import os
import json
import sys
from pathlib import Path

# 获取项目根目录
ROOT = Path(__file__).resolve().parents[1]

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

def main():
    print("=== Micro-Agent MCP 环境初始化 ===")
    
    # 1. 创建相对沙盒工作区
    workspace_dir = ROOT / "data" / "workspace"
    workspace_dir.mkdir(parents=True, exist_ok=True)
    print(f"✅ 成功确保工作区存在: {workspace_dir}")
    
    # 2. 生成适合当前本机的 mcp.json
    mcp_json_path = ROOT / "mcp.json"
    cmd = "npx.cmd" if sys.platform == "win32" else "npx"
    
    mcp_config = {
        "mcpServers": {
            "filesystem": {
                "command": cmd,
                "args": [
                    "-y",
                    "@modelcontextprotocol/server-filesystem",
                    str(workspace_dir.absolute())
                ]
            },
            "everything": {
                "command": cmd,
                "args": [
                    "-y",
                    "everything-mcp"
                ]
            },
            "git": {
                "command": cmd,
                "args": [
                    "-y",
                    "@modelcontextprotocol/server-git"
                ]
            }
        }
    }
    
    with open(mcp_json_path, 'w', encoding='utf-8') as f:
        json.dump(mcp_config, f, indent=2, ensure_ascii=False)
        
    print(f"✅ 成功生成针对本机的 MCP 配置文件: {mcp_json_path}")
    print("\n你可以将此文件（mcp.json）配置到 Cursor 或 Claude Desktop 等支持 MCP 的客户端中，即可开箱即用。")
    print("注意：mcp.json 已经被添加到 .gitignore，不会被提交到远程仓库，以免影响其他人的本地绝对路径。\n")

if __name__ == "__main__":
    main()
