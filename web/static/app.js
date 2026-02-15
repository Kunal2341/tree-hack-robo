/**
 * TreeHackNow Web UI — generate, refine, preview robots
 */

const API = {
  generate: (prompt) =>
    fetch("/api/generate", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ prompt }),
    }).then((r) => r.json()),

  generateMjcf: (prompt) =>
    fetch("/api/generate/mjcf", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ prompt }),
    }).then((r) => r.json()),

  generateSdf: (prompt) =>
    fetch("/api/generate/sdf", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ prompt }),
    }).then((r) => r.json()),

  convertMjcf: (robotId, urdf) =>
    fetch("/api/convert/mjcf", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ robot_id: robotId, urdf }),
    }).then((r) => r.json()),

  convertSdf: (robotId, urdf) =>
    fetch("/api/convert/sdf", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ robot_id: robotId, urdf }),
    }).then((r) => r.json()),

  imageToUrdf: (formData) =>
    fetch("/api/image-to-urdf", {
      method: "POST",
      body: formData,
    }).then((r) => r.json()),

  simulate: (robotId, terrainMode, opts = {}) =>
    fetch("/api/simulate", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        robot_id: robotId,
        terrain_mode: terrainMode,
        enable_motors: opts.enableMotors || false,
        record_trajectory: opts.recordTrajectory || false,
      }),
    }).then((r) => r.json()),

  stressTest: (robotId, enableMotors = false) =>
    fetch("/api/stress-test", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ robot_id: robotId, enable_motors: enableMotors }),
    }).then((r) => r.json()),

  refine: (prompt, baseId, baseUrdf) =>
    fetch("/api/refine", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        prompt,
        base_id: baseId || undefined,
        base_urdf: baseUrdf || undefined,
      }),
    }).then((r) => r.json()),

  history: () => fetch("/api/history").then((r) => r.json()),
  robot: (id) => fetch(`/api/robot/${id}`).then((r) => r.json()),
  deleteRobot: (id) =>
    fetch(`/api/robot/${id}`, { method: "DELETE" }).then((r) => r.json()),

  leaderboard: (terrainMode) => {
    const params = terrainMode ? `?terrain_mode=${terrainMode}` : "";
    return fetch(`/api/leaderboard${params}`).then((r) => r.json());
  },

  submitScore: (robotId, terrainMode) =>
    fetch("/api/leaderboard/submit", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ robot_id: robotId, terrain_mode: terrainMode }),
    }).then((r) => r.json()),
};

// Track uploaded image file
let uploadedImageFile = null;

let selectedId = null;
let selectedUrdf = null;
let scene = null;
let renderer = null;
let camera = null;
let animationId = null;

// Replay state
let replayData = null;  // trajectory object from API
let replayPlaying = false;
let replayFrame = 0;
let replayStartTime = 0;
let replayAnimId = null;
let currentRobot = null;  // Three.js robot object for replay

function toast(msg, type = "success") {
  const el = document.getElementById("toast");
  el.textContent = msg;
  el.className = `toast ${type} show`;
  setTimeout(() => el.classList.remove("show"), 3000);
}

function setLoading(loading) {
  const btn = document.getElementById("btn-generate");
  const btnRefine = document.getElementById("btn-refine");
  btn.disabled = loading;
  btn.textContent = loading ? "Generating..." : "Generate URDF";
  if (loading) {
    btnRefine.disabled = true;
    document.getElementById("btn-simulate").disabled = true;
    document.getElementById("btn-download").disabled = true;
    document.getElementById("btn-view-source").disabled = true;
    document.getElementById("btn-submit-score").disabled = true;
    document.getElementById("btn-replay").disabled = true;
    document.getElementById("btn-stress-test").disabled = true;
    document.getElementById("btn-export-mjcf").disabled = true;
    document.getElementById("btn-export-sdf").disabled = true;
  } else {
    updateRefineButton();
    updateSimulateButton();
    updateDownloadButton();
    updateViewSourceButton();
    updateSubmitButton();
    updateReplayButton();
    updateStressTestButton();
    updateExportButtons();
  }
}

function updateRefineButton() {
  const btn = document.getElementById("btn-refine");
  btn.disabled = !selectedId;
}

function updateSimulateButton() {
  const btn = document.getElementById("btn-simulate");
  btn.disabled = !selectedId;
}

function updateDownloadButton() {
  document.getElementById("btn-download").disabled = !selectedId;
}

function updateViewSourceButton() {
  document.getElementById("btn-view-source").disabled = !selectedId;
}

function updateSubmitButton() {
  document.getElementById("btn-submit-score").disabled = !selectedId;
}

function updateReplayButton() {
  document.getElementById("btn-replay").disabled = !selectedId;
}

function updateStressTestButton() {
  document.getElementById("btn-stress-test").disabled = !selectedId;
}

function updateExportButtons() {
  document.getElementById("btn-export-mjcf").disabled = !selectedId;
  document.getElementById("btn-export-sdf").disabled = !selectedId;
}

