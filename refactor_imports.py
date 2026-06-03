import os
import re

ROOT_DIR = r"j:\agent\micro-agent\micro-agent-feat-memory-extraction-and-rag-fixes"

REPLACEMENTS = [
    (r'^(from|import)\s+core(\s|\.)', r'\1 src.core\2'),
    (r'^(from|import)\s+coder(\s|\.)', r'\1 src.coder\2'),
    (r'^(from|import)\s+langchain_core(\s|\.)', r'\1 src.langchain_core\2'),
    (r'^(from|import)\s+langgraph(\s|\.)', r'\1 src.langgraph\2'),
    (r'^(from|import)\s+mcp_servers(\s|\.)', r'\1 tools.mcp_servers\2'),
    (r'^(from|import)\s+skills(\s|\.)', r'\1 tools.skills\2'),
]

# Compile regexes
compiled = [(re.compile(pattern, re.MULTILINE), replacement) for pattern, replacement in REPLACEMENTS]

def process_file(filepath):
    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()

    new_content = content
    for pattern, replacement in compiled:
        new_content = pattern.sub(replacement, new_content)

    if new_content != content:
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(new_content)
        print(f"Updated {filepath}")

for root, _, files in os.walk(ROOT_DIR):
    for file in files:
        if file.endswith(".py"):
            process_file(os.path.join(root, file))

print("Import replacement complete.")
