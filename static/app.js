// ── State ─────────────────────────────────────────────────────────────────────
let placeholders = [];       // all unique placeholder names
let selectedTags = new Set(); // currently selected tag names
let perTagPrompts = {};      // {name: prompt text}
let contentMap = {};         // {name: generated/edited text}

// ── Step 1: Upload & Scan ────────────────────────────────────────────────────

async function handleScan() {
  const fileInput = document.getElementById("fileInput");
  const status = document.getElementById("scanStatus");

  if (fileInput.files.length > 0) {
    status.textContent = "上传中...";
    const form = new FormData();
    form.append("file", fileInput.files[0]);
    const upRes = await fetch("/api/upload", { method: "POST", body: form });
    if (!upRes.ok) { status.textContent = "上传失败: " + (await upRes.text()); return; }
  }

  status.textContent = "解析占位符中...";
  try {
    const res = await fetch("/api/placeholders");
    if (!res.ok) throw new Error(await res.text());
    const data = await res.json();

    placeholders = data.unique_placeholders || [];
    selectedTags.clear();
    perTagPrompts = {};
    contentMap = {};
    status.textContent = `找到 ${data.total_placeholders} 个占位符（${placeholders.length} 个唯一）`;

    document.getElementById("step2").classList.remove("hidden");
    document.getElementById("step3").classList.add("hidden");
    document.getElementById("step4").classList.add("hidden");
    renderPlaceholderTags();
    renderTagPromptAreas();
  } catch (e) {
    status.textContent = "解析失败: " + e.message;
  }
}

// ── Step 2: Tag Selection & Per-Tag Prompts ──────────────────────────────────

function renderPlaceholderTags() {
  const container = document.getElementById("placeholderTags");
  container.innerHTML = placeholders.map(p => {
    const sel = selectedTags.has(p);
    const cls = sel
      ? "bg-blue-600 text-white border-blue-600"
      : "bg-white text-gray-600 border-gray-300 hover:border-blue-400 hover:text-blue-600";
    return `<button type="button" data-name="${escapeAttr(p)}"
                    onclick="toggleTag('${escapeJs(p)}')"
                    class="px-3 py-1 rounded-full border text-xs font-mono cursor-pointer transition ${cls}">
              {${escapeHtml(p)}}
            </button>`;
  }).join("");
}

function toggleTag(name) {
  if (selectedTags.has(name)) {
    selectedTags.delete(name);
    delete perTagPrompts[name];
  } else {
    selectedTags.add(name);
    if (!perTagPrompts[name]) perTagPrompts[name] = "";
  }
  renderPlaceholderTags();
  renderTagPromptAreas();
}

function renderTagPromptAreas() {
  const container = document.getElementById("tagPromptAreas");
  container.innerHTML = "";

  for (const name of selectedTags) {
    const div = document.createElement("div");
    div.className = "flex items-start gap-3 bg-gray-50 rounded-lg p-3 border border-gray-200";

    div.innerHTML = `
      <span class="shrink-0 mt-1 px-2 py-0.5 bg-blue-100 text-blue-700 rounded text-xs font-mono">
        {${escapeHtml(name)}}
      </span>
      <div class="flex-1 flex gap-2">
        <input type="text" data-tag="${escapeAttr(name)}"
               value="${escapeAttr(perTagPrompts[name] || "")}"
               oninput="perTagPrompts[this.dataset.tag] = this.value"
               class="flex-1 border border-gray-300 rounded px-2 py-1 text-sm
                      focus:ring-2 focus:ring-blue-500 focus:border-transparent tag-prompt-input"
               placeholder="为该占位符写一句提示词，如：写一句激励人心的口号" />
        <button onclick="handleSingleGenerate('${escapeJs(name)}')"
                class="shrink-0 px-3 py-1 bg-purple-500 text-white rounded text-xs
                       hover:bg-purple-600 transition">
          生成
        </button>
      </div>
    `;
    container.appendChild(div);
  }
}

// ── Generate: Single Tag ─────────────────────────────────────────────────────