function updateRobotCount(count) {
  const badge = document.getElementById("robot-count-badge");
  if (badge) {
    badge.textContent = `${count} robot${count !== 1 ? "s" : ""}`;
  }
}

function renderHistory(history) {
  updateRobotCount(history.length);
  const ul = document.getElementById("history-list");
  ul.innerHTML = history
    .map(
      (e) => `
    <li data-id="${e.id}" class="${e.id === selectedId ? "selected" : ""}">
      <div class="history-row">
        <div class="history-info">
          <span class="prompt-text">${escapeHtml(e.prompt)}</span>
          <span class="meta">${e.refined_from ? "↳ refined" : "new"}</span>
        </div>
        <button class="btn-delete" data-id="${e.id}" title="Delete this robot">✕</button>
      </div>
    </li>
  `
    )
    .join("");

  ul.querySelectorAll("li").forEach((li) => {
    li.addEventListener("click", (e) => {
      // Don't select when clicking the delete button
      if (e.target.classList.contains("btn-delete")) return;
      selectRobot(li.dataset.id);
    });
  });

  ul.querySelectorAll(".btn-delete").forEach((btn) => {
    btn.addEventListener("click", async (e) => {
      e.stopPropagation();
      const id = btn.dataset.id;
      try {
        await API.deleteRobot(id);
        if (selectedId === id) {
          selectedId = null;
          selectedUrdf = null;
          document.getElementById("preview-placeholder").style.display = "flex";
          document.getElementById("preview-canvas").style.display = "none";
          document.getElementById("source-panel").style.display = "none";
          document.getElementById("preview-prompt").textContent = "";
          updateRefineButton();
          updateSimulateButton();
          updateDownloadButton();
          updateViewSourceButton();
          updateSubmitButton();
          updateReplayButton();
          updateStressTestButton();
          updateExportButtons();
        }
        const { history: h } = await API.history();
        renderHistory(h);
        toast("Robot deleted");
      } catch (err) {
        toast("Failed to delete: " + err.message, "error");
      }
    });
  });
}

function escapeHtml(s) {
  const div = document.createElement("div");
  div.textContent = s;
  return div.innerHTML;
}

function selectRobot(id) {
  selectedId = id;
  document.querySelectorAll("#history-list li").forEach((li) => {
    li.classList.toggle("selected", li.dataset.id === id);
  });
  updateRefineButton();
  updateSimulateButton();
  updateDownloadButton();
  updateViewSourceButton();
  updateSubmitButton();
  updateReplayButton();
  updateStressTestButton();
  updateExportButtons();
  // Hide panels when switching robots
  document.getElementById("source-panel").style.display = "none";
  document.getElementById("score-display").style.display = "none";
  document.getElementById("sim-metrics").style.display = "none";
  document.getElementById("sanity-check-result").style.display = "none";
  document.getElementById("feedback-panel").style.display = "none";
  document.getElementById("replay-controls").style.display = "none";
  document.getElementById("stress-test-display").style.display = "none";
  stopReplay();
  loadRobotForPreview(id);
}

async function loadRobotForPreview(id) {
  const placeholder = document.getElementById("preview-placeholder");
  const canvas = document.getElementById("preview-canvas");
  const errEl = document.getElementById("preview-error");
  const promptEl = document.getElementById("preview-prompt");

  try {
    const data = await API.robot(id);
    promptEl.textContent = data.prompt;
    errEl.style.display = "none";
    selectedUrdf = data.urdf || null;

    if (data.urdf) {
      await renderUrdf(data.urdf, canvas, placeholder);
    } else {
      placeholder.style.display = "flex";
      canvas.style.display = "none";
    }
  } catch (e) {
    errEl.textContent = "Failed to load robot: " + e.message;
    errEl.style.display = "block";
    placeholder.style.display = "flex";
    canvas.style.display = "none";
  }
}

