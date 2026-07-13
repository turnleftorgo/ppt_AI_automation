// ── State ─────────────────────────────────────────────────────────────────────
let templates = [];           // from /api/templates
let currentConfig = null;     // full YAML config for selected template
let userInputs = {};          // { input_id: value } from Characterize section
let chatHistory = {};         // { target_placeholder: [{ role, content, fullContent? }] }
let generatingSet = new Set();
let ragContexts = [];         // RAG knowledge base retrieval results
let currentSessionId = null;  // UUID per report; isolates Dify conversation + RAG cache across concurrent reports
let lastBaseline = {};        // { placeholder_key: last_generated_content } 用于检测右侧编辑

// Preview field registry: [{ key, label, source, group }]
// source: 'userInputs' | 'chatHistory'
let previewFields = [];

// Tab-mode preview state
// previewTabs: flat list of [{ sourceKey, key, label, source, hasExtract }] in display order (llm_tasks order, closure last)
// activePreviewTab: sourceKey of the currently visible tab
let previewTabs = [];
let activePreviewTab = null;

// ── Dependency graph for serial generation (read from YAML context_graph) ───
function getContextGraph() {
  const cg = currentConfig && currentConfig.context_graph;
  if (cg && cg.generation_order) return cg;
  // Fallback: no context_graph defined — derive from llm_tasks in YAML order
  const tasks = (currentConfig && currentConfig.llm_tasks) || [];
  const order = tasks.map(t => t.target_placeholder);
  const deps = {}; const ds = {};
  for (const t of tasks) { deps[t.target_placeholder] = []; ds[t.target_placeholder] = []; }
  return { generation_order: order, dependencies: deps, downstream: ds };
}

function collectContext(placeholderKey) {
  const graph = getContextGraph();
  const ctx = {};
  for (const dep of (graph.dependencies[placeholderKey] || [])) {
    const history = chatHistory[dep] || [];
    const lastAI = [...history].reverse().find(m => m.role === "assistant");
    ctx[dep] = lastAI ? (lastAI.fullContent || lastAI.content || "") : "";
  }
  return ctx;
}

function captureRagContext(text) {
  const value = (text || "").trim();
  if (value && !ragContexts.includes(value)) {
    ragContexts.push(value);
  }
}

// ── User identity from URL query params ─────────────────────────────────────

let currentUser = {
  username: "anonymous",
  display_name: null,
  email: null,
  groups: [],
};

function parseUserFromURL() {
  const params = new URLSearchParams(window.location.search);
  currentUser.username = params.get("username") || "anonymous";
  currentUser.display_name = params.get("display_name") || null;
  currentUser.email = params.get("email") || null;
  const groups = params.get("groups");
  currentUser.groups = groups ? groups.split(",") : [];
}

// ── Init: Load templates on page load ────────────────────────────────────────

async function init() {
  parseUserFromURL();
  const select = document.getElementById("templateSelect");
  const desc = document.getElementById("templateDesc");

  try {
    const res = await fetch("/api/templates");
    if (!res.ok) throw new Error(await res.text());
    templates = await res.json();

    select.innerHTML = '<option value="">-- 请选择模板 --</option>';
    for (const t of templates) {
      const opt = document.createElement("option");
      opt.value = t.template_id;
      opt.textContent = t.template_name;
      select.appendChild(opt);
    }
    desc.textContent = `已加载 ${templates.length} 个模板`;
  } catch (e) {
    select.innerHTML = '<option value="">-- 加载失败 --</option>';
    desc.textContent = "加载模板失败: " + e.message;
  }
}

// ── Template selection ────────────────────────────────────────────────────────

