const state = {
  profiles: [],
  methods: {},
  settings: {},
  selectedSerial: "",
  lastScreenshotUrl: "",
  recordings: [],
  readyPresets: [],
  isRecording: false,
  recordedActions: [],
  projectFiles: [],
  currentProjectFile: "",
  translations: {},
  lang: "en",
  helpMode: true,
  recordingLastActionAt: 0,
  phonePointer: null,
};

const $ = (id) => document.getElementById(id);

function toast(message) {
  const node = $("toast");
  node.textContent = message;
  node.classList.add("show");
  window.clearTimeout(node._timer);
  node._timer = window.setTimeout(() => node.classList.remove("show"), 3200);
}

async function api(path, options = {}) {
  const response = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  const contentType = response.headers.get("Content-Type") || "";
  const data = contentType.includes("application/json") ? await response.json() : await response.text();
  if (!response.ok || (data && data.error)) {
    throw new Error((data && data.error) || response.statusText);
  }
  return data;
}

function fillSelect(node, values, selected) {
  node.innerHTML = "";
  values.forEach((value) => {
    const option = document.createElement("option");
    option.value = value;
    option.textContent = value;
    if (value === selected) option.selected = true;
    node.appendChild(option);
  });
}

function setInput(id, value) {
  const node = $(id);
  if (!node) return;
  if (node.type === "checkbox") node.checked = Boolean(value);
  else node.value = value ?? "";
}

function getInput(id) {
  const node = $(id);
  if (!node) return "";
  return node.type === "checkbox" ? node.checked : node.value;
}

async function loadTranslations() {
  try {
    const response = await fetch("/static/i18n.json", { cache: "no-store" });
    state.translations = await response.json();
  } catch (error) {
    state.translations = { en: {}, ru: {} };
  }
}

function t(key) {
  return (
    state.translations[state.lang] && state.translations[state.lang][key]
  ) || (
    state.translations.en && state.translations.en[key]
  ) || key;
}

function applyTranslations(root = document) {
  root.querySelectorAll("[data-i18n]").forEach((node) => {
    node.textContent = t(node.dataset.i18n);
  });
  root.querySelectorAll("[data-i18n-placeholder]").forEach((node) => {
    node.setAttribute("placeholder", t(node.dataset.i18nPlaceholder));
  });
  root.querySelectorAll("[data-i18n-title]").forEach((node) => {
    node.setAttribute("title", t(node.dataset.i18nTitle));
  });
  root.querySelectorAll("[data-i18n-alt]").forEach((node) => {
    node.setAttribute("alt", t(node.dataset.i18nAlt));
  });
  document.documentElement.lang = state.lang;
  document.body.dataset.help = state.helpMode ? "on" : "off";
  const ru = $("langRu");
  const en = $("langEn");
  if (ru) ru.classList.toggle("active", state.lang === "ru");
  if (en) en.classList.toggle("active", state.lang === "en");
  if ($("helpMode")) $("helpMode").checked = state.helpMode;
}

function setLanguage(lang) {
  state.lang = lang === "ru" ? "ru" : "en";
  localStorage.setItem("dashboard.language", state.lang);
  applyTranslations();
}

function setHelpMode(enabled) {
  state.helpMode = Boolean(enabled);
  localStorage.setItem("dashboard.helpMode", state.helpMode ? "1" : "0");
  applyTranslations();
}

function listText(value) {
  return Array.isArray(value) ? value.join("\n") : (value || "");
}

function splitListText(value) {
  return String(value || "")
    .split(/[\n,]+/)
    .map((item) => item.trim())
    .filter(Boolean);
}

function deviceDisplayName(device, index) {
  if (!device || !device.serial) return "device";
  const modelMatch = String(device.details || "").match(/model:([^\s]+)/);
  const model = modelMatch ? modelMatch[1].replace(/_/g, " ") : "";
  return model ? `device-${index + 1} · ${model}` : `device-${index + 1}`;
}

function renderStages(enabled) {
  const host = $("stages");
  const selected = new Set(enabled || []);
  host.innerHTML = "";
  (state.methods.stages || []).forEach((stage) => {
    const label = document.createElement("label");
    const input = document.createElement("input");
    input.type = "checkbox";
    input.value = stage;
    input.checked = selected.has(stage);
    label.append(input, document.createTextNode(stage));
    host.appendChild(label);
  });
}

function readStages() {
  return [...$("stages").querySelectorAll("input:checked")].map((node) => node.value);
}

