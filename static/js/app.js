/**
 * Ninfer Model Launcher & Manager - Frontend Controller
 * Real-time monitoring, SSE logs, preset switching, chat testing & BAT generation
 */

// Global State
let currentPresets = [];
let detectedModels = [];
let currentLogCount = 0;
let eventSource = null;
let lastStatus = "stopped";
let pollTimer = null;
let currentUptime = 0;

// Initialize on DOM Ready
document.addEventListener("DOMContentLoaded", () => {
  initTabs();
  initPresetsAndConfig();
  initModels();
  initSSELogs();
  initSystemPolling();
  initEngineControls();
  initChatPlayground();
  initExportTab();
  initFormChangeListeners();
});

// ================= Toast Notification =================
function showToast(message, type = "info") {
  const toast = document.getElementById("toast");
  toast.textContent = message;
  toast.className = `toast toast-${type}`;
  toast.style.display = "block";
  setTimeout(() => {
    toast.style.display = "none";
  }, 3500);
}

// ================= Tabs Switching =================
function initTabs() {
  const tabBtns = document.querySelectorAll(".tab-btn");
  tabBtns.forEach(btn => {
    btn.addEventListener("click", () => {
      const targetId = btn.getAttribute("data-tab");
      tabBtns.forEach(b => b.classList.remove("active"));
      document.querySelectorAll(".tab-panel").forEach(p => p.classList.remove("active"));

      btn.classList.add("active");
      const targetPanel = document.getElementById(targetId);
      if (targetPanel) {
        targetPanel.classList.add("active");
      }

      // If export tab clicked, regenerate previews
      if (targetId === "tab-export") {
        updateExportPreviews();
      }
    });
  });
}

// ================= Presets & Config =================
async function initPresetsAndConfig() {
  try {
    const res = await fetch("/api/presets");
    currentPresets = await res.json();
    renderPresetDropdown();

    // Load persisted config or default
    const cfgRes = await fetch("/api/config");
    const cfg = await cfgRes.json();
    if (cfg && cfg.selected_preset) {
      document.getElementById("presetSelect").value = cfg.selected_preset;
      applyConfigToForm(cfg);
    } else if (currentPresets.length > 0) {
      applyPreset(currentPresets[0].id);
    }
  } catch (err) {
    console.error("加载预设失败:", err);
    showToast("加载预设失败: " + err.message, "error");
  }

  // Preset Buttons
  document.getElementById("presetSelect").addEventListener("change", (e) => {
    applyPreset(e.target.value);
  });

  document.getElementById("btnSaveNewPreset").addEventListener("click", saveAsNewPreset);
  document.getElementById("btnOverwritePreset").addEventListener("click", overwriteCurrentPreset);
  document.getElementById("btnDeletePreset").addEventListener("click", deleteCurrentPreset);
}

function renderPresetDropdown() {
  const select = document.getElementById("presetSelect");
  select.innerHTML = "";
  currentPresets.forEach(preset => {
    const opt = document.createElement("option");
    opt.value = preset.id;
    opt.textContent = preset.name;
    select.appendChild(opt);
  });
}

function applyPreset(presetId) {
  const preset = currentPresets.find(p => p.id === presetId);
  if (!preset) return;

  document.getElementById("presetSelect").value = preset.id;
  document.getElementById("presetDesc").textContent = preset.description || "无预设描述";
  applyConfigToForm(preset);
  showToast(`已载入预设: ${preset.name}`, "info");
}

