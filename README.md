# micro-agent

micro-agent 是一个用于学习和实验的对话式 agent 骨架。它把一次用户请求拆成清晰的运行链路：路由、记忆、RAG、工具调用、退出时记忆整理都能被追踪和阅读。这个仓库的目标是：未来把项目交给 Codex 时，它能快速理解项目结构和 agent 逻辑。

英文版文档保留在 [README.en.md](./README.en.md)。

## 快速开始

```bash
pip install -r requirements.txt
python -m coder
```

项目从根目录 `.env` 读取密钥和服务配置。`.env` 已被 `.gitignore` 忽略，不会上传到 GitHub。

## 入口命令

- `python -m coder`：启动交互式 CLI
- `/new`：新建一个聊天命名空间
- `/exit`：保存当前会话并退出
- `/exit -n`：保存当前会话，但继续留在 CLI
- `/compress`：压缩当前聊天窗口历史
- `/del <namespace>`：删除指定聊天窗口历史
- `/tools`：打印当前可用工具列表
- `/rag <strategy>`：切换当前会话的 RAG 检索策略（支持三种模式：`base` 基础检索、`mqe` 多查询扩展、`hyde` 假设性文档嵌入）
- `/net on|once|off|status`：控制网页/外部工具偏好
- `/your-namespace`：切换到某个会话命名空间
- `python -m coder memory-worker <job.json>`：执行后台记忆整理任务
- `python -m coder mcp-server amap|weather`：启动本地 MCP 工具服务

## 项目文档

- [架构说明](./MICRO_AGENT_ARCHITECTURE.md)
- [English README](./README.en.md)
- [English architecture guide](./MICRO_AGENT_ARCHITECTURE.en.md)

## 技术栈

- Python 3.10+：CLI、agent runtime、记忆管线、本地工具
- DeepSeek-compatible Chat API：封装在 `core/llm_client.py`，并提供专属的 `MemoryLLMClient` 利用 Qwen 小模型进行极低成本的后台记忆归纳抽取
- LangGraph-style 状态机：用于 ReAct 执行流程
- LangChain-style message shim：`langchain_core/` 中提供轻量兼容层
- MCP-style JSON-line 工具协议：用于加载外部工具
- Amap Web Service APIs：天气、地理编码、静态地图、周边搜索、路线、公交
- FreeWeb MCP：公共网页搜索、浏览、内容提取、GitHub 搜索、并行浏览、截图
- 本地 JSON 存储：会话、窗口记忆、全局长期记忆
- 本地 RAG：读取 `knowledge_base/` 中的资料
- 可选 Qdrant 向量检索实验：位于 `core/rag.py`

## 工具体系

micro-agent 有两层工具。

本地工具直接注册在 `core/tools.py`：

- `Calculator`：安全算术表达式计算
- `Now`：获取当前本地日期和时间

外部工具通过 provider 和 MCP 加载：

- `AmapCapabilityProvider` 启动 `python -m coder mcp-server amap`
- `FreeWebProvider` 优先启动本地 `freeweb/dist/index.js`，不存在时回退到 `npx -y freeweb-mcp@latest`

Amap MCP 工具：

- `Weather`
- `Geocode`
- `Regeocode`
- `StaticMap`
- `NearbySearch`
- `InputTips`
- `Route`
- `Bus`

FreeWeb MCP 工具：

- `web_search`
- `search_and_browse`
- `browse_page`
- `smart_browse`
- `deep_search`
- `github_search`
- `github_repo_files`
- `parallel_browse`
- `get_page_links`
- `screenshot`
- `inspect_llms_txt`

## 项目结构

```text
micro-agent/
├── coder/
│   └── cli/
├── core/
│   ├── providers/
│   ├── protocols/
│   └── product/
├── skills/
│   └── engineering-exploration/
├── scripts/
├── examples/
├── knowledge_base/
├── freeweb/
├── langchain_core/
├── langgraph/
└── data/
```

- `coder/`：CLI 入口、命令解析、后台记忆 worker
- `core/`：底层 agent、记忆、RAG、工具和 MCP 兼容实现
- `core/product/`：面向产品层的封装，建议优先阅读
- `core/providers/`：外部能力 provider
- `core/protocols/`：MCP 等协议层实现
- `skills/`：本地能力包目录
- `scripts/`：离线 smoke test 和辅助脚本
- `examples/`：演示、调试脚本、轨迹日志
- `knowledge_base/`：本地 RAG 语料
- `freeweb/`：可选网页工具子模块，供 FreeWeb provider 使用
- `langchain_core/`：轻量 message 兼容层
- `langgraph/`：本地状态机兼容实现
- `data/`：运行时生成的会话、窗口记忆和全局记忆

如果 clone 后缺少 `freeweb/` 子模块，运行：

```bash
git submodule update --init --recursive
```

## 运行模型

- 判断当前输入是记忆更新、直接回答，还是 ReAct 工具调用
- 按需注入工作记忆、长期记忆和本地 RAG 资料
- 通过 LangGraph 风格流程执行：`think -> act -> reflect -> repair/stop`
- 退出会话时整理当前窗口，把窗口摘要合并进长期记忆

## 数据状态

仓库中的 `data/` 目录已经清空。项目运行后会自动重新生成会话、窗口记忆和全局长期记忆文件。
