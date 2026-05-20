// zeroAgent Web · 前端
// 功能：
//   - Provider 列表 / 切换（底部下拉）
//   - 多会话历史（localStorage 持久化，左侧栏新建/切换/删除/重命名）
//   - 流式 SSE / 非流式 fallback
//   - Markdown 渲染（marked + DOMPurify）
//   - 代码高亮（highlight.js）+ 数学公式（KaTeX）
//   - 流式中实时装饰代码块、消息时间戳、复制按钮

const $ = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));

const LS_CONV = "zeroAgent.conversations.v1";
const LS_PREFS = "zeroAgent.prefs.v1";

const state = {
  providers: [],
  defaultProvider: null,

  conversations: [],   // [{id, title, provider, createdAt, updatedAt, messages: [{role, content, ts, tool_calls?}]}]
  activeId: null,

  prefs: {
    temperature: 0.7,
    streaming: true,
    system: "",
    provider: null,
    toolsEnabled: false,
  },

  inFlight: false,
  abortCtrl: null,

  // 当前 run 的会话状态
  run: null,           // { runId, msgRef, calls: Map<id, {el, tool, args, result?}> }
  pendingApproval: null, // { runId, callId, tool, args, side_effect, description }
};

// ========== marked + hljs ==========

if (window.marked) {
  marked.setOptions({
    gfm: true,
    breaks: true,
    headerIds: false,
    mangle: false,
    highlight: function (code, lang) {
      if (!window.hljs) return code;
      try {
        if (lang && hljs.getLanguage(lang)) {
          return hljs.highlight(code, { language: lang, ignoreIllegals: true }).value;
        }
        return hljs.highlightAuto(code).value;
      } catch {
        return code;
      }
    },
  });
}

function renderMarkdown(text) {
  if (!text) return "";
  // 把 KaTeX 风格的 $...$ / $$...$$ / \(\) / \[\] 占位，避免被 marked 把下标/星号破坏
  // 简化策略：在 marked 之前先用 placeholder 抽掉数学块，渲染完再塞回去
  const { masked, slots } = maskMath(text);
  let html;
  if (window.marked && window.DOMPurify) {
    html = marked.parse(masked);
  } else {
    html = escapeHtml(masked).replace(/\n/g, "<br>");
  }
  html = unmaskMath(html, slots);
  if (window.DOMPurify) {
    html = DOMPurify.sanitize(html, {
      ADD_ATTR: ["target", "rel"],
      // KaTeX 渲染产物用 <span class="katex">…</span>，DOMPurify 默认放行
    });
  }
  return html;
}

// 抽取数学块，避免 markdown 干扰；占位符长度足够独特
function maskMath(text) {
  const slots = [];
  const push = (raw) => {
    const idx = slots.length;
    slots.push(raw);
    return `\u0000MATH${idx}\u0000`;
  };
  let masked = text;
  // 顺序：$$...$$ -> \[...\] -> \(...\) -> $...$
  masked = masked.replace(/\$\$([\s\S]+?)\$\$/g, (_, c) => push(`$$${c}$$`));
  masked = masked.replace(/\\\[([\s\S]+?)\\\]/g, (_, c) => push(`\\[${c}\\]`));
  masked = masked.replace(/\\\(([\s\S]+?)\\\)/g, (_, c) => push(`\\(${c}\\)`));
  // 行内 $...$：要求 $ 紧贴非空白，避免误吞货币符号
  masked = masked.replace(/(?<![\\$])\$(?!\s)([^\$\n]+?)(?<!\s)\$(?!\d)/g, (_, c) => push(`$${c}$`));
  return { masked, slots };
}

function unmaskMath(html, slots) {
  return html.replace(/\u0000MATH(\d+)\u0000/g, (_, i) => slots[Number(i)] || "");
}

function renderMath(rootEl) {
  if (!window.renderMathInElement) return;
  try {
    renderMathInElement(rootEl, {
      delimiters: [
        { left: "$$", right: "$$", display: true },
        { left: "\\[", right: "\\]", display: true },
        { left: "\\(", right: "\\)", display: false },
        { left: "$", right: "$", display: false },
      ],
      throwOnError: false,
      ignoredTags: ["script", "noscript", "style", "textarea", "pre", "code"],
    });
  } catch {}
}

