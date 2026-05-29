1.0项目概览                                                                      
                                                                                
  技术栈： FastAPI + Jinja2 + lxml + Dify API + Tailwind CSS                    
                                                                                
  核心流程：                                                                    
  1. 用户选择 YAML 配置的模板                                                   
  2. 填写 Characterize 表单（元数据）                                           
  3. 系统按依赖顺序调用 LLM 生成各个占位符内容
  4. 用户可以编辑/对话调整 AI 生成的内容                                        
  5. 导出填充好占位符的 PPTX 文件                                               
                                                                                
  优点                                                                          
                                                                                
  1. 模块化架构清晰 — core/ 分离了 PPT 引擎、LLM 调用、YAML 加载、prompt        
  构建，职责分明                                                                
  2. YAML 驱动 — 新增模板只需写 YAML + PPTX，不需要改代码                       
  3. 智能文本分配 — _intelligent_distribute() 保留了原始格式（字体、颜色等）    
  4. 依赖图设计 — 前端 dependencies 确保 ISSUE_ANALYSIS → ROOT_CAUSE →          
  CONTAINMENT → CORRECTIVE 按序生成                                             
  5. RAG 预留 — rag_stub.py 已经为未来知识库检索做好了接口                      
                                                                                
  可以改进的地方  
                                                                                
  1. 会话管理 — _conversation_ids 用全局 dict 存，多用户会冲突                  
  2. 错误处理 — Dify API 调用失败时返回的错误信息可以更结构化
  3. 类型提示 — 部分函数缺少返回类型注解                                        
  4. 测试覆盖 — test/ 目录有测试脚本，但没有用 pytest 框架                      
                                                                                
  总结                                                                          
                                                                                
  这是一个很实用的工具，特别适合制造业的 FACA                                   
  报告生成场景。架构上已经考虑了扩展性（加 docx
  输出、加新模板都很简单），是一个完成度较高的项目。

 
 1.1 从
 
 
 renderCharacterize(currentConfig.user_inputs || []);
  renderAIModules(currentConfig.llm_tasks || []);
  renderClosure(currentConfig.closure_tasks || []);

  这三行就是"遍历 YAML 配置动态拼 HTML"的入口。具体：

  renderCharacterize()（app.js:83）— 遍历 user_inputs 数组，对每个元素调 buildFieldHTML()
  生成表单控件，appendChild 到 DOM。
  renderAIModules()（app.js:146）— 遍历 llm_tasks 数组，先按 module 字段分组，再对每个 task 调
   renderAITask() 生成聊天对话框。
  renderClosure()（app.js:408）— 遍历 closure_tasks 数组，对每个 task 也调 renderAITask()
  生成聊天对话框。

  --------------------------------------------

数据流

