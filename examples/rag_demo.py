from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.core.rag import KnowledgeBase


KB_ROOT = ROOT / "knowledge_base"


def main() -> None:
    parser = argparse.ArgumentParser(description="Explore the local RAG knowledge base.")
    parser.add_argument("question", nargs="?", default="RAG 是什么，和 Memory 有什么区别？")
    parser.add_argument("--top-k", type=int, default=3)
    args = parser.parse_args()

    kb = KnowledgeBase.from_directory(KB_ROOT)
    print("Knowledge base root:", KB_ROOT)
    print("Chunk count:", kb.chunk_count())
    print("Sources:")
    for source in kb.sources():
        print("-", source)

    print()
    print("Question:", args.question)
    hits = kb.search(args.question, top_k=args.top_k)
    if not hits:
        print("No relevant chunks found.")
        return

    print("\nRetrieved chunks:")
    for hit in hits:
        print(f"\n[{hit.chunk.source}#{hit.chunk.chunk_id}] score={hit.score}")
        print(hit.chunk.text)

    print("\nRAG context:")
    print(kb.format_context(args.question, top_k=args.top_k))


if __name__ == "__main__":
    main()