function renderDevices(devices) {
  const select = $("deviceSelect");
  select.innerHTML = "";
  const active = devices.filter((device) => device.state === "device");
  if (!active.length) {
    const option = document.createElement("option");
    option.value = "";
    option.textContent = "No ADB device";
    select.appendChild(option);
    state.selectedSerial = "";
  } else {
    active.forEach((device, index) => {
      const option = document.createElement("option");
      option.value = device.serial;
      option.textContent = deviceDisplayName(device, index);
      select.appendChild(option);
    });
    const requested = state.settings.localDevice;
    const requestedDevice = active.find((device) => device.serial === requested);
    select.value = requestedDevice ? requestedDevice.serial : active[0].serial;
    state.selectedSerial = select.value;
  }

  const host = $("deviceCards");
  host.innerHTML = "";
  if (!devices.length) {
    host.innerHTML = `<div class="device-card"><strong>No ADB devices</strong><p>Connect a phone or start an emulator.</p></div>`;
    return;
  }
  devices.forEach((device, index) => {
    const card = document.createElement("div");
    card.className = "device-card";
    card.innerHTML = `<strong></strong><p></p>`;
    card.querySelector("strong").textContent = deviceDisplayName(device, index);
    card.querySelector("p").textContent = `${device.state} ${device.details || ""}`;
    host.appendChild(card);
  });
}

function renderRecordings(recordings) {
  state.recordings = recordings || [];
  const select = $("recordingSelect");
  if (!select) return;
  select.innerHTML = "";
  if (!state.recordings.length) {
    const option = document.createElement("option");
    option.value = "";
    option.textContent = "No recordings";
    select.appendChild(option);
    return;
  }
  state.recordings.forEach((item) => {
    const option = document.createElement("option");
    option.value = item.path;
    option.textContent = `${item.name} (${item.actions})`;
    select.appendChild(option);
  });
}

function renderProjectFiles(files) {
  state.projectFiles = files || [];
  const select = $("projectFileSelect");
  if (!select) return;
  select.innerHTML = "";
  state.projectFiles.forEach((item) => {
    const option = document.createElement("option");
    option.value = item.path;
    option.textContent = `${item.path} (${item.size}b)`;
    select.appendChild(option);
  });
  if (state.currentProjectFile) {
    select.value = state.currentProjectFile;
  }
}

function renderReadyPresets(presets) {
  state.readyPresets = presets || [];
  const select = $("readyPreset");
  if (!select) return;
  select.innerHTML = "";
  if (!state.readyPresets.length) {
    const option = document.createElement("option");
    option.value = "";
    option.textContent = "No ready presets";
    select.appendChild(option);
    $("presetDescription").textContent = "";
    return;
  }
  state.readyPresets.forEach((preset, index) => {
    const option = document.createElement("option");
    option.value = String(index);
    option.textContent = preset.title || preset.name;
    select.appendChild(option);
  });
  select.value = "0";
  $("presetDescription").textContent = state.readyPresets[0].description || "";
  setInput("presetName", state.readyPresets[0].name || "");
  setInput("presetTitle", state.readyPresets[0].title || "");
  setInput("presetDescriptionInput", state.readyPresets[0].description || "");
}

function loadReadyPreset(indexValue) {
  const index = Number(indexValue || 0);
  const preset = state.readyPresets[index];
  if (!preset) return;
  const cleanSettings = { ...preset.settings };
  delete cleanSettings.title;
  delete cleanSettings.description;
  applySettings({ ...state.settings, ...cleanSettings });
  $("presetDescription").textContent = preset.description || "";
}

function roundedSeconds(ms) {
  return Math.max(0, Math.round((ms / 1000) * 100) / 100);
}

function addRecordedAction(action, actionAtMs = Date.now()) {
  if (!state.isRecording) return;
  if (state.recordingLastActionAt && state.recordedActions.length) {
    const previous = state.recordedActions[state.recordedActions.length - 1];
    previous.pause = roundedSeconds(actionAtMs - state.recordingLastActionAt);
  }
  state.recordedActions.push({ ...action, pause: 0 });
  state.recordingLastActionAt = actionAtMs;
  updateRecordCount();
}

function updateRecordCount() {
  $("recordCount").textContent = `${state.recordedActions.length} actions`;
}

function renderGameProfileSelect(selected) {
  const profileIds = state.profiles.map((profile) => profile.id);
  fillSelect($("gameProfile"), profileIds, selected);
}

function renderProfiles() {
  const table = $("profilesTable");
  table.innerHTML = "";
  state.profiles.forEach((profile) => {
    const tr = document.createElement("tr");
    const status = profile.maturity || (profile.proven ? "proven" : "starter");
    tr.innerHTML = `
      <td><strong></strong><br><span></span></td>
      <td></td>
      <td></td>
      <td></td>
      <td></td>
      <td><button class="secondary small" type="button">Edit</button></td>
    `;
    tr.children[0].querySelector("strong").textContent = profile.id;
    tr.children[0].querySelector("span").textContent = profile.name;
    tr.children[1].textContent = profile.package || "";
    tr.children[2].textContent = profile.gameplay_strategy || "none";
    tr.children[3].textContent = profile.source === "custom" ? `${status} · custom` : status;
    tr.children[4].textContent = profile.notes || "";
    const editButton = tr.children[5].querySelector("button");
    editButton.textContent = t("button.edit");
    editButton.addEventListener("click", () => fillProfileForm(profile));
    table.appendChild(tr);
  });
}

