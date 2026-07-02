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

  要改吗？