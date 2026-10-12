(() => {
  "use strict";

  const state = {
    csrf: "",
    username: "",
    role: "",
    canWrite: false,
    page: 1,
    totalPages: 1,
    selected: null,
    reindexTimer: null,
    mbtiProfiles: [],
    mbtiRevision: null,
    mbtiSource: "bundled",
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
    state.username = session.username;
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
    Array.from(byId("evaluation-case-form").elements).forEach((control) => {
      control.disabled = !state.canWrite;
    });
    loadList();
    loadMbtiCatalog();
    loadEvaluation();
    loadFeedbackSummary();
  };

  const showLogin = () => {
    state.csrf = "";
    state.username = "";
    state.role = "";
    state.canWrite = false;
    state.selected = null;
    state.mbtiProfiles = [];
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

  const mbtiSection = (label, value) => {
    const section = document.createElement("section");
    const heading = document.createElement("h4");
    heading.textContent = label;
    section.append(heading);
    if (Array.isArray(value)) {
      const list = document.createElement("ul");
      value.forEach((item) => {
        const entry = document.createElement("li");
        entry.textContent = item;
        list.append(entry);
      });
      section.append(list);
    } else {
      const paragraph = document.createElement("p");
      paragraph.textContent = value;
      section.append(paragraph);
    }
    return section;
  };

  const renderMbtiProfile = () => {
    const profile = state.mbtiProfiles.find((item) => item.code === byId("admin-mbti-select").value);
    if (!profile) return;
    const heading = document.createElement("h3");
    heading.textContent = `${profile.code} · ${profile.name_zh}`;
    const summary = document.createElement("p");
    summary.textContent = profile.summary;
    const reviewed = document.createElement("p");
    reviewed.className = "muted";
    reviewed.textContent = `此類型查證日期：${profile.reviewed_at}`;
    const grid = document.createElement("div");
    grid.className = "mbti-detail-grid";
    [
      ["資訊處理", profile.information_style],
      ["決策風格", profile.decision_style],
      ["互動方式", profile.interaction_style],
      ["行動節奏", profile.action_style],
      ["優勢", profile.strengths],
      ["可能需要留意", profile.blind_spots],
      ["壓力下的可能傾向", profile.stress_pattern],
      ["成長建議", profile.growth_tips],
    ].forEach(([label, value]) => grid.append(mbtiSection(label, value)));
    byId("admin-mbti-details").replaceChildren(heading, summary, reviewed, grid);
    byId("admin-mbti-terms").replaceChildren(...profile.weighted_terms.map((item) => {
      const row = document.createElement("tr");
      const term = document.createElement("td");
      const weight = document.createElement("td");
      term.textContent = item.term;
      weight.textContent = String(item.weight);
      row.append(term, weight);
      return row;
    }));
    const sources = [];
    profile.source_urls.forEach((value) => {
      try {
        const url = new URL(value);
        if (url.protocol !== "https:") return;
        const entry = document.createElement("li");
        const link = document.createElement("a");
        link.href = url.href;
        link.textContent = url.hostname + url.pathname;
        link.target = "_blank";
        link.rel = "noopener noreferrer";
        entry.append(link);
        sources.push(entry);
      } catch (_) {
        // Skip malformed references instead of inserting an unsafe link.
      }
    });
    byId("admin-mbti-sources").replaceChildren(...sources);
    byId("admin-mbti-status").textContent = `正在查看 ${profile.code}，共 16 型。`;
    renderMbtiEditor(profile);
  };

  const mbtiEditFields = [
    ["name_zh", "中文名稱"], ["summary", "完整摘要"],
    ["information_style", "資訊處理"], ["decision_style", "決策風格"],
    ["interaction_style", "互動方式"], ["action_style", "行動節奏"],
    ["strengths", "優勢（每行一項）"], ["blind_spots", "盲點（每行一項）"],
    ["stress_pattern", "壓力傾向"], ["growth_tips", "成長建議（每行一項）"],
    ["source_urls", "HTTPS 研究來源（每行一個網址）"],
    ["reviewed_at", "查證日期"], ["weighted_terms", "行為詞與權重（每行：詞 | 權重）"],
  ];
  const mbtiListFields = new Set(["strengths", "blind_spots", "growth_tips", "source_urls"]);

  const renderMbtiEditor = (profile) => {
    const enabled = state.canWrite && state.mbtiSource === "database";
    byId("admin-mbti-editor").hidden = !enabled;
    byId("admin-mbti-edit-note").textContent = state.mbtiSource !== "database"
      ? "目前使用內建介紹；啟用資料庫來源後可由編輯者修改。"
      : enabled ? "儲存會發布完整新版介紹。若他人先儲存，請重新載入後再編輯。" : "目前帳號僅可檢視介紹。";
    const fields = byId("admin-mbti-fields");
    fields.replaceChildren();
    if (!enabled) return;
    mbtiEditFields.forEach(([key, label]) => {
      const wrapper = document.createElement("label");
      wrapper.className = "field";
      const caption = document.createElement("span");
      caption.textContent = label;
      const input = document.createElement(key === "reviewed_at" ? "input" : "textarea");
      input.name = key;
      input.required = true;
      if (key === "reviewed_at") input.type = "date";
      else input.rows = key === "weighted_terms" ? 10 : 4;
      if (key === "name_zh") input.maxLength = 40;
      input.value = key === "weighted_terms"
        ? profile[key].map((item) => `${item.term} | ${item.weight}`).join("\n")
        : Array.isArray(profile[key]) ? profile[key].join("\n") : profile[key];
      wrapper.append(caption, input);
      fields.append(wrapper);
    });
  };

  byId("admin-mbti-editor").addEventListener("submit", async (event) => {
    event.preventDefault();
    const profile = state.mbtiProfiles.find((item) => item.code === byId("admin-mbti-select").value);
    if (!profile || !state.canWrite || state.mbtiSource !== "database") return;
    const updated = { ...profile };
    const lines = (value) => value.split(/\r?\n/).map((line) => line.trim()).filter(Boolean);
    try {
      for (const [key] of mbtiEditFields) {
        const value = event.currentTarget.elements.namedItem(key).value.trim();
        if (key === "weighted_terms") {
          updated[key] = lines(value).map((line) => {
            const parts = line.split("|");
            const weight = Number(parts[1]);
            if (parts.length !== 2 || !parts[0].trim() || !Number.isFinite(weight) || weight <= 0 || weight > 5) {
              throw new Error("每個行為詞請使用「詞 | 權重」，權重需大於 0 且不超過 5。");
            }
            return { term: parts[0].trim(), weight };
          });
        } else updated[key] = mbtiListFields.has(key) ? lines(value) : value;
      }
      byId("admin-mbti-save").disabled = true;
      byId("admin-mbti-select").disabled = true;
      byId("admin-mbti-reload").disabled = true;
      await api(`/mbti/profiles/${encodeURIComponent(profile.code)}`, {
        method: "PUT", body: JSON.stringify({ expected_revision: state.mbtiRevision, profile: updated }),
      });
      await loadMbtiCatalog();
      setStatus(`已儲存 ${profile.code}，修訂 ${state.mbtiRevision}。`);
    } catch (error) {
      setStatus(error.message, true);
    } finally {
      byId("admin-mbti-save").disabled = false;
      byId("admin-mbti-select").disabled = false;
      byId("admin-mbti-reload").disabled = false;
    }
  });

  const loadMbtiCatalog = async () => {
    const select = byId("admin-mbti-select");
    const reload = byId("admin-mbti-reload");
    const previous = select.value;
    select.disabled = true;
    reload.disabled = true;
    byId("admin-mbti-status").textContent = "正在載入 MBTI 介紹…";
    try {
      const catalog = await api("/personality/traits");
      if (!Array.isArray(catalog.traits) || catalog.traits.length !== 16) {
        throw new Error("MBTI 介紹資料不完整，請重新載入。");
      }
      state.mbtiProfiles = catalog.traits;
      state.mbtiRevision = catalog.revision;
      state.mbtiSource = catalog.source;
      select.replaceChildren(...state.mbtiProfiles.map((profile) => {
        const option = document.createElement("option");
        option.value = profile.code;
        option.textContent = `${profile.code} · ${profile.name_zh}`;
        return option;
      }));
      if (state.mbtiProfiles.some((profile) => profile.code === previous)) select.value = previous;
      byId("admin-mbti-version").textContent =
        `版本 ${catalog.catalog_version} · 修訂 ${catalog.revision} · 查證日期 ${catalog.reviewed_at}`;
      select.disabled = false;
      renderMbtiProfile();
    } catch (error) {
      state.mbtiProfiles = [];
      byId("admin-mbti-editor").hidden = true;
      select.replaceChildren();
      byId("admin-mbti-details").replaceChildren();
      byId("admin-mbti-terms").replaceChildren();
      byId("admin-mbti-sources").replaceChildren();
      byId("admin-mbti-version").textContent = "";
      byId("admin-mbti-status").textContent = error.message;
    } finally {
      reload.disabled = false;
    }
  };

  const gradeSelect = (className, pokemonId, selectedGrade, disabled = false) => {
    const select = document.createElement("select");
    select.className = className;
    select.dataset.pokemonId = String(pokemonId);
    select.disabled = disabled;
    [
      ["", "尚未評分"],
      ["0", "0 · 不相關"],
      ["1", "1 · 部分相關"],
      ["2", "2 · 高度相關"],
      ["3", "3 · 核心標註"],
    ].forEach(([value, label]) => {
      const option = document.createElement("option");
      option.value = value;
      option.textContent = label;
      option.selected = selectedGrade !== null && String(selectedGrade) === value;
      select.append(option);
    });
    return select;
  };

  const collectJudgments = (container, selector) => Array.from(container.querySelectorAll(selector))
    .filter((control) => control.value !== "")
    .map((control) => ({
      pokemon_id: Number(control.dataset.pokemonId),
      grade: Number(control.value),
    }));

  const saveEvaluationJudgments = async (caseId, container, kind) => {
    const selector = kind === "annotations"
      ? ".evaluation-annotation-grade"
      : ".evaluation-adjudication-grade";
    const judgments = collectJudgments(container, selector);
    if (!judgments.length) {
      setStatus("請至少選擇一筆相關性評分。", true);
      return;
    }
    try {
      await api(`/evaluation/cases/${caseId}/${kind}`, {
        method: "PUT",
        body: JSON.stringify({ judgments }),
      });
      setStatus(kind === "annotations" ? "個人標註已儲存。" : "最終仲裁已儲存。");
      await loadEvaluation();
    } catch (error) {
      setStatus(error.message, true);
    }
  };

  const evaluationCaseCard = (item) => {
    const article = document.createElement("article");
    article.className = "evaluation-case";
    const heading = document.createElement("div");
    heading.className = "evaluation-case-heading";
    const title = document.createElement("div");
    const name = document.createElement("h3");
    const summary = document.createElement("p");
    const badge = document.createElement("span");
    name.textContent = item.case_key;
    summary.className = "muted";
    summary.textContent = `${item.dataset_version} · ${item.segment} · ${item.query}`;
    badge.className = `status-badge status-${item.status === "active" ? "active" : "inactive"}`;
    badge.textContent = item.status;
    title.append(name, summary);
    heading.append(title, badge);

    const candidateList = document.createElement("div");
    candidateList.className = "evaluation-candidate-list";
    item.candidates.forEach((candidate) => {
      const row = document.createElement("div");
      row.className = "evaluation-candidate";
      const label = document.createElement("strong");
      const mine = candidate.annotations.find((entry) => entry.annotator === state.username);
      const consensus = document.createElement("small");
      label.textContent = `#${String(candidate.pokedex_number).padStart(4, "0")} ${candidate.name_zh}`;
      consensus.textContent = candidate.annotations.length
        ? candidate.annotations.map((entry) => `${entry.annotator}: ${entry.grade}`).join(" · ")
        : "尚無標註";
      const annotation = gradeSelect(
        "evaluation-annotation-grade",
        candidate.pokemon_id,
        mine ? mine.grade : null,
        !state.canWrite,
      );
      annotation.setAttribute("aria-label", `${candidate.name_zh} 的個人標註`);
      const adjudication = gradeSelect(
        "evaluation-adjudication-grade",
        candidate.pokemon_id,
        candidate.adjudication ? candidate.adjudication.grade : null,
        state.role !== "admin",
      );
      adjudication.setAttribute("aria-label", `${candidate.name_zh} 的最終仲裁`);
      const identity = document.createElement("span");
      identity.append(label, consensus);
      row.append(identity, annotation, adjudication);
      candidateList.append(row);
    });

    const actions = document.createElement("div");
    actions.className = "editor-actions";
    if (state.canWrite) {
      const saveMine = document.createElement("button");
      saveMine.type = "button";
      saveMine.className = "button button-ghost";
      saveMine.textContent = "儲存我的標註";
      saveMine.addEventListener("click", () => saveEvaluationJudgments(item.id, article, "annotations"));
      actions.append(saveMine);
    }
    if (state.role === "admin") {
      const saveFinal = document.createElement("button");
      saveFinal.type = "button";
      saveFinal.className = "button button-ghost";
      saveFinal.textContent = "儲存仲裁";
      saveFinal.addEventListener("click", () => saveEvaluationJudgments(item.id, article, "adjudications"));
      actions.append(saveFinal);
      if (item.status !== "active") {
        const activate = document.createElement("button");
        activate.type = "button";
        activate.className = "button button-primary";
        activate.textContent = "發布至正式資料集";
        activate.addEventListener("click", async () => {
          try {
            await api(`/evaluation/cases/${item.id}/status`, {
              method: "PATCH",
              body: JSON.stringify({ status: "active" }),
            });
            setStatus("評估案例已發布。 ");
            await loadEvaluation();
          } catch (error) {
            setStatus(error.message, true);
          }
        });
        actions.append(activate);
      }
    }
    article.append(heading, candidateList, actions);
    return article;
  };

  const renderEvaluationQuality = (report) => {
    const overall = report.overall;
    const values = [
      ["案例", overall.case_count],
      ["雙人覆蓋", `${Math.round(overall.double_annotation_coverage * 100)}%`],
      ["衝突率", `${Math.round(overall.conflict_rate * 100)}%`],
      ["平均 QWK", overall.mean_quadratic_weighted_kappa ?? "尚無"],
    ];
    byId("evaluation-quality").replaceChildren(...values.map(([label, value]) => {
      const item = document.createElement("div");
      const term = document.createElement("small");
      const result = document.createElement("strong");
      term.textContent = label;
      result.textContent = String(value);
      item.append(term, result);
      return item;
    }));
  };

  async function loadEvaluation() {
    try {
      const [page, quality] = await Promise.all([
        api("/evaluation/cases?page_size=50"),
        api("/evaluation/quality"),
      ]);
      renderEvaluationQuality(quality);
      const container = byId("evaluation-cases");
      container.replaceChildren(...page.items.map(evaluationCaseCard));
      if (!page.items.length) container.textContent = "尚未建立多人標註案例。";
    } catch (error) {
      setStatus(error.message, true);
    }
  }

  async function loadFeedbackSummary() {
    try {
      const summary = await api("/feedback/summary");
      const values = [
        ["推薦收據", summary.total_impressions],
        ["已回饋收據", summary.rated_impressions],
        ["回應率", `${Math.round(summary.response_rate * 100)}%`],
        ["符合率", `${Math.round(summary.match_rate * 100)}%`],
      ];
      byId("feedback-summary").replaceChildren(...values.map(([label, value]) => {
        const item = document.createElement("div");
        const term = document.createElement("small");
        const result = document.createElement("strong");
        term.textContent = String(label);
        result.textContent = String(value);
        item.append(term, result);
        return item;
      }));
      const breakdown = byId("feedback-breakdown");
      breakdown.replaceChildren(...summary.by_rank.map((item) => {
        const row = document.createElement("p");
        row.textContent = `Rank ${item.rank} · ${item.feedback_count} 筆 · 符合率 ${Math.round(item.match_rate * 100)}%`;
        return row;
      }));
      if (!summary.by_rank.length) breakdown.textContent = "尚未收到推薦回饋。";
    } catch (error) {
      setStatus(error.message, true);
    }
  }

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

  byId("admin-mbti-select").addEventListener("change", renderMbtiProfile);
  byId("admin-mbti-reload").addEventListener("click", loadMbtiCatalog);

  byId("evaluation-case-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const pokemonIds = byId("evaluation-pokemon-ids").value
      .split(",")
      .map((value) => Number(value.trim()))
      .filter((value) => Number.isInteger(value) && value > 0);
    if (pokemonIds.length < 2 || new Set(pokemonIds).size !== pokemonIds.length) {
      setStatus("候選 Pokémon DB ID 至少需要兩筆且不可重複。", true);
      return;
    }
    try {
      await api("/evaluation/cases", {
        method: "POST",
        body: JSON.stringify({
          case_key: byId("evaluation-case-key").value.trim(),
          query: byId("evaluation-query").value.trim(),
          segment: byId("evaluation-segment").value.trim(),
          dataset_version: byId("evaluation-version").value.trim(),
          pokemon_ids: pokemonIds,
        }),
      });
      event.currentTarget.reset();
      byId("evaluation-segment").value = "general";
      setStatus("多人標註草稿已建立。 ");
      await loadEvaluation();
    } catch (error) {
      setStatus(error.message, true);
    }
  });
  byId("evaluation-refresh").addEventListener("click", loadEvaluation);
  byId("feedback-summary-refresh").addEventListener("click", loadFeedbackSummary);

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

  api("/session").then(showDashboard).catch(showLogin);
})();
