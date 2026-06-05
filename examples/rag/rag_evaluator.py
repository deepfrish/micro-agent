from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.core.rag import KnowledgeBase, QdrantKnowledgeBase
from src.core.llm_client import DeepSeekClient

KB_ROOT = ROOT / "data" / "knowledge_base"

DATASET_PATH = ROOT / "examples" / "rag" / "rag_test_dataset.json"

if DATASET_PATH.exists():
    import json as builtin_json
    with open(DATASET_PATH, "r", encoding="utf-8") as f:
        DATASET = builtin_json.load(f)
else:
    DATASET = []

JUDGE_PROMPT = """You are an expert judge evaluating a Retrieval-Augmented Generation (RAG) system.
You will be provided with:
1. QUESTION: The user's question.
2. GROUND TRUTH: The correct answer based on the company's knowledge base.
3. CONTEXT: The retrieved text chunks from the knowledge base.
4. GENERATED ANSWER: The RAG system's answer.

Please evaluate the RAG system on FOUR metrics, each on a scale of 1 to 5.

Metric 1: Faithfulness (忠实度) - 1 to 5
- Does the GENERATED ANSWER strictly rely only on the CONTEXT?
- Score 5 if it relies purely on the context. Score 1 if it hallucinates or invents facts not in the context.

Metric 2: Answer Relevance (回答相关性) - 1 to 5
- Does the GENERATED ANSWER directly address the QUESTION? Is it accurate compared to the GROUND TRUTH?
- Score 5 if it fully answers the question correctly according to ground truth. Score 1 if it fails to address the question or is entirely wrong.

Metric 3: Context Recall (上下文召回率) - 1 to 5
- Does the retrieved CONTEXT contain all the factual information needed to match the GROUND TRUTH?
- Score 5 if the context contains all necessary facts to form the ground truth answer. Score 1 if the context is completely missing the required facts.

Metric 4: Context Precision/Relevance (上下文精确度) - 1 to 5
- Are the retrieved CONTEXT chunks highly relevant to the QUESTION, without unnecessary noise?
- Score 5 if almost all of the context is highly relevant to the question. Score 1 if the context is mostly irrelevant noise.

Output your response strictly as a JSON object with the following format without any markdown wrappers or code block formatting if possible. Just the JSON.
{
    "faithfulness_score": <int>,
    "faithfulness_reasoning": "<string>",
    "answer_relevance_score": <int>,
    "answer_relevance_reasoning": "<string>",
    "context_recall_score": <int>,
    "context_recall_reasoning": "<string>",
    "context_precision_score": <int>,
    "context_precision_reasoning": "<string>"
}"""

def extract_json(text: str) -> dict:
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError:
            pass
    return {}

def main() -> None:
    sys.stdout.reconfigure(encoding='utf-8')
    print("=== RAG Evaluation Script (LLM-as-a-Judge) ===")
    
    # Initialize components
    print("Loading Knowledge Base and Indexing into Qdrant...")
    kb = KnowledgeBase.from_directory(KB_ROOT)
    client = DeepSeekClient()
    qdrant_kb = QdrantKnowledgeBase(llm_client=client)
    qdrant_kb.index(kb, recreate=True)
    
    total_faithfulness = 0
    total_relevance = 0
    total_context_recall = 0
    total_context_precision = 0
    valid_evals = 0
    
    for i, data in enumerate(DATASET, 1):
        question = data["question"]
        ground_truth = data["ground_truth"]
        
        print(f"\n[{i}/{len(DATASET)}] Evaluating Question: {question}")
        
        # 1. Retrieval
        context = qdrant_kb.format_context(question, top_k=5, strategy="base")
        if not context or context == "No relevant context found.":
            context = "NO CONTEXT RETRIEVED"
            
        import time
        max_retries = 3
        
        # 2. Generation
        generation_prompt = (
            "Relevant knowledge-base context. You MUST strictly adhere to the information provided here. "
            "If the context contains specific numbers, dates, or policies, use them exactly as written "
            "and DO NOT override them with your pre-trained knowledge or general laws:\n"
            f"{context}"
        )
        messages = [
            {"role": "system", "content": generation_prompt},
            {"role": "user", "content": question}
        ]
        
        answer = None
        for attempt in range(max_retries):
            try:
                answer = client.chat(messages, temperature=0.1)
                break
            except Exception as e:
                time.sleep(2)
                
        if not answer:
            print("  -> ERROR: Failed to generate answer after retries.")
            continue
        
        # 3. LLM-as-a-Judge Evaluation
        eval_content = (
            f"QUESTION: {question}\n\n"
            f"GROUND TRUTH: {ground_truth}\n\n"
            f"CONTEXT:\n{context}\n\n"
            f"GENERATED ANSWER:\n{answer}"
        )
        eval_messages = [
            {"role": "system", "content": JUDGE_PROMPT},
            {"role": "user", "content": eval_content}
        ]
        
        eval_response = None
        for attempt in range(max_retries):
            try:
                eval_response = client.chat(eval_messages, temperature=0.1)
                break
            except Exception as e:
                time.sleep(2)
                
        if not eval_response:
            print("  -> ERROR: Failed to evaluate after retries.")
            continue
        
        scores = extract_json(eval_response)
        if not scores:
            print("  -> ERROR: Failed to parse LLM judge response.")
            continue
            
        f_score = scores.get("faithfulness_score", 0)
        a_score = scores.get("answer_relevance_score", 0)
        cr_score = scores.get("context_recall_score", 0)
        cp_score = scores.get("context_precision_score", 0)
        
        total_faithfulness += f_score
        total_relevance += a_score
        total_context_recall += cr_score
        total_context_precision += cp_score
        valid_evals += 1
        
        print(f"  -> Generated Answer Length: {len(answer)} chars")
        print(f"  -> Faithfulness: {f_score}/5 ({scores.get('faithfulness_reasoning')})")
        print(f"  -> Answer Relevance: {a_score}/5 ({scores.get('answer_relevance_reasoning')})")
        print(f"  -> Context Recall: {cr_score}/5 ({scores.get('context_recall_reasoning')})")
        print(f"  -> Context Precision: {cp_score}/5 ({scores.get('context_precision_reasoning')})")
        
    if valid_evals > 0:
        print("\n=== Evaluation Results ===")
        print(f"Average Faithfulness: {total_faithfulness / valid_evals:.2f} / 5.0")
        print(f"Average Answer Relevance: {total_relevance / valid_evals:.2f} / 5.0")
        print(f"Average Context Recall: {total_context_recall / valid_evals:.2f} / 5.0")
        print(f"Average Context Precision: {total_context_precision / valid_evals:.2f} / 5.0")
    else:
        print("\nNo valid evaluations completed.")

if __name__ == "__main__":
    main()