function applyConfigToForm(data) {
  if (data.engine_path !== undefined) document.getElementById("engine_path").value = data.engine_path;
  if (data.model_path !== undefined) document.getElementById("model_path").value = data.model_path;
  if (data.host !== undefined) document.getElementById("host").value = data.host;
  if (data.port !== undefined) document.getElementById("port").value = data.port;
  if (data.model_id !== undefined) document.getElementById("model_id").value = data.model_id;
  if (data.max_concurrency !== undefined) document.getElementById("max_concurrency").value = data.max_concurrency;

  if (data.max_context !== undefined) document.getElementById("max_context").value = data.max_context;
  if (data.default_max_tokens !== undefined) document.getElementById("default_max_tokens").value = data.default_max_tokens;
  if (data.kv_capacity !== undefined) document.getElementById("kv_capacity").value = data.kv_capacity;
  if (data.kv_dtype !== undefined) document.getElementById("kv_dtype").value = data.kv_dtype;
  if (data.host_kv_mib !== undefined) document.getElementById("host_kv_mib").value = data.host_kv_mib;
  if (data.prefill_chunk !== undefined) document.getElementById("prefill_chunk").value = data.prefill_chunk;
  if (data.max_shared_prefixes !== undefined) document.getElementById("max_shared_prefixes").value = data.max_shared_prefixes;

  if (data.gdn_state_fp16 !== undefined) document.getElementById("gdn_state_fp16").checked = !!data.gdn_state_fp16;
  if (data.rope_yarn !== undefined) document.getElementById("rope_yarn").checked = !!data.rope_yarn;
  if (data.no_cuda_graph !== undefined) document.getElementById("no_cuda_graph").checked = !!data.no_cuda_graph;
  if (data.release_diverged_checkpoints !== undefined) document.getElementById("release_diverged_checkpoints").checked = !!data.release_diverged_checkpoints;
  if (data.recover_invariant_failures !== undefined) document.getElementById("recover_invariant_failures").checked = !!data.recover_invariant_failures;
  if (data.auto_restart !== undefined) document.getElementById("auto_restart").checked = !!data.auto_restart;

  if (data.spec !== undefined) document.getElementById("spec").value = data.spec;
  if (data.draft_tokens !== undefined) document.getElementById("draft_tokens").value = data.draft_tokens;
  if (data.lm_head_draft !== undefined) document.getElementById("lm_head_draft").checked = !!data.lm_head_draft;
  if (data.vision !== undefined) document.getElementById("vision").checked = !!data.vision;

  if (data.default_reasoning_effort !== undefined) document.getElementById("default_reasoning_effort").value = data.default_reasoning_effort;
  if (data.temperature !== undefined) document.getElementById("temperature").value = data.temperature;
  if (data.top_p !== undefined) document.getElementById("top_p").value = data.top_p;
  if (data.top_k !== undefined) document.getElementById("top_k").value = data.top_k;
  if (data.presence_penalty !== undefined) document.getElementById("presence_penalty").value = data.presence_penalty;

  // Env vars
  const env = data.env_vars || {};
  if (env.NINFER_KV_WINDOW !== undefined) document.getElementById("env_kv_window").value = env.NINFER_KV_WINDOW;
  if (env.NINFER_KV_RETRIEVE !== undefined) document.getElementById("env_kv_retrieve").value = env.NINFER_KV_RETRIEVE;
  if (env.NINFER_KV_RING !== undefined) document.getElementById("env_kv_ring").value = env.NINFER_KV_RING;
  if (env.NINFER_HOST_PAGEABLE !== undefined) document.getElementById("env_host_pageable").value = env.NINFER_HOST_PAGEABLE;
  if (env.NINFER_TERNARY_PTQ1_FAST !== undefined) {
    document.getElementById("env_ptq1_fast").checked = env.NINFER_TERNARY_PTQ1_FAST == "1";
  } else {
    document.getElementById("env_ptq1_fast").checked = false;
  }

  // Filters & extra args
  if (data.log_filters) {
    document.getElementById("log_filters").value = Array.isArray(data.log_filters) ? data.log_filters.join(", ") : data.log_filters;
  }
  if (data.extra_args !== undefined) document.getElementById("extra_args").value = data.extra_args;

  // Match model dropdown if exists
  syncModelDropdownWithInput();
}

function collectFormData() {
  const logFilterStr = document.getElementById("log_filters").value;
  const filters = logFilterStr.split(",").map(s => s.trim()).filter(Boolean);

  const env_vars = {
    NINFER_KV_WINDOW: document.getElementById("env_kv_window").value.trim(),
    NINFER_KV_RETRIEVE: document.getElementById("env_kv_retrieve").value.trim(),
    NINFER_KV_RING: document.getElementById("env_kv_ring").value.trim(),
    NINFER_HOST_PAGEABLE: document.getElementById("env_host_pageable").value.trim(),
    NINFER_KV_REUSE_HOSTBACKED: "1"
  };
  if (document.getElementById("env_ptq1_fast").checked) {
    env_vars.NINFER_TERNARY_PTQ1_FAST = "1";
  }

  return {
    selected_preset: document.getElementById("presetSelect").value,
    engine_path: document.getElementById("engine_path").value.trim(),
    model_path: document.getElementById("model_path").value.trim(),
    host: document.getElementById("host").value.trim() || "127.0.0.1",
    port: parseInt(document.getElementById("port").value, 10) || 8094,
    model_id: document.getElementById("model_id").value.trim() || "qwen3.8-27b",
    max_concurrency: parseInt(document.getElementById("max_concurrency").value, 10) || 1,

    max_context: parseInt(document.getElementById("max_context").value, 10) || 1048576,
    default_max_tokens: parseInt(document.getElementById("default_max_tokens").value, 10) || 262144,
    kv_capacity: parseInt(document.getElementById("kv_capacity").value, 10) || 60000,
    kv_dtype: document.getElementById("kv_dtype").value,
    host_kv_mib: parseInt(document.getElementById("host_kv_mib").value, 10) || 26000,
    prefill_chunk: parseInt(document.getElementById("prefill_chunk").value, 10) || 512,
    max_shared_prefixes: parseInt(document.getElementById("max_shared_prefixes").value, 10) || 0,

    gdn_state_fp16: document.getElementById("gdn_state_fp16").checked,
    rope_yarn: document.getElementById("rope_yarn").checked,
    no_cuda_graph: document.getElementById("no_cuda_graph").checked,
    release_diverged_checkpoints: document.getElementById("release_diverged_checkpoints").checked,
    recover_invariant_failures: document.getElementById("recover_invariant_failures").checked,
    auto_restart: document.getElementById("auto_restart").checked,

    spec: document.getElementById("spec").value,
    draft_tokens: parseInt(document.getElementById("draft_tokens").value, 10) || 4,
    lm_head_draft: document.getElementById("lm_head_draft").checked,
    vision: document.getElementById("vision").checked,

    default_reasoning_effort: document.getElementById("default_reasoning_effort").value,
    temperature: parseFloat(document.getElementById("temperature").value) || 0.7,
    top_p: parseFloat(document.getElementById("top_p").value) || 0.9,
    top_k: parseInt(document.getElementById("top_k").value, 10) || 20,
    presence_penalty: parseFloat(document.getElementById("presence_penalty").value) || 0.0,

    env_vars: env_vars,
    log_filters: filters,
    extra_args: document.getElementById("extra_args").value.trim()
  };
}