async function handleTemplateChange(templateId) {
  const contentArea = document.getElementById("contentArea");
  const rightPanel = document.getElementById("rightPanel");
  const desc = document.getElementById("templateDesc");

  if (!templateId) {
    contentArea.classList.add("hidden");
    rightPanel.classList.add("hidden");
    currentConfig = null;
    return;
  }

  try {
    const res = await fetch(`/api/template/${templateId}`);
    if (!res.ok) throw new Error(await res.text());
    currentConfig = await res.json();
  } catch (e) {
    desc.textContent = "加载模板配置失败: " + e.message;
    return;
  }

  // Reset state
  userInputs = {};
  chatHistory = {};
  generatingSet.clear();
  ragContexts = [];
  lastBaseline = {};
  currentSessionId = (crypto.randomUUID && crypto.randomUUID()) ||
    (Date.now().toString(36) + Math.random().toString(36).slice(2));

  desc.textContent = currentConfig.description || `已选择：${currentConfig.template_name}`;

  // Render all sections
  renderCharacterize(currentConfig.user_inputs || []);
  renderAIModules(currentConfig.llm_tasks || []);
  renderClosure(currentConfig.closure_tasks || []);

  contentArea.classList.remove("hidden");

  // Render preview table
  document.getElementById("previewTitle").textContent =
    (currentConfig.template_name || "Report") + " Preview";
  renderPreviewTable(currentConfig);
  rightPanel.classList.remove("hidden");
}

// ── Section 1: Characterize ───────────────────────────────────────────────────

function renderCharacterize(inputs) {
  const container = document.getElementById("characterizeFields");
  container.innerHTML = "";

  const section = document.getElementById("characterizeSection");
  if (!inputs || inputs.length === 0) {
    section.classList.add("hidden");
    return;
  }
  section.classList.remove("hidden");

  for (const inp of inputs) {
    const div = document.createElement("div");
    div.innerHTML = buildFieldHTML(inp, "userInputs");
    container.appendChild(div);
  }
}

function buildFieldHTML(inp, stateKey) {
  const req = inp.required ? "required" : "";
  const reqMark = inp.required ? '<span class="text-red-500">*</span>' : "";

  if (inp.type === "textarea") {
    return `
      <div>
        <label class="block text-sm font-medium text-gray-700 mb-1">
          ${escapeHtml(inp.label)} ${reqMark}
        </label>
        <textarea id="input-${inp.id}" rows="3" ${req}
                  oninput="${stateKey}['${escapeJs(inp.id)}'] = this.value; updatePreview()"
                  placeholder="${escapeHtml(inp.placeholder || '')}"
                  class="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm
                         focus:ring-2 focus:ring-blue-500 focus:border-transparent"></textarea>
      </div>`;
  }
  if (inp.type === "date") {
    return `
      <div>
        <label class="block text-sm font-medium text-gray-700 mb-1">
          ${escapeHtml(inp.label)} ${reqMark}
        </label>
        <input type="date" id="input-${inp.id}" ${req}
               oninput="${stateKey}['${escapeJs(inp.id)}'] = this.value; updatePreview()"
               class="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm
                      focus:ring-2 focus:ring-blue-500 focus:border-transparent" />
      </div>`;
  }
  // Default: text
  return `
    <div>
      <label class="block text-sm font-medium text-gray-700 mb-1">
        ${escapeHtml(inp.label)} ${reqMark}
      </label>
      <input type="text" id="input-${inp.id}" ${req}
             oninput="${stateKey}['${escapeJs(inp.id)}'] = this.value; updatePreview()"
             placeholder="${escapeHtml(inp.placeholder || '')}"
             class="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm
                    focus:ring-2 focus:ring-blue-500 focus:border-transparent" />
    </div>`;
}

// ── Section 2: AI Generation (grouped by module) ─────────────────────────────

function renderAIModules(tasks) {
  const container = document.getElementById("aiModules");
  container.innerHTML = "";

  if (!tasks || tasks.length === 0) {
    document.getElementById("aiSection").classList.add("hidden");
    return;
  }
  document.getElementById("aiSection").classList.remove("hidden");

  // Group tasks by module
  const modules = {};
  for (const task of tasks) {
    const mod = task.module || "default";
    if (!modules[mod]) modules[mod] = { label: task.module_label || mod, tasks: [] };
    modules[mod].tasks.push(task);
  }

  for (const [modKey, mod] of Object.entries(modules)) {
    const groupDiv = document.createElement("div");
    groupDiv.className = "module-group pl-4 py-3";
    groupDiv.innerHTML = `
      <h3 class="text-md font-semibold text-purple-700 mb-3">${escapeHtml(mod.label)}</h3>
      <div class="space-y-4" id="mod-${cssId(modKey)}"></div>
    `;
    container.appendChild(groupDiv);

    const modContainer = groupDiv.querySelector(`#mod-${cssId(modKey)}`);
    for (const task of mod.tasks) {
      renderAITask(modContainer, task);
    }
  }
}

