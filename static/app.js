// ── State ─────────────────────────────────────────────────────────────────────
let templates = [];           // [{ template_id, template_name, placeholders }]
let selectedTemplateId = null;
let finalData = {};           // { placeholder_key: final text }
let generatingSet = new Set(); // placeholders currently generating

// ── Init: Load templates on page load ────────────────────────────────────────

async function init() {
  const select = document.getElementById("templateSelect");
  const info = document.getElementById("templateInfo");

  try {
    const res = await fetch("/api/templates");
    if (!res.ok) throw new Error(await res.text());
    templates = await res.json();

    select.innerHTML = '<option value="">-- 请选择模板 --</option>';
    for (const t of templates) {
      const opt = document.createElement("option");
      opt.value = t.template_id;
      opt.textContent = `${t.template_name}（${t.placeholders.length} 个占位符）`;
      select.appendChild(opt);
    }
    info.textContent = `已加载 ${templates.length} 个内置模板`;
  } catch (e) {
    select.innerHTML = '<option value="">-- 加载失败 --</option>';
    info.textContent = "加载模板失败: " + e.message;
  }
}

// ── Step 1: Template selection ────────────────────────────────────────────────

function handleTemplateChange(value) {
  const templateId = parseInt(value, 10);
  const step2 = document.getElementById("step2");
  const step3 = document.getElementById("step3");
  const info = document.getElementById("templateInfo");

  if (!templateId) {
    step2.classList.add("hidden");
    step3.classList.add("hidden");
    selectedTemplateId = null;
    return;
  }

  selectedTemplateId = templateId;
  const template = templates.find(t => t.template_id === templateId);
  if (!template) return;

  info.textContent = `已选择：${template.template_name}，共 ${template.placeholders.length} 个占位符`;

  // Reset state
  finalData = {};
  generatingSet.clear();

  // Render placeholders
  renderPlaceholders(template.placeholders);
  step2.classList.remove("hidden");
  step3.classList.remove("hidden");
}

// ── Step 2: Per-placeholder UI ────────────────────────────────────────────────

function renderPlaceholders(placeholders) {
  const container = document.getElementById("placeholderList");
  container.innerHTML = "";

  for (const name of placeholders) {
    const div = document.createElement("div");
    div.className = "placeholder-row border border-gray-200 rounded-lg p-4 fade-in";
    div.id = `row-${cssId(name)}`;

    div.innerHTML = `
      <!-- Header: placeholder name + generate button -->
      <div class="flex items-center gap-3 mb-3">
        <span class="px-2 py-0.5 bg-blue-100 text-blue-700 rounded text-xs font-mono">
          {${escapeHtml(name)}}
        </span>
        <div class="flex-1"></div>
        <div class="flex items-center gap-2">
          <input type="text" id="prompt-${cssId(name)}"
                 class="w-64 border border-gray-300 rounded px-2 py-1 text-sm
                        focus:ring-2 focus:ring-blue-500 focus:border-transparent"
                 placeholder="输入提示词..." />
          <button onclick="handleGenerate('${escapeJs(name)}')"
                  id="btn-${cssId(name)}"
                  class="px-3 py-1 bg-purple-500 text-white rounded text-xs
                         hover:bg-purple-600 transition disabled:opacity-50">
            生成
          </button>
        </div>
      </div>

      <!-- Final result textarea (manual edit fallback) -->
      <div>
        <label class="block text-xs text-gray-500 mb-1">最终结果（可手动修改）</label>
        <textarea id="final-${cssId(name)}" rows="3"
                  oninput="finalData['${escapeJs(name)}'] = this.value"
                  class="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm
                         focus:ring-2 focus:ring-blue-500 focus:border-transparent"
                  placeholder="AI 生成后自动填入，也可直接手动输入..."></textarea>
      </div>

      <!-- Status -->
      <div id="status-${cssId(name)}" class="mt-2 text-xs text-gray-400"></div>
    `;

    container.appendChild(div);
  }
}

// ── Generate: single placeholder ─────────────────────────────────────────────

async function handleGenerate(name) {
  const promptInput = document.getElementById(`prompt-${cssId(name)}`);
  const finalTextarea = document.getElementById(`final-${cssId(name)}`);
  const statusEl = document.getElementById(`status-${cssId(name)}`);
  const btn = document.getElementById(`btn-${cssId(name)}`);

  const prompt = (promptInput.value || "").trim();
  if (!prompt) {
    statusEl.textContent = "请先填写提示词";
    statusEl.className = "mt-2 text-xs text-red-500";
    return;
  }

  generatingSet.add(name);
  btn.disabled = true;
  btn.textContent = "生成中...";
  statusEl.textContent = "正在生成...";
  statusEl.className = "mt-2 text-xs text-blue-500";

  try {
    const res = await fetch("/api/generate", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ placeholder_key: name, prompt }),
    });
    if (!res.ok) throw new Error(await res.text());
    const data = await res.json();

    // Fill the final result textarea
    finalTextarea.value = data.content;
    finalData[name] = data.content;

    statusEl.textContent = "生成完成";
    statusEl.className = "mt-2 text-xs text-green-600";
  } catch (e) {
    statusEl.textContent = "生成失败: " + e.message;
    statusEl.className = "mt-2 text-xs text-red-500";
  } finally {
    generatingSet.delete(name);
    btn.disabled = false;
    btn.textContent = "生成";
  }
}

// ── Step 3: Export ───────────────────────────────────────────────────────────

async function handleExport() {
  const status = document.getElementById("exportStatus");
  const btn = document.getElementById("btnExport");

  if (!selectedTemplateId) {
    status.textContent = "请先选择模板";
    return;
  }

  // Sync all textarea values to finalData
  const template = templates.find(t => t.template_id === selectedTemplateId);
  if (template) {
    for (const name of template.placeholders) {
      const textarea = document.getElementById(`final-${cssId(name)}`);
      if (textarea) {
        finalData[name] = textarea.value;
      }
    }
  }

  // Filter out empty values
  const exportData = {};
  for (const [k, v] of Object.entries(finalData)) {
    if (v.trim()) exportData[k] = v;
  }

  if (Object.keys(exportData).length === 0) {
    status.textContent = "没有可导出的内容，请先生成或手动填写";
    return;
  }

  status.textContent = "导出中...";
  btn.disabled = true;

  try {
    const res = await fetch("/api/export", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ template_id: selectedTemplateId, final_data: exportData }),
    });
    if (!res.ok) throw new Error(await res.text());

    const blob = await res.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = "final_output.pptx";
    a.click();
    URL.revokeObjectURL(url);
    status.textContent = "导出成功！文件已开始下载。";
  } catch (e) {
    status.textContent = "导出失败: " + e.message;
  } finally {
    btn.disabled = false;
  }
}

// ── Helpers ──────────────────────────────────────────────────────────────────

function escapeHtml(str) {
  const d = document.createElement("div");
  d.textContent = str;
  return d.innerHTML;
}

function escapeJs(str) {
  return str.replace(/\\/g, "\\\\").replace(/'/g, "\\'");
}

function cssId(str) {
  // Convert a placeholder name into a valid CSS id
  return str.replace(/[^a-zA-Z0-9_-]/g, "_");
}

// ── Boot ─────────────────────────────────────────────────────────────────────
init();