前端用户输入最终也是 JSON，和测试数据结构一样。整个链路是这样的：

  用户在前端做了什么

  1. 选模板 → 下拉框选 "5C 异常处理报告"
  2. 填 Characterize 表单 → 填 radar_no、issue_title、issue_description 等
  3. 点"确认并生成" → 触发 handleCharacterizeConfirm()（app.js:228）

  前端发出的请求

  点"确认并生成"后，前端不是发一个大 JSON 给后端一次性处理，而是对 llm_tasks 里的每个 task
  逐个调 /api/generate：

  // app.js:274 - 循环 5 次（5 个 llm_tasks）
  for (const task of tasks) {
      await fetch("/api/generate", {
          method: "POST",
          body: JSON.stringify({
              template_id: "5c_report_v1",
              placeholder_key: task.target_placeholder,  // 每次不同
              message: "请根据上述信息自动生成内容",
              history: [],
              user_inputs: {                              // 每次都带完整 userInputs
                  radar_no: "RDR-2026-0412",
                  issue_title: "HSG Discoloration",
                  issue_description: "EVT阶段发现...",
                  ...
              }
          })
      })
  }

  后端做了什么（main.py:98-142）

  每次收到 /api/generate 请求：

  placeholder_key + user_inputs
      ↓
  在 YAML 的 llm_tasks / closure_tasks 里找匹配的 task
      ↓
  build_prompt(task.prompt, user_inputs) → 渲染 Jinja2
      ↓
  generate_content() → 调 Dify API
      ↓
  返回 {ack, content}

  导出时

  用户对 AI 生成的内容满意后（或手动编辑后），点"导出"，前端调 POST /api/export：

  {
      template_id: "5c_report_v1",
      user_inputs: { ... },        // Characterize 的直填数据
      final_data: {                 // AI 生成 + 用户编辑后的最终内容
          "Fill in list of containment actions": "...",
          "Fill in list of root cause": "...",
          ...
      }
  }

  后端把 user_inputs 通过 direct_mappings 填入对应占位符，final_data 直接填入，然后输出 PPTX。

  总结

  ┌──────────────┬──────────────────┬─────────────────────────────┬───────────────────────┐
  │     阶段     │     用户操作     │         前端发什么          │      后端做什么       │
  ├──────────────┼──────────────────┼─────────────────────────────┼───────────────────────┤
  │ Characterize │ 填表单           │ 无请求，存本地状态          │ 无                    │
  ├──────────────┼──────────────────┼─────────────────────────────┼───────────────────────┤
  │ AI 生成      │ 点"确认并生成"   │ N 次 /api/generate（N=task  │ 渲染 prompt → 调 Dify │
  │              │                  │ 数）                        │                       │
  ├──────────────┼──────────────────┼─────────────────────────────┼───────────────────────┤
  │ 多轮对话     │ 在聊天框继续对话 │ 再次 /api/generate（带      │ 带上下文调 Dify       │
  │              │                  │ history）                   │                       │
  ├──────────────┼──────────────────┼─────────────────────────────┼───────────────────────┤
  │ 导出         │ 点"导出"         │ 1 次 /api/export            │ 合并数据 → 填模板 →   │
  │              │                  │                             │ 输出 PPTX             │
  └──────────────┴──────────────────┴─────────────────────────────┴───────────────────────┘

  没有"分解"这一步 — 分解是 YAML 模板提前定义好的，后端只是按配置逐个执行。

----------------------------------------------

更改输出格式