async function saveAsNewPreset() {
  const name = prompt("请输入新预设方案名称：", "自定义配置方案");
  if (!name) return;
  const desc = prompt("请输入方案描述说明：", "自定义保存的 Ninfer 启动配置");

  const config = collectFormData();
  const newPreset = {
    ...config,
    id: "preset-" + Date.now(),
    name: name,
    description: desc || ""
  };

  try {
    const res = await fetch("/api/presets", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(newPreset)
    });
    const result = await res.json();
    if (result.success) {
      currentPresets = result.presets;
      renderPresetDropdown();
      document.getElementById("presetSelect").value = newPreset.id;
      document.getElementById("presetDesc").textContent = newPreset.description;
      showToast("新预设已成功保存！", "success");
    }
  } catch (err) {
    showToast("保存预设失败: " + err.message, "error");
  }
}

async function overwriteCurrentPreset() {
  const currentId = document.getElementById("presetSelect").value;
  const preset = currentPresets.find(p => p.id === currentId);
  if (!preset) return;

  if (!confirm(`确定要用当前表单参数覆盖更新预设「${preset.name}」吗？`)) return;

  const config = collectFormData();
  const updatedPreset = {
    ...config,
    id: preset.id,
    name: preset.name,
    description: preset.description
  };

  try {
    const res = await fetch("/api/presets", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(updatedPreset)
    });
    const result = await res.json();
    if (result.success) {
      currentPresets = result.presets;
      showToast(`预设「${preset.name}」已更新！`, "success");
    }
  } catch (err) {
    showToast("更新预设失败: " + err.message, "error");
  }
}

async function deleteCurrentPreset() {
  const currentId = document.getElementById("presetSelect").value;
  const preset = currentPresets.find(p => p.id === currentId);
  if (!preset) return;

  if (currentPresets.length <= 1) {
    alert("至少需要保留一个预设方案，无法删除！");
    return;
  }

  if (!confirm(`确定要删除预设方案「${preset.name}」吗？`)) return;

  try {
    const res = await fetch("/api/presets/delete", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ id: currentId })
    });
    const result = await res.json();
    if (result.success) {
      currentPresets = result.presets;
      renderPresetDropdown();
      applyPreset(currentPresets[0].id);
      showToast("预设已删除", "info");
    }
  } catch (err) {
    showToast("删除预设失败: " + err.message, "error");
  }
}

// ================= Model Scanning =================
async function initModels() {
  const select = document.getElementById("model_select");
  const modelPathInput = document.getElementById("model_path");

  select.addEventListener("change", (e) => {
    if (e.target.value) {
      modelPathInput.value = e.target.value;
      updateExportPreviews();
    }
  });

  document.getElementById("btnRescanModels").addEventListener("click", rescanModels);
  document.getElementById("btnCheckEngine").addEventListener("click", checkEnginePath);

  await rescanModels();
}

async function rescanModels() {
  try {
    const res = await fetch("/api/models");
    detectedModels = await res.json();
    const select = document.getElementById("model_select");
    select.innerHTML = '<option value="">-- 请选择或在下方手动输入 --</option>';

    detectedModels.forEach(m => {
      const opt = document.createElement("option");
      opt.value = m.path;
      opt.textContent = `${m.name} (${m.size_gb} GB)`;
      select.appendChild(opt);
    });

    syncModelDropdownWithInput();
    showToast(`扫描完毕，共发现 ${detectedModels.length} 个模型文件`, "info");
  } catch (err) {
    console.error("扫描模型失败:", err);
  }
}

function syncModelDropdownWithInput() {
  const currentPath = document.getElementById("model_path").value.trim().toLowerCase();
  const select = document.getElementById("model_select");
  let matched = false;
  for (let i = 0; i < select.options.length; i++) {
    if (select.options[i].value.toLowerCase() === currentPath) {
      select.selectedIndex = i;
      matched = true;
      break;
    }
  }
  if (!matched && select.options.length > 0) {
    select.selectedIndex = 0;
  }
}

function checkEnginePath() {
  const path = document.getElementById("engine_path").value.trim();
  if (!path) {
    showToast("请输入引擎文件路径", "warn");
    return;
  }
  showToast("路径已保存，将在启动时校验其可执行性", "info");
}

