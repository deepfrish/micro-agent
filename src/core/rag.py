from __future__ import annotations

import csv
from dataclasses import dataclass, field
import hashlib
import json
import math
import os
import re
from pathlib import Path
import sys
from typing import Any, List, Sequence
import urllib.error
import urllib.parse
import urllib.request
from uuid import NAMESPACE_URL, uuid5

from .tools import Tool, ToolParameter, ParameterInput
from .llm_client import DeepSeekClient
from .long_term_memory import LongTermMemoryStore


PROJECT_ROOT = Path(__file__).resolve().parents[2]
LOCAL_DEPS = PROJECT_ROOT / ".venv_deps"
if LOCAL_DEPS.exists() and str(LOCAL_DEPS) not in sys.path:
    sys.path.insert(0, str(LOCAL_DEPS))

TEXT_EXTENSIONS = {".md", ".txt", ".csv", ".tsv", ".docx", ".pdf", ".xlsx", ".pptx", ".html", ".json"}


def _normalize_text(text: str) -> str:
    return " ".join(text.split()).strip()


def _clean_document_text(text: str) -> str:
    cleaned = text.replace("\r\n", "\n").replace("\r", "\n").strip()
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned


def _load_dotenv() -> None:
    env_path = PROJECT_ROOT / ".env"
    if not env_path.exists():
        return

    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip("'").strip('"')
        if key and key not in os.environ:
            os.environ[key] = value


def _tokenize(text: str) -> List[str]:
    tokens: List[str] = []
    for match in re.finditer(r"[A-Za-z0-9_]+|[\u4e00-\u9fff]", text.lower()):
        token = match.group(0).strip()
        if token and token not in tokens:
            tokens.append(token)
    return tokens


