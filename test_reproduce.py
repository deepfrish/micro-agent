import sys
from pathlib import Path
import json

PROJECT_ROOT = Path(r"j:\agent\micro-agent\micro-agent-feat-memory-extraction-and-rag-fixes")
sys.path.insert(0, str(PROJECT_ROOT))

from src.core.tools import create_default_registry
from src.core.conversation import ConversationManager
from src.core.framework import AgentConfig
from src.core.llm_client import DeepSeekClient

def test_run():
    from src.core.tools import _load_dotenv
    _load_dotenv()
    
    registry = create_default_registry()
    print("=== Registered Tools ===")
    for t in registry.list_tools():
        print(t.name)
    print("========================\n")
    
    question = "请在你的工作路径下帮我创建一个叫 hello.txt 的文件，里面写上‘你好，世界！’"
    print(f"User: {question}")
    
    config = AgentConfig(
        provider="openai",
        model="deepseek-chat",
    )
    client = DeepSeekClient(model=config.model)
    manager = ConversationManager(config=config, client=client)
    
    # We will just run ask to see what it outputs
    print("=== Running Pipeline ===")
    session, answer, created_new = manager.ask(question)
    
    print("FINAL ANSWER:")
    print(answer)

if __name__ == "__main__":
    test_run()