async function renderUrdf(urdfXml, canvasEl, placeholderEl) {
  try {
    const { Scene, PerspectiveCamera, WebGLRenderer, AmbientLight, DirectionalLight, Color } = await import(
      "https://esm.sh/three@0.160.0"
    );
    const urdfMod = await import("https://esm.sh/urdf-loader@0.15.0");
    const URDFLoader = urdfMod.default ?? urdfMod.URDFLoader;

    if (animationId) cancelAnimationFrame(animationId);

    const container = document.getElementById("preview-container");
    const width = container.clientWidth;
    const height = container.clientHeight;

    if (!scene) {
      scene = new Scene();
      scene.background = new Color(0x0f0f12);
      scene.add(new AmbientLight(0x404040, 1.5));
      scene.add(new DirectionalLight(0xffffff, 1).position.set(2, 5, 3));

      camera = new PerspectiveCamera(50, width / height, 0.1, 100);
      camera.position.set(2, 1.5, 2);
      camera.lookAt(0, 0, 0);

      renderer = new WebGLRenderer({ antialias: true, canvas: canvasEl, alpha: false });
      renderer.setSize(width, height);
      renderer.setPixelRatio(window.devicePixelRatio);
    }

    // Remove previous robot
    scene.children
      .filter((c) => c.type === "Group" || c.name === "urdf-robot")
      .forEach((c) => scene.remove(c));

    const loader = new URDFLoader();
    loader.packages = "";
    loader.workingPath = "";

    let robot;
    try {
      if (typeof loader.parse === "function") {
        const parser = new DOMParser();
        const xmlDoc = parser.parseFromString(urdfXml, "text/xml");
        robot = loader.parse(xmlDoc);
      } else {
        throw new Error("parse not available");
      }
    } catch (_) {
      const blob = new Blob([urdfXml], { type: "application/xml" });
      const url = URL.createObjectURL(blob);
      robot = await new Promise((resolve, reject) => {
        loader.load(url, (r) => {
          URL.revokeObjectURL(url);
          resolve(r);
        }, undefined, (err) => {
          URL.revokeObjectURL(url);
          reject(err);
        });
      });
    }

    robot.name = "urdf-robot";
    currentRobot = robot;
    scene.add(robot);
    placeholderEl.style.display = "none";
    canvasEl.style.display = "block";
    renderer.setSize(container.clientWidth, container.clientHeight);
    camera.aspect = container.clientWidth / container.clientHeight;
    camera.updateProjectionMatrix();

    function animate() {
      animationId = requestAnimationFrame(animate);
      if (robot.rotation) robot.rotation.y += 0.005;
      renderer.render(scene, camera);
    }
    animate();
  } catch (e) {
    placeholderEl.style.display = "flex";
    placeholderEl.textContent = "3D preview requires supported URDF (no external meshes)";
    canvasEl.style.display = "none";
  }
}

async function doGenerate() {
  const prompt = document.getElementById("prompt").value.trim();
  const outputFormat = document.getElementById("output-format").value;

  // Image-to-URDF mode
  if (uploadedImageFile) {
    return doImageToUrdf(prompt);
  }

  if (!prompt) {
    toast("Enter a description for your robot", "error");
    return;
  }

  setLoading(true);
  try {
    let res;
    if (outputFormat === "mjcf") {
      res = await API.generateMjcf(prompt);
      if (res.success) {
        // Download MJCF directly (not saved to history as URDF)
        downloadText(res.mjcf, `robot-${Date.now()}.xml`, "application/xml");
        toast("MJCF generated and downloaded!");
        setLoading(false);
        return;
      }
    } else if (outputFormat === "sdf") {
      res = await API.generateSdf(prompt);
      if (res.success) {
        downloadText(res.sdf, `robot-${Date.now()}.sdf`, "application/xml");
        toast("SDF generated and downloaded!");
        setLoading(false);
        return;
      }
    } else {
      res = await API.generate(prompt);
    }

    if (res.success) {
      toast("Robot generated!");
      const hist = await API.history();
      renderHistory(hist.history);
      if (res.id) selectRobot(res.id);
      document.getElementById("prompt").value = "";
    } else {
      toast(res.error || "Generation failed", "error");
    }
  } catch (e) {
    toast("Error: " + e.message, "error");
  } finally {
    setLoading(false);
  }
}

async function doImageToUrdf(additionalPrompt) {
  if (!uploadedImageFile) {
    toast("No image uploaded", "error");
    return;
  }

  setLoading(true);
  const btn = document.getElementById("btn-generate");
  btn.textContent = "Analyzing image...";

  try {
    const formData = new FormData();
    formData.append("image", uploadedImageFile);
    formData.append("additional_prompt", additionalPrompt || "");
    formData.append("mode", "two_stage");

    const res = await API.imageToUrdf(formData);

    if (res.success) {
      toast("Robot generated from image!");
      const hist = await API.history();
      renderHistory(hist.history);
      if (res.id) selectRobot(res.id);
      document.getElementById("prompt").value = "";
      clearImageUpload();

      // Show description if available
      if (res.description) {
        console.log("Vision analysis:", res.description);
      }
    } else {
      toast(res.error || "Image-to-URDF failed", "error");
    }
  } catch (e) {
    toast("Error: " + e.message, "error");
  } finally {
    setLoading(false);
  }
}

function downloadText(content, filename, mimeType = "text/plain") {
  const blob = new Blob([content], { type: mimeType });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
}

async function doExportMjcf() {
  if (!selectedId && !selectedUrdf) {
    toast("Select a robot first", "error");
    return;
  }

  const btn = document.getElementById("btn-export-mjcf");
  btn.disabled = true;
  btn.textContent = "Converting...";

  try {
    const res = await API.convertMjcf(selectedId, selectedUrdf);
    if (res.success) {
      downloadText(res.mjcf, `robot-${selectedId ? selectedId.slice(0, 8) : "export"}.xml`, "application/xml");
      toast("MJCF exported!");
    } else {
      toast(res.error || "Conversion failed", "error");
    }
  } catch (e) {
    toast("Error: " + e.message, "error");
  } finally {
    btn.disabled = false;
    btn.textContent = "Export MJCF";
    updateExportButtons();
  }
}