// ========== 初始化 ==========

async function init() {
  loadPrefs();
  loadConversations();
  bindUI();
  await loadProviders();
  // 没会话则建一个
  if (state.conversations.length === 0) {
    newConversation();
  } else {
    setActive(state.conversations[0].id);
  }
  renderConvList();
}

function loadPrefs() {
  try {
    const raw = localStorage.getItem(LS_PREFS);
    if (raw) Object.assign(state.prefs, JSON.parse(raw));
  } catch {}
}

function savePrefs() {
  try { localStorage.setItem(LS_PREFS, JSON.stringify(state.prefs)); } catch {}
}

function loadConversations() {
  try {
    const raw = localStorage.getItem(LS_CONV);
    if (raw) state.conversations = JSON.parse(raw);
  } catch {}
}

function saveConversations() {
  try {
    localStorage.setItem(LS_CONV, JSON.stringify(state.conversations));
  } catch {}
}

async function loadProviders() {
  try {
    const res = await fetch("/api/providers");
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();
    state.providers = data.providers;
    state.defaultProvider = data.current;
    if (!state.prefs.provider) state.prefs.provider = data.current;
    renderModelMenu();
    updateModelLabel();
  } catch (e) {
    setStatus(`加载 Provider 失败：${e.message}`, true);
  }
}

// ========== 会话管理 ==========

function genId() {
  return "c-" + Date.now().toString(36) + "-" + Math.random().toString(36).slice(2, 8);
}

function activeConv() {
  return state.conversations.find((c) => c.id === state.activeId) || null;
}

function newConversation() {
  const c = {
    id: genId(),
    title: "新对话",
    provider: state.prefs.provider || state.defaultProvider,
    createdAt: Date.now(),
    updatedAt: Date.now(),
    messages: [],
  };
  state.conversations.unshift(c);
  saveConversations();
  setActive(c.id);
  renderConvList();
}

function setActive(id) {
  state.activeId = id;
  const c = activeConv();
  if (c) {
    $("#conv-title").textContent = c.title;
    state.prefs.provider = c.provider || state.prefs.provider;
    updateModelLabel();
    renderMessages();
  }
}

function deleteConversation(id) {
  const idx = state.conversations.findIndex((c) => c.id === id);
  if (idx < 0) return;
  state.conversations.splice(idx, 1);
  saveConversations();
  if (state.activeId === id) {
    if (state.conversations.length === 0) newConversation();
    else setActive(state.conversations[0].id);
  }
  renderConvList();
}

function renameConversation(id, title) {
  const c = state.conversations.find((c) => c.id === id);
  if (!c) return;
  c.title = (title || "未命名").slice(0, 60);
  c.updatedAt = Date.now();
  saveConversations();
  renderConvList();
}

function pushMessage(role, content) {
  const c = activeConv();
  if (!c) return;
  c.messages.push({ role, content, ts: Date.now() });
  c.updatedAt = Date.now();
  // 首条 user 消息自动定标题
  if (c.title === "新对话" && role === "user") {
    c.title = content.replace(/\s+/g, " ").trim().slice(0, 30) || "新对话";
    $("#conv-title").textContent = c.title;
  }
  saveConversations();
  renderConvList();
}

function renderConvList() {
  const list = $("#conv-list");
  if (state.conversations.length === 0) {
    list.innerHTML = `<div class="muted">暂无会话</div>`;
    return;
  }
  list.innerHTML = "";
  state.conversations.forEach((c) => {
    const item = document.createElement("div");
    item.className = "conv-item" + (c.id === state.activeId ? " active" : "");
    item.dataset.id = c.id;
    const sub = c.messages.length
      ? `${c.messages.length} 条 · ${formatRelative(c.updatedAt)}`
      : "空对话";
    item.innerHTML = `
      <div class="conv-main">
        <div class="conv-title" title="${escapeHtml(c.title)}">${escapeHtml(c.title)}</div>
        <div class="conv-sub">${escapeHtml(sub)}</div>
      </div>
      <button class="conv-del" data-act="del-conv" title="删除">
        <svg viewBox="0 0 16 16" width="13" height="13" fill="none" stroke="currentColor" stroke-width="1.6">
          <path d="M3 4h10M6.5 4V2.5h3V4M5 4l.5 9h5L11 4" stroke-linecap="round" stroke-linejoin="round"/>
        </svg>
      </button>
    `;
    list.appendChild(item);
  });
}

