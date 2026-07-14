## Context Engineering

 涉及的脚本（共 5 层）

  ┌───────────┬──────────────────┬─────────────────────────────────────────┐
  │   层级    │       文件       │                  职责                   │
  ├───────────┼──────────────────┼─────────────────────────────────────────┤
  │ 1. 依赖图 │ app.js:14-28     │ 硬编码 generationOrder、dependencies、d │
  │ 定义      │                  │ ownstream                               │
  ├───────────┼──────────────────┼─────────────────────────────────────────┤
  │ 2. 上下文 │ app.js:30-38     │ collectContext() 从 chatHistory         │
  │ 收集      │                  │ 取上游结果                              │
  ├───────────┼──────────────────┼─────────────────────────────────────────┤
  │ 3. 上下文 │ main.py:205-207  │ 把 req.context 转为 context_XXX 键写入  │
  │ 注入      │                  │ render_inputs                           │
  ├───────────┼──────────────────┼─────────────────────────────────────────┤
  │ 4. Prompt │ prompt_builder.p │ Jinja2 把 {{context_XXX}} 替换进 prompt │
  │  渲染     │ y                │  模板                                   │
  ├───────────┼──────────────────┼─────────────────────────────────────────┤
  │ 5. Prompt │ YAML 文件        │ 在 prompt 里引用                        │
  │  模板     │                  │ {{context_ISSUE_ANALYSIS}} 等变量       │
  └───────────┴──────────────────┴─────────────────────────────────────────┘

------------

  各模板与 context engineering 的兼容性

  模板: FACA_report.yaml
  用了 context？: 是（{{context_ISSUE_ANALYSIS}} 等）
  placeholder_key 与前端匹配？: 匹配（ISSUE_ANALYSIS, ROOT_CAUSE, CONTAINMENT,
    CORRECTIVE）
  ────────────────────────────────────────
  模板: FACA_report_with_reference.yaml
  用了 context？: 是（同上）
  placeholder_key 与前端匹配？: 匹配
  ────────────────────────────────────────
  模板: standard_report.yaml
  用了 context？: 是（同上）
  placeholder_key 与前端匹配？: 匹配
  ────────────────────────────────────────
  模板: 5c_report.yaml
  用了 context？: 否
  placeholder_key 与前端匹配？: 不匹配（Fill in list of...）
  ────────────────────────────────────────
  模板: 8d_report.yaml
  用了 context？: 否
  placeholder_key 与前端匹配？: 不匹配（Fill in predicted...）

  5c/8d 的 prompt 里完全没有 {{context_XXX}} 引用，且 placeholder_key
  命名风格完全不同。

--------------

