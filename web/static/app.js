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

  simulate: (robotId, terrainMode) =>
    fetch("/api/simulate", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ robot_id: robotId, terrain_mode: terrainMode }),
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
};

let selectedId = null;
let selectedUrdf = null;
let scene = null;
let renderer = null;
let camera = null;
let animationId = null;

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
  btn.textContent = loading ? "Generating…" : "Generate";
  if (loading) {
    btnRefine.disabled = true;
    document.getElementById("btn-simulate").disabled = true;
    document.getElementById("btn-download").disabled = true;
    document.getElementById("btn-view-source").disabled = true;
  } else {
    updateRefineButton();
    updateSimulateButton();
    updateDownloadButton();
    updateViewSourceButton();
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
  // Hide source panel when switching robots
  document.getElementById("source-panel").style.display = "none";
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
  if (!prompt) {
    toast("Enter a description for your robot", "error");
    return;
  }

  setLoading(true);
  try {
    const res = await API.generate(prompt);
    if (res.success) {
      toast("Robot generated!");
      const hist = await API.history();
      renderHistory(hist.history);
      selectRobot(res.id);
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

async function doSimulate() {
  if (!selectedId) {
    toast("Select a robot from history first", "error");
    return;
  }

  const terrainMode = document.getElementById("terrain-mode").value;
  const btn = document.getElementById("btn-simulate");
  btn.disabled = true;
  btn.textContent = "Simulating…";

  try {
    const res = await API.simulate(selectedId, terrainMode);
    if (res.success) {
      toast(`Simulation OK on ${terrainMode} terrain`);
    } else {
      toast(res.error || "Simulation failed", "error");
    }
    renderSimMetrics(res.metrics, res.success);
  } catch (e) {
    toast("Error: " + e.message, "error");
  } finally {
    btn.disabled = false;
    btn.textContent = "Simulate";
    updateSimulateButton();
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

async function init() {
  document.getElementById("btn-generate").addEventListener("click", doGenerate);
  document.getElementById("btn-refine").addEventListener("click", doRefine);
  document.getElementById("btn-simulate").addEventListener("click", doSimulate);
  document.getElementById("btn-download").addEventListener("click", doDownload);
  document.getElementById("btn-view-source").addEventListener("click", doViewSource);

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
