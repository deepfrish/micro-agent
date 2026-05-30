import sys
from pathlib import Path
import argparse

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.tools import create_default_registry
from core.agent import ReActAgent

def test_freeweb_direct():
    print("=== Testing freeweb directly ===")
    registry = create_default_registry(include_external=True)
    freeweb_tools = [tool for tool in registry.list_tools() if "freeweb" in tool.source_label().lower()]
    
    if not freeweb_tools:
        print("❌ FreeWeb tools not found. Is freeweb configured or available?")
        return False
        
    print(f"✅ Found FreeWeb tools: {[t.name for t in freeweb_tools]}")
    try:
        search_tool = registry.find_tool("search_and_browse")
        query = "今日科技新闻热点"
        print(f"Calling search_and_browse with query: '{query}'...")
        result = search_tool.run({
            "query": query,
            "maxResults": 2,
            "browseTop": 1,
            "engine": "auto",
        })
        
        preview = str(result)[:1000]
        print("\n--- Result preview ---")
        print(preview)
        print("--- End preview ---\n")
        
        if result and "error" not in str(result).lower()[:100]:
            print("✅ Direct freeweb test: SUCCESS (Able to access external network)")
            return True
        else:
            print("❌ Direct freeweb test: FAILED or returned error.")
            return False
            
    except Exception as e:
        print(f"❌ Error testing freeweb directly: {e}")
        return False

def test_agent_with_freeweb():
    print("\n=== Testing agent with freeweb ===")
    agent = ReActAgent()
    question = "请用search_and_browse工具搜索一下今天的科技类新闻热点，给我简单总结3条。你需要真实去搜索外部网络。"
    print(f"Question to agent: {question}")
    print("Agent is thinking and acting...")
    
    try:
        final_answer = agent.run(question)
        print("\n=== Agent Final Answer ===")
        print(final_answer)
        
        # Check if the tool was actually called by checking the tool trace
        if hasattr(agent, "tool_call_trace"):
            trace = agent.tool_call_trace
            freeweb_called = any("freeweb" in t.lower() for t in trace)
            print("\nTool trace:", trace)
            if freeweb_called:
                print("✅ Agent successfully decided to use freeweb tools.")
            else:
                print("⚠️ Agent finished without using freeweb tools.")
                
        print("✅ Agent test complete.")
        return True
    except Exception as e:
        print(f"❌ Error testing agent with freeweb: {e}")
        return False

def main():
    parser = argparse.ArgumentParser(description="Test FreeWeb MCP access directly and via ReActAgent.")
    args = parser.parse_args()
    
    # Check for correct encoding on Windows
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
            sys.stderr.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

    print("Starting FreeWeb tests...\n")
    success_direct = test_freeweb_direct()
    if not success_direct:
        print("\nSkipping agent test because direct test failed.")
        return
        
    test_agent_with_freeweb()

if __name__ == "__main__":
    main()