能否解耦并为 5c/8d 单独做 context engineering？

  可以，但需要改动两个层面：

  方案：把依赖图从 app.js 硬编码迁入 YAML 声明

  在每个 YAML 里新增一个 context_graph 字段，例如 5c_report.yaml：

  context_graph:
    generation_order: ["ISSUE_ANALYSIS", "ROOT_CAUSE", "CONTAINMENT",
  "CORRECTIVE"]
    dependencies:
      ROOT_CAUSE: ["ISSUE_ANALYSIS"]
      CONTAINMENT: ["ISSUE_ANALYSIS", "ROOT_CAUSE"]
      CORRECTIVE: ["ISSUE_ANALYSIS", "ROOT_CAUSE", "CONTAINMENT"]

  同时把 5c/8d 的 target_placeholder 统一改为短 key（ISSUE_ANALYSIS 等），并在
  prompt 里加上 {{context_XXX}} 引用。

  改动范围：

  ┌─────────────┬───────────────────────────────────────────────────────────┐
  │    文件     │                          改什么                           │
  ├─────────────┼───────────────────────────────────────────────────────────┤
  │ 5c_report.y │ 新增 context_graph，统一 target_placeholder 为短          │
  │ aml         │ key，prompt 加 {{context_XXX}}                            │
  ├─────────────┼───────────────────────────────────────────────────────────┤
  │ 8d_report.y │ 同上                                                      │
  │ aml         │                                                           │
  ├─────────────┼───────────────────────────────────────────────────────────┤
  │ app.js      │ 删除硬编码的 generationOrder/dependencies/downstream，改  │
  │             │ 为从后端接口获取或由后端传入                              │
  ├─────────────┼───────────────────────────────────────────────────────────┤
  │             │ /api/generate 返回 YAML 中的 context_graph                │
  │ main.py     │ 给前端；first_turn_placeholders 也改为从 YAML             │
  │             │ 读取而非硬编码                                            │
  ├─────────────┼───────────────────────────────────────────────────────────┤
  │ schemas.py  │ GenerateResponse 可能需要新增字段传递 graph 信息          │
  └─────────────┴───────────────────────────────────────────────────────────┘

  ----------------

  核心思路：后端是通用的（context_ 前缀注入 + Jinja2 渲染已经支持任意
  key），问题出在前端硬编码了 FACA 的依赖图。只要把依赖图下沉到
  YAML，每个模板就能独立声明自己的 context engineering 链路，互不干扰。

  

  ⏺ 不会丢失这个效果。方案不是"删除前端依赖图"，而是换数据源：─────────────────────────────────────────────────────────────────┘

  现在：                                                                                                                                                                                                          
  app.js 硬编码 → 直接用
                                                                                                                                                                                                                  
  改后：                                                                                                                                                                                                          
  YAML 定义 context_graph → 后端 API 返回给前端 → 前端动态使用                                                                                                                                                    
                                                                                                                                                                                                                  
  具体来说，前端加载模板时，后端已经有一个接口返回模板配置（user_inputs、llm_tasks 等）。只需要把 YAML 里的 context_graph 也一并返回，前端用返回的数据替代硬编码的                                                
  generationOrder/dependencies/downstream，阻塞逻辑完全不变：                                                                                                                                                     
                                                                                                                                                                                                                  
  // 之前：硬编码                                                                                                                                                                                                 
  const dependencies = {                                                                                                                                                                                          
    ISSUE_ANALYSIS: [],                                                                                                                                                                                           
    ROOT_CAUSE: ["ISSUE_ANALYSIS"],                                                                                                                                                                               
    ...                                                                                                                                                                                                           
  };心思路：后端是通用的（context_ 前缀注入 + Jinja2 渲染已经支持任意 key），问题出在前端硬编码了 FACA 的依赖图。只要把依赖图下沉到 YAML，每个模板就能独立声明自己的 context engineering 链路，互不干扰。         
                                                                                                                                                                                                                  
  // 之后：从后端接口拿
  const dependencies = templateConfig.context_graph.dependencies;
                                                                                                                                                                                                                  
  前端的 collectContext()、按钮禁用、级联生成这些逻辑本身不依赖"key 是硬编码的"这个事实，它只依赖 dependencies 这个对象的结构。只要数据结构一样，从哪来的无所谓。                                                 
                                                                                                                                                                                                                  
  所以 5c、8d 各自在 YAML 里声明自己的依赖图，前端拿到后按同样的逻辑处理，互不干扰，阻塞效果也保留。


  --------------------------

    ---
  ## 改动hard coding 依赖图后，数据流变化

  现在

  YAML 定义 prompt + target_placeholder
                      ↓
          GET /api/template/{id} 返回给前端
                      ↓
  前端 app.js 硬编码 dependencies/generationOrder/downstream（只认 FACA 的 4 个 key）
                      ↓
  前端 collectContext() 从 chatHistory 取上游结果 → 作为 context 传给 /api/generate
                      ↓
  后端 context_ 前缀注入 → Jinja2 渲染 → LLM

  问题：依赖图只存在于 app.js 源码里，和 YAML 配置脱节。5c/8d 拿不到这套逻辑。

  改后

  YAML 定义 prompt + target_placeholder + context_graph（新增）
                      ↓
          GET /api/template/{id} 返回给前端（多了一个 context_graph 字段）
                      ↓
  前端 app.js 从 currentConfig.context_graph 读取 dependencies/generationOrder/downstream
                      ↓
  （后续流程完全不变）
  前端 collectContext() → context 传给后端 → context_ 前缀注入 → Jinja2 → LLM

  指令流变化

  批量生成顺序：
  - 现在：app.js 硬编码 ["ISSUE_ANALYSIS", "ROOT_CAUSE", "CONTAINMENT", "CORRECTIVE"] → 遍历
  - 改后：从 currentConfig.context_graph.generation_order 读取，每个 YAML 自己声明

  级联再生：
  - 现在：app.js 硬编码 downstream map → 上游改了自动再生下游
  - 改后：从 currentConfig.context_graph.downstream 读取

  首次生成免责声明：
  - 现在：main.py 硬编码 {"ISSUE_ANALYSIS", "ROOT_CAUSE"} → 对这两个 key 注入免责声明
  - 改后：从 YAML 的 context_graph.first_turn_disclaimers 读取

  本质：数据源从"散落在 JS 和 Python 源码里"变成"集中在 YAML 配置里"，指令流的逻辑不变，只是读取位置变了。


  --------------------

  数据驱动渲染链路                                    
                           
  选择模板 → GET /api/template/{id} 返回 YAML 全文 → 前端按字段渲染             
                                                                                
  具体看 app.js:121：                                                           
  renderClosure(currentConfig.closure_tasks || []);                             
                                                                                
  再看 renderClosure（app.js:529-543）：                                        
  if (!closureTasks || closureTasks.length === 0) {                             
    section.classList.add("hidden");  // 没有 closure_tasks → 隐藏              
    return;                                                                     
  }                                                                             
  section.classList.remove("hidden");  // 有 closure_tasks → 显示               
                                                                                
  所以只要 YAML 里声明了 closure_tasks 且不为空，前端就自动显示 closure         
  栏目。8d_report.yaml 有这段：                                                 
                                                                                
  closure_tasks:                                                                
    - target_placeholder: "Fill in verification"                                
      ...                                                                       
    - target_placeholder: "user input congratulate"                             
      ...                                                                       
                                                            
  前端拿到后自动渲染，不需要任何额外代码。                                      
                                                            
  整个前端的架构就是这样的——user_inputs、llm_tasks、closure_tasks 三个 section  
  都是读 YAML 动态渲染，YAML 里有就显示，没有就隐藏。这也是为什么刚才我们把
  context_graph 下沉到 YAML 后，前端只需要从 currentConfig                      
  读取就能工作——架构本身已经支持配置驱动。

    ## 8D依赖链路

  D3 Containment → D4 Root Cause → D5 Corrective ──┐
                                 → D6 Preventive ──┘                            
  D7 Verification (closure, 独立)                                               
  D8 Congratulate (closure, 独立) 

  ## 5c / 8D 添加

    链路：每个 task 生成时 → 后端调 Dify 知识库检索 → 结果注入 system_prompt 给   
  LLM 参考 + 前端累积 → 导出时自动填入第二页 Related_text / 
  Related_text_2。后端和前端代码零改动

  ## debug for system -- export_single_slide 

  当前架构

  export_single_slide(ppt_path, slide_index, content_map, font_config)
      ├── 扫描所有占位符
      ├── 删除 slide_index 以外的 slide
      ├── 填充保留 slide 的占位符
      └── 重新打包

  fill_template(ppt_path, content_map, output_path)
      ├── 扫描所有占位符
      ├── 填充所有 slide 的占位符
      └── 重新打包

  两个方法做的是同一件事（扫描→填充→打包），export_single_slide
  只是多了一步"删页"。

  为什么要删页？

  原始设计假设：一个 PPT 文件里有多个 slide 模板，每个 YAML
  只用其中一页。所以需要 export_single_slide 把不需要的页删掉。

  但现在的实际用法是：每个 PPT 文件就是一个完整的报告，所有页都要导出。5C/8D
  加了 reference 页后，我们已经在用 slide_index: [1, 2]
  来"保留全部"——这等于在绕过删页逻辑。

  删掉后的变化

  ┌──────────┬───────────────────────────────────┬──────────────────────────┐
  │   维度   │               现在                │           删后           │
  ├──────────┼───────────────────────────────────┼──────────────────────────┤
  │ YAML     │ 需要声明 slide_index              │ 不需要，少一个配置项     │
  │ 配置     │                                   │                          │
  ├──────────┼───────────────────────────────────┼──────────────────────────┤
  │ 导出入口 │ export_single_slide               │ fill_to_bytes（已存在）  │
  ├──────────┼───────────────────────────────────┼──────────────────────────┤
  │ 代码量   │ 两个方法功能重叠                  │ 只保留 fill_template     │
  │          │                                   │ 一个                     │
  ├──────────┼───────────────────────────────────┼──────────────────────────┤
  │ 数据流   │ content_map → 过滤 slide → 填充 → │ content_map → 填充 →     │
  │          │  打包                             │ 打包                     │
  ├──────────┼───────────────────────────────────┼──────────────────────────┤
  │ 指令流   │ main.py 调 export_single_slide 传 │ main.py 调 fill_to_bytes │
  │          │  slide_index                      │                          │
  └──────────┴───────────────────────────────────┴──────────────────────────┘

  对模块的影响：
  - ppt_core.py：删除 export_single_slide 方法（~80 行），保留 fill_template +
  fill_to_bytes
  - main.py：export 端点从调 export_single_slide 改为调 fill_to_bytes，删除
  slide_index 读取逻辑
  - 所有 YAML：删除 slide_index 字段（FACA_report.yaml 也有）
  - 前端：无变化

  唯一风险：如果未来某个 PPT
  文件里确实有多余的页不想导出，就没有删页机制了。但目前没有任何模板有这个需求。

  
  ##  multi_turn_chat

  不过这个担心其实也站不住——因为 Dify 会话历史会把第二轮的
  multi_turn_prompt（含当时的脱敏版）和模型回复都存下来。第三轮时模型看得到第二
  轮的完整上下文，包括当时注入的脱敏版和模型的改写。所以"第 2
  条"是有明确指代的。

  除非用户在第二轮和第三轮之间又手动改了 textarea
  的内容——这种情况确实会脱节。但这种"用户在两次追问之间手改内容"的场景很少，而且
  就算脱节，模型基于第二轮的版本改也不会出大问题，用户再追问一次就行。

  所以我同意你的方案

  ┌────────────────────────┬────────────────────────────────────┬───────────────
  ──────────────────────────────────────────────┐
  │          轮次          │          conversation_id           │
               query                            │
  ├────────────────────────┼────────────────────────────────────┼───────────────
  ──────────────────────────────────────────────┤
  │ 首轮 pipeline          │ 各步 fresh；缓存 reason 的 conv_id │ YAML steps
  prompt                                           │
  ├────────────────────────┼────────────────────────────────────┼───────────────
  ──────────────────────────────────────────────┤
  │ 第二次多轮（首次追问） │ reason 的 conv_id                  │
  multi_turn_prompt 渲染（含 current_content + user_message） │
  ├────────────────────────┼────────────────────────────────────┼───────────────
  ──────────────────────────────────────────────┤
  │ 第三次及以后           │ reason 的 conv_id                  │
  用户原始消息，不包装                                        │
  └────────────────────────┴────────────────────────────────────┴───────────────
  ──────────────────────────────────────────────┘

  判定方式：用 history 的长度。history 为空 → 首轮 pipeline；history 有 1 条 →
  第二次多轮（注入）；history ≥ 2 条 → 直接发用户消息。

  这个方案干净、简单，也符合"会话历史已经积累了足够上下文"的事实。

  要动手改吗？