function clearProfileForm() {
  [
    "profileId",
    "profileName",
    "profilePackage",
    "profileInstallQuery",
    "profileAliases",
    "profileTutorialHints",
    "profilePurchaseHints",
    "profileBlockerWords",
    "profileNotes",
    "profileMaxTutorialSteps",
    "profileMaxPurchaseSteps",
  ].forEach((id) => setInput(id, ""));
  setInput("profilePlayerPrefix", "Player");
  setInput("profileGameplayStrategy", "none");
  setInput("profileProven", false);
}

function fillProfileForm(profile) {
  setInput("profileId", profile.id);
  setInput("profileName", profile.name);
  setInput("profilePackage", profile.package);
  setInput("profileInstallQuery", profile.install_query || profile.name);
  setInput("profilePlayerPrefix", profile.player_name_prefix || "Player");
  setInput("profileGameplayStrategy", profile.gameplay_strategy || "none");
  setInput("profileMaxTutorialSteps", profile.max_tutorial_steps || "");
  setInput("profileMaxPurchaseSteps", profile.max_purchase_steps || "");
  setInput("profileProven", profile.proven);
  setInput("profileAliases", listText(profile.aliases));
  setInput("profileTutorialHints", listText(profile.tutorial_hints));
  setInput("profilePurchaseHints", listText(profile.purchase_hints));
  setInput("profileBlockerWords", listText(profile.blocker_words));
  setInput("profileNotes", profile.notes || "");
}

function collectProfile() {
  return {
    id: getInput("profileId"),
    name: getInput("profileName"),
    package: getInput("profilePackage"),
    install_query: getInput("profileInstallQuery"),
    player_name_prefix: getInput("profilePlayerPrefix") || "Player",
    gameplay_strategy: getInput("profileGameplayStrategy") || "none",
    max_tutorial_steps: getInput("profileMaxTutorialSteps"),
    max_purchase_steps: getInput("profileMaxPurchaseSteps"),
    proven: getInput("profileProven"),
    aliases: splitListText(getInput("profileAliases")),
    tutorial_hints: splitListText(getInput("profileTutorialHints")),
    purchase_hints: splitListText(getInput("profilePurchaseHints")),
    blocker_words: splitListText(getInput("profileBlockerWords")),
    notes: getInput("profileNotes"),
  };
}

function applyProfileToRun(profile) {
  setInput("gameProfile", profile.id);
  setInput("gameName", profile.name);
  setInput("gamePackage", profile.package);
  setInput("playerPrefix", profile.player_name_prefix || "Player");
  if (profile.max_tutorial_steps) setInput("cvTutorialMaxSteps", profile.max_tutorial_steps);
  if (profile.max_purchase_steps) setInput("cvPurchaseMaxSteps", profile.max_purchase_steps);
  if (profile.tutorial_hints && profile.tutorial_hints.length) {
    setInput("cvTutorialInstructions", listText(profile.tutorial_hints));
  }
  if (profile.purchase_hints && profile.purchase_hints.length) {
    setInput("cvPurchaseInstructions", listText(profile.purchase_hints));
  }
  if (profile.blocker_words && profile.blocker_words.length) {
    setInput("cvExtraBlockers", profile.blocker_words.join(","));
  }
  if (profile.gameplay_strategy === "fast_runner") setInput("gameplayMethod", "fast");
  if (profile.gameplay_strategy === "match3_solver") setInput("gameplayMethod", "auto");
}

function renderReport(report) {
  $("reportStatus").textContent = report && report.final_status ? report.final_status : "None";
  const host = $("reportTimeline");
  host.innerHTML = "";
  if (!report || !report.stages) {
    host.innerHTML = `<p>No run report yet.</p>`;
    return;
  }
  report.stages.forEach((stage) => {
    const item = document.createElement("div");
    item.className = "timeline-item";
    item.innerHTML = `<strong>${stage.stage}: ${stage.status}</strong><p>${stage.message || ""} · ${stage.elapsed_seconds}s</p>`;
    host.appendChild(item);
  });
}

function renderRun(run) {
  const pill = $("runStatePill");
  if (run && run.running) {
    pill.textContent = `Running pid ${run.pid}`;
    pill.className = "pill good";
  } else if (run && run.returncode !== undefined && run.returncode !== null) {
    pill.textContent = `Exited ${run.returncode}`;
    pill.className = run.returncode === 0 ? "pill good" : "pill warn";
  } else {
    pill.textContent = "Idle";
    pill.className = "pill neutral";
  }
}

