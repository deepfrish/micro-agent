import os
import re

def process_dir(directory, old_str, new_str):
    for root, _, files in os.walk(directory):
        for file in files:
            if file.endswith(".py"):
                path = os.path.join(root, file)
                with open(path, 'r', encoding='utf-8') as f:
                    content = f.read()
                
                new_content = content.replace(old_str, new_str)
                if new_content != content:
                    with open(path, 'w', encoding='utf-8') as f:
                        f.write(new_content)
                    print(f"Updated {path}")

base = r"j:\agent\micro-agent\micro-agent-feat-memory-extraction-and-rag-fixes\src"
process_dir(os.path.join(base, "core"), "parents[1]", "parents[2]")
process_dir(os.path.join(base, "coder"), "parents[2]", "parents[3]")