function formatRelative(ts) {
  const d = Date.now() - ts;
  if (d < 60_000) return "刚刚";
  if (d < 3_600_000) return Math.floor(d / 60_000) + " 分钟前";
  if (d < 86_400_000) return Math.floor(d / 3_600_000) + " 小时前";
  if (d < 7 * 86_400_000) return Math.floor(d / 86_400_000) + " 天前";
  const dt = new Date(ts);
  return `${dt.getMonth() + 1}/${dt.getDate()}`;
}

function renderMessages() {
  const c = activeConv();
  const m = $("#messages");
  if (!c || c.messages.length === 0) {
    renderEmpty();
    return;
  }
  m.innerHTML = "";
  c.messages.forEach((msg) => {
    appendMessage(msg.role, msg.content, {
      provider: msg.role === "assistant" ? c.provider : undefined,
      ts: msg.ts,
      persisted: true,
    });
  });
}

// ========== Provider / 模型下拉 ==========

function renderModelMenu() {
  const list = $("#model-menu-list");
  list.innerHTML = "";
  state.providers.forEach((p) => {
    const item = document.createElement("button");
    item.type = "button";
    item.className = "model-item" + (p.name === state.prefs.provider ? " active" : "");
    item.dataset.name = p.name;
    item.innerHTML = `
      <span class="model-item-name">${escapeHtml(p.name)}</span>
      <span class="model-item-model">${escapeHtml(p.model)}</span>
      ${p.is_default ? '<span class="model-item-badge">默认</span>' : ""}
    `;
    list.appendChild(item);
  });
}

function updateModelLabel() {
  const p = state.providers.find((x) => x.name === state.prefs.provider);
  $("#model-label").textContent = p ? p.name : (state.prefs.provider || "选择模型");
  // 把当前会话的 provider 同步
  const c = activeConv();
  if (c) {
    c.provider = state.prefs.provider;
    saveConversations();
  }
  renderModelMenu();
}

function toggleModelMenu(force) {
  const menu = $("#model-menu");
  const open = force === undefined ? menu.hasAttribute("hidden") : force;
  if (open) menu.removeAttribute("hidden");
  else menu.setAttribute("hidden", "");
}

function toggleSettings(force) {
  const pop = $("#settings-pop");
  const open = force === undefined ? pop.hasAttribute("hidden") : force;
  if (open) pop.removeAttribute("hidden");
  else pop.setAttribute("hidden", "");
}

// ========== UI 绑定 ==========