function renderAITask(container, task) {
  const name = task.target_placeholder;
  const div = document.createElement("div");
  div.className = "border border-gray-200 rounded-lg p-4";
  div.id = `task-${cssId(name)}`;

  div.innerHTML = `
    <!-- Task header -->
    <div class="flex items-center gap-2 mb-3">
      <span class="px-2 py-0.5 bg-purple-100 text-purple-700 rounded text-xs font-mono">
        ${escapeHtml(name)}
      </span>
    </div>

    <!-- Chat area -->
    <div class="mb-3">
      <label class="block text-xs text-gray-500 mb-1">对话</label>
      <div id="chat-${cssId(name)}"
           class="border border-gray-200 rounded-lg p-3 bg-gray-50
                  min-h-[60px] max-h-[200px] overflow-y-auto text-sm space-y-2">
        <div class="text-gray-400 text-xs italic">输入提示词开始对话...</div>
      </div>
    </div>

    <!-- Chat input -->
    <div class="flex items-center gap-2">
      <input type="text" id="prompt-${cssId(name)}"
             onkeydown="if(event.key==='Enter'&&!event.shiftKey){event.preventDefault();handleGenerate('${escapeJs(name)}')}"
             class="flex-1 border border-gray-300 rounded px-3 py-1.5 text-sm
                    focus:ring-2 focus:ring-blue-500 focus:border-transparent"
             placeholder="输入提示词，如：帮我写一句问题描述..." />
      <button onclick="handleGenerate('${escapeJs(name)}')"
              id="btn-${cssId(name)}"
              class="shrink-0 px-4 py-1.5 bg-purple-500 text-white rounded text-sm
                     hover:bg-purple-600 transition disabled:opacity-50">
        发送
      </button>
    </div>

    <div class="mt-2 flex items-center gap-2">
      <span id="status-${cssId(name)}" class="text-xs text-gray-400"></span>
      <button id="regen-${cssId(name)}" onclick="handleRegenerate('${escapeJs(name)}')"
              class="regen-btn hidden"
              title="重新生成此环节（重开 pipeline）"
              aria-label="重新生成">
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor"
             stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
          <path d="M3 12a9 9 0 0 1 15-6.7L21 8"/>
          <path d="M21 3v5h-5"/>
          <path d="M21 12a9 9 0 0 1-15 6.7L3 16"/>
          <path d="M3 21v-5h5"/>
        </svg>
      </button>
    </div>
  `;

  container.appendChild(div);
}

// ── Characterize Confirm: batch generate all AI tasks ─────────────────────────