function applySettings(settings) {
  renderGameProfileSelect(settings.gameProfile);
  fillSelect($("farm"), state.methods.farms || [], settings.farm);
  fillSelect($("googleRegisterVia"), state.methods.googleRegister || [], settings.googleRegisterVia);
  fillSelect($("installMethod"), state.methods.install || [], settings.installMethod);
  fillSelect($("tutorialMethod"), state.methods.tutorial || [], settings.tutorialMethod);
  fillSelect($("gameplayMethod"), state.methods.gameplay || [], settings.gameplayMethod);
  fillSelect($("purchaseMethod"), state.methods.purchase || [], settings.purchaseMethod);

  [
    "gameName",
    "gamePackage",
    "localDevice",
    "appiumPort",
    "playerPrefix",
    "apkPath",
    "googleEmail",
    "fastGameplaySeconds",
    "match3Bounds",
    "manualTimeout",
    "cvModels",
    "cvCoordinateScale",
    "cvTutorialMaxSteps",
    "cvPurchaseMaxSteps",
    "cvInstallBasePrompt",
    "cvTutorialBasePrompt",
    "cvPurchaseBasePrompt",
    "cvInstallInstructions",
    "cvTutorialInstructions",
    "cvPurchaseInstructions",
    "cvExtraBlockers",
    "recordedInstallPath",
    "recordedTutorialPath",
    "recordedGameplayPath",
  ].forEach((id) => setInput(id, settings[id]));
  setInput("testRun", settings.testRun);
  setInput("stopAtPhone", settings.stopAtPhone);
  setInput("leavePurchaseOpen", settings.leavePurchaseOpen);
  setInput("cvFallbackManual", settings.cvFallbackManual);
  renderStages(settings.stages);
}

function collectSettings() {
  return {
    gameProfile: getInput("gameProfile"),
    farm: getInput("farm"),
    gameName: getInput("gameName"),
    gamePackage: getInput("gamePackage"),
    localDevice: getInput("localDevice"),
    appiumPort: getInput("appiumPort"),
    googleRegisterVia: getInput("googleRegisterVia"),
    installMethod: getInput("installMethod"),
    tutorialMethod: getInput("tutorialMethod"),
    gameplayMethod: getInput("gameplayMethod"),
    purchaseMethod: getInput("purchaseMethod"),
    playerPrefix: getInput("playerPrefix"),
    apkPath: getInput("apkPath"),
    googleEmail: getInput("googleEmail"),
    fastGameplaySeconds: getInput("fastGameplaySeconds"),
    match3Bounds: getInput("match3Bounds"),
    manualTimeout: getInput("manualTimeout"),
    cvFallbackManual: getInput("cvFallbackManual"),
    cvModels: getInput("cvModels"),
    cvCoordinateScale: getInput("cvCoordinateScale"),
    cvTutorialMaxSteps: getInput("cvTutorialMaxSteps"),
    cvPurchaseMaxSteps: getInput("cvPurchaseMaxSteps"),
    cvInstallBasePrompt: getInput("cvInstallBasePrompt"),
    cvTutorialBasePrompt: getInput("cvTutorialBasePrompt"),
    cvPurchaseBasePrompt: getInput("cvPurchaseBasePrompt"),
    cvInstallInstructions: getInput("cvInstallInstructions"),
    cvTutorialInstructions: getInput("cvTutorialInstructions"),
    cvPurchaseInstructions: getInput("cvPurchaseInstructions"),
    cvExtraBlockers: getInput("cvExtraBlockers"),
    recordedInstallPath: getInput("recordedInstallPath"),
    recordedTutorialPath: getInput("recordedTutorialPath"),
    recordedGameplayPath: getInput("recordedGameplayPath"),
    openrouterKey: getInput("openrouterKey"),
    genymotionToken: getInput("genymotionToken"),
    browserstackUsername: getInput("browserstackUsername"),
    browserstackAccessKey: getInput("browserstackAccessKey"),
    lambdatestUsername: getInput("lambdatestUsername"),
    lambdatestAccessKey: getInput("lambdatestAccessKey"),
    fivesimApiKey: getInput("fivesimApiKey"),
    googlePhoneNumber: getInput("googlePhoneNumber"),
    googleSmsCode: getInput("googleSmsCode"),
    googleSmsCodeFile: getInput("googleSmsCodeFile"),
    testRun: getInput("testRun"),
    stopAtPhone: getInput("stopAtPhone"),
    leavePurchaseOpen: getInput("leavePurchaseOpen"),
    stages: readStages(),
    purchaseMode: "preview",
    googlePhoneMode: "manual",
  };
}

