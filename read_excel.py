import pandas as pd
df = pd.read_excel('j:/agent/micro-agent/micro-agent-feat-memory-extraction-and-rag-fixes/data/knowledge_base/通用企业全场景FAQ知识库_豆包AI生成.xlsx')
pd.set_option('display.max_columns', None)
pd.set_option('display.max_colwidth', None)
filtered = df[df.apply(lambda row: row.astype(str).str.contains('试用期').any(), axis=1)]
with open('temp_excel_out.txt', 'w', encoding='utf-8') as f:
    f.write(filtered.to_string(index=False))
