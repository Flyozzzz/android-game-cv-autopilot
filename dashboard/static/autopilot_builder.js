(function () {
  const $ = (id) => document.getElementById(id);

  function translate(key, fallback) {
    if (typeof window.t === "function") {
      const value = window.t(key);
      if (value && value !== key) return value;
    }
    return fallback || key;
  }

  function setStatus(key, fallback, className) {
    const node = $("builderStatus");
    if (!node) return;
    node.textContent = translate(key, fallback);
    node.className = `pill ${className || "neutral"}`;
  }

  function showError(error) {
    setStatus("builder.status.failed", "Failed", "bad");
    $("builderOutput").textContent = JSON.stringify({ error: error.message || String(error) }, null, 2);
  }

  function getValue(id) {
    const node = $(id);
    if (!node) return "";
    return node.type === "checkbox" ? node.checked : node.value;
  }

  function selectedSerial() {
    const select = $("deviceSelect");
    return select ? select.value : "";
  }

  function splitPaths(value) {
    return String(value || "")
      .split(/[\n,]+/)
      .map((item) => item.trim())
      .filter(Boolean);
  }

  async function jsonApi(path, options = {}) {
    const response = await fetch(path, {
      headers: { "Content-Type": "application/json" },
      ...options,
    });
    const data = await response.json();
    if (!response.ok || data.error) {
      throw new Error(data.error || response.statusText);
    }
    return data;
  }

  function payload() {
    const prompt = String(getValue("builderPrompt") || "").trim();
    if (!prompt) throw new Error(translate("builder.error.promptRequired", "Builder prompt is required"));
    return {
      prompt,
      mode: getValue("builderMode") || "create",
      serial: selectedSerial(),
      package: getValue("builderPackage") || getValue("gamePackage"),
      openrouterKey: getValue("openrouterKey"),
      models: getValue("builderModels") || getValue("cvModels"),
      framePaths: splitPaths(getValue("builderFramePaths")),
      liveValidation: Boolean(getValue("builderLiveValidation")),
      launchApp: Boolean(getValue("builderLaunchApp")),
    };
  }

  function renderBundles(state) {
    const list = $("builderBundleList");
    const count = $("builderBundleCount");
    if (!list || !count) return;
    const bundles = Array.isArray(state.bundles) ? state.bundles : [];
    count.textContent = String(bundles.length);
    if (!bundles.length) {
      list.textContent = translate("builder.bundles.empty", "No autopilot bundles saved yet.");
      return;
    }
    list.innerHTML = "";
    bundles.forEach((bundle) => {
      const item = document.createElement("div");
      item.className = "builder-bundle-item";
      const title = document.createElement("strong");
      title.textContent = bundle.id || "autopilot";
      const path = document.createElement("span");
      path.textContent = bundle.path || "";
      item.append(title, path);
      list.appendChild(item);
    });
  }

  async function refreshBuilder() {
    const state = await jsonApi("/api/builder/state");
    renderBundles(state);
    return state;
  }

  async function buildAutopilot() {
    setStatus("builder.status.running", "Running", "warn");
    $("builderOutput").textContent = translate("builder.output.running", "Building autopilot...");
    const data = await jsonApi("/api/builder/build", {
      method: "POST",
      body: JSON.stringify(payload()),
    });
    $("builderOutput").textContent = JSON.stringify(data, null, 2);
    setStatus(data.status === "ok" ? "builder.status.ready" : "builder.status.warning", data.status || "Done", data.status === "ok" ? "good" : "warn");
    await refreshBuilder();
  }

  function wire() {
    if (!$("builderBuildBtn")) return;
    $("builderBuildBtn").addEventListener("click", () => buildAutopilot().catch(showError));
    $("builderRefreshBtn").addEventListener("click", () => refreshBuilder().catch(showError));
    $("builderLoadLastBtn").addEventListener("click", () => refreshBuilder().catch(showError));
    refreshBuilder().catch(() => {});
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", wire);
  } else {
    wire();
  }

  window.refreshAutopilotBuilder = refreshBuilder;
})();