async function refreshState(options = {}) {
  const applyForm = options.applySettings !== false;
  const data = await api("/api/state");
  state.profiles = data.profiles || [];
  state.methods = data.methods || {};
  state.settings = data.settings || {};
  renderProfiles();
  if (applyForm && state.profiles.length) fillProfileForm(state.profiles[0]);
  if (applyForm) applySettings(state.settings);
  else renderGameProfileSelect(getInput("gameProfile") || state.settings.gameProfile);
  renderDevices(data.devices || []);
  renderRecordings(data.recordings || []);
  if (applyForm || !state.readyPresets.length) renderReadyPresets(data.readyPresets || []);
  $("visionStatus").textContent = data.vision && data.vision.keyConfigured ? "Configured" : "Missing";
  renderReport(data.latestReport || {});
  renderRun(data.activeRun || {});
}

async function refreshProjectFiles() {
  const data = await api("/api/files");
  renderProjectFiles(data.files || []);
}

async function refreshPresetsOnly() {
  const data = await api("/api/presets");
  renderReadyPresets(data.presets || []);
}

async function loadProjectFile(pathValue = "") {
  const path = pathValue || getInput("projectFilePath") || $("projectFileSelect").value;
  if (!path) {
    toast("Choose a project file");
    return;
  }
  const data = await api(`/api/files/read?path=${encodeURIComponent(path)}`);
  state.currentProjectFile = data.path;
  setInput("projectFilePath", data.path);
  $("projectFileSelect").value = data.path;
  $("projectEditor").value = data.content || "";
  $("projectEditorStatus").textContent = `${data.path} · ${data.size} bytes`;
}

async function saveProjectFile() {
  const path = getInput("projectFilePath") || state.currentProjectFile;
  if (!path) {
    toast("Choose a project file");
    return;
  }
  const data = await api("/api/files/write", {
    method: "POST",
    body: JSON.stringify({ path, content: $("projectEditor").value }),
  });
  state.currentProjectFile = data.path;
  $("projectEditorStatus").textContent = `Saved ${data.path} · ${data.size} bytes`;
  toast(`Saved ${data.path}`);
  await refreshProjectFiles();
}

window.loadProjectFile = loadProjectFile;
window.refreshProjectFiles = refreshProjectFiles;

async function loadSelectedRecording() {
  const path = $("recordingSelect").value;
  if (!path) {
    toast("No recording selected");
    return;
  }
  const data = await api(`/api/recordings/read?path=${encodeURIComponent(path)}`);
  $("recordingPreview").value = data.content || "";
  toast(`Loaded ${data.actions} recorded actions`);
}

function useSelectedRecording(stage) {
  const path = $("recordingSelect").value;
  if (!path) {
    toast("No recording selected");
    return;
  }
  if (stage === "install") {
    setInput("installMethod", "recorded");
    setInput("recordedInstallPath", path);
  } else if (stage === "tutorial") {
    setInput("tutorialMethod", "recorded");
    setInput("recordedTutorialPath", path);
  } else if (stage === "gameplay") {
    setInput("gameplayMethod", "recorded");
    setInput("recordedGameplayPath", path);
  }
  toast(`Recording assigned to ${stage}`);
}

async function refreshLog() {
  const data = await api("/api/log");
  $("runLog").textContent = data.log || "No active dashboard run.";
}

async function refreshScreenshot() {
  if (!state.selectedSerial) {
    toast("No ADB device selected");
    return;
  }
  const img = $("phoneShot");
  $("shotEmpty").style.display = "none";
  const url = `/api/device/screenshot?serial=${encodeURIComponent(state.selectedSerial)}&t=${Date.now()}`;
  img.src = url;
  state.lastScreenshotUrl = url;
}

function phoneImagePoint(event, img = $("phoneShot")) {
  if (!img || !img.naturalWidth || !img.naturalHeight) return null;
  const rect = img.getBoundingClientRect();
  const x = Math.round((event.clientX - rect.left) * (img.naturalWidth / rect.width));
  const y = Math.round((event.clientY - rect.top) * (img.naturalHeight / rect.height));
  return {
    x: Math.max(0, Math.min(img.naturalWidth, x)),
    y: Math.max(0, Math.min(img.naturalHeight, y)),
  };
}

function selectedSerial() {
  return $("deviceSelect").value || state.selectedSerial;
}

async function devicePost(path, payload = {}) {
  return api(path, {
    method: "POST",
    body: JSON.stringify({ serial: selectedSerial(), ...payload }),
  });
}

function cvTestPayload() {
  const goal = getInput("cvTestGoal").trim();
  if (!goal) throw new Error(t("cvtest.goalRequired"));
  let values = {};
  const valuesText = getInput("cvTestValues").trim();
  if (valuesText) {
    values = JSON.parse(valuesText);
  }
  return {
    serial: selectedSerial(),
    goal,
    values,
    openrouterKey: getInput("openrouterKey"),
    models: getInput("cvModels"),
    maxSteps: Number(getInput("cvTestMaxSteps") || 5),
  };
}