function bindUI() {
  $("#send-btn").onclick = onSend;
  $("#input").addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey && !e.isComposing) {
      e.preventDefault();
      onSend();
    }
  });
  $("#input").addEventListener("input", (e) => autoResize(e.target));

  $("#clear-btn").onclick = () => {
    const c = activeConv();
    if (!c) return;
    if (state.inFlight && state.abortCtrl) state.abortCtrl.abort();
    c.messages = [];
    c.title = "新对话";
    c.updatedAt = Date.now();
    saveConversations();
    $("#conv-title").textContent = c.title;
    renderEmpty();
    renderConvList();
    setStatus("已清空");
  };
  $("#new-chat-btn").onclick = () => newConversation();

  // 标题就地编辑
  const titleEl = $("#conv-title");
  titleEl.addEventListener("blur", () => {
    const c = activeConv();
    if (c) renameConversation(c.id, titleEl.textContent);
  });
  titleEl.addEventListener("keydown", (e) => {
    if (e.key === "Enter") { e.preventDefault(); titleEl.blur(); }
  });

  // 参数面板
  const tempEl = $("#temperature");
  const streamEl = $("#stream-toggle");
  const sysEl = $("#system-prompt");
  tempEl.value = state.prefs.temperature;
  streamEl.checked = state.prefs.streaming;
  sysEl.value = state.prefs.system || "";
  $("#temp-val").textContent = state.prefs.temperature;
  tempEl.oninput = (e) => {
    state.prefs.temperature = parseFloat(e.target.value);
    $("#temp-val").textContent = e.target.value;
    savePrefs();
  };
  streamEl.onchange = (e) => { state.prefs.streaming = e.target.checked; savePrefs(); };
  sysEl.onchange = (e) => { state.prefs.system = e.target.value; savePrefs(); };

  // 工具开关
  updateToolsBtn();
  $("#tools-btn").onclick = () => {
    state.prefs.toolsEnabled = !state.prefs.toolsEnabled;
    savePrefs();
    updateToolsBtn();
    setStatus(state.prefs.toolsEnabled ? "已启用工具（ReAct）" : "已关闭工具");
  };

  // 审批弹层
  $("#approval-allow").onclick = () => respondApproval(true);
  $("#approval-deny").onclick = () => respondApproval(false);

  // 模型按钮
  $("#model-btn").onclick = (e) => {
    e.stopPropagation();
    toggleSettings(false);
    toggleModelMenu();
  };
  $("#settings-btn").onclick = (e) => {
    e.stopPropagation();
    toggleModelMenu(false);
    toggleSettings();
  };
  // 模型菜单点击
  $("#model-menu-list").addEventListener("click", (e) => {
    const it = e.target.closest(".model-item");
    if (!it) return;
    state.prefs.provider = it.dataset.name;
    savePrefs();
    updateModelLabel();
    toggleModelMenu(false);
  });

  // 全局点击关闭弹层
  document.addEventListener("click", (e) => {
    if (!e.target.closest("#model-picker")) toggleModelMenu(false);
    if (!e.target.closest("#settings-btn") && !e.target.closest("#settings-pop")) toggleSettings(false);
  });

  // 空态建议
  $("#messages").addEventListener("click", (e) => {
    const sg = e.target.closest(".suggest");
    if (sg) {
      $("#input").value = sg.dataset.text;
      autoResize($("#input"));
      $("#input").focus();
      return;
    }
    onMessagesClick(e);
  });

  // 会话列表点击
  $("#conv-list").addEventListener("click", (e) => {
    const delBtn = e.target.closest('[data-act="del-conv"]');
    const item = e.target.closest(".conv-item");
    if (delBtn && item) {
      e.stopPropagation();
      deleteConversation(item.dataset.id);
      return;
    }
    if (item) setActive(item.dataset.id);
  });
}

function autoResize(ta) {
  ta.style.height = "auto";
  ta.style.height = Math.min(ta.scrollHeight, 200) + "px";
}

// ========== 时间戳 / 复制 ==========

function formatTime(ts) {
  const d = ts ? new Date(ts) : new Date();
  const pad = (n) => String(n).padStart(2, "0");
  return `${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`;
}

async function copyText(text, btn) {
  try {
    await navigator.clipboard.writeText(text);
    flashBtn(btn, "已复制");
  } catch {
    const ta = document.createElement("textarea");
    ta.value = text;
    document.body.appendChild(ta);
    ta.select();
    try {
      document.execCommand("copy");
      flashBtn(btn, "已复制");
    } catch {
      flashBtn(btn, "失败", true);
    } finally { ta.remove(); }
  }
}

function flashBtn(btn, text, isErr = false) {
  if (!btn) return;
  const orig = btn.dataset.label || btn.textContent;
  btn.dataset.label = orig;
  btn.textContent = text;
  btn.classList.toggle("ok", !isErr);
  btn.classList.toggle("err", isErr);
  setTimeout(() => {
    btn.textContent = orig;
    btn.classList.remove("ok", "err");
  }, 1200);
}

function onMessagesClick(e) {
  const target = e.target.closest("[data-act]");
  if (!target) return;
  const act = target.dataset.act;
  if (act === "copy-msg") {
    const msgEl = target.closest(".msg");
    copyText(msgEl?.dataset.raw || "", target);
  } else if (act === "copy-code") {
    const pre = target.closest(".code-block")?.querySelector("pre");
    copyText(pre ? pre.innerText : "", target);
  }
}