// ================= SSE Live Logs =================
function initSSELogs() {
  const terminal = document.getElementById("terminalBody");
  const sseBadge = document.getElementById("sseBadge");
  const autoScroll = document.getElementById("chkAutoScroll");
  const searchInput = document.getElementById("logSearchInput");

  function connectSSE() {
    if (eventSource) {
      eventSource.close();
    }
    eventSource = new EventSource("/api/logs/stream");

    eventSource.onopen = () => {
      sseBadge.textContent = "● 实时监听中";
      sseBadge.style.color = "var(--accent-emerald)";
    };

    eventSource.onmessage = (event) => {
      try {
        const item = JSON.parse(event.data);
        appendLogLine(item);
      } catch (e) {}
    };

    eventSource.onerror = () => {
      sseBadge.textContent = "○ 正在重连...";
      sseBadge.style.color = "var(--accent-warning)";
    };
  }

  function appendLogLine(item) {
    currentLogCount++;
    document.getElementById("logTotalLines").textContent = currentLogCount;
    document.getElementById("logCounterBadge").textContent = currentLogCount;

    const line = document.createElement("div");
    line.className = "term-line";
    if (item.level === "ERROR") line.classList.add("term-line-error");
    if (item.level === "KVMEM") line.classList.add("term-line-kvmem");

    // Filter check
    const query = searchInput.value.trim().toLowerCase();
    if (query && !item.text.toLowerCase().includes(query)) {
      line.style.display = "none";
    }

    const timeSpan = document.createElement("span");
    timeSpan.className = "term-time";
    timeSpan.textContent = `[${item.time}]`;

    const tagSpan = document.createElement("span");
    tagSpan.className = `term-tag term-tag-${item.level.toLowerCase()}`;
    tagSpan.textContent = item.level;

    const textSpan = document.createElement("span");
    textSpan.textContent = item.text;

    line.appendChild(timeSpan);
    line.appendChild(tagSpan);
    line.appendChild(textSpan);
    terminal.appendChild(line);

    if (autoScroll.checked) {
      terminal.scrollTop = terminal.scrollHeight;
    }
  }

  searchInput.addEventListener("input", () => {
    const q = searchInput.value.trim().toLowerCase();
    const lines = terminal.querySelectorAll(".term-line");
    lines.forEach(l => {
      if (!q || l.textContent.toLowerCase().includes(q)) {
        l.style.display = "";
      } else {
        l.style.display = "none";
      }
    });
  });

  document.getElementById("btnClearLogs").addEventListener("click", async () => {
    terminal.innerHTML = "";
    currentLogCount = 0;
    document.getElementById("logTotalLines").textContent = "0";
    document.getElementById("logCounterBadge").textContent = "0";
    await fetch("/api/logs/clear", { method: "POST" });
    showToast("日志已清空", "info");
  });

  document.getElementById("btnCopyLogs").addEventListener("click", () => {
    const text = terminal.innerText;
    navigator.clipboard.writeText(text).then(() => {
      showToast("已复制全部日志到剪贴板", "success");
    });
  });

  connectSSE();
}

// ================= System & Engine Status Polling =================
function initSystemPolling() {
  pollStatus();
  pollTimer = setInterval(pollStatus, 1500);
}

async function pollStatus() {
  try {
    const res = await fetch("/api/system/status");
    if (!res.ok) return;
    const data = await res.json();
    renderHardwareMetrics(data.hardware);
    renderEngineStatus(data.engine);
  } catch (err) {
    // Ignore transient network errors
  }
}

