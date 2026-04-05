# KG-skills

面向威胁情报知识图谱（Threat Intelligence KG）的 Agentic Skills 集合。

## 项目目标

将威胁情报输入（报告文本、IOC 列表、结构化 JSON）转换为可落库的知识图谱结果，支持以下流程：

1. 实体/关系/证据抽取
2. IOC 校验与归一化
3. Neo4j 映射与 Cypher 生成

## 目录结构

```text
skills/
  threat-intel-kg-agentic/   # 主控编排 skill（只负责调用与流程）
  ti-llm-extract/            # 抽取 skill（实体/关系/证据）
  ti-ioc-tool/               # IOC 处理 skill（校验/归一/去重）
  ti-neo4j-ingest/           # 入库 skill（Neo4j 映射/Cypher）
```

每个 skill 均包含：

- `SKILL.md`：能力说明与执行规范
- `agents/openai.yaml`：UI 元信息（显示名、简述、默认提示词）

## Skills 说明

### 1) `threat-intel-kg-agentic`

- 职责：流程编排，不承载具体业务规则。
- 调用顺序：`ti-llm-extract -> ti-ioc-tool -> ti-neo4j-ingest`
- 输出：聚合 `entities/relations/evidence/iocs/cypher/stats/errors`

### 2) `ti-llm-extract`

- 职责：从文本提取实体、关系和证据。
- 重点：本体白名单、证据绑定、关系有效性校验、置信度打分。

### 3) `ti-ioc-tool`

- 职责：IOC 类型识别、合法性校验、归一化、去重。
- 重点：输出 `iocs` 与 `invalid_iocs`，为入图提供质量控制。

### 4) `ti-neo4j-ingest`

- 职责：将结构化结果映射为 Neo4j 节点/关系并生成幂等 Cypher。
- 重点：约束建议、主键策略、低置信关系过滤、失败降级。

## 快速使用建议

1. 需要端到端执行时，优先触发 `threat-intel-kg-agentic`。
2. 仅做局部任务时，直接调用对应功能 skill：
   - 抽取：`ti-llm-extract`
   - IOC 清洗：`ti-ioc-tool`
   - 入库：`ti-neo4j-ingest`

## 设计原则

- 主控只编排，不下沉业务规则。
- 具体规则全部放到功能 skill，便于独立演进与测试。
- 输出结构尽量统一，降低跨阶段字段对接成本。


## LangGraph Agent（工具 + MCP + Skill）

仓库已新增一个基于 LangGraph 的可运行 Agent，实现以下能力：

- 工具加载：从 `local_tool_modules` 动态加载本地工具
- MCP 加载：从 `mcp_servers` 配置加载 MCP 工具（可选依赖）
- Skill 加载：自动扫描 `skills/*/SKILL.md` 和 `agents/openai.yaml`

### 新增文件

- `pyproject.toml`
- `agent.example.yaml`
- `src/kg_agent/`

### 安装

```bash
pip install -e .
```

如果需要 MCP：

```bash
pip install -e .[mcp]
```

### 配置

复制示例配置：

```bash
cp agent.example.yaml agent.yaml
```

PowerShell：

```powershell
Copy-Item agent.example.yaml agent.yaml
```

关键配置项：

- `model`: 模型名（默认 `deepseek-chat`）
- `skills_dir`: skill 根目录（默认 `skills`）
- `local_tool_modules`: 本地工具模块列表（需暴露 `TOOLS` 或 `get_tools()`）
- `api_base`: OpenAI 兼容接口地址（DeepSeek 默认 `https://api.deepseek.com/v1`）
- `api_key_env`: 模型 API Key 的环境变量名（默认 `DEEPSEEK_API_KEY`）
- `mcp_servers`: MCP server 配置（transport/command/args/env）
- `memory_backend`: LangGraph checkpoint 后端，支持 `memory` / `sqlite` / `redis`
- `redis_url`: 当 `memory_backend=redis` 时必填
- `redis_key_prefix`: Redis checkpoint namespace 前缀
- `redis_ttl_seconds`: checkpoint TTL，单位秒；内部会按分钟向上取整

说明：当 `memory_backend=redis` 时，Redis 是硬依赖。若 `redis_url` 缺失、Redis 不可达或 Redis saver 初始化失败，Agent 会直接构建失败，不会回退到内存模式。

### 启动

先设置环境变量：

```bash
export DEEPSEEK_API_KEY=your_key
```

PowerShell：