async function runCvTest(path, statusText) {
  $("cvTestStatus").textContent = statusText;
  $("cvTestStatus").className = "pill warn";
  $("cvTestOutput").textContent = "Running...";
  const data = await api(path, {
    method: "POST",
    body: JSON.stringify(cvTestPayload()),
  });
  $("cvTestStatus").textContent = "Done";
  $("cvTestStatus").className = "pill good";
  $("cvTestOutput").textContent = JSON.stringify(data, null, 2);
  window.setTimeout(() => refreshScreenshot().catch(() => {}), 600);
}

function wireEvents() {
  $("langRu").addEventListener("click", () => setLanguage("ru"));
  $("langEn").addEventListener("click", () => setLanguage("en"));
  $("helpMode").addEventListener("change", (event) => setHelpMode(event.target.checked));

  $("logoutBtn").addEventListener("click", async () => {
    await api("/api/logout", { method: "POST", body: "{}" });
    window.location.href = "/";
  });

  $("refreshBtn").addEventListener("click", async () => {
    await refreshState({ applySettings: true });
    toast("State refreshed");
  });

  $("logRefreshBtn").addEventListener("click", refreshLog);
  $("shotBtn").addEventListener("click", refreshScreenshot);
  $("deviceSelect").addEventListener("change", (event) => {
    state.selectedSerial = event.target.value;
    refreshScreenshot().catch((e) => toast(e.message));
  });

  $("readyPreset").addEventListener("change", (event) => {
    const preset = state.readyPresets[Number(event.target.value || 0)];
    $("presetDescription").textContent = preset ? preset.description || "" : "";
    setInput("presetName", preset ? preset.name || "" : "");
    setInput("presetTitle", preset ? preset.title || "" : "");
    setInput("presetDescriptionInput", preset ? preset.description || "" : "");
  });

  $("loadPresetBtn").addEventListener("click", () => {
    loadReadyPreset($("readyPreset").value);
    toast("Ready preset loaded");
  });

  $("useDeviceBtn").addEventListener("click", () => {
    setInput("localDevice", selectedSerial());
    toast(`Run device set to ${selectedSerial()}`);
  });

  $("gameProfile").addEventListener("change", () => {
    const profile = state.profiles.find((item) => item.id === $("gameProfile").value);
    if (!profile) return;
    setInput("gameName", profile.name);
    setInput("gamePackage", profile.package);
    setInput("playerPrefix", profile.player_name_prefix || "Player");
    if (profile.gameplay_strategy === "fast_runner") setInput("gameplayMethod", "fast");
    if (profile.gameplay_strategy === "match3_solver") setInput("gameplayMethod", "auto");
  });

  $("savePresetBtn").addEventListener("click", async () => {
    await api("/api/preset", { method: "POST", body: JSON.stringify({ settings: collectSettings() }) });
    toast("Preset saved");
  });

  $("saveNamedPresetBtn").addEventListener("click", async () => {
    const data = await api("/api/presets", {
      method: "POST",
      body: JSON.stringify({
        name: getInput("presetName"),
        title: getInput("presetTitle"),
        description: getInput("presetDescriptionInput"),
        settings: collectSettings(),
      }),
    });
    toast(`Preset saved: ${data.path}`);
    await refreshPresetsOnly();
  });

  $("deletePresetBtn").addEventListener("click", async () => {
    const preset = state.readyPresets[Number($("readyPreset").value || 0)];
    if (!preset || !preset.path) {
      toast("No preset selected");
      return;
    }
    const data = await api("/api/presets/delete", {
      method: "POST",
      body: JSON.stringify({ path: preset.path }),
    });
    toast(data.deleted ? `Deleted ${data.path}` : "Preset was already absent");
    await refreshPresetsOnly();
  });

  $("newProfileBtn").addEventListener("click", () => {
    clearProfileForm();
    toast("New profile form ready");
  });

  $("saveProfileBtn").addEventListener("click", async () => {
    const data = await api("/api/profiles", {
      method: "POST",
      body: JSON.stringify({ profile: collectProfile() }),
    });
    toast(`Profile saved: ${data.path}`);
    await refreshState({ applySettings: false });
    const profile = state.profiles.find((item) => item.id === data.profile.id);
    if (profile) fillProfileForm(profile);
  });

  $("applyProfileBtn").addEventListener("click", () => {
    const profile = collectProfile();
    applyProfileToRun(profile);
    toast(`Profile applied: ${profile.id || profile.name}`);
  });

  $("deleteProfileBtn").addEventListener("click", async () => {
    const profileId = getInput("profileId");
    if (!profileId) {
      toast("No profile id");
      return;
    }
    const data = await api("/api/profiles/delete", {
      method: "POST",
      body: JSON.stringify({ id: profileId }),
    });
    toast(data.deleted ? `Deleted custom profile ${data.id}` : "No custom profile file to delete");
    await refreshState({ applySettings: false });
    clearProfileForm();
  });

  $("startRunBtn").addEventListener("click", async () => {
    const settings = collectSettings();
    const data = await api("/api/run", { method: "POST", body: JSON.stringify({ settings }) });
    toast(`Run started: pid ${data.pid}`);
    await refreshState();
    await refreshLog();
  });

  $("stopRunBtn").addEventListener("click", async () => {
    const data = await api("/api/stop", { method: "POST", body: "{}" });
    toast(data.stopped ? "Run stopped" : data.message);
    await refreshState();
  });

  $("checkBtn").addEventListener("click", async () => {
    $("checkOutput").textContent = "Running compileall and pytest...";
    const data = await api("/api/check", { method: "POST", body: "{}" });
    $("testStatus").textContent = data.ok ? "Passed" : "Failed";
    $("checkOutput").textContent = data.outputs.map((item) => {
      return `$ ${item.command}\nexit ${item.code}\n${item.stdout}${item.stderr ? "\n" + item.stderr : ""}`;
    }).join("\n\n");
    toast(data.ok ? "Checks passed" : "Checks failed");
  });

  $("refreshFilesBtn").addEventListener("click", async () => {
    await refreshProjectFiles();
    toast("Project files refreshed");
  });

  $("projectFileSelect").addEventListener("change", (event) => {
    setInput("projectFilePath", event.target.value);
  });

  $("projectFileSelect").addEventListener("dblclick", () => {
    loadProjectFile().catch((e) => toast(e.message));
  });

  $("loadFileBtn").addEventListener("click", () => {
    loadProjectFile().catch((e) => toast(e.message));
  });

  $("saveFileBtn").addEventListener("click", () => {
    saveProjectFile().catch((e) => toast(e.message));
  });

  $("continueBtn").addEventListener("click", async () => {
    await api("/api/manual/continue", { method: "POST", body: "{}" });
    toast("Manual checkpoint released");
  });

  $("cvPlanBtn").addEventListener("click", () => {
    runCvTest("/api/cv/plan", t("cvtest.planning")).catch((e) => {
      $("cvTestStatus").textContent = "Error";
      $("cvTestStatus").className = "pill warn";
      $("cvTestOutput").textContent = e.message;
      toast(e.message);
    });
  });

  $("cvRunGoalBtn").addEventListener("click", () => {
    runCvTest("/api/cv/run", t("cvtest.running")).catch((e) => {
      $("cvTestStatus").textContent = "Error";
      $("cvTestStatus").className = "pill warn";
      $("cvTestOutput").textContent = e.message;
      toast(e.message);
    });
  });

  $("phoneShot").addEventListener("pointerdown", (event) => {
    const img = event.currentTarget;
    const point = phoneImagePoint(event, img);
    if (!point) return;
    state.phonePointer = { ...point, pointerId: event.pointerId, startedAt: Date.now() };
    if (img.setPointerCapture) img.setPointerCapture(event.pointerId);
    event.preventDefault();
  });

  $("phoneShot").addEventListener("pointerup", async (event) => {
    const img = event.currentTarget;
    const start = state.phonePointer;
    const end = phoneImagePoint(event, img);
    if (!start || !end || start.pointerId !== event.pointerId) return;
    state.phonePointer = null;
    if (img.releasePointerCapture) img.releasePointerCapture(event.pointerId);
    const actionAt = Date.now();
    const dx = end.x - start.x;
    const dy = end.y - start.y;
    const distance = Math.hypot(dx, dy);
    if (distance >= 34) {
      const duration = Math.max(120, Math.min(1200, actionAt - start.startedAt));
      await devicePost("/api/device/swipe", {
        x1: start.x,
        y1: start.y,
        x2: end.x,
        y2: end.y,
        duration,
      });
      addRecordedAction({
        action: "swipe",
        x1: start.x,
        y1: start.y,
        x2: end.x,
        y2: end.y,
        duration,
      }, actionAt);
      $("manualStatus").textContent = `Swiped ${start.x}, ${start.y} -> ${end.x}, ${end.y}`;
    } else {
      await devicePost("/api/device/tap", { x: end.x, y: end.y });
      addRecordedAction({ action: "tap", x: end.x, y: end.y }, actionAt);
      $("manualStatus").textContent = `Tapped ${end.x}, ${end.y}`;
    }
    window.setTimeout(() => refreshScreenshot().catch(() => {}), 450);
  });

  $("phoneShot").addEventListener("pointercancel", () => {
    state.phonePointer = null;
  });

  document.querySelectorAll("[data-key]").forEach((button) => {
    button.addEventListener("click", async () => {
      const actionAt = Date.now();
      await devicePost("/api/device/key", { key: button.dataset.key });
      addRecordedAction({ action: "key", key: button.dataset.key }, actionAt);
      $("manualStatus").textContent = `Sent key ${button.dataset.key}`;
      window.setTimeout(() => refreshScreenshot().catch(() => {}), 450);
    });
  });

  $("typeBtn").addEventListener("click", async () => {
    const actionAt = Date.now();
    await devicePost("/api/device/text", { text: $("manualText").value });
    addRecordedAction({ action: "text", text: $("manualText").value }, actionAt);
    $("manualStatus").textContent = "Text sent";
    window.setTimeout(() => refreshScreenshot().catch(() => {}), 450);
  });

  $("swipeUpBtn").addEventListener("click", () => swipePreset("up"));
  $("swipeDownBtn").addEventListener("click", () => swipePreset("down"));
  $("swipeLeftBtn").addEventListener("click", () => swipePreset("left"));
  $("swipeRightBtn").addEventListener("click", () => swipePreset("right"));

  $("recordBtn").addEventListener("click", () => {
    state.isRecording = !state.isRecording;
    state.recordingLastActionAt = 0;
    $("recordBtn").textContent = state.isRecording ? t("button.stopRecording") : t("button.startRecording");
    toast(state.isRecording ? "Recording manual actions" : "Recording paused");
  });

  $("clearRecordBtn").addEventListener("click", () => {
    state.recordedActions = [];
    state.recordingLastActionAt = 0;
    updateRecordCount();
    toast("Recording cleared");
  });

  $("saveRecordingBtn").addEventListener("click", async () => {
    const data = await api("/api/recordings", {
      method: "POST",
      body: JSON.stringify({ name: $("recordingName").value, actions: state.recordedActions }),
    });
    toast(`Recording saved: ${data.path}`);
    await refreshState({ applySettings: false });
    setInput("recordingSelect", data.path);
  });

  $("loadRecordingBtn").addEventListener("click", () => {
    loadSelectedRecording().catch((e) => toast(e.message));
  });

  $("useInstallRecordingBtn").addEventListener("click", () => useSelectedRecording("install"));
  $("useTutorialRecordingBtn").addEventListener("click", () => useSelectedRecording("tutorial"));
  $("useGameplayRecordingBtn").addEventListener("click", () => useSelectedRecording("gameplay"));

  $("replayBtn").addEventListener("click", async () => {
    const path = $("recordingSelect").value;
    if (!path) {
      toast("No recording selected");
      return;
    }
    const data = await api("/api/recordings/replay", {
      method: "POST",
      body: JSON.stringify({ serial: selectedSerial(), path }),
    });
    toast(`Replayed ${data.actions} actions`);
    window.setTimeout(() => refreshScreenshot().catch(() => {}), 700);
  });
}