function renderHardwareMetrics(hw) {
  if (!hw) return;

  // CPU
  const cpuVal = hw.cpu_percent || 0;
  document.getElementById("cpuVal").textContent = cpuVal.toFixed(1);
  document.getElementById("cpuBadge").textContent = `${cpuVal.toFixed(0)}%`;
  document.getElementById("cpuBar").style.width = `${Math.min(100, cpuVal)}%`;
  document.getElementById("dtCpuUtil").textContent = `${cpuVal.toFixed(1)}%`;

  // RAM
  const ramUsed = hw.ram_used_gb || 0;
  const ramTotal = hw.ram_total_gb || 0;
  const ramFree = hw.ram_free_gb || 0;
  const ramPct = hw.ram_percent || 0;

  document.getElementById("ramUsedVal").textContent = ramUsed.toFixed(1);
  document.getElementById("ramTotalVal").textContent = ramTotal.toFixed(1);
  document.getElementById("ramFreeVal").textContent = ramFree.toFixed(1);
  document.getElementById("ramBadge").textContent = `${ramPct.toFixed(0)}%`;
  document.getElementById("ramBar").style.width = `${Math.min(100, ramPct)}%`;

  document.getElementById("dtRamTotal").textContent = `${ramTotal.toFixed(2)} GB`;
  document.getElementById("dtRamUsed").textContent = `${ramUsed.toFixed(2)} GB`;
  document.getElementById("dtRamFree").textContent = `${ramFree.toFixed(2)} GB`;
  document.getElementById("dtRamLoad").textContent = `${ramPct.toFixed(1)}%`;

  // GPU
  if (hw.gpu_available) {
    const gpuNameShort = hw.gpu_name.replace("NVIDIA GeForce ", "");
    document.getElementById("gpuName").textContent = `GPU: ${gpuNameShort}`;
    document.getElementById("gpuUtilVal").textContent = (hw.gpu_util_percent || 0).toFixed(0);
    document.getElementById("gpuBadge").textContent = `${(hw.gpu_util_percent || 0).toFixed(0)}%`;
    document.getElementById("gpuBar").style.width = `${Math.min(100, hw.gpu_util_percent || 0)}%`;
    document.getElementById("gpuTempVal").textContent = hw.gpu_temp_c || 0;
    document.getElementById("gpuPowerVal").textContent = (hw.gpu_power_w || 0).toFixed(1);

    // VRAM (MB -> GB)
    const vramTotalGb = (hw.vram_total_mb || 0) / 1024;
    const vramUsedGb = (hw.vram_used_mb || 0) / 1024;
    const vramFreeGb = (hw.vram_free_mb || 0) / 1024;
    const vramPct = hw.vram_percent || 0;

    document.getElementById("vramUsedVal").textContent = vramUsedGb.toFixed(2);
    document.getElementById("vramTotalVal").textContent = vramTotalGb.toFixed(1);
    document.getElementById("vramFreeVal").textContent = vramFreeGb.toFixed(2);
    document.getElementById("vramBadge").textContent = `${vramPct.toFixed(0)}%`;
    document.getElementById("vramBar").style.width = `${Math.min(100, vramPct)}%`;

    // Detailed table
    document.getElementById("dtGpuName").textContent = hw.gpu_name;
    document.getElementById("dtGpuUtil").textContent = `${hw.gpu_util_percent}%`;
    document.getElementById("dtVramTotal").textContent = `${hw.vram_total_mb} MB (${vramTotalGb.toFixed(2)} GB)`;
    document.getElementById("dtVramUsed").textContent = `${hw.vram_used_mb} MB (${vramUsedGb.toFixed(2)} GB)`;
    document.getElementById("dtVramFree").textContent = `${hw.vram_free_mb} MB (${vramFreeGb.toFixed(2)} GB)`;
    document.getElementById("dtGpuTemp").textContent = `${hw.gpu_temp_c} °C`;
    document.getElementById("dtGpuPower").textContent = `${hw.gpu_power_w} W`;

    // GPU Processes
    const tbody = document.getElementById("tbodyGpuProcs");
    if (hw.gpu_processes && hw.gpu_processes.length > 0) {
      tbody.innerHTML = hw.gpu_processes.map(p => `
        <tr>
          <td>${p.pid}</td>
          <td><strong>${p.name}</strong></td>
          <td>${p.vram_mb} MiB</td>
        </tr>
      `).join("");
    } else {
      tbody.innerHTML = '<tr><td colspan="3" style="text-align: center; color: #888;">无其他独立图形应用占用显存</td></tr>';
    }
  }
}

