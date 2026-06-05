import json
import random
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.core.rag import KnowledgeBase
from src.core.llm_client import DeepSeekClient

KB_ROOT = ROOT / "data" / "knowledge_base"
OUTPUT_FILE = ROOT / "examples" / "rag" / "rag_test_dataset.json"

TARGET_FILES = {
    "通用企业全场景FAQ知识库_豆包AI生成.xlsx",
    "虚拟SaaS平台技术文档（完整版）.pdf",
    "XX有限公司公司管理制度守则（完整版）.docx"
}

GENERATE_PROMPT = """You are an expert at generating realistic user queries for evaluating Retrieval-Augmented Generation systems.
I will provide you with a text chunk extracted from a company's internal documents.
Your task is to generate ONE realistic user question that can be answered using ONLY this text chunk, and provide the concise Ground Truth answer based ONLY on the chunk.

IMPORTANT: Do not generate questions that are too vague. Ensure the ground truth captures the key factual details.

Please output your response strictly as a JSON object with the following format:
{
    "question": "<realistic user question>",
    "ground_truth": "<concise correct answer derived from the chunk>"
}
"""

def extract_json(text: str) -> dict:
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError:
            pass
    return {}

def main() -> None:
    print("Loading Knowledge Base...")
    kb = KnowledgeBase.from_directory(KB_ROOT)
    
    # Filter chunks
    valid_chunks = []
    for chunk in kb.chunks:
        # chunk.source is a relative path, extract the filename
        filename = Path(chunk.source).name
        if filename in TARGET_FILES:
            valid_chunks.append(chunk)
            
    print(f"Found {len(valid_chunks)} chunks from target files.")
    
    if len(valid_chunks) < 50:
        print(f"Warning: Only {len(valid_chunks)} chunks available, sampling all of them.")
        sampled_chunks = valid_chunks
    else:
        sampled_chunks = random.sample(valid_chunks, 50)
        
    client = DeepSeekClient()
    dataset = []
    
    print(f"Generating dataset with {len(sampled_chunks)} chunks...")
    for i, chunk in enumerate(sampled_chunks, 1):
        print(f"Processing {i}/{len(sampled_chunks)} [Source: {chunk.source}]...")
        
        messages = [
            {"role": "system", "content": GENERATE_PROMPT},
            {"role": "user", "content": f"DOCUMENT CHUNK:\n{chunk.text}"}
        ]
        
        try:
            response = client.chat(messages, temperature=0.7)
            data = extract_json(response)
            if data and "question" in data and "ground_truth" in data:
                # Add context metadata for debugging purposes
                data["source"] = chunk.source
                dataset.append(data)
                print(f"  -> Q: {data['question']}")
            else:
                print("  -> ERROR: Invalid JSON generated")
        except Exception as e:
            print(f"  -> ERROR generating for chunk: {e}")
            
    print(f"Successfully generated {len(dataset)} items.")
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(dataset, f, ensure_ascii=False, indent=2)
        
    print(f"Dataset saved to {OUTPUT_FILE}")

if __name__ == "__main__":
    main()
