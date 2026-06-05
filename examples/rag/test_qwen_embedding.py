import os
import sys
from pathlib import Path

# Setup paths
PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

from src.core.rag import QdrantKnowledgeBase, QwenEmbeddingModel

def test():
    try:
        model = QwenEmbeddingModel()
        print(f"[OK] Successfully initialized QwenEmbeddingModel.")
        print(f"Model dimensions (default): {model.dimensions}")
        print(f"URL: {model.url}")
        
        # Try to embed a simple text
        print("Requesting embedding for 'Hello, world!'...")
        vector = model.embed("Hello, world!")
        
        print(f"[OK] Successfully retrieved vector of size: {len(vector)}")
        print(f"Updated Model dimensions: {model.dimensions}")
        
    except Exception as e:
        print(f"[ERROR] Failed to test QwenEmbeddingModel: {e}")
        
    print("\n--- Testing QdrantKnowledgeBase auto-initialization ---")
    try:
        kb = QdrantKnowledgeBase()
        print(f"KnowledgeBase using embedding model: {kb.embedding_model.__class__.__name__}")
        print(f"Dimensions configured for Qdrant Vector Store: {kb.vector_store.dimensions}")
    except Exception as e:
        print(f"[ERROR] Failed to initialize QdrantKnowledgeBase: {e}")

if __name__ == "__main__":
    test()