// 给代码块包工具栏 + 应用 hljs（幂等）
function decorateCodeBlocks(rootEl) {
  rootEl.querySelectorAll("pre").forEach((pre) => {
    if (pre.parentElement?.classList.contains("code-block")) return;
    const codeEl = pre.querySelector("code");
    const lang = codeEl?.className.match(/language-(\w+)/)?.[1] || "";
    const wrap = document.createElement("div");
    wrap.className = "code-block";
    wrap.innerHTML = `
      <div class="code-toolbar">
        <span class="code-lang">${escapeHtml(lang || "text")}</span>
        <button class="code-copy" data-act="copy-code" title="复制代码">复制</button>
      </div>
    `;
    pre.parentElement.insertBefore(wrap, pre);
    wrap.appendChild(pre);
    if (codeEl && window.hljs && !codeEl.dataset.hljs) {
      try {
        if (lang && hljs.getLanguage(lang)) {
          hljs.highlightElement(codeEl);
        } else {
          // 已经被 marked.highlight 处理过的会带 hljs class，这里只对裸 <code> 兜底
          if (!codeEl.classList.contains("hljs")) hljs.highlightElement(codeEl);
        }
        codeEl.dataset.hljs = "1";
      } catch {}
    }
  });
  rootEl.querySelectorAll("a[href^='http']").forEach((a) => {
    a.target = "_blank";
    a.rel = "noopener noreferrer";
  });
}

// ========== 消息渲染 ==========

function renderEmpty() {
  $("#messages").innerHTML = `
    <div class="empty-state">
      <div class="empty-emoji">✨</div>
      <div class="empty-title">开始与 zeroAgent 对话</div>
      <div class="empty-sub">在下方选择模型并输入消息</div>
      <div class="suggest-row">
        <button class="suggest" data-text="你是谁？用一句话介绍。">你是谁</button>
        <button class="suggest" data-text="解释一下 MCP 协议是什么">解释 MCP</button>
        <button class="suggest" data-text="写一个 Python 装饰器，记录函数执行时间">写代码</button>
        <button class="suggest" data-text="推导 $e^{i\\pi} + 1 = 0$ 并解释欧拉公式">数学公式</button>
      </div>
    </div>
  `;
}

/**
 * @param {string} role  user|assistant
 * @param {string} content  原始 markdown
 * @param {object} opts  { provider, ts, error, persisted }
 */
function appendMessage(role, content, opts = {}) {
  const empty = document.querySelector(".empty-state");
  if (empty) empty.remove();

  const wrap = document.createElement("div");
  wrap.className = `msg ${role}` + (opts.error ? " error" : "");
  wrap.dataset.raw = content;
  const ts = formatTime(opts.ts);
  wrap.innerHTML = `
    <div class="avatar">${role === "user" ? "🧑" : "🤖"}</div>
    <div class="body">
      <div class="role-tag">
        <span class="role-name">${role === "user" ? "你" : "助手"}</span>
        ${opts.provider ? `<span class="badge">${escapeHtml(opts.provider)}</span>` : ""}
        <span class="time">${ts}</span>
        <span class="role-actions">
          <button class="msg-copy" data-act="copy-msg" title="复制消息原文">复制</button>
        </span>
      </div>
      <div class="content"></div>
    </div>
  `;
  const contentEl = wrap.querySelector(".content");
  contentEl.innerHTML = renderMarkdown(content);
  decorateCodeBlocks(contentEl);
  renderMath(contentEl);

  $("#messages").appendChild(wrap);
  scrollToBottom();

  return {
    root: wrap,
    contentEl,
    setRaw: (s) => { wrap.dataset.raw = s; },
  };
}

function scrollToBottom() {
  const m = $("#messages");
  m.scrollTop = m.scrollHeight;
}

// ========== 发送 ==========