async function handleCharacterizeConfirm() {
  const btn = document.getElementById("btnConfirm");
  const statusEl = document.getElementById("confirmStatus");

  if (!currentConfig) return;

  // Validate required fields
  for (const inp of (currentConfig.user_inputs || [])) {
    if (inp.required) {
      const field = document.getElementById(`input-${inp.id}`);
      if (field && !field.value.trim()) {
        statusEl.textContent = `请填写必填项：${inp.label}`;
        statusEl.className = "text-sm text-red-500";
        field.focus();
        return;
      }
    }
  }

  // Collect all user input values
  for (const inp of (currentConfig.user_inputs || [])) {
    const field = document.getElementById(`input-${inp.id}`);
    if (field) {
      userInputs[inp.id] = field.value;
    }
  }

  const tasks = currentConfig.llm_tasks || [];
  if (tasks.length === 0) return;

  btn.disabled = true;
  btn.style.opacity = "0.4";
  statusEl.className = "text-sm text-gray-400";

  // Serial generation in dependency order
  const taskMap = {};
  for (const t of tasks) taskMap[t.target_placeholder] = t;

  let succeeded = 0;
  let failed = 0;

  const genOrder = getContextGraph().generation_order;
  for (let i = 0; i < genOrder.length; i++) {
    const name = genOrder[i];
    const task = taskMap[name];
    if (!task) continue;  // skip if not in this template's llm_tasks

    statusEl.textContent = `正在生成 (${i + 1}/${genOrder.length})：${task.module_label || name}...`;

    const statusTaskEl = document.getElementById(`status-${cssId(name)}`);
    if (statusTaskEl) {
      statusTaskEl.textContent = "正在生成...";
      statusTaskEl.className = "text-xs text-blue-500";
    }

    const context = collectContext(name);

    try {
      const res = await fetch("/api/generate", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          session_id: currentSessionId,
          template_id: currentConfig.template_id,
          placeholder_key: name,
          message: "请根据上述信息自动生成内容",
          history: [],
          user_inputs: userInputs,
          context,
          user: currentUser,
        }),
      });
      if (!res.ok) throw new Error(await res.text());
      const data = await res.json();

      if (!chatHistory[name]) chatHistory[name] = [];
      chatHistory[name].push({
        role: "assistant",
        content: data.ack || "",
        fullContent: data.content || "",
        extractedData: data.extracted_data || "",
      });
      // 更新基线，用于下次检测右侧编辑
      lastBaseline[name] = data.content || "";
      // Capture RAG context for reference slide
      captureRagContext(data.rag_context);
      renderChatHistory(name);
      // Auto-switch preview tab to the field just generated
      switchPreviewTab(name);
      updatePreview();

      if (statusTaskEl) {
        statusTaskEl.textContent = "生成完成";
        statusTaskEl.className = "text-xs text-green-600";
      }
      const regenBtn = document.getElementById(`regen-${cssId(name)}`);
      if (regenBtn) regenBtn.classList.remove("hidden");
      succeeded++;
    } catch (e) {
      if (statusTaskEl) {
        statusTaskEl.textContent = "生成失败: " + e.message;
        statusTaskEl.className = "text-xs text-red-500";
      }
      failed++;
      // fallback: upstream failed, continue to next task (context will be empty)
    }
  }

  btn.disabled = false;
  btn.style.opacity = "1";
  statusEl.textContent = failed > 0
    ? `完成：${succeeded} 成功，${failed} 失败`
    : `全部完成 (${succeeded}/${genOrder.length})`;
  statusEl.className = failed > 0 ? "text-sm text-yellow-600" : "text-sm text-green-600";
}

// ── Generate: multi-turn conversation ─────────────────────────────────────────

async function handleGenerate(name) {
  const input = document.getElementById(`prompt-${cssId(name)}`);
  const statusEl = document.getElementById(`status-${cssId(name)}`);
  const btn = document.getElementById(`btn-${cssId(name)}`);

  const message = (input.value || "").trim();
  if (!message) return;

  // Init history if needed
  if (!chatHistory[name]) chatHistory[name] = [];

  // Append user message to history & render
  chatHistory[name].push({ role: "user", content: message });
  renderChatHistory(name);
  input.value = "";

  generatingSet.add(name);
  btn.disabled = true;
  btn.style.opacity = "0.4";
  statusEl.textContent = "正在生成中";
  statusEl.className = "text-xs text-blue-500";

  try {
    const context = collectContext(name);
    // 取用户当前在占位符文本框里看到/编辑后的内容（脱敏版），供第二次多轮 prompt 注入
    const ta = document.querySelector(`textarea[data-source-key="${CSS.escape(name)}"]`);
    const current_content = ta ? ta.value : "";

    // 检测右侧内容是否有手动编辑，如有则拼接到 prompt
    let finalMessage = message;
    const baseline = lastBaseline[name] || "";
    if (current_content && baseline && current_content !== baseline) {
      finalMessage = `用户已修改当前内容为：\n${current_content}\n\n用户消息：${message}`;
    }

    const res = await fetch("/api/generate", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        session_id: currentSessionId,
        template_id: currentConfig.template_id,
        placeholder_key: name,
        message: finalMessage,
        history: chatHistory[name],
        user_inputs: userInputs,
        context,
        user: currentUser,
        current_content,
      }),
    });
    if (!res.ok) throw new Error(await res.text());
    const data = await res.json();

    // Append AI response: ack for chat bubble, fullContent for preview/export
    if (data.ack || data.content) {
      chatHistory[name].push({
        role: "assistant",
        content: data.ack || "",
        fullContent: data.content || "",
        extractedData: data.extracted_data || "",
      });
      // 更新基线，用于下次检测右侧编辑
      lastBaseline[name] = data.content || "";
      // Capture RAG context for reference slide
      captureRagContext(data.rag_context);
      renderChatHistory(name);
      // Auto-switch preview tab to the field just updated
      switchPreviewTab(name);
    }

    statusEl.textContent = "生成完成";
    statusEl.className = "text-xs text-green-600";
    const regenBtn = document.getElementById(`regen-${cssId(name)}`);
    if (regenBtn) regenBtn.classList.remove("hidden");

  } catch (e) {
    statusEl.textContent = "生成失败: " + e.message;
    statusEl.className = "text-xs text-red-500";
  } finally {
    generatingSet.delete(name);
    btn.disabled = false;
    btn.style.opacity = "1";
  }

  updatePreview();
}

