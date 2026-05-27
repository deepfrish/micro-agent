from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.rag import KnowledgeBase, QdrantKnowledgeBase


KB_ROOT = ROOT / "knowledge_base"


def main() -> None:
    parser = argparse.ArgumentParser(description="Index and search the RAG knowledge base with Qdrant.")
    parser.add_argument("question", nargs="?", default="RAG 是什么，和 Memory 有什么区别？")
    parser.add_argument("--top-k", type=int, default=3)
    parser.add_argument("--no-reindex", action="store_true", help="Skip indexing and only query Qdrant.")
    parser.add_argument("--recreate", action="store_true", help="Delete and recreate the Qdrant collection before indexing.")
    args = parser.parse_args()

    kb = KnowledgeBase.from_directory(KB_ROOT)
    qdrant_kb = QdrantKnowledgeBase()

    print("Knowledge base root:", KB_ROOT)
    print("Chunk count:", kb.chunk_count())
    print("Sources:")
    for source in kb.sources():
        print("-", source)

    if not args.no_reindex:
        indexed = qdrant_kb.index(kb, recreate=args.recreate)
        print(f"\nIndexed {indexed} chunk(s) into Qdrant.")

    print("\nQuestion:", args.question)
    hits = qdrant_kb.search(args.question, top_k=args.top_k)
    if not hits:
        print("No relevant chunks found.")
        return

    print("\nRetrieved chunks from Qdrant:")
    for hit in hits:
        print(f"\n[{hit.chunk.source}#{hit.chunk.chunk_id}] score={hit.score:.4f}")
        print(hit.chunk.text)

    print("\nRAG context:")
    print(qdrant_kb.format_context(args.question, top_k=args.top_k))


if __name__ == "__main__":
    main()
