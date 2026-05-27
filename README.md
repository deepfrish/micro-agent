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
- DeepSeek-compatible Chat API：封装在 `core/llm_client.py`
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

## 核心目录

- `coder/`：CLI 入口、命令解析、后台记忆 worker
- `core/product/`：面向产品层的封装，建议优先阅读
- `core/`：底层 agent、记忆、RAG、工具、MCP 兼容实现
- `freeweb/`：可选网页工具子模块，供 FreeWeb provider 使用
- `knowledge_base/`：本地 RAG 语料
- `examples/`：演示、调试脚本、轨迹日志

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
