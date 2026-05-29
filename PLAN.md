迭代一

# PPT AI Automation 重构计划 — 内置模板选择 + 占位符独立生成

## 当前流程
上传 PPT → 全局扫描占位符 → 批量生成 → 导出

## 目标流程
内置模板下拉选择 → 按模板显示占位符 → 每个占位符独立输入提示词+生成 → 人工修改兜底 → 单页切片导出

---

## 阶段一: 内置模板解析与 UI 联动

**改动文件:**

1. **`core/ppt_core.py`** — 新增 `list_templates()` 方法
   - 读取内置 `品質改善報告模板Template.pptx`
   - 按 slide 页拆分，每页作为一个模板实体
   - 提取每页的标题作为模板名，扫描该页的占位符列表
   - 返回: `[{ template_id: 1, template_name: "FACA 模板一", placeholders: [...] }]`

2. **`main.py`** — 接口重构
   - 新增 `GET /api/templates` → 返回 4 个模板的列表
   - 移除 `POST /api/upload`（不再需要上传）
   - `GET /api/placeholders/{template_id}` → 只返回指定模板的占位符

3. **`models/schemas.py`** — 新增 `TemplateInfo` schema

4. **`static/index.html`** — 移除文件上传 `<input>`，替换为模板选择 `<select>` 下拉菜单

5. **`static/app.js`** — 页面加载时调 `/api/templates` 填充下拉菜单，选择后调占位符接口

---

## 阶段二: 占位符级别独立生成

6. **`models/schemas.py`** — `GenerateRequest` 改为: `{ template_id, placeholder_key, prompt }`

7. **`main.py`** — `/api/generate` 改为接收单个占位符请求

8. **`core/llm_engine.py`** — 新增 `generate_single(placeholder_key, prompt) -> str`，极简 prompt，返回纯文本

9. **前端** — 每个占位符一行: 名称标签 + 提示词输入框 + "生成"按钮

---

## 阶段三: 人工兜底

10. **前端** — 每个占位符下方增加"最终结果" textarea，AI 生成后自动填入，用户可手动修改，`contentMap` 只绑定 textarea 值

---

## 阶段四: 单页切片导出

11. **`models/schemas.py`** — `ExportRequest` 改为: `{ template_id, final_data }`

12. **`core/ppt_core.py`** — 新增 `export_single_slide()` 方法: 打开内置 PPTX → 删除未选中的 slides → 替换占位符 → 重新打包

13. **`main.py`** — `/api/export` 改为调用单页导出

---

## 文件变更清单

| 文件 | 变更类型 | 阶段 |
|------|---------|------|
| `core/ppt_core.py` | 修改: 新增 `list_templates()`, `export_single_slide()` | 1, 4 |
| `main.py` | 修改: 新增 `/api/templates`, 移除 `/api/upload`, 调整 `/api/generate` 和 `/api/export` | 1, 2, 4 |
| `models/schemas.py` | 修改: 新增 `TemplateInfo`, 调整 `GenerateRequest`, `ExportRequest` | 1, 2, 4 |
| `static/index.html` | 修改: 移除上传 UI, 新增模板选择下拉, 重构步骤布局 | 1, 2, 3 |
| `static/app.js` | 修改: 重构初始化流程, 移除上传逻辑, 新增模板选择/独立生成/兜底编辑 | 1, 2, 3 |

## 验证方式

1. `cd G:\ppt-ai-automation && python main.py` 启动服务
2. 浏览器打开 `http://127.0.0.1:8000`
3. 确认页面加载后显示模板下拉菜单（4 个选项）
4. 选择任意模板，确认下方显示该模板的占位符列表
5. 为某个占位符输入提示词，点击"生成"，确认返回结果填入 textarea
6. 手动修改 textarea 内容，点击"导出"，确认下载的 PPTX 只包含选中的那一页且占位符已替换


  
实验一
  
调整算法的流程

  1. 跑一次，看 test_results.json 里哪些 task 内容不理想
  2. 改 templates/5c_report.yaml 里对应 task 的 prompt 字段
  3. 重新跑，对比前后结果
  4. 重复直到满意


测试

  前置条件

  确认 .env 里有 Dify 配置：
  DIFY_API_KEY=你的key
  DIFY_BASE_URL=你的dify地址

  启动测试

  cd /mnt/e/workspace/ppt_AI_automation
  python -m test.test_generate

  不需要启动 python main.py，脚本直接调 core 层函数。

  执行流程

  读 test_data.json (3个测试案例)
      ↓
  读 5c_report.yaml (拿到 5+2=7 个 task 的 prompt 模板)
      ↓
  对每个案例 × 每个 task：
      build_prompt() → 渲染 Jinja2 模板
      ↓
      generate_content() → 调 Dify API
      ↓
      打印 ack + content + 耗时
      ↓
  结果写入 test/test_results.json

  输出

  - 终端实时打印每个 task 的生成结果和耗时
  - 最后输出汇总表（OK/FAIL 状态）
  - 完整结果保存到 test/test_results.json

 