async function doExportSdf() {
  if (!selectedId && !selectedUrdf) {
    toast("Select a robot first", "error");
    return;
  }

  const btn = document.getElementById("btn-export-sdf");
  btn.disabled = true;
  btn.textContent = "Converting...";

  try {
    const res = await API.convertSdf(selectedId, selectedUrdf);
    if (res.success) {
      downloadText(res.sdf, `robot-${selectedId ? selectedId.slice(0, 8) : "export"}.sdf`, "application/xml");
      toast("SDF exported!");
    } else {
      toast(res.error || "Conversion failed", "error");
    }
  } catch (e) {
    toast("Error: " + e.message, "error");
  } finally {
    btn.disabled = false;
    btn.textContent = "Export SDF";
    updateExportButtons();
  }
}

function clearImageUpload() {
  uploadedImageFile = null;
  document.getElementById("image-upload").value = "";
  document.getElementById("image-preview-area").style.display = "none";
  document.getElementById("image-preview-thumb").src = "";
  const btn = document.getElementById("btn-generate");
  btn.textContent = "Generate URDF";
}

function handleImageUpload(file) {
  if (!file) return;
  uploadedImageFile = file;

  const reader = new FileReader();
  reader.onload = (e) => {
    const thumb = document.getElementById("image-preview-thumb");
    thumb.src = e.target.result;
    document.getElementById("image-preview-area").style.display = "flex";
  };
  reader.readAsDataURL(file);

  // Update generate button text
  const btn = document.getElementById("btn-generate");
  btn.textContent = "Generate from Image";
}

async function doSimulate() {
  if (!selectedId) {
    toast("Select a robot from history first", "error");
    return;
  }

  const terrainMode = document.getElementById("terrain-mode").value;
  const enableMotors = document.getElementById("chk-motors").checked;
  const btn = document.getElementById("btn-simulate");
  btn.disabled = true;
  btn.textContent = "Simulating…";

  try {
    const res = await API.simulate(selectedId, terrainMode, { enableMotors });
    if (res.success) {
      toast(`Simulation OK on ${terrainMode} terrain`);
    } else {
      toast(res.error || "Simulation failed", "error");
    }
    renderSanityCheck(res.sanity_check);
    renderSimMetrics(res.metrics, res.success);
    renderScoreDisplay(res.score);
    renderFeedbackSuggestions(res.feedback_suggestions || [], res.success);
  } catch (e) {
    toast("Error: " + e.message, "error");
  } finally {
    btn.disabled = false;
    btn.textContent = "Simulate";
    updateSimulateButton();
  }
}

function renderSanityCheck(sanity) {
  const el = document.getElementById("sanity-check-result");
  if (!sanity) {
    el.style.display = "none";
    return;
  }
  const passed = sanity.passed;
  const diag = sanity.diagnostics || {};
  const issues = diag.issues || [];
  const selfCollInit = diag.self_collisions_initial || [];
  const selfCollFinal = diag.self_collisions_final || [];

  let html = `<div class="sanity-header ${passed ? "sanity-pass" : "sanity-fail"}">`;
  html += `<span class="sanity-icon">${passed ? "&#10003;" : "&#10007;"}</span>`;
  html += `<span>Physics Sanity Check: <strong>${passed ? "PASSED" : "FAILED"}</strong></span>`;
  html += `</div>`;

  if (issues.length > 0) {
    html += `<ul class="sanity-issues">`;
    issues.forEach((issue) => {
      html += `<li>${escapeHtml(issue)}</li>`;
    });
    html += `</ul>`;
  }

  if (selfCollInit.length > 0) {
    html += `<div class="sanity-detail">Self-collisions at spawn: ${escapeHtml(selfCollInit.join(", "))}</div>`;
  }
  if (selfCollFinal.length > 0 && selfCollFinal.join(",") !== selfCollInit.join(",")) {
    html += `<div class="sanity-detail">Self-collisions after settling: ${escapeHtml(selfCollFinal.join(", "))}</div>`;
  }

  el.innerHTML = html;
  el.style.display = "block";
}

function renderFeedbackSuggestions(suggestions, simSuccess) {
  const panel = document.getElementById("feedback-panel");
  const container = document.getElementById("feedback-suggestions");

  if (!selectedId) {
    panel.style.display = "none";
    return;
  }

  container.innerHTML = "";
  suggestions.forEach((s) => {
    const chip = document.createElement("button");
    chip.className = "feedback-chip";
    chip.textContent = s.text;
    chip.title = s.prompt;
    chip.addEventListener("click", () => doFeedbackRefine(s.prompt));
    container.appendChild(chip);
  });

  panel.style.display = "block";
}