整个架构的输出格式只在一个地方耦合：

  和输出格式相关的只有一层

  YAML 配置 + 用户输入 → prompt 构建 → Dify API → {placeholder: content} → 填入模板
                                                          ↑
                                                    这一步之前完全通用

  content_map 就是个 dict[str, str]，跟 PPT 没有任何关系。生成 PPT 的逻辑全部封装在
  core/ppt_core.py 的 export_single_slide() 里。

  改成 Docs 要动什么

  加一个 core/docs_core.py — 实现 export_single_doc(template_path, content_map) ->
  bytes，把占位符填入 .docx 模板（用 python-docx 库）
  YAML 加一个字段 — 比如 output_format: "docx"，区分用哪个导出器
  /api/export 路由 — 根据 output_format 调 ppt_core 或 docs_core
  模板文件 — 提供 .docx 模板代替 .pptx

  AI 生成部分、用户输入收集、prompt 构建、对话管理 — 一行都不用改。

  本质上这个程序是个"AI 内容生成 + 模板填充"的框架，PPT 只是当前选的填充目标而已。


  ---------------------------------------------------------------

  测试生成内容

    指标: context_recall
  RAGAS 函数: ragas.metrics.context_recall
  评什么: 检索质量
  怎么评: 把 ground_truth 拆成多条 claim，检查 Dify 检索命中的 contexts 覆盖了多少条 claim
  ────────────────────────────────────────
  指标: answer_correctness
  RAGAS 函数: ragas.metrics.answer_correctness
  评什么: 生成质量
  怎么评: 把 AI 生成的 answer 和 ground_truth 做语义相似度 + 事实一致性对比

  ----------------------------------------------------------------

  ground_truth_reports.json 在流程里扮演两个完全独立的角色：

  ground_truth_reports.json
          │
          ├── metadata + problem_description ──→ 构建 prompt ──→ Dify API
          │                                                          │
          │                                                          ▼
          │                                                     Dify 生成的内容
          │                                                          │
          └── sections（root_cause, containment...）                  │
                      │                                              │
                      │         ┌────────────────────────────────────┘
                      ▼         ▼
                  RAGAS 对比：Dify 生成 vs 人工标准答案

  Dify 只收到 metadata + problem_description，不会看到 sections。

  举例：
  - Dify 的输入："问题标题：J70x HSG RC 內腔結構過銑", "製程：金加（CNC）",
  "问题描述：08/19..."
  - Dify 的输出：AI 生成的根本原因、围堵措施等
  - Ground Truth：人工写的 "CNC機台T3開粗刀把夾屑..."（只用来对比打分，不发给 Dify）

  ----------------------------------------------------------------

  Prompt 拼接架构图

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                          YAML 模板定义层                                      │
│                         templates/*.yaml                                    │
│                                                                             │
│  ┌──────────────┐    ┌──────────────┐    ┌──────────────┐    ┌───────────┐  │
│  │ llm_tasks[0] │───▶│ llm_tasks[1] │───▶│ llm_tasks[2] │───▶│ llm_tasks │  │
│  │ 问题分析      │    │ 根本原因      │    │ 围堵措施      │    │ 改善对策   │  │
│  │              │    │              │    │              │    │           │  │
│  │ prompt:      │    │ prompt:      │    │ prompt:      │    │ prompt:   │  │
│  │ {{metadata}} │    │ {{metadata}} │    │ {{metadata}} │    │{{metadata}}│  │
│  │{{issue_desc}}│    │{{issue_desc}}│    │{{issue_desc}}│    │{{issue_dsc}}│  │
│  │              │    │ {{context_   │    │ {{context_   │    │ {{context_│  │
│  │              │    │  ISSUE_*}}   │    │  ISSUE_*}}   │    │  ISSUE_*}}│  │
│  │              │    │              │    │ {{context_   │    │ {{context_│  │
│  │              │    │              │    │  ROOT_*}}    │    │  ROOT_*}} │  │
│  │              │    │              │    │              │    │ {{context_│  │
│  │              │    │              │    │              │    │  CONT_*}} │  │
│  └──────────────┘    └──────────────┘    └──────────────┘    └───────────┘  │
└─────────────────────────────────────────────────────────────────────────────┘
                                      │
                                      ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                          main.py /api/generate                              │
│                                                                             │
│   user_inputs          context (上游输出)                                    │
│   ┌──────────┐        ┌──────────────────────┐                              │
│   │file_name │        │ISSUE_ANALYSIS: "..." │                              │
│   │ipad_model│        │ROOT_CAUSE: "..."     │                              │
│   │issue_desc│        └──────────┬───────────┘                              │
│   │...       │                   │                                          │
│   └────┬─────┘                   │                                          │
│        │                         │                                          │
│        │    ┌────────────────────┘                                          │
│        │    │                                                               │
│        ▼    ▼                                                               │
│   ┌─────────────────┐                                                       │
│   │  render_inputs   │  user_inputs + metadata 组装 + context_ 前缀化       │
│   │                  │  {"metadata": {"file_name":"...",                    │
│   │                  │    "ipad_model":"Pro", "build":"EVT", ...},          │
│   │                  │   "issue_description":"...",                         │
│   │                  │   "context_ISSUE_ANALYSIS":"...",                    │
│   │                  │   "context_ROOT_CAUSE":"..."}                        │
│   └────────┬─────────┘                                                      │
│            │                                                                │
│            ▼                                                                │
│   ┌─────────────────┐                                                       │
│   │  build_prompt()  │  Jinja2 渲染                                         │
│   │  prompt_builder  │  {{metadata}} → "{file_name:..., ipad_model:...}"    │
│   │                  │  {{context_ROOT_CAUSE}} → "..."                      │
│   └────────┬─────────┘                                                      │
│            │                                                                │
│            ▼                                                                │
│   ┌─────────────────────────────────────┐                                   │
│   │         rendered_prompt             │                                   │
│   │  (模板变量全部替换为实际值)            │                                   │
│   └────────────────┬────────────────────┘                                   │
│                    │                                                        │
│            ┌───────┴───────┐                                                │
│            ▼               ▼                                                │
│   ┌──────────────┐  ┌────────────────────────────┐                          │
│   │ 免责声明注入   │  │ RAG 知识库 (use_rag=true)  │                          │
│   │ (首次生成时)   │  │ rag_context → system_prompt│                          │
│   └──────┬───────┘  └────────────┬───────────────┘                          │
│          │                       │                                          │
│          ▼                       ▼                                          │
└──────────┼───────────────────────┼──────────────────────────────────────────┘
           │                       │
           ▼                       ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                        core/llm_engine.py                                   │
│                                                                             │
│   ┌─────────────────────────────────────────────────────────────────────┐   │
│   │                         最终 query 组装                               │   │
│   │                                                                     │   │
│   │  ┌─────────────────────────────────────────────────────────────┐   │   │
│   │  │  system_prompt                                              │   │   │
│   │  │  (task.system_prompt 或 YAML cfg.system_prompt)             │   │   │
│   │  │  + RAG 知识库 (如有)                                         │   │   │
│   │  └─────────────────────────────────────────────────────────────┘   │   │
│   │                              +                                      │   │
│   │  "\n\n---\n\n[当前占位符：{placeholder_key}]\n\n"                    │   │
│   │                              +                                      │   │
│   │  ┌─────────────────────────────────────────────────────────────┐   │   │
│   │  │  rendered_prompt (+ 免责声明, 如有)                           │   │   │
│   │  └─────────────────────────────────────────────────────────────┘   │   │
│   └─────────────────────────────────────────────────────────────────────┘   │
│                                    │                                        │
│                                    ▼                                        │
│                          ┌──────────────────┐                               │
│                          │   Dify Chat API   │                               │
│                          │   _call_dify()    │                               │
│                          └──────────────────┘                               │
└─────────────────────────────────────────────────────────────────────────────┘
```

数据流方向：**YAML 定义** → **用户输入 + 上游 context** → **Jinja2 渲染** → **注入声明/RAG** → **拼接 system_prompt** → **发送 Dify**

  简单说：render_inputs 是原料，build_prompt() 是搅拌机，rendered_prompt        
  是成品。YAML 里写的是菜谱（带变量的模板），render_inputs                      
  带来真实食材（用户输入 + 上游输出），build_prompt()
  按菜谱把食材放进去，再加上system prompt:# Build query: system prompt context + user message
    effective_system = system_prompt or ""
    query = f"{effective_system}\n\n---\n\n[当前占位符：{placeholder_key}]\n\n{message}"
    产出一道完整的菜（发给 LLM 的 prompt）。


    -----------------------------------------

    │   依赖    │   对应环节    │                  具体作用                   │
  ├───────────┼───────────────┼─────────────────────────────────────────────┤
  │           │               │ Web 框架，提供                              │
  │ fastapi   │ 全程          │ /api/templates、/api/generate、/api/export  │
  │           │               │ 等接口                                      │
  ├───────────┼───────────────┼─────────────────────────────────────────────┤
  │ uvicorn   │ 全程          │ ASGI 服务器，跑 FastAPI 用的                │
  ├───────────┼───────────────┼─────────────────────────────────────────────┤
  │ pydantic  │ 按模板显示占  │ 定义 GenerateRequest、ExportRequest         │
  │           │ 位符          │ 等数据模型，校验前端传来的参数              │
  ├───────────┼───────────────┼─────────────────────────────────────────────┤
  │ pyyaml    │ 内置模板下拉  │ 加载 standard_report.yaml，解析模板配置（us │
  │           │ 选择          │ er_inputs、llm_tasks、direct_mappings）     │
  ├───────────┼───────────────┼─────────────────────────────────────────────┤
  │           │ 每个占位符独  │ 把 YAML 里的                                │
  │ jinja2    │ 立输入提示词  │ {{metadata}}、{{context_ISSUE_ANALYSIS}}    │
  │           │               │ 渲染成最终 prompt                           │
  ├───────────┼───────────────┼─────────────────────────────────────────────┤
  │ requests  │ 生成          │ 调用 Dify /chat-messages API，把渲染好的    │
  │           │               │ prompt 发给 LLM                             │
  ├───────────┼───────────────┼─────────────────────────────────────────────┤
  │ python-do │ 生成          │ 从 .env 读取 DIFY_API_KEY、DIFY_BASE_URL    │
  │ tenv      │               │                                             │
  ├───────────┼───────────────┼─────────────────────────────────────────────┤
  │ lxml      │ 单页切片导出  │ 解析 PPTX 的 XML，在 <a:t> 标签里替换       │
  │           │               │ {PLACEHOLDER} 占位符，保留字体/颜色/大小    │
  ├───────────┼───────────────┼─────────────────────────────────────────────┤
  │ python-mu │ 人工修改兜底  │ FastAPI 处理文件上传（如果前端需要上传 PPTX │
  │ ltipart   │               │  模板）

  
  
  