function renderEngineStatus(eng) {
  if (!eng) return;

  const dot = document.getElementById("statusDot");
  const label = document.getElementById("statusLabel");
  const meta = document.getElementById("statusMeta");
  const btnStart = document.getElementById("btnStart");
  const btnStop = document.getElementById("btnStop");
  const btnRestart = document.getElementById("btnRestart");
  const btnApiLink = document.getElementById("btnApiLink");

  const probeBadge = document.getElementById("probeBadge");
  const probeHost = document.getElementById("probeHost");
  const probeStatusText = document.getElementById("probeStatusText");
  const healthPulse = document.getElementById("healthPulse");
  const enginePidText = document.getElementById("enginePidText");

  probeHost.textContent = `${eng.host}:${eng.port}`;

  // Real-time Token Speed Rendering
  const spd = eng.speed || { decode_tok_s: 0.0, last_decode_tok_s: 0.0, prefill_tok_s: 0.0, ttft_ms: 0, is_generating: false };
  const cardSpeed = document.getElementById("cardSpeed");
  const speedBadge = document.getElementById("speedBadge");
  const speedMainVal = document.getElementById("speedMainVal");
  const speedBarTrack = document.getElementById("speedBarTrack");
  const speedPrefillVal = document.getElementById("speedPrefillVal");
  const speedTtftVal = document.getElementById("speedTtftVal");

  const navSpeedPill = document.getElementById("navSpeedPill");
  const navSpeedText = document.getElementById("navSpeedText");

  const currentSpeed = spd.decode_tok_s || 0.0;
  const isGenerating = spd.is_generating || currentSpeed > 0;

  if (currentSpeed > 0) {
    speedMainVal.textContent = currentSpeed.toFixed(1);
  } else if (spd.last_decode_tok_s > 0) {
    speedMainVal.textContent = spd.last_decode_tok_s.toFixed(1);
  } else {
    speedMainVal.textContent = "0.0";
  }

  speedPrefillVal.textContent = (spd.prefill_tok_s || 0).toFixed(1);
  speedTtftVal.textContent = spd.ttft_ms || 0;

  const pct = Math.min(100, Math.max(0, (currentSpeed / 180) * 100));
  speedBarTrack.style.width = isGenerating ? `${Math.max(5, pct)}%` : (spd.last_decode_tok_s > 0 ? `${Math.min(100, (spd.last_decode_tok_s / 180) * 100)}%` : "0%");

  if (isGenerating && currentSpeed > 0) {
    cardSpeed.classList.add("generating");
    speedBadge.textContent = "● 生成中";
    speedBadge.style.color = "var(--accent-cyan)";
    speedBadge.style.background = "rgba(0, 229, 255, 0.15)";

    navSpeedPill.style.display = "inline-flex";
    navSpeedText.textContent = `${currentSpeed.toFixed(1)} tok/s`;
  } else {
    cardSpeed.classList.remove("generating");
    speedBadge.textContent = spd.last_decode_tok_s > 0 ? `空闲 (前次 ${spd.last_decode_tok_s.toFixed(1)})` : "空闲 0.0";
    speedBadge.style.color = "var(--text-muted)";
    speedBadge.style.background = "rgba(255, 255, 255, 0.05)";

    navSpeedPill.style.display = "none";
  }

  if (eng.status === "running") {
    dot.className = "status-dot dot-running";
    label.textContent = "运行中";
    const minutes = Math.floor(eng.uptime_seconds / 60);
    const seconds = eng.uptime_seconds % 60;
    meta.textContent = `PID: ${eng.pid} | 运行: ${minutes}分${seconds}秒`;

    btnStart.disabled = true;
    btnStop.disabled = false;
    btnRestart.disabled = false;

    btnApiLink.style.display = "inline-flex";
    btnApiLink.href = `http://${eng.host}:${eng.port}/v1/models`;

    enginePidText.textContent = `PID: ${eng.pid}`;

    if (eng.is_healthy) {
      probeBadge.textContent = "ONLINE READY";
      probeBadge.style.color = "var(--accent-emerald)";
      probeStatusText.textContent = "HTTP 200 服务就绪 (可接收推理请求)";
      healthPulse.className = "health-pulse pulse-ready";
    } else {
      probeBadge.textContent = "LOADING...";
      probeBadge.style.color = "var(--accent-warning)";
      probeStatusText.textContent = "权重加载中 / 正在建立缓存...";
      healthPulse.className = "health-pulse";
    }

  } else if (eng.status === "starting") {
    dot.className = "status-dot dot-starting";
    label.textContent = "正在启动...";
    meta.textContent = "";

    btnStart.disabled = true;
    btnStop.disabled = false;
    btnRestart.disabled = true;
    btnApiLink.style.display = "none";

    probeBadge.textContent = "STARTING";
    probeBadge.style.color = "var(--accent-warning)";
    probeStatusText.textContent = "引擎进程已启动，等待就绪...";
    healthPulse.className = "health-pulse";
    enginePidText.textContent = eng.pid ? `PID: ${eng.pid}` : "-";

  } else if (eng.status === "error") {
    dot.className = "status-dot dot-error";
    label.textContent = "异常退出";
    meta.textContent = eng.exit_code !== null ? `退出码: ${eng.exit_code}` : "";

    btnStart.disabled = false;
    btnStop.disabled = true;
    btnRestart.disabled = true;
    btnApiLink.style.display = "none";

    probeBadge.textContent = "ERROR";
    probeBadge.style.color = "var(--accent-danger)";
    probeStatusText.textContent = eng.error_message || "进程已异常终止";
    healthPulse.className = "health-pulse";
    enginePidText.textContent = "已停止";

  } else {
    dot.className = "status-dot dot-stopped";
    label.textContent = "未运行";
    meta.textContent = "";

    btnStart.disabled = false;
    btnStop.disabled = true;
    btnRestart.disabled = true;
    btnApiLink.style.display = "none";

    probeBadge.textContent = "OFFLINE";
    probeBadge.style.color = "var(--text-muted)";
    probeStatusText.textContent = "引擎已停止";
    healthPulse.className = "health-pulse";
    enginePidText.textContent = "PID: -";
  }

  // Update terminal footer cmd
  if (eng.current_cmdline) {
    document.getElementById("terminalCmdline").textContent = `命令行: ${eng.current_cmdline}`;
  }
}

// ================= Engine Start / Stop / Restart =================
function initEngineControls() {
  document.getElementById("btnStart").addEventListener("click", async () => {
    const config = collectFormData();
    if (!config.engine_path) {
      showToast("请先指定引擎可执行文件路径！", "warn");
      return;
    }
    if (!config.model_path) {
      showToast("请先指定或选择模型文件路径！", "warn");
      return;
    }

    try {
      showToast("正在启动引擎...", "info");
      const res = await fetch("/api/engine/start", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(config)
      });
      const data = await res.json();
      if (data.success) {
        showToast("引擎进程启动成功！切换至运行日志查看输出", "success");
        // Automatically switch to live logs tab
        document.querySelector('[data-tab="tab-logs"]').click();
      } else {
        showToast("启动失败: " + data.error, "error");
      }
    } catch (err) {
      showToast("请求失败: " + err.message, "error");
    }
  });

  document.getElementById("btnStop").addEventListener("click", async () => {
    try {
      showToast("正在停止引擎...", "info");
      const res = await fetch("/api/engine/stop", { method: "POST" });
      const data = await res.json();
      if (data.success) {
        showToast("引擎已停止", "info");
      }
    } catch (err) {
      showToast("停止请求失败: " + err.message, "error");
    }
  });

  document.getElementById("btnRestart").addEventListener("click", async () => {
    try {
      showToast("正在重启引擎...", "info");
      const res = await fetch("/api/engine/restart", { method: "POST" });
      const data = await res.json();
      if (data.success) {
        showToast("引擎已重启！", "success");
      } else {
        showToast("重启失败: " + data.error, "error");
      }
    } catch (err) {
      showToast("重启请求失败: " + err.message, "error");
    }
  });

  document.getElementById("btnExportTop").addEventListener("click", () => {
    document.querySelector('[data-tab="tab-export"]').click();
  });
}