async function doFeedbackRefine(feedbackPrompt) {
  if (!selectedId) {
    toast("No robot selected", "error");
    return;
  }
  if (!feedbackPrompt || !feedbackPrompt.trim()) {
    toast("Enter some feedback first", "error");
    return;
  }

  setLoading(true);
  const btn = document.getElementById("btn-feedback-submit");
  btn.disabled = true;
  btn.textContent = "Refining…";

  try {
    const res = await API.refine(feedbackPrompt.trim(), selectedId);
    if (res.success) {
      toast("Robot updated with your feedback!");
      const hist = await API.history();
      renderHistory(hist.history);
      selectRobot(res.id);
      document.getElementById("feedback-input").value = "";
    } else {
      toast(res.error || "Refinement failed", "error");
    }
  } catch (e) {
    toast("Error: " + e.message, "error");
  } finally {
    btn.disabled = false;
    btn.textContent = "Apply Feedback";
    setLoading(false);
  }
}

async function doRefine() {
  const prompt = document.getElementById("prompt").value.trim();
  if (!prompt) {
    toast("Enter a refinement (e.g. make it heavier)", "error");
    return;
  }
  if (!selectedId) {
    toast("Select a robot from history first", "error");
    return;
  }

  setLoading(true);
  try {
    const res = await API.refine(prompt, selectedId);
    if (res.success) {
      toast("Robot refined!");
      const hist = await API.history();
      renderHistory(hist.history);
      selectRobot(res.id);
      document.getElementById("prompt").value = "";
    } else {
      toast(res.error || "Refinement failed", "error");
    }
  } catch (e) {
    toast("Error: " + e.message, "error");
  } finally {
    setLoading(false);
  }
}

function renderSimMetrics(metrics, success) {
  const el = document.getElementById("sim-metrics");
  if (!metrics) {
    el.style.display = "none";
    return;
  }
  const pos = metrics.final_position;
  const statusIcon = success ? "&#10003;" : "&#10007;";
  const statusClass = success ? "metric-ok" : "metric-fail";
  const uprightIcon = metrics.is_upright ? "&#10003;" : "&#10007;";
  const uprightClass = metrics.is_upright ? "metric-ok" : "metric-fail";

  el.innerHTML = `
    <div class="metrics-grid">
      <div class="metric">
        <span class="metric-label">Status</span>
        <span class="metric-value ${statusClass}">${statusIcon} ${success ? "Stable" : "Unstable"}</span>
      </div>
      <div class="metric">
        <span class="metric-label">Final Position</span>
        <span class="metric-value">(${pos.x}, ${pos.y}, ${pos.z})</span>
      </div>
      <div class="metric">
        <span class="metric-label">Distance</span>
        <span class="metric-value">${metrics.distance_from_origin}m</span>
      </div>
      <div class="metric">
        <span class="metric-label">Displacement</span>
        <span class="metric-value">${metrics.displacement}m</span>
      </div>
      <div class="metric">
        <span class="metric-label">Upright</span>
        <span class="metric-value ${uprightClass}">${uprightIcon} ${metrics.is_upright ? "Yes" : "No"} (${metrics.tilt_cos})</span>
      </div>
      <div class="metric">
        <span class="metric-label">Terrain</span>
        <span class="metric-value">${metrics.terrain_mode}</span>
      </div>
    </div>
  `;
  el.style.display = "block";
}

