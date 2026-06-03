import sys
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.core.tools import ToolRegistry
from src.core.agent import ReActAgent
from src.core.protocols.mcp.client import load_mcp_tools, MCPServerConfig

def test_amap_agent():
    print("\n=== Testing Agent with Amap MCP ===")
    registry = ToolRegistry()
    amap_tools = load_mcp_tools(MCPServerConfig(command=[sys.executable, "-m", "coder", "mcp-server", "amap"]), provider_name="amap")
    if not amap_tools:
        print("❌ Failed to load Amap tools.")
        return False
        
    agent = ReActAgent()
    agent.tool_registry.register_tools(amap_tools)
    
    question = "请用高德地图MCP查询一下北京现在的天气情况。"
    print(f"Question to agent: {question}")
    
    try:
        final_answer = agent.run(question)
        print("\n=== Agent Final Answer ===")
        print(final_answer)
        
        if hasattr(agent, "tool_call_trace"):
            trace = agent.tool_call_trace
            if trace:
                print("✅ Agent successfully used Amap tools:", trace)
                return True
            else:
                print("⚠️ Agent finished without using tools.")
                return False
    except Exception as e:
        print(f"❌ Error testing Amap agent: {e}")
        return False

def test_fs_agent():
    print("\n=== Testing Agent with Filesystem MCP ===")
    registry = ToolRegistry()
    import os
    workspace_dir = os.path.abspath(os.path.join(ROOT, "data", "workspace"))
    os.makedirs(workspace_dir, exist_ok=True)
    
    cmd = "npx.cmd" if sys.platform == "win32" else "npx"
    fs_tools = load_mcp_tools(MCPServerConfig(command=[cmd, "-y", "@modelcontextprotocol/server-filesystem", workspace_dir]), provider_name="fs")
    
    if not fs_tools:
        print("❌ Failed to load Filesystem tools.")
        return False
        
    agent = ReActAgent()
    agent.tool_registry.register_tools(fs_tools)
    
    question = f"请在 {workspace_dir} 下列出当前的文件，并告诉我有没有名叫 mcp.json 的文件。"
    print(f"Question to agent: {question}")
    
    try:
        final_answer = agent.run(question)
        print("\n=== Agent Final Answer ===")
        print(final_answer)
        
        if hasattr(agent, "tool_call_trace"):
            trace = agent.tool_call_trace
            if trace:
                print("✅ Agent successfully used Filesystem tools:", trace)
                return True
            else:
                print("⚠️ Agent finished without using tools.")
                return False
    except Exception as e:
        print(f"❌ Error testing Filesystem agent: {e}")
        return False

if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
            sys.stderr.reconfigure(encoding="utf-8", errors="replace")
        except:
            pass
            
    print("Starting MCP Coordination Tests...\n")
    test_amap_agent()
    test_fs_agent()
