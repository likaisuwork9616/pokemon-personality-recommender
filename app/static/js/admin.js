(() => {
  "use strict";

  const state = {
    csrf: "",
    role: "",
    canWrite: false,
    page: 1,
    totalPages: 1,
    selected: null,
    reindexTimer: null,
    traits: [],
    vocabularyTraitCode: "",
    vocabularySnapshot: null,
  };
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
      const message = body.detail?.errors?.[0]?.message || body.detail?.message || "管理操作失敗。";
      throw new Error(message);
    }
    return body;
  };

  const showDashboard = (session) => {
    state.csrf = session.csrf_token;
    state.role = session.role;
    state.canWrite = session.permissions.includes("admin:write");
    loginPanel.hidden = true;
    dashboard.hidden = false;
    byId("admin-logout").hidden = false;
    byId("admin-identity").textContent = `${session.username} · ${session.role}`;
    byId("admin-audit-link").hidden = !session.permissions.includes("audit:read");
    byId("admin-new").hidden = !state.canWrite;
    byId("admin-reindex").hidden = !state.canWrite;
    Array.from(byId("admin-editor").elements).forEach((control) => {
      control.disabled = !state.canWrite;
    });
    Array.from(byId("vocabulary-trait-form").elements).forEach((control) => {
      control.disabled = !state.canWrite;
    });
    Array.from(byId("vocabulary-synonym-form").elements).forEach((control) => {
      control.disabled = !state.canWrite;
    });
    loadList();
    loadVocabulary();
  };

  const showLogin = () => {
    state.csrf = "";
    state.role = "";
    state.canWrite = false;
    state.selected = null;
    state.traits = [];
    state.vocabularyTraitCode = "";
    state.vocabularySnapshot = null;
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

  const renderIndexStatus = (data) => {
    const labels = {
      ready: "可用",
      stale: "等待重建",
      failed: "重建失敗，可重試",
      unindexed: "尚未建立",
    };
    byId("admin-index-panel").hidden = false;
    byId("admin-index-summary").textContent = `整體狀態：${labels[data.status] || data.status}`;
    const rows = data.sources.map((source) => {
      const item = document.createElement("li");
      const name = document.createElement("strong");
      const status = document.createElement("span");
      name.textContent = source.source_key;
      status.textContent = `${labels[source.status] || source.status} · ${source.ready_chunks}/${source.total_chunks} chunks`;
      item.append(name, status);
      if (source.last_error) {
        const error = document.createElement("small");
        error.textContent = source.last_error;
        item.append(error);
      }
      return item;
    });
    const list = byId("admin-index-sources");
    list.replaceChildren(...rows);
    if (!rows.length) list.textContent = "目前沒有可建立索引的敘述。";
  };

  const loadIndexStatus = async (pokemonId) => {
    try {
      renderIndexStatus(await api(`/pokemon/${pokemonId}/index-status`));
    } catch (error) {
      byId("admin-index-summary").textContent = error.message;
    }
  };

  const renderReindexProgress = (job) => {
    const panel = byId("admin-reindex-progress");
    const meter = byId("admin-reindex-meter");
    const total = Math.max(0, job.progress_total || 0);
    panel.hidden = false;
    meter.max = Math.max(1, total);
    meter.value = Math.min(job.progress_current || 0, meter.max);
    byId("admin-reindex-message").textContent =
      `${job.message || job.status} · ${job.progress_current}/${total} chunks`;
  };

  const pollReindexJob = async (jobId) => {
    const button = byId("admin-reindex");
    try {
      const job = await api(`/reindex-jobs/${jobId}`);
      renderReindexProgress(job);
      if (["queued", "running"].includes(job.status)) {
        state.reindexTimer = window.setTimeout(() => pollReindexJob(jobId), 1000);
        return;
      }
      button.disabled = false;
      if (job.index) renderIndexStatus(job.index);
      const failed = job.status === "failed";
      setStatus(
        failed
          ? `${job.message || "索引重建失敗"}${job.last_error ? `：${job.last_error}` : ""}`
          : `索引已更新，共建立 ${job.embedded} 個 embedding。`,
        failed,
      );
    } catch (error) {
      button.disabled = false;
      setStatus(error.message, true);
    }
  };

  const loadDetail = async (pokemonId) => {
    try {
      if (state.reindexTimer) window.clearTimeout(state.reindexTimer);
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
      toggle.hidden = !state.canWrite;
      toggle.textContent = data.is_active ? "停用" : "恢復";
      toggle.classList.toggle("button-danger", data.is_active);
      toggle.classList.toggle("button-success", !data.is_active);
      setStatus(`已載入 ${data.name_zh}。`);
      await loadIndexStatus(data.id);
    } catch (error) {
      setStatus(error.message, true);
    }
  };

  const resetEditor = () => {
    if (state.reindexTimer) window.clearTimeout(state.reindexTimer);
    state.selected = null;
    byId("admin-editor").reset();
    byId("admin-id").value = "";
    byId("admin-form-key").value = "default";
    byId("admin-editor-title").textContent = "新增資料";
    byId("admin-toggle-active").hidden = true;
    byId("admin-index-panel").hidden = true;
    byId("admin-reindex-progress").hidden = true;
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

  const selectedTrait = () =>
    state.traits.find((item) => item.code === byId("vocabulary-trait-select").value) || null;

  const normalizeText = (value) => String(value ?? "").trim();
  const normalizeTerm = (value) => normalizeText(value).normalize("NFKC");
  const normalizeWeight = (value) => {
    const parsed = Number(value);
    return Number.isFinite(parsed) ? parsed : null;
  };

  const synonymStateFromRow = (row) => ({
    originalTerm: normalizeTerm(row.dataset.originalTerm),
    term: normalizeTerm(row.querySelector('[data-synonym-field="term"]').value),
    languageCode: normalizeText(row.querySelector('[data-synonym-field="language"]').value),
    weight: normalizeWeight(row.querySelector('[data-synonym-field="weight"]').value),
    isActive: row.dataset.active === "true",
  });

  const captureVocabularyState = () => ({
    traitCode: state.vocabularyTraitCode,
    traitName: normalizeText(byId("vocabulary-trait-name").value),
    newSynonym: {
      term: normalizeTerm(byId("vocabulary-new-term").value),
      languageCode: normalizeText(byId("vocabulary-new-language").value),
      weight: normalizeWeight(byId("vocabulary-new-weight").value),
    },
    synonyms: Array.from(
      byId("vocabulary-synonyms").querySelectorAll("tr[data-original-term]"),
      synonymStateFromRow,
    ),
  });

  const serializedVocabularyState = () => JSON.stringify(captureVocabularyState());

  const isVocabularyDirty = () =>
    state.vocabularySnapshot !== null
    && serializedVocabularyState() !== JSON.stringify(state.vocabularySnapshot);

  const confirmVocabularyDiscard = (action) =>
    !isVocabularyDirty()
    || window.confirm(`人格詞庫尚有未儲存的變更。${action}會捨棄這些內容，確定要繼續嗎？`);

  const commitTraitSnapshot = () => {
    if (state.vocabularySnapshot) {
      state.vocabularySnapshot.traitName = normalizeText(byId("vocabulary-trait-name").value);
    }
  };

  const commitNewSynonymSnapshot = () => {
    if (state.vocabularySnapshot) {
      state.vocabularySnapshot.newSynonym = captureVocabularyState().newSynonym;
    }
  };

  const commitSynonymSnapshot = (previousTerm, row) => {
    if (!state.vocabularySnapshot) return;
    const previousKey = normalizeTerm(previousTerm);
    const index = state.vocabularySnapshot.synonyms.findIndex(
      (item) => item.originalTerm === previousKey,
    );
    const current = synonymStateFromRow(row);
    if (index === -1) state.vocabularySnapshot.synonyms.push(current);
    else state.vocabularySnapshot.synonyms[index] = current;
  };

  const replaceTraitSynonym = (trait, previousTerm, updated) => {
    const index = trait.synonyms.findIndex((item) => item.term === previousTerm);
    if (index === -1) trait.synonyms.push(updated);
    else trait.synonyms[index] = updated;
  };

  const applySynonymToRow = (row, synonym) => {
    row.dataset.originalTerm = synonym.term;
    row.dataset.active = String(synonym.is_active);
    row.querySelector('[data-synonym-field="term"]').value = synonym.term;
    row.querySelector('[data-synonym-field="language"]').value = synonym.language_code;
    row.querySelector('[data-synonym-field="weight"]').value = String(synonym.weight);
    row.querySelector('[data-synonym-status]').textContent = synonym.is_active ? "啟用" : "停用";
    row.querySelector('[data-synonym-toggle]').textContent = synonym.is_active ? "停用" : "恢復";
  };

  const setSynonymRowBusy = (row, busy) => {
    row.querySelectorAll("input, button").forEach((control) => {
      control.disabled = busy;
    });
  };

  const saveSynonymRow = async (row, trait, nextActive = null) => {
    const term = row.querySelector('[data-synonym-field="term"]');
    const language = row.querySelector('[data-synonym-field="language"]');
    const weight = row.querySelector('[data-synonym-field="weight"]');
    if (![term, language, weight].every((input) => input.reportValidity())) return;

    const previousTerm = row.dataset.originalTerm;
    const wasActive = row.dataset.active === "true";
    const payload = {
      original_term: previousTerm,
      term: term.value.trim(),
      language_code: language.value.trim(),
      weight: Number(weight.value),
    };
    if (nextActive !== null) payload.is_active = nextActive;

    setSynonymRowBusy(row, true);
    try {
      const updated = await api(
        `/personality/traits/${encodeURIComponent(trait.code)}/synonyms`,
        { method: "PATCH", body: JSON.stringify(payload) },
      );
      replaceTraitSynonym(trait, previousTerm, updated);
      applySynonymToRow(row, updated);
      commitSynonymSnapshot(previousTerm, row);
      setStatus(
        nextActive === null
          ? `已更新同義詞「${updated.term}」。`
          : `已${wasActive ? "停用" : "恢復"}「${updated.term}」。`,
      );
    } catch (error) {
      setStatus(error.message, true);
    } finally {
      setSynonymRowBusy(row, false);
    }
  };

  const createSynonymRow = (trait, synonym) => {
    const row = document.createElement("tr");
    const termCell = document.createElement("td");
    const languageCell = document.createElement("td");
    const weightCell = document.createElement("td");
    const statusCell = document.createElement("td");
    const actionCell = document.createElement("td");
    const term = document.createElement("input");
    const language = document.createElement("input");
    const weight = document.createElement("input");
    const save = document.createElement("button");
    const toggle = document.createElement("button");

    term.dataset.synonymField = "term";
    term.maxLength = 80;
    term.required = true;
    term.ariaLabel = "同義詞";
    language.dataset.synonymField = "language";
    language.maxLength = 10;
    language.required = true;
    language.ariaLabel = "語言代碼";
    weight.dataset.synonymField = "weight";
    weight.type = "number";
    weight.min = "0.01";
    weight.max = "5";
    weight.step = "0.01";
    weight.required = true;
    weight.ariaLabel = "同義詞權重";
    statusCell.dataset.synonymStatus = "";
    save.type = "button";
    toggle.type = "button";
    save.className = "button button-ghost button-small";
    toggle.className = "button button-ghost button-small";
    save.textContent = "儲存";
    toggle.dataset.synonymToggle = "";
    save.addEventListener("click", () => saveSynonymRow(row, trait));
    toggle.addEventListener("click", () => {
      saveSynonymRow(row, trait, row.dataset.active !== "true");
    });
    for (const control of [term, language, weight, save, toggle]) {
      control.disabled = !state.canWrite;
    }

    termCell.append(term);
    languageCell.append(language);
    weightCell.append(weight);
    actionCell.append(save, toggle);
    row.append(termCell, languageCell, weightCell, statusCell, actionCell);
    applySynonymToRow(row, synonym);
    return row;
  };

  const appendSynonymRow = (trait, synonym) => {
    const body = byId("vocabulary-synonyms");
    if (!body.querySelector("tr[data-original-term]")) body.replaceChildren();
    const row = createSynonymRow(trait, synonym);
    body.append(row);
    return row;
  };

  const renderVocabularyTrait = () => {
    const trait = selectedTrait();
    if (!trait) return;
    state.vocabularyTraitCode = trait.code;
    byId("vocabulary-trait-code").value = trait.code;
    byId("vocabulary-vector-index").value = String(trait.vector_index);
    byId("vocabulary-trait-name").value = trait.name_zh;
    byId("vocabulary-synonym-form").reset();
    const rows = trait.synonyms.map((synonym) => createSynonymRow(trait, synonym));
    const body = byId("vocabulary-synonyms");
    body.replaceChildren(...rows);
    if (!rows.length) {
      const row = document.createElement("tr");
      const cell = document.createElement("td");
      cell.colSpan = 5;
      cell.textContent = "目前沒有同義詞。";
      row.append(cell);
      body.append(row);
    }
    state.vocabularySnapshot = captureVocabularyState();
  };

  const loadVocabulary = async (selectedCode = "") => {
    if (!confirmVocabularyDiscard("重新載入人格詞庫")) return false;
    const stateBeforeRequest = serializedVocabularyState();
    try {
      const previous = selectedCode || state.vocabularyTraitCode || byId("vocabulary-trait-select").value;
      const traits = await api("/personality/traits");
      if (
        state.vocabularySnapshot !== null
        && serializedVocabularyState() !== stateBeforeRequest
        && !confirmVocabularyDiscard("重新載入人格詞庫")
      ) return false;
      state.traits = traits;
      const select = byId("vocabulary-trait-select");
      select.replaceChildren(...state.traits.map((trait) => {
        const option = document.createElement("option");
        option.value = trait.code;
        option.textContent = `${trait.vector_index}. ${trait.name_zh}`;
        return option;
      }));
      if (state.traits.some((trait) => trait.code === previous)) select.value = previous;
      renderVocabularyTrait();
      return true;
    } catch (error) {
      setStatus(error.message, true);
      return false;
    }
  };

  byId("admin-login-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    try {
      const password = byId("admin-password").value;
      const username = byId("admin-username").value.trim();
      const session = await api("/session", {
        method: "POST",
        body: JSON.stringify({ username, password }),
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

  byId("vocabulary-trait-select").addEventListener("change", (event) => {
    if (!confirmVocabularyDiscard("切換人格特質")) {
      event.target.value = state.vocabularyTraitCode;
      return;
    }
    renderVocabularyTrait();
  });
  byId("vocabulary-trait-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const trait = selectedTrait();
    if (!trait) return;
    const nameInput = byId("vocabulary-trait-name");
    if (!nameInput.reportValidity()) return;
    const submit = event.submitter;
    nameInput.readOnly = true;
    if (submit) submit.disabled = true;
    try {
      const updated = await api(`/personality/traits/${encodeURIComponent(trait.code)}`, {
        method: "PATCH",
        body: JSON.stringify({ name_zh: nameInput.value.trim() }),
      });
      trait.name_zh = updated.name_zh;
      nameInput.value = updated.name_zh;
      const option = Array.from(byId("vocabulary-trait-select").options)
        .find((item) => item.value === trait.code);
      if (option) option.textContent = `${trait.vector_index}. ${updated.name_zh}`;
      commitTraitSnapshot();
      setStatus("人格特質名稱已更新。");
    } catch (error) {
      setStatus(error.message, true);
    } finally {
      nameInput.readOnly = false;
      if (submit) submit.disabled = false;
    }
  });
  byId("vocabulary-synonym-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const trait = selectedTrait();
    if (!trait) return;
    const form = event.currentTarget;
    const controls = Array.from(form.querySelectorAll("input, button"));
    controls.forEach((control) => { control.disabled = true; });
    try {
      const term = byId("vocabulary-new-term").value.trim();
      const created = await api(`/personality/traits/${encodeURIComponent(trait.code)}/synonyms`, {
        method: "POST",
        body: JSON.stringify({
          term,
          language_code: byId("vocabulary-new-language").value.trim(),
          weight: Number(byId("vocabulary-new-weight").value),
        }),
      });
      trait.synonyms.push(created);
      byId("vocabulary-new-term").value = "";
      const row = appendSynonymRow(trait, created);
      commitSynonymSnapshot(created.term, row);
      commitNewSynonymSnapshot();
      setStatus(`已加入同義詞「${created.term || term}」。`);
    } catch (error) {
      setStatus(error.message, true);
    } finally {
      controls.forEach((control) => { control.disabled = false; });
    }
  });

  byId("admin-reindex").addEventListener("click", async () => {
    if (!state.selected) return;
    const button = byId("admin-reindex");
    button.disabled = true;
    setStatus("已送出背景重建工作，可在此查看進度。");
    try {
      const job = await api(`/pokemon/${state.selected.id}/reindex`, { method: "POST" });
      renderReindexProgress(job);
      pollReindexJob(job.id);
    } catch (error) {
      setStatus(error.message, true);
      button.disabled = false;
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
    if (!confirmVocabularyDiscard("登出後台")) return;
    const logout = byId("admin-logout");
    logout.disabled = true;
    dashboard.inert = true;
    try {
      await api("/session", { method: "DELETE" });
    } finally {
      dashboard.inert = false;
      logout.disabled = false;
      showLogin();
    }
  });

  window.addEventListener("beforeunload", (event) => {
    if (!isVocabularyDirty()) return;
    const message = "人格詞庫尚有未儲存的變更。離開頁面會捨棄這些內容。";
    event.preventDefault();
    event.returnValue = message;
    return message;
  });

  api("/session").then(showDashboard).catch(showLogin);
})();
