# PPT AI Automation

基于 FastAPI + Dify API 的 YAML 驱动 PPT 模板自动填充系统。用户选择模板、填写表单，系统按依赖顺序调用 LLM 生成各占位符内容，支持多轮对话调整，最终导出填充好的 PPTX 文件。

## 核心流程

```
选择模板 → 填写表单（元数据） → AI 按依赖顺序生成内容 → 多轮对话调整 → 导出 PPTX
```

| 阶段 | 用户操作 | 系统行为 |
|------|---------|---------|
| 选择模板 | 下拉框选择内置模板 | 加载 YAML 配置，渲染表单和 AI 模块 |
| 填写表单 | 填写机种、制程、问题描述等 | 数据存前端，暂不发请求 |
| AI 生成 | 点击"确认并生成" | 按依赖图逐个调用 Dify API 生成各占位符内容 |
| 多轮对话 | 在聊天框继续提问 | 带上下文再次调用 Dify，优化生成内容 |
| 导出 | 点击"导出" | 合并用户输入 + AI 结果，填入模板，输出 PPTX |

## 前置依赖

- Docker + Docker Compose
- 一个可用的 [Dify](https://github.com/langgenius/dify) API 实例（需要有 `chat-messages` 接口）

## 环境变量

复制 `.env.example` 为 `.env`，填入实际配置：

```bash
cp .env.example .env
```

| 变量 | 必填 | 说明 |
|------|------|------|
| `DIFY_API_KEY` | 是 | Dify 应用的 API Key |
| `DIFY_BASE_URL` | 是 | Dify API 地址，如 `http://192.168.1.100:3001/v1` |
| `SILICONFLOW_API_KEY` | 否 | 仅用于 RAGAS 测试评估，运行服务不需要 |
| `SILICONFLOW_BASE_URL` | 否 | 同上 |
| `SILICONFLOW_MODEL` | 同上 | 同上 |

> 如果未配置 `DIFY_API_KEY`，系统会使用离线 stub 返回测试占位内容，方便本地调试前端。

## 启动服务

```bash
# 构建并启动
docker compose up -d

# 查看日志
docker compose logs -f

# 停止服务
docker compose down
```

服务启动后访问 `http://localhost:3001`。

## 挂载说明（调试用）

`docker-compose.yml` 将宿主机文件直接映射进容器，修改代码无需重建镜像：

| 宿主机路径 | 容器路径 | 说明 |
|-----------|---------|------|
| `./core` | `/app/core` | 核心逻辑（PPT 引擎、LLM 调用、Prompt 构建等） |
| `./models` | `/app/models` | Pydantic 数据模型 |
| `./static` | `/app/static` | 前端页面（HTML + JS） |
| `./templates` | `/app/templates` | PPT 模板文件 + YAML 配置 |
| `./main.py` | `/app/main.py` | FastAPI 入口 |
| `./.env` | `/app/.env` | 环境变量（只读挂载） |

**生效规则：**

- 修改 `core/`、`models/`、`main.py` → 需要重启容器：`docker compose restart`
- 修改 `static/`、`templates/` → 刷新浏览器即可生效

## 项目结构

```
ppt_AI_automation/
├── main.py                  # FastAPI 入口，定义所有 API 路由
├── core/
│   ├── ppt_core.py          # PPT 引擎：占位符扫描、文本填充、导出
│   ├── llm_engine.py        # LLM 调用：封装 Dify Chat API，支持多轮对话
│   ├── prompt_builder.py    # Prompt 构建：Jinja2 渲染 YAML 中的 prompt 模板
│   ├── yaml_loader.py       # YAML 加载：解析 templates/*.yaml 配置
│   └── rag_stub.py          # RAG 预留接口（当前为空实现）
├── models/
│   └── schemas.py           # Pydantic 模型：GenerateRequest、ExportRequest 等
├── static/
│   ├── index.html           # 前端页面
│   └── app.js               # 前端逻辑：模板选择、表单渲染、AI 对话、导出
├── templates/
│   ├── *.pptx               # PPT 模板文件
│   └── *.yaml               # 模板配置（定义表单字段、AI 任务、Prompt、依赖关系）
├── .env.example             # 环境变量模板
├── Dockerfile               # Docker 镜像定义
├── docker-compose.yml       # Docker Compose 编排
└── requirements.txt         # Python 依赖
```

## 添加新模板

新增模板只需两步，不需要改任何代码：

1. **准备 PPTX 模板** — 在 `templates/` 下放置 `.pptx` 文件，用 `{PLACEHOLDER_NAME}` 格式标记需要填充的占位符
2. **编写 YAML 配置** — 在 `templates/` 下创建同名 `.yaml` 文件，定义：
   - `template_id` / `template_name` — 模板标识和显示名称
   - `ppt_file_path` — 对应的 PPTX 文件名
   - `user_inputs` — 用户需要填写的表单字段
   - `llm_tasks` — AI 生成任务（含 prompt 模板和目标占位符）
   - `closure_tasks` — 收尾任务（基于前面 AI 输出的补充生成）
   - `direct_mappings` — 用户输入直接填入的占位符（不经 AI）

YAML 中的 prompt 支持 Jinja2 变量，`{{metadata}}` 会被替换为用户填写的元数据，`{{context_*}}` 会被替换为上游 AI 任务的输出，实现任务间的内容传递和依赖。

## 技术栈

| 组件 | 作用 |
|------|------|
| FastAPI | Web 框架，提供 REST API |
| Uvicorn | ASGI 服务器 |
| Jinja2 | Prompt 模板渲染 |
| lxml | 解析 PPTX 的 XML，替换占位符并保留原始格式（字体、颜色、大小） |
| PyYAML | 加载模板配置文件 |
| Pydantic | 请求参数校验 |
| Requests | 调用 Dify API |
| python-dotenv | 加载 `.env` 环境变量 |

## 架构

```
┌─────────────────────────────────────────────────────────────┐
│                    YAML 模板定义层                            │
│                   templates/*.yaml                           │
│                                                             │
│  llm_tasks[0]  ──▶  llm_tasks[1]  ──▶  llm_tasks[2]  ──▶  │
│  问题分析            根本原因            围堵措施             │
│  {{metadata}}       {{metadata}}       {{metadata}}         │
│  {{issue_desc}}     {{context_ISSUE_*}} {{context_ROOT_*}}  │
└────────────────────────────┬────────────────────────────────┘
                             ▼
┌─────────────────────────────────────────────────────────────┐
│                    main.py /api/generate                     │
│                                                             │
│  user_inputs + context（上游输出）                            │
│        ↓                                                    │
│  Jinja2 渲染 prompt                                          │
│        ↓                                                    │
│  注入免责声明（首次生成）+ RAG 知识库（如启用）                  │
│        ↓                                                    │
│  拼接 system_prompt → 发送 Dify Chat API                     │
└─────────────────────────────────────────────────────────────┘
```