async function onSend() {
  if (state.inFlight) return;
  const input = $("#input");
  const text = input.value.trim();
  if (!text) return;
  if (!state.prefs.provider) {
    setStatus("请先选择模型", true);
    return;
  }

  pushMessage("user", text);
  appendMessage("user", text);
  input.value = "";
  autoResize(input);

  const c = activeConv();
  c.provider = state.prefs.provider;

  const payload = {
    provider: state.prefs.provider,
    messages: c.messages.map(({ role, content }) => ({ role, content })),
    system: state.prefs.system || null,
    temperature: state.prefs.temperature,
  };

  state.inFlight = true;
  $("#send-btn").disabled = true;
  setStatus(`${state.prefs.provider} 思考中…`);

  try {
    if (state.prefs.toolsEnabled) {
      await sendRun(payload);
    } else if (state.prefs.streaming) {
      await sendStream(payload);
    } else {
      await sendOnce(payload);
    }
  } catch (e) {
    if (e.name === "AbortError") {
      setStatus("已中止");
    } else {
      appendMessage("assistant", `请求失败：${e.message}`, { error: true });
      setStatus("出错", true);
    }
  } finally {
    state.inFlight = false;
    $("#send-btn").disabled = false;
  }
}

async function sendOnce(payload) {
  const res = await fetch("/api/chat", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!res.ok) throw new Error(await res.text());
  const data = await res.json();
  pushMessage("assistant", data.content);
  appendMessage("assistant", data.content, { provider: data.provider });
  setStatus("完成");
}

async function sendStream(payload) {
  state.abortCtrl = new AbortController();
  const res = await fetch("/api/chat/stream", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
    signal: state.abortCtrl.signal,
  });
  if (!res.ok || !res.body) throw new Error(`HTTP ${res.status}`);

  const msg = appendMessage("assistant", "", { provider: payload.provider });
  const contentEl = msg.contentEl;
  contentEl.innerHTML = '<span class="cursor"></span>';

  let buf = "";
  let acc = "";
  let providerActual = payload.provider;
  let lastDecorate = 0;
  const reader = res.body.getReader();
  const decoder = new TextDecoder();

  const renderInto = (text, withCursor) => {
    contentEl.innerHTML = renderMarkdown(text) + (withCursor ? '<span class="cursor"></span>' : "");
    // 流式装饰：节流，每 120ms 最多一次（避免每个 token 都 hljs 高亮一次）
    const now = performance.now();
    if (!withCursor || now - lastDecorate > 120) {
      decorateCodeBlocks(contentEl);
      renderMath(contentEl);
      lastDecorate = now;
    }
  };

  const handleSseEvent = (raw) => {
    const evt = parseSseEvent(raw);
    if (!evt) return;
    if (evt.event === "meta") {
      try { providerActual = JSON.parse(evt.data).provider || providerActual; } catch {}
      const badge = msg.root.querySelector(".role-tag .badge");
      if (badge) badge.textContent = providerActual;
    } else if (evt.event === "delta") {
      try {
        const piece = JSON.parse(evt.data).content || "";
        acc += piece;
        renderInto(acc, true);
        scrollToBottom();
      } catch {}
    } else if (evt.event === "usage") {
      try {
        const u = JSON.parse(evt.data);
        setStatus(`完成 · ${u.total_tokens} tokens (in ${u.prompt_tokens} / out ${u.completion_tokens})`);
      } catch {}
    } else if (evt.event === "error") {
      try {
        const err = JSON.parse(evt.data);
        contentEl.innerHTML = renderMarkdown(acc + `\n\n**[${err.type}]** ${err.message}`);
        decorateCodeBlocks(contentEl);
        renderMath(contentEl);
        msg.root.classList.add("error");
      } catch {}
    }
  };

  const flushEvents = () => {
    buf = buf.replace(/\r\n/g, "\n");
    let idx;
    while ((idx = buf.indexOf("\n\n")) >= 0) {
      const raw = buf.slice(0, idx);
      buf = buf.slice(idx + 2);
      handleSseEvent(raw);
    }
  };

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buf += decoder.decode(value, { stream: true });
    flushEvents();
  }
  buf += decoder.decode();
  if (buf.trim()) { buf += "\n\n"; flushEvents(); }

  // 最终化
  renderInto(acc, false);
  msg.setRaw(acc);
  pushMessage("assistant", acc);
  if (!$("#status-bar").textContent.startsWith("完成")) setStatus("完成");
}