```powershell
$env:DEEPSEEK_API_KEY="your_key"
```

单轮调用：

```bash
kg-agent --config agent.yaml --env-file .env --message "列出当前可用skills"
```

交互模式：

```bash
kg-agent --config agent.yaml --env-file .env
```

### Agent 内置 Skill 工具

- `list_skills`: 列出已加载 skills
- `read_skill(skill_name)`: 读取 skill 规范
- `invoke_skill_tool(skill_name, payload_json)`: 执行 skill

说明：若某个 skill 目录下存在 `executor.py` 且暴露 `run(payload)`，`invoke_skill_tool` 会执行真实逻辑；
若不存在 `executor.py`，则自动使用该 skill 的 `SKILL.md` 规范作为系统提示，调用 LLM 执行（llm-from-spec 模式）。



### Tavily 实时搜索工具

内置工具 `tavily_search`，需在环境变量中提供 `TAVILY_API_KEY`。

PowerShell：

```powershell
$env:TAVILY_API_KEY="your_key"
```

示例提问：

```text
请调用 tavily_search 搜索 "latest CVE for OpenSSH"，max_results=5，topic=news
```



## FastAPI Web 管理页面

已提供 FastAPI 后端 + 单页前端，用于：

- 创建 Agent
- 配置 Tool 模块
- 配置 MCP Servers
- 查看/刷新 Skills
- 直接发送聊天消息测试 Agent

### 启动方式

```powershell
pip install -e .[mcp]
kg-agent-web --host 127.0.0.1 --port 8000 --env-file .env
```

打开：`http://127.0.0.1:8000`

### 主要接口

- `GET /api/defaults`
- `GET /api/skills?skills_dir=skills`
- `GET /api/agents`
- `POST /api/agents`
- `GET /api/agents/{agent_id}`
- `PATCH /api/agents/{agent_id}`（重命名线程 / Agent）
- `POST /api/agents/{agent_id}/chat`（非流式）
- `GET /api/agents/{agent_id}/chat/stream?message=...&thread_id=...`（SSE 流式）
- `POST /api/agents/{agent_id}/save`
- `DELETE /api/agents/{agent_id}?purge_conversations=true|false`（默认 `true`，级联清理该线程会话）

### SSE 事件类型

`/api/agents/{agent_id}/chat/stream` 会输出：

- `status`：阶段状态（如 assistant_thinking、tool_execution）
- `tool`：工具调用事件（planned/start/end）
- `token`：模型增量文本
- `error`：错误信息
- `done`：流结束

说明：页面展示的是运行阶段与工具调用动态，不暴露模型私有思维链。




### 持久化记忆

新增配置：

- `memory_backend`: `sqlite` 或 `memory`
- `memory_path`: 当 `memory_backend=sqlite` 时生效，例如 `.kg_agent/checkpoints.sqlite`

说明：

- `sqlite`：会话按 `thread_id` 持久化，服务重启后可继续上下文
- `memory`：仅进程内内存，重启后丢失


### TS 前端开发（Vite + React）

前端已迁移到 `frontend/`（TypeScript 架构）。

开发模式：

```powershell
cd frontend
npm install
npm run dev
```

生产构建并由 FastAPI 托管：

```powershell
cd frontend
npm install
npm run build
cd ..
kg-agent-web --host 127.0.0.1 --port 8000 --env-file .env
```

说明：

- 开发时 `vite` 默认运行在 `http://127.0.0.1:5173`
- `vite.config.ts` 已将 `/api` 代理到 `http://127.0.0.1:8000`
- 构建产物在 `frontend/dist`，FastAPI 会优先返回该前端页面

### M5 异步记忆摘要（严格版）

`POST /api/v1/sessions/{session_id}/memory/summarize` 已切换为 `arq + Redis` 队列执行。

需要先启动 Redis 和 worker：

```powershell
# Redis 环境变量（可选，默认 127.0.0.1:6379 db0）
$env:KG_REDIS_HOST="127.0.0.1"
$env:KG_REDIS_PORT="6379"
$env:KG_REDIS_DB="0"

# 启动 worker
kg-agent-worker
```

任务查询接口：

- `GET /api/v1/memory/jobs/{job_id}`
- `GET /api/v1/sessions/{session_id}/memories`

### M6 沙箱执行（严格版）

`POST /api/v1/sandbox/execute` 仅使用 Docker 沙箱执行（`python:3.10-slim`，禁网，内存限制 256m）。

如果 Docker daemon 不可用，接口会返回 `503`。