async function swipePreset(direction) {
  const img = $("phoneShot");
  const width = img.naturalWidth || 1080;
  const height = img.naturalHeight || 2400;
  const centerX = Math.round(width * 0.5);
  const centerY = Math.round(height * 0.5);
  const points = {
    up: [centerX, Math.round(height * 0.75), centerX, Math.round(height * 0.35)],
    down: [centerX, Math.round(height * 0.35), centerX, Math.round(height * 0.75)],
    left: [Math.round(width * 0.78), centerY, Math.round(width * 0.22), centerY],
    right: [Math.round(width * 0.22), centerY, Math.round(width * 0.78), centerY],
  };
  const [x1, y1, x2, y2] = points[direction] || points.up;
  const actionAt = Date.now();
  await devicePost("/api/device/swipe", { x1, y1, x2, y2, duration: 320 });
  addRecordedAction({ action: "swipe", x1, y1, x2, y2, duration: 320 }, actionAt);
  $("manualStatus").textContent = `Swipe ${direction}`;
  window.setTimeout(() => refreshScreenshot().catch(() => {}), 600);
}

async function boot() {
  await loadTranslations();
  const savedLang = localStorage.getItem("dashboard.language") || "en";
  const savedHelp = localStorage.getItem("dashboard.helpMode");
  state.helpMode = savedHelp === null ? true : savedHelp === "1";
  state.lang = savedLang === "ru" ? "ru" : "en";
  applyTranslations();
  wireEvents();
  await refreshState({ applySettings: true });
  await refreshProjectFiles();
  refreshScreenshot().catch(() => {});
  refreshLog().catch(() => {});
  window.setInterval(() => {
    refreshState({ applySettings: false }).catch(() => {});
    refreshLog().catch(() => {});
  }, 7000);
}

boot().catch((error) => toast(error.message));