function parseSseEvent(raw) {
  const lines = raw.split("\n");
  const out = { event: "message", data: "" };
  for (const line of lines) {
    if (line.startsWith("event:")) {
      out.event = line.slice(6).trim();
    } else if (line.startsWith("data:")) {
      let v = line.slice(5);
      if (v.startsWith(" ")) v = v.slice(1);
      out.data += v;
    }
  }
  return out.data ? out : null;
}

function escapeHtml(s) {
  return String(s)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#039;");
}

function setStatus(text, isErr = false) {
  const el = $("#status-bar");
  el.textContent = text;
  el.style.color = isErr ? "var(--danger)" : "var(--text-mute)";
}

// ========== 工具开关 ==========

function updateToolsBtn() {
  const btn = $("#tools-btn");
  const lab = $("#tools-btn-label");
  if (state.prefs.toolsEnabled) {
    btn.classList.add("on");
    lab.textContent = "工具：开";
  } else {
    btn.classList.remove("on");
    lab.textContent = "工具：关";
  }
}

// ========== /api/run/stream（带工具的 ReAct） ==========

async function sendRun(payload) {
  state.abortCtrl = new AbortController();
  const runPayload = {
    provider: payload.provider,
    messages: payload.messages,
    system: payload.system,
    temperature: payload.temperature,
    max_steps: 8,
  };
  const res = await fetch("/api/run/stream", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(runPayload),
    signal: state.abortCtrl.signal,
  });
  if (!res.ok || !res.body) throw new Error(`HTTP ${res.status}`);

  // assistant 气泡（流式追加 final_content + 工具时间线卡片）
  const msg = appendMessage("assistant", "", { provider: payload.provider });
  const contentEl = msg.contentEl;
  // 时间线容器：放在 content 之上
  const timeline = document.createElement("div");
  timeline.className = "tool-timeline";
  msg.root.querySelector(".body").insertBefore(timeline, contentEl);
  contentEl.innerHTML = '<span class="muted">规划中…</span>';

  state.run = { runId: null, msgRef: msg, timeline, calls: new Map() };

  let buf = "";
  let finalText = "";
  const reader = res.body.getReader();
  const decoder = new TextDecoder();

  const setFinal = (text) => {
    finalText = text || "";
    contentEl.innerHTML = renderMarkdown(finalText);
    decorateCodeBlocks(contentEl);
    renderMath(contentEl);
    msg.setRaw(finalText);
  };

  const handleEvt = (evt) => {
    const data = safeJSON(evt.data);
    switch (evt.event) {
      case "meta":
        state.run.runId = data.run_id;
        break;
      case "run_start":
        appendTimeline(timeline, `<div class="tl-row tl-info">▶ 开始（max_steps=${data.max_steps}, tools=${(data.tools || []).length}）</div>`);
        break;
      case "step_start":
        appendTimeline(timeline, `<div class="tl-step">— 步骤 ${data.step + 1} —</div>`);
        break;
      case "llm_message":
        if (data.tool_calls && data.tool_calls.length) {
          // 把规划中的占位换掉
          if (contentEl.querySelector(".muted")) contentEl.innerHTML = `<span class="muted">调用工具中…</span>`;
          data.tool_calls.forEach((tc) => renderToolCallStart(timeline, tc));
        } else if (data.content) {
          setFinal(data.content);
        }
        break;
      case "policy_check":
        markCallStatus(timeline, data.id, "policy", "审批中…");
        break;
      case "policy_decision":
        markCallStatus(timeline, data.id, "policy", data.decision === "allow" ? "已允许" : `已拒绝（${data.reason}）`);
        break;
      case "approval_request":
        showApproval({
          runId: state.run.runId,
          callId: data.call_id,
          tool: data.tool,
          args: data.arguments,
          side_effect: data.side_effect,
          description: data.description,
        });
        break;
      case "tool_call_start":
        markCallStatus(timeline, data.id, "running", "执行中…");
        break;
      case "tool_call_result":
        renderToolCallResult(timeline, data);
        break;
      case "tool_error":
        renderToolCallResult(timeline, { id: data.id, name: data.name, is_error: true, content: data.error });
        break;
      case "result":
        setFinal(data.final_content);
        setStatus(`完成 · ${data.steps} 步 · ${data.tool_calls} 次工具调用 · ${data.stopped_reason}`);
        break;
      case "error":
        contentEl.innerHTML = renderMarkdown(`**[${data.type || "Error"}]** ${data.message || "未知错误"}`);
        msg.root.classList.add("error");
        setStatus("出错", true);
        break;
      case "done":
        // result 已经处理；这里只是 SSE 收尾
        break;
    }
  };

  const flush = () => {
    buf = buf.replace(/\r\n/g, "\n");
    let idx;
    while ((idx = buf.indexOf("\n\n")) >= 0) {
      const raw = buf.slice(0, idx);
      buf = buf.slice(idx + 2);
      const evt = parseSseEvent(raw);
      if (evt) handleEvt(evt);
    }
  };

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buf += decoder.decode(value, { stream: true });
    flush();
  }
  buf += decoder.decode();
  if (buf.trim()) { buf += "\n\n"; flush(); }

  // 落库
  pushMessage("assistant", finalText || "(空回复)");
  state.run = null;
}