def _read_text_file(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return path.read_text(encoding="utf-8", errors="replace")


_md_instance = None

def _get_markitdown():
    global _md_instance
    if _md_instance is None:
        try:
            from markitdown import MarkItDown
            _md_instance = MarkItDown()
        except ImportError as exc:
            raise RuntimeError("Reading documents requires markitdown. Install it with `pip install markitdown`.") from exc
    return _md_instance


def _read_xlsx(path: Path) -> str:
    """Read an xlsx file directly with openpyxl, bypassing MarkItDown's
    xlsx->HTML->BeautifulSoup pipeline which hangs on large files."""
    try:
        import openpyxl
    except ImportError:
        raise RuntimeError(
            "Reading .xlsx files requires openpyxl. Install it with `pip install openpyxl`."
        )
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    lines: list[str] = []
    for sheet in wb.worksheets:
        lines.append(f"# Sheet: {sheet.title}")
        for row in sheet.iter_rows(values_only=True):
            # Skip rows where every cell is empty
            if all(cell is None or str(cell).strip() == "" for cell in row):
                continue
            lines.append("\t".join("" if cell is None else str(cell) for cell in row))
    wb.close()
    return "\n".join(lines)


def read_document(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix in {".md", ".txt"}:
        return _read_text_file(path)

    # xlsx files are read directly to avoid MarkItDown's xlsx->HTML->bs4 path,
    # which can hang indefinitely on large files due to bs4 version conflicts.
    if suffix == ".xlsx":
        try:
            return _read_xlsx(path)
        except Exception as exc:
            print(f"[WARNING] openpyxl failed for {path}: {exc}")
            return ""

    md = _get_markitdown()
    try:
        result = md.convert(str(path))
        if result and result.text_content:
            return result.text_content
        return ""
    except Exception as exc:
        print(f"[WARNING] MarkItDown conversion failed for {path}: {exc}")
        return ""


def _is_cjk(ch: str) -> bool:
    code = ord(ch)
    return (
        0x4E00 <= code <= 0x9FFF or
        0x3400 <= code <= 0x4DBF or
        0x20000 <= code <= 0x2A6DF or
        0x2A700 <= code <= 0x2B73F or
        0x2B740 <= code <= 0x2B81F or
        0x2B820 <= code <= 0x2CEAF or
        0xF900 <= code <= 0xFAFF
    )

def _approx_token_len(text: str) -> int:
    cjk = sum(1 for ch in text if _is_cjk(ch))
    non_cjk_tokens = len([t for t in text.split() if t])
    return cjk + non_cjk_tokens

def _split_paragraphs_with_headings(text: str) -> List[dict[str, Any]]:
    lines = text.splitlines()
    heading_stack: List[str] = []
    paragraphs: List[dict[str, Any]] = []
    buf: List[str] = []
    
    def flush_buf():
        if not buf:
            return
        content = "\n".join(buf).strip()
        if not content:
            return
        paragraphs.append({
            "content": content,
            "heading_path": " > ".join(heading_stack) if heading_stack else None,
        })
    
    for raw in lines:
        if raw.strip().startswith("#"):
            flush_buf()
            level = len(raw) - len(raw.lstrip('#'))
            title = raw.lstrip('#').strip()
            
            if level <= 0:
                level = 1
            if level <= len(heading_stack):
                heading_stack = heading_stack[:level-1]
            heading_stack.append(title)
            continue
        
        if raw.strip() == "":
            flush_buf()
            buf = []
        else:
            buf.append(raw)
    
    flush_buf()
    
    if not paragraphs:
        paragraphs = [{"content": text.strip(), "heading_path": None}]
    
    return paragraphs

def chunk_text(text: str, chunk_size: int = 800, overlap: int = 120) -> List[dict[str, Any]]:
    cleaned = _clean_document_text(text)
    if not cleaned:
        return []

    paragraphs = _split_paragraphs_with_headings(cleaned)
    chunks: List[dict[str, Any]] = []
    cur: List[dict[str, Any]] = []
    cur_tokens = 0
    i = 0
    
    while i < len(paragraphs):
        p = paragraphs[i]
        p_tokens = _approx_token_len(p["content"]) or 1
        
        if cur_tokens + p_tokens <= chunk_size or not cur:
            cur.append(p)
            cur_tokens += p_tokens
            i += 1
        else:
            content = "\n\n".join(x["content"] for x in cur)
            heading_path = next((x["heading_path"] for x in reversed(cur) if x.get("heading_path")), None)
            
            chunks.append({
                "content": content,
                "heading_path": heading_path,
            })
            
            if overlap > 0 and cur:
                kept: List[dict[str, Any]] = []
                kept_tokens = 0
                for x in reversed(cur):
                    t = _approx_token_len(x["content"]) or 1
                    if kept_tokens + t > overlap:
                        break
                    kept.append(x)
                    kept_tokens += t
                cur = list(reversed(kept))
                cur_tokens = kept_tokens
            else:
                cur = []
                cur_tokens = 0
    
    if cur:
        content = "\n\n".join(x["content"] for x in cur)
        heading_path = next((x["heading_path"] for x in reversed(cur) if x.get("heading_path")), None)
        chunks.append({
            "content": content,
            "heading_path": heading_path,
        })
    
    return chunks


@dataclass(slots=True)
class KnowledgeChunk:
    key: str
    chunk_id: str
    source: str
    text: str
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_context_block(self) -> str:
        return f"[{self.source}#{self.chunk_id}]\n{self.text}"


@dataclass(slots=True)
class SearchHit:
    chunk: KnowledgeChunk
    score: float


class KnowledgeBase:
    """A tiny local RAG corpus with chunking and lexical retrieval."""

    def __init__(self, chunks: Sequence[KnowledgeChunk]) -> None:
        self.chunks = list(chunks)
        self._indexed_terms = {
            chunk.key: set(_tokenize(chunk.text + " " + chunk.source)) for chunk in self.chunks
        }

    @classmethod
    def from_directory(
        cls,
        root: Path,
        *,
        chunk_size: int = 800,
        overlap: int = 120,
    ) -> "KnowledgeBase":
        chunks: List[KnowledgeChunk] = []
        root = Path(root)
        if not root.exists():
            return cls([])

        for path in sorted(root.rglob("*")):
            if not path.is_file() or path.suffix.lower() not in TEXT_EXTENSIONS:
                continue
            text = read_document(path).strip()
            if not text:
                continue

            for index, chunk_info in enumerate(chunk_text(text, chunk_size=chunk_size, overlap=overlap), start=1):
                source = str(path.relative_to(root)).replace("\\", "/")
                content = chunk_info["content"]
                heading_path = chunk_info.get("heading_path")
                if heading_path:
                    content = f"[{heading_path}]\n\n{content}"
                chunks.append(
                    KnowledgeChunk(
                        key=f"{source}::{index:03d}",
                        chunk_id=f"{index:03d}",
                        source=source,
                        text=content,
                        metadata={"path": str(path), "heading_path": heading_path},
                    )
                )

        return cls(chunks)

    def search(self, query: str, top_k: int = 4) -> List[SearchHit]:
        query_tokens = _tokenize(query)
        if not query_tokens:
            return []

        scored: List[SearchHit] = []
        query_text = query.lower()
        for chunk in self.chunks:
            terms = self._indexed_terms.get(chunk.key, set())
            score = sum(1 for token in query_tokens if token in terms)
            if chunk.source.lower() in query_text:
                score += 1
            if any(token in chunk.text.lower() for token in query_tokens if len(token) > 1):
                score += 1
            if score:
                scored.append(SearchHit(chunk=chunk, score=score))

        scored.sort(key=lambda item: (-item.score, item.chunk.source, item.chunk.chunk_id))
        return scored[: max(1, top_k)]

    def format_context(self, query: str, top_k: int = 4) -> str:
        hits = self.search(query, top_k=top_k)
        if not hits:
            return "No relevant context found."
        blocks = [hit.chunk.to_context_block() for hit in hits]
        return "\n\n".join(blocks)

    def sources(self) -> List[str]:
        return sorted({chunk.source for chunk in self.chunks})

    def chunk_count(self) -> int:
        return len(self.chunks)


class HashEmbeddingModel:
    """Deterministic local embedding model for learning vector retrieval."""

    def __init__(self, dimensions: int = 384) -> None:
        self.dimensions = dimensions

    def embed(self, text: str) -> List[float]:
        vector = [0.0] * self.dimensions
        tokens = _tokenize(text)
        if not tokens:
            return vector

        for token in tokens:
            digest = hashlib.blake2b(token.encode("utf-8"), digest_size=8).digest()
            bucket = int.from_bytes(digest[:4], "big") % self.dimensions
            sign = 1.0 if digest[4] % 2 == 0 else -1.0
            vector[bucket] += sign

        norm = math.sqrt(sum(value * value for value in vector))
        if not norm:
            return vector
        return [value / norm for value in vector]


class QwenEmbeddingModel:
    """Qwen (DashScope) text embedding model."""

    def __init__(self, url: str | None = None, api_key: str | None = None, model: str = "text-embedding-v3") -> None:
        _load_dotenv()
        self.url = (url or os.getenv("QANWEN_EMBEDDING_URL") or "https://dashscope.aliyuncs.com/api/v1/services/embeddings/text-embedding/text-embedding").rstrip("/")
        self.api_key = api_key or os.getenv("QANWEN_EMBEDDING_KEY") or os.getenv("QANWEN_API_KEY") or ""
        self.model = model
        self.dimensions = 1024 if "v3" in self.model else 1536
        
        if not self.api_key:
            raise RuntimeError("Missing Qwen API key in .env or environment. Please set QANWEN_EMBEDDING_KEY or QANWEN_API_KEY.")

    def _post_with_retry(
        self,
        texts: List[str],
        text_type: str = "document",
        *,
        timeout: float = 90.0,
        max_retries: int = 3,
    ) -> List[List[float]]:
        """POST a batch of texts to the DashScope embedding API with retry/backoff.
        DashScope supports up to 25 texts per request.
        Returns a list of embedding vectors in the same order as input.
        """
        import time
        payload = {
            "model": self.model,
            "input": {"texts": texts},
            "parameters": {"text_type": text_type},
        }
        data = json.dumps(payload).encode("utf-8")
        last_exc: Exception | None = None
        for attempt in range(max_retries):
            if attempt > 0:
                wait = 2 ** attempt  # 2s, 4s backoff
                print(f"[INFO] Qwen API retry {attempt}/{max_retries - 1} after {wait}s...")
                time.sleep(wait)
            request = urllib.request.Request(
                self.url,
                data=data,
                method="POST",
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {self.api_key}",
                },
            )
            try:
                with urllib.request.urlopen(request, timeout=timeout) as response:
                    body = response.read().decode("utf-8")
                res_json = json.loads(body)
                embeddings = res_json.get("output", {}).get("embeddings", [])
                if not embeddings:
                    raise RuntimeError(f"Unexpected response from Qwen API: {body}")
                # embeddings list is sorted by index field
                embeddings.sort(key=lambda e: e.get("text_index", 0))
                vectors = [e.get("embedding", []) for e in embeddings]
                # Auto-detect dimension from first call
                if vectors and len(vectors[0]) != self.dimensions:
                    self.dimensions = len(vectors[0])
                return vectors
            except urllib.error.HTTPError as exc:
                body = exc.read().decode("utf-8", errors="ignore")
                raise RuntimeError(f"Qwen Embedding API error: {exc.code} {body}") from exc
            except OSError as exc:
                last_exc = exc
        raise RuntimeError(f"Qwen network error after {max_retries} attempts: {last_exc}") from last_exc

    def embed(self, text: str) -> List[float]:
        if not text.strip():
            return [0.0] * self.dimensions
        return self._post_with_retry([text])[0]

    def embed_batch(self, texts: List[str], batch_size: int = 10) -> List[List[float]]:
        """Embed a list of texts efficiently using batched API calls.
        DashScope supports up to 10 texts per request.
        """
        results: List[List[float]] = []
        for i in range(0, len(texts), batch_size):
            batch = texts[i : i + batch_size]
            # Replace empty strings with a single space to avoid API errors
            safe_batch = [t if t.strip() else " " for t in batch]
            vectors = self._post_with_retry(safe_batch)
            results.extend(vectors)
        return results


class QdrantVectorStore:
    def __init__(
        self,
        url: str | None = None,
        api_key: str | None = None,
        collection: str = "micro_agent_rag",
        dimensions: int = 384,
        timeout: float = 60.0,
    ) -> None:
        _load_dotenv()
        self.url = (url or os.getenv("QDRANT_API_URL", "")).rstrip("/")
        self.api_key = api_key or os.getenv("QDRANT_API_KEY", "")
        self.collection = collection
        self.dimensions = dimensions
        self.timeout = timeout
        if not self.url:
            raise RuntimeError("Missing QDRANT_API_URL in .env or environment.")
        if not self.api_key:
            raise RuntimeError("Missing QDRANT_API_KEY in .env or environment.")

    def recreate_collection(self) -> None:
        self._request("DELETE", f"/collections/{self.collection}", allow_404=True)
        self.ensure_collection()

    def ensure_collection(self) -> None:
        payload = {
            "vectors": {
                "size": self.dimensions,
                "distance": "Cosine",
            }
        }
        try:
            self._request("PUT", f"/collections/{self.collection}", payload)
        except RuntimeError as e:
            if "409" in str(e) or "already exists" in str(e).lower():
                pass
            else:
                raise

    def upsert_chunks(self, chunks: Sequence[KnowledgeChunk], embeddings: Sequence[List[float]]) -> None:
        points = []
        for chunk, vector in zip(chunks, embeddings):
            point_id = str(uuid5(NAMESPACE_URL, chunk.key))
            points.append(
                {
                    "id": point_id,
                    "vector": vector,
                    "payload": {
                        "key": chunk.key,
                        "chunk_id": chunk.chunk_id,
                        "source": chunk.source,
                        "text": chunk.text,
                        "metadata": chunk.metadata,
                    },
                }
            )

        if not points:
            return
        self._request(
            "PUT",
            f"/collections/{self.collection}/points?wait=true",
            {"points": points},
        )

    def search(self, vector: List[float], limit: int = 4) -> List[SearchHit]:
        payload = {
            "vector": vector,
            "limit": max(1, limit),
            "with_payload": True,
        }
        data = self._request("POST", f"/collections/{self.collection}/points/search", payload)
        results = data.get("result", [])
        hits: List[SearchHit] = []
        for item in results:
            payload = item.get("payload") or {}
            chunk = KnowledgeChunk(
                key=str(payload.get("key", "")),
                chunk_id=str(payload.get("chunk_id", "")),
                source=str(payload.get("source", "")),
                text=str(payload.get("text", "")),
                metadata=payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {},
            )
            hits.append(SearchHit(chunk=chunk, score=float(item.get("score", 0.0))))
        return hits

    def _request(
        self,
        method: str,
        path: str,
        payload: dict[str, Any] | None = None,
        *,
        allow_404: bool = False,
    ) -> dict[str, Any]:
        data = None if payload is None else json.dumps(payload).encode("utf-8")
        request = urllib.request.Request(
            f"{self.url}{path}",
            data=data,
            method=method,
            headers={
                "Content-Type": "application/json",
                "api-key": self.api_key,
                "Authorization": f"Bearer {self.api_key}",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                body = response.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            if allow_404 and exc.code == 404:
                return {}
            body = exc.read().decode("utf-8", errors="ignore")
            raise RuntimeError(f"Qdrant API error: {exc.code} {body}") from exc
        except OSError as exc:
            raise RuntimeError(f"Qdrant network error: {exc}") from exc
        return json.loads(body) if body else {}


class QdrantKnowledgeBase:
    def __init__(
        self,
        vector_store: QdrantVectorStore | None = None,
        embedding_model: Any | None = None,
        llm_client: Any | None = None,
    ) -> None:
        if embedding_model is None:
            _load_dotenv()
            api_key = os.getenv("QANWEN_EMBEDDING_KEY") or os.getenv("QANWEN_API_KEY")
            if api_key:
                try:
                    embedding_model = QwenEmbeddingModel()
                except Exception as e:
                    print(f"Failed to initialize QwenEmbeddingModel, falling back to HashEmbeddingModel. Error: {e}")
                    embedding_model = HashEmbeddingModel()
            else:
                embedding_model = HashEmbeddingModel()
                
        self.embedding_model = embedding_model
        self.vector_store = vector_store or QdrantVectorStore(dimensions=self.embedding_model.dimensions)
        self.llm_client = llm_client

    def index(self, knowledge_base: KnowledgeBase, *, recreate: bool = False) -> int:
        if recreate:
            self.vector_store.recreate_collection()
        else:
            self.vector_store.ensure_collection()

        texts = [chunk.text for chunk in knowledge_base.chunks]
        # Use batch embedding if available (QwenEmbeddingModel), otherwise fall back one-by-one
        if hasattr(self.embedding_model, "embed_batch"):
            print(f"[INFO] Embedding {len(texts)} chunks in batches...")
            embeddings = self.embedding_model.embed_batch(texts)
        else:
            embeddings = [self.embedding_model.embed(t) for t in texts]
        self.vector_store.upsert_chunks(knowledge_base.chunks, embeddings)
        return len(knowledge_base.chunks)

    def search(self, query: str, top_k: int = 4, strategy: str = "base") -> List[SearchHit]:
        if strategy == "mqe":
            if not getattr(self, "llm_client", None):
                raise ValueError("MQE strategy requires an llm_client initialized in QdrantKnowledgeBase.")
            
            prompt = (
                f"You are an AI assistant. Please generate 3 different but semantically similar versions "
                f"of the following query to help with a search task. Return each on a new line. Query: {query}"
            )
            try:
                response = self.llm_client.chat([{"role": "user", "content": prompt}])
                queries = [q.strip("- \t\n") for q in response.splitlines() if q.strip()]
                queries.append(query)
            except Exception as e:
                print(f"MQE LLM error: {e}")
                queries = [query]
            
            all_hits = {}
            for q in set(queries):
                vector = self.embedding_model.embed(q)
                hits = self.vector_store.search(vector, limit=top_k)
                for hit in hits:
                    if hit.chunk.chunk_id not in all_hits or all_hits[hit.chunk.chunk_id].score < hit.score:
                        all_hits[hit.chunk.chunk_id] = hit
            
            merged_hits = sorted(all_hits.values(), key=lambda x: x.score, reverse=True)
            return merged_hits[:top_k]

        elif strategy == "hyde":
            if not getattr(self, "llm_client", None):
                raise ValueError("HyDE strategy requires an llm_client initialized in QdrantKnowledgeBase.")
            
            prompt = (
                f"You are a helpful expert. Please write a brief, hypothetical document or answer "
                f"that would perfectly answer the following query: {query}"
            )
            try:
                hypothetical_doc = self.llm_client.chat([{"role": "user", "content": prompt}])
            except Exception as e:
                print(f"HyDE LLM error: {e}")
                hypothetical_doc = query
                
            vector = self.embedding_model.embed(hypothetical_doc)
            return self.vector_store.search(vector, limit=top_k)

        else:
            vector = self.embedding_model.embed(query)
            return self.vector_store.search(vector, limit=top_k)

    def format_context(self, query: str, top_k: int = 4, strategy: str = "base") -> str:
        hits = self.search(query, top_k=top_k, strategy=strategy)
        if not hits:
            return "No relevant context found."
        return "\n\n".join(hit.chunk.to_context_block() for hit in hits)


class RAGTool(Tool):
    """
    RAGTool provides end-to-end RAG capabilities.
    Actions supported:
    - 'add_document': Ingests a document from file_path into the vector store.
    - 'ask': Answers a question using the retrieved context from the vector store.
    """

    def __init__(
        self,
        qdrant_kb: QdrantKnowledgeBase | None = None,
        llm_client: Any | None = None,
        memory_store: LongTermMemoryStore | None = None,
        namespace: str = "default",
        source_label: str = "local tool"
    ) -> None:
        super().__init__(
            name="RAGTool",
            description="End-to-end RAG tool for document ingestion and question answering. Action can be 'add_document' or 'ask'.",
            source_label=source_label,
        )
        self.llm_client = llm_client or DeepSeekClient()
        self.qdrant_kb = qdrant_kb or QdrantKnowledgeBase(llm_client=self.llm_client)
        self.memory_store = memory_store
        self.namespace = namespace
        self.default_strategy = "base"

    def run(self, parameters: ParameterInput) -> str:
        normalized = self.normalize_parameters(parameters)
        action = normalized.get("action")

        if action == "add_document":
            file_path = str(normalized.get("file_path") or "").strip()
            if not file_path:
                return "Error: file_path is required for add_document."
            return self._add_document(file_path)
        elif action == "ask":
            question = str(normalized.get("question") or "").strip()
            strategy = str(normalized.get("strategy") or "base").strip()
            if not question:
                return "Error: question is required for ask."
            return self._ask(question, strategy)
        else:
            return f"Error: Unknown action '{action}'. Supported actions are 'add_document' and 'ask'."

    def _add_document(self, file_path: str) -> str:
        path = Path(file_path)
        if not path.exists():
            return f"Error: File not found at {file_path}"
        try:
            if path.is_file():
                text = read_document(path).strip()
                if not text:
                    return f"Warning: No text extracted from {file_path}"

                chunks: List[KnowledgeChunk] = []
                for index, chunk_info in enumerate(chunk_text(text), start=1):
                    source = path.name
                    content = chunk_info["content"]
                    heading_path = chunk_info.get("heading_path")
                    if heading_path:
                        content = f"[{heading_path}]\n\n{content}"
                    chunks.append(
                        KnowledgeChunk(
                            key=f"{source}::{index:03d}",
                            chunk_id=f"{index:03d}",
                            source=source,
                            text=content,
                            metadata={"path": str(path), "heading_path": heading_path},
                        )
                    )
                temp_kb = KnowledgeBase(chunks)
                num_indexed = self.qdrant_kb.index(temp_kb, recreate=False)
                if self.memory_store:
                    self.memory_store.add_record(self.namespace, f"Indexed document '{path.name}' into RAG knowledge base.", kind="note", action="append")
                return f"Successfully ingested document '{path.name}'. Indexed {num_indexed} chunks."
            elif path.is_dir():
                temp_kb = KnowledgeBase.from_directory(path)
                num_indexed = self.qdrant_kb.index(temp_kb, recreate=False)
                if self.memory_store:
                    self.memory_store.add_record(self.namespace, f"Indexed directory '{path.name}' into RAG knowledge base.", kind="note", action="append")
                return f"Successfully ingested directory '{path.name}'. Indexed {num_indexed} chunks."
            else:
                return f"Error: {file_path} is neither a file nor a directory."
        except Exception as e:
            return f"Error ingesting document: {str(e)}"

    def _ask(self, question: str, strategy: str = "base") -> str:
        try:
            context = self.qdrant_kb.format_context(question, top_k=5, strategy=strategy)
            if not context or "No relevant context found" in context:
                return "I couldn't find any relevant information in the knowledge base to answer your question."

            prompt = (
                "You are an intelligent knowledge base assistant. Answer the user's question based ONLY on the provided context.\n"
                "If the context does not contain enough information to answer the question, state that clearly. Do not use outside knowledge.\n\n"
                "Context:\n"
                f"{context}\n\n"
                "Question:\n"
                f"{question}"
            )

            messages = [{"role": "user", "content": prompt}]
            answer = self.llm_client.chat(messages)

            if self.memory_store:
                self.memory_store.add_record(self.namespace, f"Queried RAG for '{question}' using strategy '{strategy}'.", kind="note", action="append")
                
                # Extract semantic knowledge
                extract_prompt = (
                    "Extract the core facts or semantic knowledge points from the following answer to a user's question. "
                    "Output a concise summary of the factual knowledge that an agent should remember for future reference. "
                    "If the answer does not contain meaningful long-term knowledge, return nothing.\n\n"
                    f"Question: {question}\n"
                    f"Answer: {answer}"
                )
                try:
                    knowledge = self.llm_client.chat([{"role": "user", "content": extract_prompt}]).strip()
                    if knowledge and not knowledge.lower().startswith("nothing") and len(knowledge) > 5:
                        self.memory_store.add_record(self.namespace, f"Learned from RAG: {knowledge}", kind="fact", action="append")
                except Exception:
                    pass

            return answer
        except Exception as e:
            return f"Error during question answering: {str(e)}"

    def get_parameters(self) -> Sequence[ToolParameter]:
        return [
            ToolParameter(
                name="action",
                type="string",
                description="The action to perform: 'add_document' or 'ask'.",
                required=True,
            ),
            ToolParameter(
                name="file_path",
                type="string",
                description="The absolute or relative path to the document or directory (required if action is 'add_document').",
                required=False,
            ),
            ToolParameter(
                name="question",
                type="string",
                description="The question to ask based on the ingested documents (required if action is 'ask').",
                required=False,
            ),
            ToolParameter(
                name="strategy",
                type="string",
                description="Advanced retrieval strategy: 'base', 'mqe' (Multi-Query Expansion), or 'hyde' (Hypothetical Document Embeddings). Defaults to 'base'.",
                required=False,
                default="base"
            ),
        ]