// ================= Chat Playground =================
function initChatPlayground() {
  const input = document.getElementById("chatInput");
  const btnSend = document.getElementById("btnSendChat");
  const btnClear = document.getElementById("btnClearChat");
  const history = document.getElementById("chatHistory");

  let isGenerating = false;

  btnSend.addEventListener("click", () => {
    sendChatMessage();
  });

  input.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) {
      e.preventDefault();
      sendChatMessage();
    }
  });

  btnClear.addEventListener("click", () => {
    history.innerHTML = `
      <div class="chat-msg msg-assistant">
        <div class="msg-avatar">⚡</div>
        <div class="msg-bubble">对话记录已清空。请输入新的测试指令。</div>
      </div>
    `;
    document.getElementById("speedBar").style.display = "none";
  });

  // Quick Prompt buttons
  document.querySelectorAll(".quick-btn").forEach(btn => {
    btn.addEventListener("click", () => {
      input.value = btn.getAttribute("data-prompt");
      sendChatMessage();
    });
  });

  async function sendChatMessage() {
    const text = input.value.trim();
    if (!text || isGenerating) return;

    input.value = "";
    isGenerating = true;
    btnSend.disabled = true;

    // Append User Message
    appendMessage("user", text);

    // Append Assistant Message Placeholder
    const assistantMsgElem = appendMessage("assistant", "");
    const bubble = assistantMsgElem.querySelector(".msg-bubble");
    bubble.innerHTML = '<span class="typing-indicator">思考中...</span>';

    // Speed metrics tracking
    const speedBar = document.getElementById("speedBar");
    speedBar.style.display = "flex";
    const statSpeed = document.getElementById("statSpeed");
    const statTtft = document.getElementById("statTtft");
    const statTokens = document.getElementById("statTokens");
    const statElapsed = document.getElementById("statElapsed");

    const startTime = performance.now();
    let firstTokenTime = 0;
    let tokenCount = 0;
    let fullContent = "";
    let thinkingContent = "";
    let inThinkTag = false;

    try {
      const modelId = document.getElementById("model_id").value.trim() || "qwen3.8-27b";
      const temperature = parseFloat(document.getElementById("temperature").value) || 0.7;

      const reqPayload = {
        model: modelId,
        messages: [
          { role: "user", content: text }
        ],
        stream: true,
        temperature: temperature
      };

      const resp = await fetch("/api/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(reqPayload)
      });

      if (!resp.ok) {
        throw new Error(`HTTP ${resp.status} - 引擎可能尚未就绪或已停止`);
      }

      const reader = resp.body.getReader();
      const decoder = new TextDecoder("utf-8");
      let buffer = "";

      bubble.innerHTML = "";

      // Thinking reasoning container
      let thinkBox = null;
      let thinkBody = null;

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split("\n");
        buffer = lines.pop(); // keep partial

        for (const line of lines) {
          const trimmed = line.trim();
          if (!trimmed || trimmed.startsWith(":")) continue;

          if (trimmed.startsWith("data:")) {
            const dataStr = trimmed.slice(5).trim();
            if (dataStr === "[DONE]") break;

            try {
              const parsed = JSON.parse(dataStr);
              const delta = parsed.choices?.[0]?.delta?.content || "";
              if (delta) {
                tokenCount++;
                if (firstTokenTime === 0) {
                  firstTokenTime = performance.now();
                  statTtft.textContent = Math.round(firstTokenTime - startTime);
                }

                // Check for <think> reasoning tags
                if (delta.includes("<think>")) {
                  inThinkTag = true;
                  thinkBox = document.createElement("div");
                  thinkBox.className = "thinking-box";
                  thinkBox.innerHTML = '<div class="thinking-title">🧠 思考过程 (Thinking Process)</div>';
                  thinkBody = document.createElement("div");
                  thinkBody.className = "thinking-body";
                  thinkBox.appendChild(thinkBody);
                  bubble.appendChild(thinkBox);
                }

                if (inThinkTag) {
                  if (delta.includes("</think>")) {
                    inThinkTag = false;
                    const parts = delta.split("</think>");
                    thinkingContent += parts[0].replace("<think>", "");
                    if (thinkBody) thinkBody.textContent = thinkingContent;
                    if (parts[1]) {
                      fullContent += parts[1];
                      updateMainBubbleText(bubble, thinkBox, fullContent);
                    }
                  } else {
                    thinkingContent += delta.replace("<think>", "");
                    if (thinkBody) thinkBody.textContent = thinkingContent;
                  }
                } else {
                  fullContent += delta;
                  updateMainBubbleText(bubble, thinkBox, fullContent);
                }

                // Update Speed Stats
                const now = performance.now();
                const elapsedSec = (now - (firstTokenTime || startTime)) / 1000;
                statTokens.textContent = tokenCount;
                statElapsed.textContent = ((now - startTime) / 1000).toFixed(1);
                if (elapsedSec > 0) {
                  statSpeed.textContent = (tokenCount / elapsedSec).toFixed(1);
                }

                history.scrollTop = history.scrollHeight;
              }
            } catch (jsonErr) {}
          }
        }
      }

      if (!fullContent && !thinkingContent) {
        bubble.textContent = "(模型未返回任何文本)";
      }

    } catch (err) {
      bubble.innerHTML = `<span style="color: var(--accent-danger);">错误: ${err.message}</span>`;
    } finally {
      isGenerating = false;
      btnSend.disabled = false;
    }
  }

  function updateMainBubbleText(bubble, thinkBox, text) {
    let mainTextNode = bubble.querySelector(".main-response-text");
    if (!mainTextNode) {
      mainTextNode = document.createElement("div");
      mainTextNode.className = "main-response-text";
      mainTextNode.style.whiteSpace = "pre-wrap";
      bubble.appendChild(mainTextNode);
    }
    mainTextNode.textContent = text;
  }

  function appendMessage(role, text) {
    const msg = document.createElement("div");
    msg.className = `chat-msg msg-${role}`;
    msg.innerHTML = `
      <div class="msg-avatar">${role === "user" ? "👤" : "⚡"}</div>
      <div class="msg-bubble">${text ? escapeHtml(text) : ""}</div>
    `;
    history.appendChild(msg);
    history.scrollTop = history.scrollHeight;
    return msg;
  }
}

