(function () {
  const byId = (id) => document.getElementById(id);
  let latestInspector = null;
  let latestDrawnBox = null;
  let dragStart = null;
  let latestEditableProfilePath = "";

  function tr(key, fallback) {
    return typeof window.t === "function" ? window.t(key) : fallback;
  }

  async function loadInspector() {
    const select = byId("deviceSelect");
    const serial = select ? select.value : "";
    const query = serial ? `?serial=${encodeURIComponent(serial)}` : "";
    setStatus("vision.status.loading", "Loading");
    const response = await fetch(`/api/vision/inspector${query}`, { cache: "no-store" });
    const data = await response.json();
    if (!response.ok || data.error) throw new Error(data.error || response.statusText);
    latestInspector = data;
    latestDrawnBox = null;
    latestEditableProfilePath = "";
    renderInspector(data);
    setStatus("vision.status.ready", "Ready");
  }

  function renderInspector(data) {
    const shot = byId("visionInspectorShot");
    const overlay = byId("visionInspectorOverlay");
    const frame = data.frame || {};
    const decision = data.decision || {};
    const overlayData = data.overlay || {};
    if (shot && frame.screenshotUrl) {
      shot.src = `${frame.screenshotUrl}${frame.screenshotUrl.includes("?") ? "&" : "?"}_=${Date.now()}`;
      shot.onload = () => drawOverlay(overlay, shot, overlayData);
      if (shot.complete) drawOverlay(overlay, shot, overlayData);
    }
    byId("visionFrameSource").textContent = frame.source || "-";
    byId("visionLlmCalled").textContent = decision.llmCalled ? tr("common.yes", "yes") : tr("common.no", "no");
    byId("visionProviders").textContent = (decision.providersCalled || []).join(", ") || "-";
    byId("visionSelected").textContent = selectedLabel(overlayData.selectedCandidate);
    byId("visionLatency").textContent = JSON.stringify(data.latency || {}, null, 2);
    const selected = overlayData.selectedCandidate;
    if (selected) {
      if (byId("visionTemplateId") && !byId("visionTemplateId").value) {
        byId("visionTemplateId").value = String(selected.name || "template").toLowerCase().replace(/[^a-z0-9_-]+/g, "-");
      }
      if (byId("visionTemplateNamespace") && !byId("visionTemplateNamespace").value) {
        const profile = byId("gameProfile");
        byId("visionTemplateNamespace").value = profile && profile.value ? profile.value : "common";
      }
      if (byId("visionRoiName") && !byId("visionRoiName").value) {
        byId("visionRoiName").value = String(selected.name || "selected_roi").toLowerCase().replace(/[^a-z0-9_-]+/g, "-");
      }
    }
  }

  function drawOverlay(svg, image, overlayData) {
    if (!svg || !image.naturalWidth || !image.naturalHeight) return;
    svg.innerHTML = "";
    svg.setAttribute("viewBox", `0 0 ${image.naturalWidth} ${image.naturalHeight}`);
    const roi = overlayData.roi && overlayData.roi.pixel_box;
    if (roi) svg.appendChild(rect(roi, "vision-roi"));
    const selected = overlayData.selectedCandidate || {};
    (overlayData.candidates || []).forEach((candidate) => {
      if (!candidate.bbox) return;
      const className = sameBox(candidate.bbox, selected.bbox) ? "vision-box selected" : "vision-box";
      svg.appendChild(rect(candidate.bbox, className));
    });
    if (latestDrawnBox) svg.appendChild(rect(latestDrawnBox, "vision-drawn"));
  }

  function rect(box, className) {
    const node = document.createElementNS("http://www.w3.org/2000/svg", "rect");
    const [x1, y1, x2, y2] = box;
    node.setAttribute("x", x1);
    node.setAttribute("y", y1);
    node.setAttribute("width", Math.max(1, x2 - x1));
    node.setAttribute("height", Math.max(1, y2 - y1));
    node.setAttribute("class", className);
    return node;
  }

  function selectedLabel(candidate) {
    if (!candidate) return "-";
    const confidence = Number(candidate.confidence || 0).toFixed(2);
    return `${candidate.name || "element"} (${candidate.source || "unknown"} ${confidence})`;
  }

  function sameBox(left, right) {
    return Array.isArray(left) && Array.isArray(right) && left.join(",") === right.join(",");
  }

  window.addEventListener("DOMContentLoaded", () => {
    const button = byId("visionInspectorRefreshBtn");
    if (button) button.addEventListener("click", () => runInspectorAction(loadInspector));
    const saveTemplate = byId("visionSaveTemplateBtn");
    if (saveTemplate) saveTemplate.addEventListener("click", () => runInspectorAction(saveTemplateFromSelected));
    const createRoi = byId("visionCreateRoiBtn");
    if (createRoi) createRoi.addEventListener("click", () => runInspectorAction(createRoiFromSelected));
    const clearDrawn = byId("visionClearDrawnBoxBtn");
    if (clearDrawn) clearDrawn.addEventListener("click", clearDrawnBox);
    const exportLabel = byId("visionExportLabelBtn");
    if (exportLabel) exportLabel.addEventListener("click", () => runInspectorAction(exportSelectedLabel));
    const openProfile = byId("visionOpenSavedProfileBtn");
    if (openProfile) openProfile.addEventListener("click", () => runInspectorAction(openSavedProfile));
    const refreshTemplates = byId("visionRefreshTemplatesBtn");
    if (refreshTemplates) refreshTemplates.addEventListener("click", () => runInspectorAction(loadTemplates));
    attachDrawing();
  });

  async function runInspectorAction(fn) {
    try {
      await fn();
    } catch (error) {
      setStatus("vision.status.error", "Error", error && error.message ? error.message : String(error));
      if (typeof window.toast === "function") {
        window.toast(error && error.message ? error.message : String(error));
      }
      console.error(error);
    }
  }

  async function saveTemplateFromSelected() {
    const box = activeBox();
    const serial = byId("deviceSelect") ? byId("deviceSelect").value : "";
    const templateId = requiredValue("visionTemplateId", "vision.error.templateIdRequired", "Template id is required");
    const payload = {
      serial,
      templateId,
      namespace: byId("visionTemplateNamespace").value || "common",
      bbox: box,
      roi: byId("visionRoiName").value || "",
      threshold: Number(byId("visionTemplateThreshold").value || 0.82),
      screenshotBase64: screenshotBase64(),
    };
    const result = await postJson("/api/vision/templates", payload);
    renderSaveResult("template", result);
    await loadTemplates();
    setStatus("vision.status.templateSaved", "Template saved");
  }

  async function createRoiFromSelected() {
    const box = activeBox();
    const shot = byId("visionInspectorShot");
    const profile = byId("gameProfile");
    const zoneName = requiredValue("visionRoiName", "vision.error.roiNameRequired", "ROI zone name is required");
    if (!shot || !shot.naturalWidth || !shot.naturalHeight) {
      throw new Error(tr("vision.error.refreshFirst", "Refresh inspector before saving ROI"));
    }
    const payload = {
      profileId: profile && profile.value ? profile.value : "custom",
      zoneName,
      pixelBox: box,
      width: shot.naturalWidth,
      height: shot.naturalHeight,
    };
    const result = await postJson("/api/vision/roi", payload);
    renderSaveResult("roi", result);
    setStatus("vision.status.roiSaved", "ROI saved");
  }

  async function exportSelectedLabel() {
    const selected = activeCandidate();
    const profile = byId("gameProfile");
    const payload = {
      profileId: profile && profile.value ? profile.value : "custom",
      labelId: selected.name || "element",
      goal: latestInspector && latestInspector.decision ? latestInspector.decision.goal : "",
      roi: latestInspector && latestInspector.overlay ? latestInspector.overlay.roi : null,
      candidate: selected,
    };
    const result = await postJson("/api/vision/labels", payload);
    renderSaveResult("label", result);
    setStatus("vision.status.labelExported", "Label exported");
  }

  function selectedCandidate() {
    const selected = latestInspector && latestInspector.overlay && latestInspector.overlay.selectedCandidate;
    if (!selected || !selected.bbox) {
      throw new Error(tr("vision.error.noSelectedCandidate", "Refresh inspector and select a candidate first"));
    }
    return selected;
  }

  function activeBox() {
    if (latestDrawnBox) return latestDrawnBox;
    const selected = latestInspector && latestInspector.overlay && latestInspector.overlay.selectedCandidate;
    if (selected && selected.bbox) return selected.bbox;
    throw new Error(tr("vision.error.noActiveBox", "Draw a box on the screenshot or refresh inspector for a selected candidate"));
  }

  function activeCandidate() {
    if (latestDrawnBox) {
      return {
        name: byId("visionTemplateId").value || byId("visionRoiName").value || "manual_box",
        source: "manual",
        confidence: 1,
        bbox: latestDrawnBox,
      };
    }
    return selectedCandidate();
  }

  function attachDrawing() {
    const overlay = byId("visionInspectorOverlay");
    const shot = byId("visionInspectorShot");
    if (!overlay || !shot) return;
    overlay.addEventListener("pointerdown", (event) => {
      const point = overlayPoint(event, overlay);
      if (!point) return;
      dragStart = point;
      latestDrawnBox = [point.x, point.y, point.x + 1, point.y + 1];
      overlay.setPointerCapture(event.pointerId);
      drawOverlay(overlay, shot, (latestInspector && latestInspector.overlay) || {});
      event.preventDefault();
    });
    overlay.addEventListener("pointermove", (event) => {
      if (!dragStart) return;
      const point = overlayPoint(event, overlay);
      if (!point) return;
      latestDrawnBox = normalizedDragBox(dragStart, point);
      drawOverlay(overlay, shot, (latestInspector && latestInspector.overlay) || {});
      event.preventDefault();
    });
    overlay.addEventListener("pointerup", (event) => {
      if (!dragStart) return;
      const point = overlayPoint(event, overlay);
      if (point) latestDrawnBox = normalizedDragBox(dragStart, point);
      dragStart = null;
      if (!latestDrawnBox || latestDrawnBox[2] - latestDrawnBox[0] < 4 || latestDrawnBox[3] - latestDrawnBox[1] < 4) {
        latestDrawnBox = null;
      }
      drawOverlay(overlay, shot, (latestInspector && latestInspector.overlay) || {});
      if (latestDrawnBox) {
        fillManualDefaults();
        setStatus("vision.status.drawnBoxReady", "Drawn box ready");
      }
      event.preventDefault();
    });
    overlay.addEventListener("pointercancel", () => {
      dragStart = null;
    });
  }

  function overlayPoint(event, overlay) {
    const box = overlay.getBoundingClientRect();
    const view = overlay.viewBox && overlay.viewBox.baseVal;
    if (!box.width || !box.height || !view || !view.width || !view.height) return null;
    const x = Math.max(0, Math.min(view.width, ((event.clientX - box.left) / box.width) * view.width));
    const y = Math.max(0, Math.min(view.height, ((event.clientY - box.top) / box.height) * view.height));
    return { x: Math.round(x), y: Math.round(y) };
  }

  function normalizedDragBox(start, end) {
    return [
      Math.min(start.x, end.x),
      Math.min(start.y, end.y),
      Math.max(start.x, end.x),
      Math.max(start.y, end.y),
    ];
  }

  function clearDrawnBox() {
    latestDrawnBox = null;
    const overlay = byId("visionInspectorOverlay");
    const shot = byId("visionInspectorShot");
    drawOverlay(overlay, shot, (latestInspector && latestInspector.overlay) || {});
    setStatus("vision.status.ready", "Ready");
  }

  function fillManualDefaults() {
    const templateId = byId("visionTemplateId");
    const roiName = byId("visionRoiName");
    const namespace = byId("visionTemplateNamespace");
    if (templateId && !templateId.value) templateId.value = "manual_template";
    if (roiName && !roiName.value) roiName.value = "manual_roi";
    if (namespace && !namespace.value) {
      const profile = byId("gameProfile");
      namespace.value = profile && profile.value ? profile.value : "common";
    }
  }

  function renderSaveResult(kind, result) {
    const output = byId("visionSaveResult");
    const editablePath = result && result.path && String(result.path).startsWith("dashboard/profiles/")
      ? String(result.path)
      : "";
    latestEditableProfilePath = editablePath;
    const openButton = byId("visionOpenSavedProfileBtn");
    if (openButton) openButton.disabled = !latestEditableProfilePath;
    if (!output) return;
    const payload = { type: kind, ...result };
    output.textContent = JSON.stringify(payload, null, 2);
  }

  async function openSavedProfile() {
    if (!latestEditableProfilePath) {
      throw new Error(tr("vision.error.noEditableProfile", "Save an ROI first to open its profile JSON"));
    }
    if (typeof window.refreshProjectFiles === "function") {
      await window.refreshProjectFiles();
    }
    if (typeof window.loadProjectFile === "function") {
      await window.loadProjectFile(latestEditableProfilePath);
    } else {
      const response = await fetch(`/api/files/read?path=${encodeURIComponent(latestEditableProfilePath)}`, { cache: "no-store" });
      const data = await response.json();
      if (!response.ok || data.error) throw new Error(data.error || response.statusText);
      if (byId("projectFilePath")) byId("projectFilePath").value = data.path;
      if (byId("projectEditor")) byId("projectEditor").value = data.content || "";
      if (byId("projectEditorStatus")) byId("projectEditorStatus").textContent = `${data.path} · ${data.size} bytes`;
    }
    window.location.hash = "project";
    setStatus("vision.status.profileOpened", "Profile JSON opened");
  }

  async function loadTemplates() {
    const response = await fetch("/api/vision/templates", { cache: "no-store" });
    const data = await response.json();
    if (!response.ok || data.error) throw new Error(data.error || response.statusText);
    renderTemplateList(data.templates || []);
  }

  function renderTemplateList(templates) {
    const host = byId("visionTemplateList");
    if (!host) return;
    host.innerHTML = "";
    if (!templates.length) {
      host.textContent = tr("vision.templates.empty", "No templates saved yet.");
      return;
    }
    templates.forEach((template) => {
      const item = document.createElement("div");
      item.className = "vision-template-item";

      const title = document.createElement("div");
      title.className = "vision-template-title";
      const name = document.createElement("strong");
      name.textContent = `${template.namespace ? template.namespace + "/" : ""}${template.id || "template"}`;
      const use = document.createElement("button");
      use.type = "button";
      use.className = "ghost small";
      use.textContent = tr("button.useTemplate", "Use");
      use.addEventListener("click", () => useTemplate(template));
      title.append(name, use);

      const meta = document.createElement("div");
      meta.className = "vision-template-meta";
      meta.textContent = `roi=${template.roi || "-"} · threshold=${template.threshold ?? "-"} · files=${template.fileCount || 0}`;

      const paths = document.createElement("div");
      paths.className = "vision-template-paths";
      const files = template.files && template.files.length ? template.files : template.paths || [];
      paths.textContent = files.slice(0, 3).join("\n") || tr("vision.templates.noFiles", "No PNG files matched");

      item.append(title, meta, paths);
      host.appendChild(item);
    });
  }

  function useTemplate(template) {
    if (byId("visionTemplateId")) byId("visionTemplateId").value = template.id || "";
    if (byId("visionTemplateNamespace")) byId("visionTemplateNamespace").value = template.namespace || "";
    if (byId("visionTemplateThreshold") && template.threshold !== undefined && template.threshold !== null) {
      byId("visionTemplateThreshold").value = template.threshold;
    }
    if (byId("visionRoiName") && template.roi) byId("visionRoiName").value = template.roi;
    setStatus("vision.status.templateSelected", "Template selected");
  }

  async function postJson(path, payload) {
    const response = await fetch(path, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const data = await response.json();
    if (!response.ok || data.error) throw new Error(data.error || response.statusText);
    return data;
  }

  function requiredValue(id, key, fallback) {
    const node = byId(id);
    const value = node ? String(node.value || "").trim() : "";
    if (!value) {
      if (node) node.focus();
      throw new Error(tr(key, fallback));
    }
    return value;
  }

  function screenshotBase64() {
    const shot = byId("visionInspectorShot");
    if (!shot || !shot.naturalWidth || !shot.naturalHeight) {
      throw new Error(tr("vision.error.refreshFirst", "Refresh inspector before saving"));
    }
    const canvas = document.createElement("canvas");
    canvas.width = shot.naturalWidth;
    canvas.height = shot.naturalHeight;
    const ctx = canvas.getContext("2d");
    ctx.drawImage(shot, 0, 0);
    return canvas.toDataURL("image/png");
  }

  function setStatus(key, fallback, detail) {
    const status = byId("visionInspectorStatus");
    if (!status) return;
    const base = tr(key, fallback);
    status.textContent = detail ? `${base}: ${detail}` : base;
  }
})();