async function handleSingleGenerate(name) {
  const status = document.getElementById("generateStatus");
  const prompt = (perTagPrompts[name] || "").trim();
  if (!prompt) { status.textContent = `请先为 {${name}} 填写提示词`; return; }

  status.textContent = `正在生成 {${name}}...`;
  try {
    const globalCtx = document.getElementById("globalContext").value.trim();
    const res = await fetch("/api/generate", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ user_input: globalCtx, items: { [name]: prompt } }),
    });
    if (!res.ok) throw new Error(await res.text());
    const data = await res.json();
    Object.assign(contentMap, data.content);
    status.textContent = `{${name}} 生成完成`;
    showEditForm();
  } catch (e) {
    status.textContent = `生成失败: ` + e.message;
  }
}

// ── Generate: Batch ──────────────────────────────────────────────────────────

async function handleBatchGenerate() {
  const status = document.getElementById("generateStatus");

  // Collect tags that are selected AND have a prompt
  const items = {};
  for (const name of selectedTags) {
    const p = (perTagPrompts[name] || "").trim();
    if (p) items[name] = p;
  }
  if (Object.keys(items).length === 0) {
    status.textContent = "请至少选择一个占位符并填写提示词";
    return;
  }

  status.textContent = `批量生成中（${Object.keys(items).length} 项）...`;
  document.getElementById("btnBatchGenerate").disabled = true;
  try {
    const globalCtx = document.getElementById("globalContext").value.trim();
    const res = await fetch("/api/generate", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ user_input: globalCtx, items }),
    });
    if (!res.ok) throw new Error(await res.text());
    const data = await res.json();
    Object.assign(contentMap, data.content);
    status.textContent = `批量生成完成（${Object.keys(data.content).length} 项）`;
    showEditForm();
  } catch (e) {
    status.textContent = "生成失败: " + e.message;
  } finally {
    document.getElementById("btnBatchGenerate").disabled = false;
  }
}

// ── Step 3: Edit Form ────────────────────────────────────────────────────────

function showEditForm() {
  renderEditForm();
  document.getElementById("step3").classList.remove("hidden");
  document.getElementById("step4").classList.remove("hidden");
}

function renderEditForm() {
  const container = document.getElementById("editForm");
  container.innerHTML = "";

  for (const name of placeholders) {
    const value = contentMap[name] || "";
    const div = document.createElement("div");
    div.className = "flex flex-col sm:flex-row sm:items-start gap-2";

    div.innerHTML = `
      <label class="sm:w-48 shrink-0 text-sm font-mono text-gray-600 pt-2">
        {${escapeHtml(name)}}
      </label>
      <textarea data-key="${escapeAttr(name)}" rows="3"
                class="flex-1 border border-gray-300 rounded-lg px-3 py-2
                       text-sm focus:ring-2 focus:ring-blue-500 focus:border-transparent
                       editable-field"
      >${escapeHtml(value)}</textarea>
    `;
    container.appendChild(div);
  }

  container.querySelectorAll(".editable-field").forEach(el => {
    el.addEventListener("input", () => { contentMap[el.dataset.key] = el.value; });
  });
}

// ── Step 4: Export ───────────────────────────────────────────────────────────

async function handleExport() {
  const status = document.getElementById("exportStatus");
  status.textContent = "生成 PPTX 中...";
  document.getElementById("btnExport").disabled = true;

  document.querySelectorAll(".editable-field").forEach(el => {
    contentMap[el.dataset.key] = el.value;
  });

  try {
    const res = await fetch("/api/export", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ content: contentMap }),
    });
    if (!res.ok) throw new Error(await res.text());

    const blob = await res.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url; a.download = "final_output.pptx"; a.click();
    URL.revokeObjectURL(url);
    status.textContent = "导出成功！文件已开始下载。";
  } catch (e) {
    status.textContent = "导出失败: " + e.message;
  } finally {
    document.getElementById("btnExport").disabled = false;
  }
}

// ── Helpers ──────────────────────────────────────────────────────────────────

function escapeHtml(str) {
  const d = document.createElement("div");
  d.textContent = str;
  return d.innerHTML;
}

function escapeAttr(str) {
  return str.replace(/&/g,"&amp;").replace(/"/g,"&quot;").replace(/</g,"&lt;").replace(/>/g,"&gt;");
}

function escapeJs(str) {
  return str.replace(/\\/g,"\\\\").replace(/'/g,"\\'");
}