// ── Regenerate: re-run first-turn pipeline for a single field ─────────────────
// Clears the field's own chatHistory so backend takes the first-turn branch
// (re-runs extract→reason→sanitize pipeline). Upstream chatHistory is preserved,
// so collectContext() still injects upstream AI outputs into the new prompt.
// Downstream fields are NOT auto-regenerated — user must trigger them individually.
async function handleRegenerate(name) {
  const statusEl = document.getElementById(`status-${cssId(name)}`);
  const regenBtn = document.getElementById(`regen-${cssId(name)}`);
  const sendBtn = document.getElementById(`btn-${cssId(name)}`);

  // Clear this field's history so backend treats it as a fresh first turn
  chatHistory[name] = [];
  renderChatHistory(name);

  if (regenBtn) regenBtn.disabled = true;
  if (sendBtn) sendBtn.disabled = true;
  if (statusEl) {
    statusEl.textContent = "正在重新生成...";
    statusEl.className = "text-xs text-blue-500";
  }

  const context = collectContext(name);
  try {
    const res = await fetch("/api/generate", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        session_id: currentSessionId,
        template_id: currentConfig.template_id,
        placeholder_key: name,
        message: "请根据上述信息自动生成内容",
        history: [],
        user_inputs: userInputs,
        context,
        user: currentUser,
      }),
    });
    if (!res.ok) throw new Error(await res.text());
    const data = await res.json();

    chatHistory[name].push({
      role: "assistant",
      content: data.ack || "",
      fullContent: data.content || "",
      extractedData: data.extracted_data || "",
    });
    captureRagContext(data.rag_context);
    renderChatHistory(name);
    switchPreviewTab(name);
    updatePreview();

    if (statusEl) {
      statusEl.textContent = "生成完成";
      statusEl.className = "text-xs text-green-600";
    }
  } catch (e) {
    if (statusEl) {
      statusEl.textContent = "生成失败: " + e.message;
      statusEl.className = "text-xs text-red-500";
    }
  } finally {
    if (regenBtn) regenBtn.disabled = false;
    if (sendBtn) sendBtn.disabled = false;
  }
}

// ── Render chat history ──────────────────────────────────────────────────────

function renderChatHistory(name) {
  const container = document.getElementById(`chat-${cssId(name)}`);
  if (!container) return;

  const history = chatHistory[name] || [];
  if (history.length === 0) {
    container.innerHTML = '<div class="text-gray-400 text-xs italic">输入提示词开始对话...</div>';
    return;
  }

  container.innerHTML = history.map(msg => {
    const isUser = msg.role === "user";
    const bubble = isUser
      ? `<div class="flex justify-end"><div class="bg-blue-100 text-blue-800 px-3 py-1.5 rounded-lg rounded-br-none max-w-[80%] text-sm">${escapeHtml(msg.content)}</div></div>`
      : `<div class="flex justify-start"><div class="bg-white border border-gray-200 text-gray-700 px-3 py-1.5 rounded-lg rounded-bl-none max-w-[80%] text-sm">${escapeHtml(msg.content)}</div></div>`;
    return bubble;
  }).join("");

  // Auto-scroll to bottom
  container.scrollTop = container.scrollHeight;
}

// ── Section 3: Closure ────────────────────────────────────────────────────────

