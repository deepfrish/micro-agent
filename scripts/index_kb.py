import os
import sys
from pathlib import Path

# Setup paths
PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from core.rag import KnowledgeBase, QdrantKnowledgeBase

def main():
    kb_path = PROJECT_ROOT / "knowledge_base"
    print(f"Reading documents from {kb_path}...")
    
    # Initialize knowledge base from directory
    # This will read the PDF and other files, and chunk them
    kb = KnowledgeBase.from_directory(kb_path, chunk_size=800, overlap=120)
    
    print(f"Found {len(kb.sources())} files, resulting in {kb.chunk_count()} chunks.")
    
    print("Initializing QdrantKnowledgeBase with QwenEmbeddingModel...")
    qdrant_kb = QdrantKnowledgeBase()
    print(f"Using Embedding model: {qdrant_kb.embedding_model.__class__.__name__} (dimensions: {qdrant_kb.vector_store.dimensions})")
    
    print("Uploading chunks to Qdrant (recreating collection due to dimension changes)...")
    # recreate=True is required because we changed the embedding dimension from 384 to 1024
    indexed_count = qdrant_kb.index(kb, recreate=True)
    
    print(f"Successfully indexed {indexed_count} chunks to Qdrant!")

if __name__ == "__main__":
    main()
