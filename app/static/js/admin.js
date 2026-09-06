(() => {
  "use strict";

  const state = { csrf: "", page: 1, totalPages: 1, selected: null };
  const byId = (id) => document.getElementById(id);
  const loginPanel = byId("admin-login-panel");
  const dashboard = byId("admin-dashboard");
  const statusLine = byId("admin-status");

  const setStatus = (message, error = false) => {
    statusLine.textContent = message;
    statusLine.classList.toggle("status-error", error);
  };

  const api = async (path, options = {}) => {
    const headers = { ...(options.headers || {}) };
    if (options.body) headers["Content-Type"] = "application/json";
    if (state.csrf && !["GET", "HEAD"].includes(options.method || "GET")) {
      headers["X-CSRF-Token"] = state.csrf;
    }
    const response = await fetch(`/api/v1/admin${path}`, { ...options, headers });
    if (response.status === 204) return null;
    const body = await response.json().catch(() => ({}));
    if (!response.ok) {
      const message = body.detail?.message || "管理操作失敗。";
      throw new Error(message);
    }
    return body;
  };

  const showDashboard = (session) => {
    state.csrf = session.csrf_token;
    loginPanel.hidden = true;
    dashboard.hidden = false;
    byId("admin-logout").hidden = false;
    loadList();
  };

  const showLogin = () => {
    state.csrf = "";
    state.selected = null;
    loginPanel.hidden = false;
    dashboard.hidden = true;
    byId("admin-logout").hidden = true;
  };

  const summaryButton = (item) => {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "admin-list-item";
    button.dataset.id = String(item.id);
    const labels = document.createElement("span");
    const title = document.createElement("strong");
    const subtitle = document.createElement("small");
    const badge = document.createElement("span");
    title.textContent = `#${String(item.pokedex_number).padStart(4, "0")} ${item.name_zh}`;
    subtitle.textContent = `${item.name_en} · Gen ${item.generation}`;
    badge.className = `status-badge ${item.is_active ? "status-active" : "status-inactive"}`;
    badge.textContent = item.is_active ? "啟用" : "停用";
    labels.append(title, subtitle);
    button.append(labels, badge);
    button.addEventListener("click", () => loadDetail(item.id));
    return button;
  };

  const loadList = async () => {
    try {
      const query = new URLSearchParams({
        page: String(state.page),
        page_size: "20",
        q: byId("admin-search").value.trim(),
      });
      const data = await api(`/pokemon?${query}`);
      state.totalPages = Math.max(1, data.total_pages);
      const container = byId("admin-list");
      container.replaceChildren(...data.items.map(summaryButton));
      if (!data.items.length) container.textContent = "沒有符合條件的資料。";
      byId("admin-page-label").textContent = `第 ${data.page} / ${state.totalPages} 頁`;
      byId("admin-prev").disabled = data.page <= 1;
      byId("admin-next").disabled = data.page >= state.totalPages;
      setStatus(`共 ${data.total} 筆寶可夢資料。`);
    } catch (error) {
      setStatus(error.message, true);
    }
  };

  const analysisDescription = (descriptions) =>
    descriptions.find((item) => item.description_kind === "analysis") || null;

  const primaryImage = (images) =>
    images.find((item) => item.is_primary) || images[0] || null;

  const loadDetail = async (pokemonId) => {
    try {
      const data = await api(`/pokemon/${pokemonId}`);
      state.selected = data;
      byId("admin-editor-title").textContent = `編輯 #${data.pokedex_number} ${data.name_zh}`;
      byId("admin-id").value = data.id;
      byId("admin-pokedex-number").value = data.pokedex_number;
      byId("admin-form-key").value = data.form_key;
      byId("admin-name-zh").value = data.name_zh;
      byId("admin-name-en").value = data.name_en;
      byId("admin-generation").value = data.generation;
      byId("admin-types").value = data.types.map((item) => item.code).join(",");
      byId("admin-category").value = data.category_zh || "";
      byId("admin-genus").value = data.genus || "";
      byId("admin-abilities").value = data.abilities || "";
      byId("admin-egg-groups").value = data.egg_groups || "";
      byId("admin-analysis").value = analysisDescription(data.descriptions)?.content || "";
      byId("admin-image-url").value = primaryImage(data.images)?.image_url || "";
      byId("admin-legendary").checked = data.is_legendary;
      byId("admin-mythical").checked = data.is_mythical;
      const toggle = byId("admin-toggle-active");
      toggle.hidden = false;
      toggle.textContent = data.is_active ? "停用" : "恢復";
      toggle.classList.toggle("button-danger", data.is_active);
      toggle.classList.toggle("button-success", !data.is_active);
      setStatus(`已載入 ${data.name_zh}。`);
    } catch (error) {
      setStatus(error.message, true);
    }
  };

  const resetEditor = () => {
    state.selected = null;
    byId("admin-editor").reset();
    byId("admin-id").value = "";
    byId("admin-form-key").value = "default";
    byId("admin-editor-title").textContent = "新增資料";
    byId("admin-toggle-active").hidden = true;
  };

  const normalizedTypes = () =>
    byId("admin-types").value.split(",").map((item) => item.trim().toLowerCase()).filter(Boolean);

  const editorPayload = () => {
    const selected = state.selected;
    const analysisText = byId("admin-analysis").value.trim();
    let descriptions;
    if (selected) {
      descriptions = selected.descriptions.map((item) => ({
        language_code: item.language_code,
        description_kind: item.description_kind,
        source_key: item.source_key,
        content: item.content,
        is_primary: item.is_primary,
      }));
      const current = descriptions.find((item) => item.description_kind === "analysis");
      if (current && analysisText) current.content = analysisText;
      if (current && !analysisText) descriptions = descriptions.filter((item) => item !== current);
      if (!current && analysisText) descriptions.push({
        language_code: "mul",
        description_kind: "analysis",
        source_key: "admin:analysis",
        content: analysisText,
        is_primary: true,
      });
    } else {
      descriptions = analysisText ? [{
        language_code: "mul",
        description_kind: "analysis",
        source_key: "admin:analysis",
        content: analysisText,
        is_primary: true,
      }] : [];
    }
    const imageUrl = byId("admin-image-url").value.trim();
    let images = selected ? selected.images.map((item) => ({
      image_kind: item.image_kind,
      image_url: item.image_url,
      is_primary: item.is_primary,
    })) : [];
    const currentImage = primaryImage(images);
    if (currentImage && imageUrl) currentImage.image_url = imageUrl;
    if (currentImage && !imageUrl) images = images.filter((item) => item !== currentImage);
    if (!currentImage && imageUrl) images.push({
      image_kind: "artwork",
      image_url: imageUrl,
      is_primary: true,
    });
    const payload = {
      pokedex_number: Number(byId("admin-pokedex-number").value),
      form_key: byId("admin-form-key").value.trim(),
      name_zh: byId("admin-name-zh").value.trim(),
      name_en: byId("admin-name-en").value.trim(),
      generation: Number(byId("admin-generation").value),
      type_codes: normalizedTypes(),
      category_zh: byId("admin-category").value.trim() || null,
      genus: byId("admin-genus").value.trim() || null,
      abilities: byId("admin-abilities").value.trim(),
      egg_groups: byId("admin-egg-groups").value.trim(),
      is_legendary: byId("admin-legendary").checked,
      is_mythical: byId("admin-mythical").checked,
      descriptions,
      images,
    };
    return payload;
  };

  byId("admin-login-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    try {
      const password = byId("admin-password").value;
      const session = await api("/session", {
        method: "POST",
        body: JSON.stringify({ password }),
      });
      byId("admin-password").value = "";
      showDashboard(session);
    } catch (error) {
      loginPanel.querySelector(".muted").textContent = error.message;
    }
  });

  byId("admin-editor").addEventListener("submit", async (event) => {
    event.preventDefault();
    try {
      const id = byId("admin-id").value;
      const saved = await api(id ? `/pokemon/${id}` : "/pokemon", {
        method: id ? "PATCH" : "POST",
        body: JSON.stringify(editorPayload()),
      });
      setStatus(`已儲存 ${saved.name_zh}。敘述異動需重新建立 embedding。`);
      state.selected = saved;
      await loadList();
      await loadDetail(saved.id);
    } catch (error) {
      setStatus(error.message, true);
    }
  });

  byId("admin-toggle-active").addEventListener("click", async () => {
    if (!state.selected) return;
    try {
      const action = state.selected.is_active ? "deactivate" : "restore";
      const updated = await api(`/pokemon/${state.selected.id}/${action}`, { method: "POST" });
      state.selected = updated;
      await loadList();
      await loadDetail(updated.id);
    } catch (error) {
      setStatus(error.message, true);
    }
  });

  byId("admin-search-form").addEventListener("submit", (event) => {
    event.preventDefault();
    state.page = 1;
    loadList();
  });
  byId("admin-prev").addEventListener("click", () => { state.page -= 1; loadList(); });
  byId("admin-next").addEventListener("click", () => { state.page += 1; loadList(); });
  byId("admin-new").addEventListener("click", resetEditor);
  byId("admin-cancel").addEventListener("click", resetEditor);
  byId("admin-logout").addEventListener("click", async () => {
    try { await api("/session", { method: "DELETE" }); } finally { showLogin(); }
  });

  api("/session").then(showDashboard).catch(showLogin);
})();