function escapeHtml(str) {
  return str.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}

// ================= BAT & CLI Export =================
function initExportTab() {
  document.getElementById("btnCopyBat").addEventListener("click", () => {
    const code = document.getElementById("batCodePreview").textContent;
    navigator.clipboard.writeText(code).then(() => {
      showToast("批处理脚本已复制到剪贴板！", "success");
    });
  });

  document.getElementById("btnDownloadBat").addEventListener("click", () => {
    const code = document.getElementById("batCodePreview").textContent;
    const blob = new Blob([code], { type: "text/plain;charset=utf-8" });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = "start-custom.bat";
    a.click();
    showToast("已触发下载 start-custom.bat", "success");
  });

  document.getElementById("btnCopyCmd").addEventListener("click", () => {
    const code = document.getElementById("cmdCodePreview").textContent;
    navigator.clipboard.writeText(code).then(() => {
      showToast("单行命令已复制到剪贴板！", "success");
    });
  });
}

async function updateExportPreviews() {
  const config = collectFormData();
  try {
    const res = await fetch("/api/export-bat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(config)
    });
    const data = await res.json();
    if (data.bat_content) {
      document.getElementById("batCodePreview").textContent = data.bat_content;
    }

    // Build single command line preview
    let cmd = `"${config.engine_path}" "${config.model_path}" --host ${config.host} --port ${config.port} --model-id ${config.model_id} --max-context ${config.max_context} --default-max-tokens ${config.default_max_tokens} --kv-capacity ${config.kv_capacity} --kv-dtype ${config.kv_dtype} --host-kv-mib ${config.host_kv_mib} --prefill-chunk ${config.prefill_chunk}`;
    if (config.spec && config.spec !== "none") cmd += ` --spec ${config.spec} --draft-tokens ${config.draft_tokens}`;
    if (config.lm_head_draft) cmd += ` --lm-head-draft`;
    if (config.vision) cmd += ` --vision`;
    if (config.no_cuda_graph) cmd += ` --no-cuda-graph`;
    if (config.gdn_state_fp16) cmd += ` --gdn-state-fp16`;
    if (config.rope_yarn) cmd += ` --rope-yarn`;
    if (config.release_diverged_checkpoints) cmd += ` --release-diverged-checkpoints`;
    if (config.recover_invariant_failures) cmd += ` --recover-invariant-failures`;
    if (config.default_reasoning_effort) cmd += ` --default-reasoning-effort ${config.default_reasoning_effort}`;
    cmd += ` --max-concurrency ${config.max_concurrency} --presence-penalty ${config.presence_penalty} --temperature ${config.temperature} --top-p ${config.top_p} --top-k ${config.top_k}`;
    if (config.extra_args) cmd += ` ${config.extra_args}`;

    document.getElementById("cmdCodePreview").textContent = cmd;
  } catch (err) {}
}

function initFormChangeListeners() {
  const form = document.getElementById("configForm");
  form.addEventListener("input", debounce(updateExportPreviews, 400));
  form.addEventListener("change", updateExportPreviews);
}

function debounce(func, wait) {
  let timeout;
  return function(...args) {
    clearTimeout(timeout);
    timeout = setTimeout(() => func.apply(this, args), wait);
  };
}