function renderClosure(closureTasks) {
  const container = document.getElementById("closureFields");
  container.innerHTML = "";

  const section = document.getElementById("closureSection");
  if (!closureTasks || closureTasks.length === 0) {
    section.classList.add("hidden");
    return;
  }
  section.classList.remove("hidden");

  for (const task of closureTasks) {
    renderAITask(container, task);
  }
}

// ── Preview Table (Right Panel) ──────────────────────────────────────────────

function renderPreviewTable(config) {
  const container = document.getElementById("previewTable");
  container.innerHTML = "";
  previewFields = [];
  previewTabs = [];
  activePreviewTab = null;

  // ── Collect tabs in display order: llm_tasks (in YAML order) first, closure last ──
  const llmTasks = config.llm_tasks || [];
  for (const task of llmTasks) {
    const key = `preview-ai-${cssId(task.target_placeholder)}`;
    const tab = {
      sourceKey: task.target_placeholder,
      key,
      label: task.module_label || task.target_placeholder,
      source: "chatHistory",
      hasExtract: true,
      accent: "purple",
    };
    previewTabs.push(tab);
    previewFields.push({
      key,
      label: task.target_placeholder,
      source: "chatHistory",
      sourceKey: task.target_placeholder,
    });
  }

  const closureTasks = config.closure_tasks || [];
  for (const task of closureTasks) {
    const key = `preview-closure-${cssId(task.target_placeholder)}`;
    const tab = {
      sourceKey: task.target_placeholder,
      key,
      label: task.label || task.target_placeholder,
      source: "chatHistory",
      hasExtract: false,
      accent: "green",
    };
    previewTabs.push(tab);
    previewFields.push({
      key,
      label: task.label || task.target_placeholder,
      source: "chatHistory",
      sourceKey: task.target_placeholder,
    });
  }

  if (previewTabs.length === 0) {
    container.innerHTML = '<div class="text-gray-400 text-sm italic">无预览字段</div>';
    return;
  }

  // ── Render tab bar + content container ──
  const ringColor = "purple"; // default; per-tab override below via data-accent
  container.innerHTML = `
    <div class="preview-tabs" id="previewTabBar">
      ${previewTabs.map(t => `
        <button class="preview-tab"
                data-source-key="${escapeJs(t.sourceKey)}"
                data-accent="${escapeJs(t.accent)}"
                data-active="false"
                onclick="switchPreviewTab('${escapeJs(t.sourceKey)}')">
          ${escapeHtml(t.label)}
        </button>
      `).join("")}
    </div>
    <div id="previewTabContent" class="flex-1 min-h-0 flex flex-col"></div>
  `;

  // Default to first tab
  switchPreviewTab(previewTabs[0].sourceKey);
}

function switchPreviewTab(sourceKey) {
  const tab = previewTabs.find(t => t.sourceKey === sourceKey);
  if (!tab) return;
  activePreviewTab = sourceKey;

  // Update tab bar highlight
  document.querySelectorAll(".preview-tab").forEach(btn => {
    btn.dataset.active = btn.dataset.sourceKey === sourceKey ? "true" : "false";
  });

  // Render tab content: header + textarea (flex-1) + optional extract panel
  const content = document.getElementById("previewTabContent");
  const ringClass = tab.accent === "green" ? "focus:ring-green-400" : "focus:ring-purple-400";
  content.innerHTML = `
    <div class="flex flex-col h-full min-h-0">
      <div class="mb-2 shrink-0 flex items-center gap-2">
        <span class="px-2 py-0.5 ${tab.accent === "green" ? "bg-green-50 text-green-700" : "bg-purple-100 text-purple-700"} rounded text-xs font-mono">
          ${escapeHtml(tab.sourceKey)}
        </span>
      </div>
      <textarea id="${tab.key}"
                data-source="${tab.source}"
                data-source-key="${escapeJs(sourceKey)}"
                oninput="handlePreviewEdit(this)"
                class="flex-1 min-h-0 h-full w-full border border-gray-200 rounded-lg px-3 py-2 text-sm resize-none
                       focus:ring-2 ${ringClass} focus:border-transparent bg-white font-mono"
                placeholder="待生成..."></textarea>
      ${tab.hasExtract ? `
        <details id="extract-${cssId(sourceKey)}" class="mt-2 shrink-0">
          <summary class="cursor-pointer text-xs text-purple-600 hover:text-purple-800 select-none">
            ▶ 资料整理
          </summary>
          <div class="mt-1 p-2 bg-purple-50 rounded text-xs text-gray-700 whitespace-pre-wrap max-h-48 overflow-y-auto"></div>
        </details>` : ""}
    </div>
  `;

  // Fill in current value + extract panel
  updatePreview();
}