function doDownload() {
  if (!selectedUrdf) {
    toast("No robot selected to download", "error");
    return;
  }
  const blob = new Blob([selectedUrdf], { type: "application/xml" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = `robot-${selectedId ? selectedId.slice(0, 8) : "export"}.urdf`;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
  toast("URDF downloaded!");
}

function doViewSource() {
  const panel = document.getElementById("source-panel");
  const code = document.getElementById("source-code");
  if (panel.style.display === "none") {
    if (!selectedUrdf) {
      toast("No robot selected", "error");
      return;
    }
    code.textContent = selectedUrdf;
    panel.style.display = "block";
  } else {
    panel.style.display = "none";
  }
}

function scoreColor(score) {
  if (score >= 90) return "#22c55e";
  if (score >= 75) return "#4ade80";
  if (score >= 60) return "#facc15";
  if (score >= 40) return "#fb923c";
  return "#ef4444";
}

function scoreLabelClass(label) {
  return (label || "unstable").toLowerCase();
}

function renderScoreDisplay(score) {
  const el = document.getElementById("score-display");
  if (!score) {
    el.style.display = "none";
    return;
  }

  const color = scoreColor(score.final_score);
  const labelClass = scoreLabelClass(score.label);

  el.innerHTML = `
    <div class="score-big">
      <span class="score-number" style="color: ${color}">${score.final_score}</span>
      <span class="score-label-text" style="color: ${color}">${score.label}</span>
    </div>
    <div class="score-breakdown">
      <div class="score-component">
        <span class="sc-label">Stability</span>
        <div class="sc-bar"><div class="sc-bar-fill" style="width: ${score.stability_score}%; background: ${scoreColor(score.stability_score)}"></div></div>
        <span class="sc-value">${score.stability_score}</span>
      </div>
      <div class="score-component">
        <span class="sc-label">Uprightness</span>
        <div class="sc-bar"><div class="sc-bar-fill" style="width: ${score.uprightness_score}%; background: ${scoreColor(score.uprightness_score)}"></div></div>
        <span class="sc-value">${score.uprightness_score}</span>
      </div>
      <div class="score-component">
        <span class="sc-label">Grounding</span>
        <div class="sc-bar"><div class="sc-bar-fill" style="width: ${score.grounding_score}%; background: ${scoreColor(score.grounding_score)}"></div></div>
        <span class="sc-value">${score.grounding_score}</span>
      </div>
      <div class="score-component">
        <span class="sc-label">Terrain</span>
        <span class="sc-value">${score.terrain_mode} (${score.terrain_multiplier}x)</span>
      </div>
    </div>
  `;
  el.style.display = "flex";
}

async function loadLeaderboard() {
  const filter = document.getElementById("lb-terrain-filter").value;
  try {
    const { leaderboard } = await API.leaderboard(filter);
    renderLeaderboard(leaderboard);
  } catch (e) {
    console.warn("Could not load leaderboard:", e);
  }
}

function renderLeaderboard(entries) {
  const el = document.getElementById("leaderboard-list");
  if (!entries || entries.length === 0) {
    el.innerHTML = '<p class="leaderboard-empty">No scores yet. Simulate a robot and submit to leaderboard!</p>';
    return;
  }

  el.innerHTML = entries
    .map((e, i) => {
      const rank = i + 1;
      const rankClass = rank === 1 ? "gold" : rank === 2 ? "silver" : rank === 3 ? "bronze" : "";
      const labelClass = scoreLabelClass(e.label);
      return `
        <div class="lb-entry" data-robot-id="${e.robot_id}">
          <span class="lb-rank ${rankClass}">#${rank}</span>
          <div class="lb-info">
            <div class="lb-prompt">${escapeHtml(e.prompt)}</div>
            <div class="lb-terrain">${e.terrain_mode}</div>
          </div>
          <span class="lb-score-badge ${labelClass}">${e.final_score}</span>
        </div>
      `;
    })
    .join("");

  el.querySelectorAll(".lb-entry").forEach((entry) => {
    entry.addEventListener("click", () => {
      const robotId = entry.dataset.robotId;
      if (robotId) {
        // Switch to history tab and select the robot
        switchSidebarTab("history");
        selectRobot(robotId);
      }
    });
  });
}

async function doSubmitScore() {
  if (!selectedId) {
    toast("Select a robot from history first", "error");
    return;
  }

  const terrainMode = document.getElementById("terrain-mode").value;
  const btn = document.getElementById("btn-submit-score");
  btn.disabled = true;
  btn.textContent = "Submitting…";

  try {
    const res = await API.submitScore(selectedId, terrainMode);
    if (res.success) {
      toast(`Score ${res.entry.final_score} submitted to leaderboard!`);
      renderScoreDisplay(res.score);
      loadLeaderboard();
    } else {
      toast(res.error || "Submission failed", "error");
    }
  } catch (e) {
    toast("Error: " + e.message, "error");
  } finally {
    btn.disabled = false;
    btn.textContent = "Submit to Leaderboard";
    updateSubmitButton();
  }
}

function switchSidebarTab(tabName) {
  document.querySelectorAll(".sidebar-tab").forEach((t) => {
    t.classList.toggle("active", t.dataset.tab === tabName);
  });
  document.querySelectorAll(".sidebar-tab-content").forEach((c) => {
    c.style.display = "none";
    c.classList.remove("active");
  });
  const target = document.getElementById(`tab-${tabName}`);
  if (target) {
    target.style.display = "block";
    target.classList.add("active");
  }
  if (tabName === "leaderboard") {
    loadLeaderboard();
  }
}

// ---- Replay functions ----

function stopReplay() {
  replayPlaying = false;
  replayData = null;
  replayFrame = 0;
  if (replayAnimId) {
    cancelAnimationFrame(replayAnimId);
    replayAnimId = null;
  }
  const playBtn = document.getElementById("replay-play");
  if (playBtn) playBtn.textContent = "Play";
}

function startReplayAnimation() {
  if (!replayData || !currentRobot) return;
  const frames = replayData.frames;
  const fps = replayData.fps;
  const frameDuration = 1000 / fps;
  const scrubber = document.getElementById("replay-scrubber");
  const timeEl = document.getElementById("replay-time");
  const duration = replayData.duration;

  replayStartTime = performance.now() - (replayFrame * frameDuration);

  function tick() {
    if (!replayPlaying) return;
    const elapsed = performance.now() - replayStartTime;
    replayFrame = Math.floor(elapsed / frameDuration);

    if (replayFrame >= frames.length) {
      replayFrame = frames.length - 1;
      replayPlaying = false;
      document.getElementById("replay-play").textContent = "Play";
    }

    applyReplayFrame(frames[replayFrame]);
    scrubber.value = Math.round((replayFrame / Math.max(frames.length - 1, 1)) * 100);
    timeEl.textContent = `${(replayFrame / fps).toFixed(1)}s / ${duration.toFixed(1)}s`;

    if (replayPlaying) {
      replayAnimId = requestAnimationFrame(tick);
    }
  }
  tick();
}

function applyReplayFrame(frame) {
  if (!currentRobot || !frame) return;

  // Apply joint positions
  if (frame.joints && currentRobot.joints) {
    for (const [name, angle] of Object.entries(frame.joints)) {
      if (currentRobot.joints[name]) {
        currentRobot.joints[name].setJointValue(angle);
      }
    }
  }
}

async function doReplay() {
  if (!selectedId) {
    toast("Select a robot from history first", "error");
    return;
  }

  const terrainMode = document.getElementById("terrain-mode").value;
  const enableMotors = document.getElementById("chk-motors").checked;
  const btn = document.getElementById("btn-replay");
  btn.disabled = true;
  btn.textContent = "Recording…";

  try {
    const res = await API.simulate(selectedId, terrainMode, {
      enableMotors,
      recordTrajectory: true,
    });

    if (res.success || res.metrics) {
      renderSimMetrics(res.metrics, res.success);
      renderScoreDisplay(res.score);

      if (res.metrics && res.metrics.trajectory) {
        replayData = res.metrics.trajectory;
        replayFrame = 0;
        replayPlaying = false;

        const controls = document.getElementById("replay-controls");
        controls.style.display = "flex";
        document.getElementById("replay-scrubber").value = 0;
        document.getElementById("replay-time").textContent =
          `0.0s / ${replayData.duration.toFixed(1)}s`;
        document.getElementById("replay-play").textContent = "Play";

        toast(`Recorded ${replayData.frame_count} frames — press Play to animate`);
      } else {
        toast("No trajectory data returned", "error");
      }
    }
    if (!res.success) {
      toast(res.error || "Simulation failed", "error");
    }
  } catch (e) {
    toast("Error: " + e.message, "error");
  } finally {
    btn.disabled = false;
    btn.textContent = "Simulate & Replay";
    updateReplayButton();
  }
}

// ---- Stress test functions ----

function renderStressTest(data) {
  const el = document.getElementById("stress-test-display");
  if (!data) {
    el.style.display = "none";
    return;
  }

  const summary = data.summary;
  const scorecard = data.scorecard;
  const terrains = ["flat", "slope", "stairs", "uneven"];

  const summaryColor = scoreColor(summary.average_score);
  let cardsHtml = terrains.map((t) => {
    const r = scorecard[t];
    const icon = r.success ? "&#10003;" : "&#10007;";
    const cls = r.success ? "metric-ok" : "metric-fail";
    const score = r.score ? r.score.final_score : "—";
    const label = r.score ? r.score.label : "N/A";
    const color = r.score ? scoreColor(r.score.final_score) : "var(--text-muted)";
    return `
      <div class="stress-card">
        <div class="stress-card-header">
          <span class="stress-terrain">${t}</span>
          <span class="${cls}">${icon}</span>
        </div>
        <span class="stress-score" style="color: ${color}">${score}</span>
        <span class="stress-label" style="color: ${color}">${label}</span>
      </div>
    `;
  }).join("");

  el.innerHTML = `
    <div class="stress-summary">
      <div class="stress-avg">
        <span class="stress-avg-score" style="color: ${summaryColor}">${summary.average_score}</span>
        <span class="stress-avg-label" style="color: ${summaryColor}">${summary.label}</span>
      </div>
      <div class="stress-meta">
        ${summary.terrains_passed}/${summary.terrains_total} terrains passed
        ${summary.motors_enabled ? " (motors on)" : ""}
      </div>
    </div>
    <div class="stress-cards">${cardsHtml}</div>
  `;
  el.style.display = "block";
}

async function doStressTest() {
  if (!selectedId) {
    toast("Select a robot from history first", "error");
    return;
  }

  const enableMotors = document.getElementById("chk-motors").checked;
  const btn = document.getElementById("btn-stress-test");
  btn.disabled = true;
  btn.textContent = "Testing…";

  try {
    const res = await API.stressTest(selectedId, enableMotors);
    if (res.error) {
      toast(res.error, "error");
    } else {
      renderStressTest(res);
      toast(`Stress test: ${res.summary.terrains_passed}/${res.summary.terrains_total} passed, avg ${res.summary.average_score}`);
    }
  } catch (e) {
    toast("Error: " + e.message, "error");
  } finally {
    btn.disabled = false;
    btn.textContent = "Stress Test";
    updateStressTestButton();
  }
}

async function init() {
  document.getElementById("btn-generate").addEventListener("click", doGenerate);
  document.getElementById("btn-refine").addEventListener("click", doRefine);
  document.getElementById("btn-simulate").addEventListener("click", doSimulate);
  document.getElementById("btn-download").addEventListener("click", doDownload);
  document.getElementById("btn-view-source").addEventListener("click", doViewSource);
  document.getElementById("btn-submit-score").addEventListener("click", doSubmitScore);
  document.getElementById("btn-replay").addEventListener("click", doReplay);
  document.getElementById("btn-stress-test").addEventListener("click", doStressTest);
  document.getElementById("btn-export-mjcf").addEventListener("click", doExportMjcf);
  document.getElementById("btn-export-sdf").addEventListener("click", doExportSdf);

  // Image upload
  document.getElementById("image-upload").addEventListener("change", (e) => {
    const file = e.target.files[0];
    if (file) handleImageUpload(file);
  });
  document.getElementById("btn-clear-image").addEventListener("click", clearImageUpload);

  // Drag and drop on the image upload label
  const uploadLabel = document.querySelector(".image-upload-label");
  uploadLabel.addEventListener("dragover", (e) => {
    e.preventDefault();
    uploadLabel.classList.add("drag-over");
  });
  uploadLabel.addEventListener("dragleave", () => {
    uploadLabel.classList.remove("drag-over");
  });
  uploadLabel.addEventListener("drop", (e) => {
    e.preventDefault();
    uploadLabel.classList.remove("drag-over");
    const file = e.dataTransfer.files[0];
    if (file && file.type.startsWith("image/")) {
      handleImageUpload(file);
    }
  });

  // Output format selector updates button text
  document.getElementById("output-format").addEventListener("change", (e) => {
    const btn = document.getElementById("btn-generate");
    const format = e.target.value.toUpperCase();
    if (!uploadedImageFile) {
      btn.textContent = `Generate ${format}`;
    }
  });

  // Replay controls
  document.getElementById("replay-play").addEventListener("click", () => {
    if (!replayData) return;
    replayPlaying = !replayPlaying;
    document.getElementById("replay-play").textContent = replayPlaying ? "Pause" : "Play";
    if (replayPlaying) {
      if (replayFrame >= replayData.frames.length - 1) replayFrame = 0;
      startReplayAnimation();
    }
  });
  document.getElementById("replay-stop").addEventListener("click", () => {
    replayPlaying = false;
    replayFrame = 0;
    document.getElementById("replay-play").textContent = "Play";
    document.getElementById("replay-scrubber").value = 0;
    document.getElementById("replay-time").textContent =
      replayData ? `0.0s / ${replayData.duration.toFixed(1)}s` : "0.0s / 0.0s";
    if (replayData && replayData.frames.length > 0) {
      applyReplayFrame(replayData.frames[0]);
    }
  });
  document.getElementById("replay-scrubber").addEventListener("input", (e) => {
    if (!replayData) return;
    const pct = parseInt(e.target.value) / 100;
    replayFrame = Math.floor(pct * (replayData.frames.length - 1));
    applyReplayFrame(replayData.frames[replayFrame]);
    document.getElementById("replay-time").textContent =
      `${(replayFrame / replayData.fps).toFixed(1)}s / ${replayData.duration.toFixed(1)}s`;
    if (replayPlaying) {
      replayStartTime = performance.now() - (replayFrame * (1000 / replayData.fps));
    }
  });

  document.getElementById("btn-feedback-submit").addEventListener("click", () => {
    const input = document.getElementById("feedback-input");
    doFeedbackRefine(input.value);
  });

  // Sidebar tabs
  document.querySelectorAll(".sidebar-tab").forEach((tab) => {
    tab.addEventListener("click", () => switchSidebarTab(tab.dataset.tab));
  });

  // Leaderboard terrain filter
  document.getElementById("lb-terrain-filter").addEventListener("change", loadLeaderboard);

  document.querySelectorAll(".example-chip").forEach((chip) => {
    chip.addEventListener("click", () => {
      document.getElementById("prompt").value = chip.dataset.prompt;
      document.getElementById("prompt").focus();
    });
  });

  document.getElementById("prompt").addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      if (selectedId) doRefine();
      else doGenerate();
    }
  });

  try {
    const { history } = await API.history();
    renderHistory(history);
    if (history.length > 0 && !selectedId) {
      selectRobot(history[0].id);
    }
  } catch (e) {
    console.warn("Could not load history:", e);
  }

  window.addEventListener("resize", () => {
    if (renderer && camera) {
      const container = document.getElementById("preview-container");
      renderer.setSize(container.clientWidth, container.clientHeight);
      camera.aspect = container.clientWidth / container.clientHeight;
      camera.updateProjectionMatrix();
    }
  });
}

init();
