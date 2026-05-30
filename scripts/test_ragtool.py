import os
import sys
from pathlib import Path

# Ensure core can be imported
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core.llm_client import DeepSeekClient
from core.long_term_memory import LongTermMemoryStore
from core.rag import QdrantKnowledgeBase, RAGTool

def test_rag_tool():
    print("=== Testing RAGTool ===")
    
    # 1. Initialize dependencies
    print("1. Initializing components...")
    llm_client = DeepSeekClient()
    qdrant_kb = QdrantKnowledgeBase(llm_client=llm_client)
    memory_store = LongTermMemoryStore()
    
    tool = RAGTool(
        qdrant_kb=qdrant_kb,
        llm_client=llm_client,
        memory_store=memory_store,
        namespace="test_namespace"
    )
    print("Tool initialized successfully.")
    
    # 2. Add Document
    print("\n2. Testing 'add_document' action...")
    csv_path = PROJECT_ROOT / "knowledge_base" / "rag_table_notes.csv"
    if not csv_path.exists():
        print(f"Error: Could not find test file at {csv_path}")
        return
        
    add_result = tool.run({
        "action": "add_document",
        "file_path": str(csv_path)
    })
    print(f"Add document result:\n{add_result}")
    
    if "Error" in add_result or "Warning" in add_result:
        print("Failed to add document properly. Aborting ask test.")
        return
        
    # 3. Ask Question
    print("\n3. Testing 'ask' action...")
    question = "WindowMemory是干什么的？"
    ask_result = tool.run({
        "action": "ask",
        "question": question,
        "strategy": "base"
    })
    print(f"Question: {question}")
    print(f"Answer:\n{ask_result}")
    
    print("\n=== Test Completed ===")

if __name__ == "__main__":
    test_rag_tool()