function handlePreviewEdit(textarea) {
  const source = textarea.dataset.source;
  const sourceKey = textarea.dataset.sourceKey;
  const value = textarea.value;

  if (source === "userInputs") {
    // Update userInputs state
    userInputs[sourceKey] = value;
    // Sync back to left panel input
    const leftInput = document.getElementById(`input-${sourceKey}`);
    if (leftInput) leftInput.value = value;
  } else if (source === "chatHistory") {
    // Update or create the last assistant message's fullContent
    if (!chatHistory[sourceKey]) chatHistory[sourceKey] = [];
    const history = chatHistory[sourceKey];
    const lastAIIdx = [...history].reverse().findIndex(m => m.role === "assistant");
    if (lastAIIdx !== -1) {
      const realIdx = history.length - 1 - lastAIIdx;
      history[realIdx].fullContent = value;
    } else {
      // No AI message yet, create a synthetic one
      history.push({ role: "assistant", content: "", fullContent: value });
    }
  }
}

function updatePreview() {
  for (const field of previewFields) {
    const el = document.getElementById(field.key);
    if (!el) continue;

    // Skip if the textarea is currently focused (user is editing)
    if (document.activeElement === el) continue;

    let value = "";

    if (field.source === "userInputs") {
      value = (userInputs[field.sourceKey] || "").trim();
    } else if (field.source === "chatHistory") {
      const history = chatHistory[field.sourceKey] || [];
      const lastAI = [...history].reverse().find(m => m.role === "assistant" && m.fullContent);
      if (lastAI) {
        value = (lastAI.fullContent || "").trim();
      }
    }

    el.value = value;

    // 更新资料整理折叠面板（扫描全历史，找任意一条有 extractedData 的消息）
    if (field.source === "chatHistory") {
      const extractEl = document.getElementById(`extract-${cssId(field.sourceKey)}`);
      if (extractEl) {
        const history = chatHistory[field.sourceKey] || [];
        const found = [...history].reverse().find(m => m.role === "assistant" && m.extractedData);
        if (found) {
          extractEl.classList.remove("hidden");
          extractEl.querySelector("div").textContent = found.extractedData;
        } else {
          extractEl.classList.add("hidden");
        }
      }
    }
  }
}

// ── Export ────────────────────────────────────────────────────────────────────

async function handleExport() {
  const status = document.getElementById("exportStatus");
  const btn = document.getElementById("btnExport");

  if (!currentConfig) {
    status.textContent = "请先选择模板";
    return;
  }

  // Compute final data from chatHistory (latest AI fullContent for each task)
  const exportFinal = {};
  for (const task of (currentConfig.llm_tasks || [])) {
    const history = chatHistory[task.target_placeholder] || [];
    const lastAI = [...history].reverse().find(m => m.role === "assistant");
    if (lastAI?.fullContent) {
      exportFinal[task.target_placeholder] = lastAI.fullContent;
    }
  }
  for (const task of (currentConfig.closure_tasks || [])) {
    const history = chatHistory[task.target_placeholder] || [];
    const lastAI = [...history].reverse().find(m => m.role === "assistant");
    if (lastAI?.fullContent) {
      exportFinal[task.target_placeholder] = lastAI.fullContent;
    }
  }

  status.textContent = "导出中...";
  btn.disabled = true;

  try {
    const res = await fetch("/api/export", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        session_id: currentSessionId,
        template_id: currentConfig.template_id,
        user_inputs: userInputs,
        final_data: exportFinal,
        rag_results: ragContexts.join("\n\n"),
      }),
    });
    if (!res.ok) throw new Error(await res.text());

    const blob = await res.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `${currentConfig.template_name || "output"}.pptx`;
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
  return str.replace(/[^a-zA-Z0-9_-]/g, "_");
}

// ── Boot ─────────────────────────────────────────────────────────────────────
init();