function safeJSON(s) {
  try { return JSON.parse(s); } catch { return {}; }
}

function appendTimeline(timeline, html) {
  const div = document.createElement("div");
  div.innerHTML = html;
  timeline.appendChild(div.firstElementChild);
  scrollToBottom();
}

function renderToolCallStart(timeline, tc) {
  const card = document.createElement("details");
  card.className = "tool-card pending";
  card.dataset.id = tc.id;
  card.open = false;
  card.innerHTML = `
    <summary>
      <span class="tc-icon">🔧</span>
      <span class="tc-name">${escapeHtml(tc.name)}</span>
      <span class="tc-status" data-role="status">等待审批…</span>
    </summary>
    <div class="tc-body">
      <div class="tc-section">
        <div class="tc-label">参数</div>
        <pre class="tc-json">${escapeHtml(prettyJson(tc.arguments))}</pre>
      </div>
      <div class="tc-section" data-role="result" hidden>
        <div class="tc-label">结果</div>
        <pre class="tc-json" data-role="result-pre"></pre>
      </div>
    </div>
  `;
  timeline.appendChild(card);
  state.run?.calls.set(tc.id, { el: card });
  scrollToBottom();
}

function markCallStatus(timeline, id, klass, text) {
  const card = timeline.querySelector(`.tool-card[data-id="${cssEscape(id)}"]`);
  if (!card) return;
  card.classList.remove("pending", "running", "ok", "err", "policy");
  card.classList.add(klass);
  const st = card.querySelector('[data-role="status"]');
  if (st) st.textContent = text;
}

function renderToolCallResult(timeline, data) {
  const card = timeline.querySelector(`.tool-card[data-id="${cssEscape(data.id)}"]`);
  if (!card) return;
  card.classList.remove("pending", "running", "policy");
  card.classList.add(data.is_error ? "err" : "ok");
  const st = card.querySelector('[data-role="status"]');
  if (st) st.textContent = data.is_error ? "失败" : "完成";
  const sec = card.querySelector('[data-role="result"]');
  const pre = card.querySelector('[data-role="result-pre"]');
  if (sec && pre) {
    sec.removeAttribute("hidden");
    pre.textContent = data.content || "";
  }
}

function prettyJson(v) {
  try { return JSON.stringify(v, null, 2); } catch { return String(v); }
}

function cssEscape(s) {
  return String(s).replace(/[^a-zA-Z0-9_-]/g, "\\$&");
}

// ========== 审批弹层 ==========

function showApproval(req) {
  state.pendingApproval = req;
  $("#approval-tool").textContent = req.tool;
  $("#approval-side").textContent = req.side_effect || "";
  $("#approval-args").textContent = prettyJson(req.args || {});
  $("#approval-desc").textContent = req.description || "";
  $("#approval-overlay").removeAttribute("hidden");
}

function hideApproval() {
  $("#approval-overlay").setAttribute("hidden", "");
  state.pendingApproval = null;
}

async function respondApproval(approve) {
  const req = state.pendingApproval;
  if (!req) { hideApproval(); return; }
  hideApproval();
  try {
    await fetch("/api/run/approve", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ run_id: req.runId, call_id: req.callId, approve }),
    });
  } catch (e) {
    setStatus("审批回执失败：" + e.message, true);
  }
}

init();
