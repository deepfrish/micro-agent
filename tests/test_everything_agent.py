import sys
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.core.tools import ToolRegistry
from src.core.agent import ReActAgent
from src.core.protocols.mcp.client import load_mcp_tools, MCPServerConfig

def test_everything_agent():
    print("\n=== Testing Agent with Everything MCP ===")
    cmd = "npx.cmd" if sys.platform == "win32" else "npx"
    everything_tools = load_mcp_tools(MCPServerConfig(command=[cmd, "-y", "everything-mcp"]), provider_name="everything")
    
    if not everything_tools:
        print("❌ Failed to load Everything tools.")
        return False
        
    print(f"✅ Loaded {len(everything_tools)} tools from Everything MCP.")
    agent = ReActAgent()
    agent.tool_registry.register_tools(everything_tools)
    
    question = "What is the capital of France?"  # Very simple question, everything-mcp has lots of tools like echo, but maybe we just ask it to use echo.
    question = "Please use the 'echo' tool from the Everything MCP to echo the word 'Antigravity'."
    print(f"Question to agent: {question}")
    
    try:
        final_answer = agent.run(question)
        print("\n=== Agent Final Answer ===")
        print(final_answer)
        
        if hasattr(agent, "tool_call_trace"):
            trace = agent.tool_call_trace
            if trace:
                print("✅ Agent successfully used Everything tools:", trace)
                return True
            else:
                print("⚠️ Agent finished without using tools.")
                return False
    except Exception as e:
        print(f"❌ Error testing Everything agent: {e}")
        return False

if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
            sys.stderr.reconfigure(encoding="utf-8", errors="replace")
        except:
            pass
            
    print("Starting Everything MCP Test...\n")
    test_everything_agent()