❯ 好，改哪些文件能实现这个功能？                                                

⏺ 按这个方案需要改 5 个文件。我先列清单，确认后动手：

  ┌───────────────────────────────────────────┬────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┐
  │                   文件                    │                                                                            改动                                                                            │
  ├───────────────────────────────────────────┼────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┤
  │ models/schemas.py                         │ GenerateRequest 加 current_content: str = "" 字段                                                                                                          │
  ├───────────────────────────────────────────┼────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┤
  │ core/llm_engine.py                        │ execute_pipeline 末尾缓存 reason 步骤的 conversation_id（而不是 sanitize 的）                                                                              │
  ├───────────────────────────────────────────┼────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┤
  │ main.py                                   │ 多轮分支按 history 长度分三档：• 空 → 首轮 pipeline（不变）• 1 条 → 渲染 multi_turn_prompt 注入 current_content + user_message• ≥2 条 → 直接发 req.message │
  ├───────────────────────────────────────────┼────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┤
  │ static/app.js                             │ 多轮请求 payload 里带上 current_content（从对应 textarea 取 value）                                                                                        │
  ├───────────────────────────────────────────┼────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┤
  │ templates/FACA_report_with_reference.yaml │ 4 个 task 各加 multi_turn_prompt 字段                                                                                                                      │
  └───────────────────────────────────────────┴────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┘

  从部署角度看，健壮性明显变强了。核心改进如下：                                
                                                                                
  ---                                                                           
  1. 内存泄漏防护（最大改进）                                                   
                                                                                
  之前：RAG 缓存和会话 ID 缓存都是普通                                          
  dict，无大小限制、无过期机制，长时间运行内存会无限增长。                      
                                                                                
  现在：换成 TTLCache：                                                         
  - RAG 缓存：maxsize=200, ttl=1h                                               
  - 会话 ID 缓存：maxsize=500, ttl=1d                                           
                                     
  这是生产部署最关键的改进 — 防止内存泄漏。                                     
                                                                                
  ---                                                                           
  2. 并发隔离（第二重要）                                                       
                                                                                
  之前：缓存 key 基于 template_id + issue_description 或
  user:placeholder_key，同一用户并发生成多份报告时会互相污染。                  
                  
  现在：前端生成 session_id（UUID），所有缓存 key 都加上                        
  session_id，彻底隔离并发会话。
                                                                                
  ---             
  3. 脱敏 Prompt 更鲁棒
                                                                                
  之前 sanitize prompt 假设一定能找到 #AI推理 标记，找不到就出错。现在加了
  fallback：找不到就对整个输入脱敏。还加了示例，减少了 LLM 输出格式错误的概率。 
                  
  ---                                                                           
  4. 前端改进     
                                                                                
  - crypto.randomUUID() 有 fallback（Date.now + Math.random），兼容非 HTTPS 环境
  - 按钮用 opacity 控制禁用状态，避免布局抖动                                   
  - updatePreview() 优先取 fullContent，减少显示空内容的 bug                    
                                                                                
  ---                                                                           
  唯一风险点                                                                    
                                                                                
  新增了 cachetools 依赖 — 但这是个成熟、零传递依赖的库，风险极低。
                                                                                
  总结：这两个 commit 把一个"能跑"的原型推向了"能部署"的状态。  