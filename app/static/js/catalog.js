(() => {
  "use strict";

  const API_ROOT = "/api/v1/pokemon";
  const TYPE_CODE = /^[a-z-]+$/;

  const text = (value, fallback = "—") => {
    if (value === null || value === undefined || value === "") return fallback;
    return String(value);
  };

  const element = (tagName, className, content) => {
    const node = document.createElement(tagName);
    if (className) node.className = className;
    if (content !== undefined) node.textContent = text(content, "");
    return node;
  };

  const dexNumber = (value) => `#${String(Number(value) || 0).padStart(4, "0")}`;

  const typeChip = (typeRecord) => {
    const chip = element("span", "type-chip", typeRecord?.name_zh || typeRecord?.name_en || "未知");
    const code = String(typeRecord?.code || "").toLowerCase();
    if (TYPE_CODE.test(code)) chip.dataset.type = code;
    return chip;
  };

  const appendRarityBadges = (container, pokemon) => {
    if (pokemon.is_legendary) container.append(element("span", "status-badge", "傳說"));
    if (pokemon.is_mythical) container.append(element("span", "status-badge mythical", "幻之"));
  };

  const apiErrorMessage = (payload, response) => {
    const detail = payload?.detail;
    if (typeof detail === "string") return detail;
    if (detail && typeof detail.message === "string") return detail.message;
    if (response.status === 404) return "找不到這筆寶可夢資料。";
    return `資料服務回應異常（${response.status}）。`;
  };

  const fetchJson = async (url, options = {}) => {
    const response = await fetch(url, {
      headers: { Accept: "application/json" },
      ...options,
    });
    let payload = null;
    try {
      payload = await response.json();
    } catch (_error) {
      // A non-JSON error is still surfaced with its HTTP status below.
    }
    if (!response.ok) throw new Error(apiErrorMessage(payload, response));
    return payload;
  };

  const createPokemonCard = (pokemon) => {
    const card = element("article", "pokemon-card");
    const link = element("a");
    link.href = `/pokemon/${encodeURIComponent(pokemon.id)}`;
    link.setAttribute("aria-label", `查看 ${text(pokemon.name_zh)} 的完整資料`);

    const visual = element("div", "card-image");
    visual.append(element("span", "image-placeholder", "?"));
    if (pokemon.image_url) {
      const image = document.createElement("img");
      image.src = pokemon.image_url;
      image.alt = `${text(pokemon.name_zh)} 圖像`;
      image.loading = "lazy";
      image.decoding = "async";
      image.addEventListener("error", () => image.remove(), { once: true });
      visual.append(image);
    }

    const body = element("div", "card-body");
    const topLine = element("div", "card-topline");
    topLine.append(element("p", "dex-number", dexNumber(pokemon.pokedex_number)));
    topLine.append(element("span", "generation-label", `第 ${text(pokemon.generation, "?")} 世代`));
    body.append(topLine);
    body.append(element("h3", "", pokemon.name_zh));
    body.append(element("p", "english-name", pokemon.name_en));

    const types = element("div", "type-list");
    types.setAttribute("aria-label", "屬性");
    (Array.isArray(pokemon.types) ? pokemon.types : []).forEach((item) => types.append(typeChip(item)));
    body.append(types);

    const badges = element("div", "badge-list");
    appendRarityBadges(badges, pokemon);
    if (badges.childElementCount) {
      badges.style.marginTop = "0.55rem";
      body.append(badges);
    }

    link.append(visual, body);
    card.append(link);
    return card;
  };

  const catalogPage = () => {
    const form = document.querySelector("#catalog-filters");
    const grid = document.querySelector("#catalog-grid");
    if (!form || !grid) return;

    const controls = {
      q: document.querySelector("#catalog-search"),
      type: document.querySelector("#catalog-type"),
      generation: document.querySelector("#catalog-generation"),
      rarity: document.querySelector("#catalog-rarity"),
    };
    const status = document.querySelector("#catalog-status");
    const empty = document.querySelector("#catalog-empty");
    const errorPanel = document.querySelector("#catalog-error");
    const errorMessage = document.querySelector("#catalog-error-message");
    const pagination = document.querySelector("#catalog-pagination");
    const pageNumbers = document.querySelector("#page-numbers");
    const previous = document.querySelector("#page-previous");
    const next = document.querySelector("#page-next");
    let activeController = null;
    let currentPage = 1;
    let totalPages = 1;

    const hydrateControls = () => {
      const params = new URLSearchParams(window.location.search);
      controls.q.value = params.get("q") || "";
      controls.type.value = params.get("type") || "";
      controls.generation.value = params.get("generation") || "";
      controls.rarity.value = params.get("is_legendary") === "true"
        ? "legendary"
        : params.get("is_mythical") === "true" ? "mythical" : "";
      currentPage = Math.max(1, Number.parseInt(params.get("page") || "1", 10) || 1);
    };

    const buildParams = (page = currentPage) => {
      const params = new URLSearchParams();
      const query = controls.q.value.trim();
      if (query) params.set("q", query);
      if (controls.type.value) params.set("type", controls.type.value);
      if (controls.generation.value) params.set("generation", controls.generation.value);
      if (controls.rarity.value === "legendary") params.set("is_legendary", "true");
      if (controls.rarity.value === "mythical") params.set("is_mythical", "true");
      params.set("page", String(page));
      params.set("page_size", "20");
      return params;
    };

    const setLocation = (params, replace = false) => {
      const visible = new URLSearchParams(params);
      visible.delete("page_size");
      if (visible.get("page") === "1") visible.delete("page");
      const suffix = visible.toString();
      const url = suffix ? `${window.location.pathname}?${suffix}` : window.location.pathname;
      window.history[replace ? "replaceState" : "pushState"]({}, "", url);
    };

    const pageWindow = (pageCount, selected) => {
      const start = Math.max(1, Math.min(selected - 2, pageCount - 4));
      const end = Math.min(pageCount, start + 4);
      return Array.from({ length: Math.max(0, end - start + 1) }, (_, index) => start + index);
    };

    const renderPagination = () => {
      pagination.hidden = totalPages <= 1;
      previous.disabled = currentPage <= 1;
      next.disabled = currentPage >= totalPages;
      pageNumbers.replaceChildren();
      pageWindow(totalPages, currentPage).forEach((page) => {
        const button = element("button", "page-number", page);
        button.type = "button";
        button.setAttribute("aria-label", `前往第 ${page} 頁`);
        if (page === currentPage) button.setAttribute("aria-current", "page");
        button.addEventListener("click", () => loadCatalog(page, true));
        pageNumbers.append(button);
      });
    };

    const showLoading = () => {
      grid.setAttribute("aria-busy", "true");
      grid.hidden = false;
      grid.replaceChildren();
      empty.hidden = true;
      errorPanel.hidden = true;
      pagination.hidden = true;
      status.textContent = "正在載入…";
      for (let index = 0; index < 8; index += 1) {
        const placeholder = element("div", "pokemon-card skeleton");
        placeholder.style.minHeight = "19rem";
        placeholder.setAttribute("aria-hidden", "true");
        grid.append(placeholder);
      }
    };

    const loadCatalog = async (page = currentPage, updateLocation = false) => {
      activeController?.abort();
      activeController = new AbortController();
      currentPage = Math.max(1, page);
      const params = buildParams(currentPage);
      if (updateLocation) setLocation(params);
      showLoading();

      try {
        const payload = await fetchJson(`${API_ROOT}?${params}`, { signal: activeController.signal });
        if (!payload || !Array.isArray(payload.items)) throw new Error("圖鑑資料格式不正確。");

        grid.replaceChildren(...payload.items.map(createPokemonCard));
        grid.setAttribute("aria-busy", "false");
        currentPage = Math.max(1, Number(payload.page) || currentPage);
        totalPages = Math.max(1, Number(payload.total_pages) || 1);
        const total = Math.max(0, Number(payload.total) || 0);
        status.textContent = total ? `共 ${total.toLocaleString("zh-Hant")} 筆・第 ${currentPage} / ${totalPages} 頁` : "沒有符合條件的資料";
        empty.hidden = payload.items.length !== 0;
        grid.hidden = payload.items.length === 0;
        renderPagination();
      } catch (error) {
        if (error.name === "AbortError") return;
        grid.replaceChildren();
        grid.hidden = true;
        grid.setAttribute("aria-busy", "false");
        errorPanel.hidden = false;
        errorMessage.textContent = error.message || "請稍後再試。";
        status.textContent = "載入失敗";
      }
    };

    const resetCatalog = () => {
      form.reset();
      currentPage = 1;
      loadCatalog(1, true);
    };

    form.addEventListener("submit", (event) => {
      event.preventDefault();
      loadCatalog(1, true);
    });
    [controls.type, controls.generation, controls.rarity].forEach((control) => {
      control.addEventListener("change", () => loadCatalog(1, true));
    });
    document.querySelector("#catalog-reset")?.addEventListener("click", resetCatalog);
    document.querySelector("#empty-reset")?.addEventListener("click", resetCatalog);
    document.querySelector("#catalog-retry")?.addEventListener("click", () => loadCatalog(currentPage));
    previous.addEventListener("click", () => loadCatalog(currentPage - 1, true));
    next.addEventListener("click", () => loadCatalog(currentPage + 1, true));
    window.addEventListener("popstate", () => {
      hydrateControls();
      loadCatalog(currentPage);
    });

    hydrateControls();
    setLocation(buildParams(currentPage), true);
    loadCatalog(currentPage);
  };

  const detailPage = () => {
    const root = document.querySelector("#detail-content");
    const pokemonId = document.body.dataset.pokemonId;
    if (!root || !pokemonId) return;

    const loading = document.querySelector("#detail-loading");
    const errorPanel = document.querySelector("#detail-error");
    const errorMessage = document.querySelector("#detail-error-message");

    const setContent = (selector, value, fallback = "—") => {
      const node = document.querySelector(selector);
      if (node) node.textContent = text(value, fallback);
    };

    const fallbackProfileValue = (value) => (
      value === null || value === undefined || value === "" ? "—" : "未收錄"
    );

    const localizedNames = (terms, fallback) => {
      const names = (Array.isArray(terms) ? terms : [])
        .map((item) => item?.name_zh)
        .filter(Boolean);
      return names.length ? names.join("、") : fallbackProfileValue(fallback);
    };

    const localizedName = (term, fallback) => (
      term?.name_zh || fallbackProfileValue(fallback)
    );

    const renderDescriptions = (descriptions) => {
      const container = document.querySelector("#detail-descriptions");
      container.replaceChildren();
      const available = (Array.isArray(descriptions) ? descriptions : []).filter(
        (item) => item?.content
          && item.description_kind === "description"
          && String(item.language_code || "").toLowerCase() === "zh-hant",
      );
      available.forEach((item) => {
        const card = element("article", "description-card");
        card.append(
          element("span", "description-meta", "中文圖鑑"),
        );
        const paragraphTexts = (Array.isArray(item.paragraphs)
          ? item.paragraphs
          : []
        ).filter((paragraph) => typeof paragraph === "string" && paragraph.trim());
        (paragraphTexts.length ? paragraphTexts : [item.content]).forEach(
          (paragraphText) => {
            const paragraph = element(
              "p",
              "description-paragraph",
              paragraphText,
            );
            if (item.language_code) paragraph.lang = item.language_code;
            card.append(paragraph);
          },
        );
        container.append(card);
      });
      if (!available.length) container.append(element("p", "english-name", "目前沒有可顯示的圖鑑敘述。"));
    };

    const renderProfile = (pokemon) => {
      const container = document.querySelector("#detail-profile");
      container.replaceChildren();
      const abilityDetails = Array.isArray(pokemon.ability_details)
        ? pokemon.ability_details
        : [];
      const rows = [
        ["世代", `第 ${text(pokemon.generation, "?")} 世代`],
        ["身高", pokemon.height_m == null ? "—" : `${pokemon.height_m} m`],
        ["體重", pokemon.weight_kg == null ? "—" : `${pokemon.weight_kg} kg`],
        [
          "特性",
          localizedNames(
            abilityDetails.filter((item) => !item.is_hidden),
            pokemon.abilities,
          ),
        ],
        [
          "隱藏特性",
          localizedNames(
            abilityDetails.filter((item) => item.is_hidden),
            pokemon.hidden_ability,
          ),
        ],
        ["棲息地", localizedName(pokemon.habitat_detail, pokemon.habitat)],
        ["蛋群", localizedNames(pokemon.egg_group_details, pokemon.egg_groups)],
        [
          "成長速度",
          localizedName(pokemon.growth_rate_detail, pokemon.growth_rate),
        ],
        ["捕獲率", pokemon.capture_rate],
      ];
      rows.forEach(([label, value]) => {
        const wrapper = element("div", "profile-row");
        wrapper.append(element("dt", "", label), element("dd", "", value));
        container.append(wrapper);
      });
    };

    const renderStats = (stats) => {
      const container = document.querySelector("#detail-stats");
      container.replaceChildren();
      const definitions = [
        ["HP", "hp"],
        ["攻擊", "attack"],
        ["防禦", "defense"],
        ["特攻", "sp_attack"],
        ["特防", "sp_defense"],
        ["速度", "speed"],
      ];
      definitions.forEach(([label, key]) => {
        const value = Number(stats?.[key]);
        const card = element("div", "stat-card");
        const heading = element("div", "stat-heading");
        heading.append(element("span", "", label), element("strong", "", Number.isFinite(value) ? value : "—"));
        const track = element("div", "stat-track");
        const fill = element("span");
        const percentage = Number.isFinite(value) ? Math.min(100, Math.max(0, (value / 255) * 100)) : 0;
        fill.style.setProperty("--value", `${percentage}%`);
        track.append(fill);
        card.append(heading, track);
        container.append(card);
      });
    };

    const renderDetail = (pokemon) => {
      document.title = `${text(pokemon.name_zh)}｜寶可夢圖鑑`;
      setContent("#detail-number", dexNumber(pokemon.pokedex_number));
      setContent("#detail-name", pokemon.name_zh);
      setContent("#detail-name-en", pokemon.name_en);
      const category = [pokemon.category_zh, pokemon.genus].filter(Boolean).join(" · ");
      setContent("#detail-category", category, "圖鑑分類未登錄");

      const types = document.querySelector("#detail-types");
      types.replaceChildren(...(Array.isArray(pokemon.types) ? pokemon.types.map(typeChip) : []));
      const badges = document.querySelector("#detail-badges");
      badges.replaceChildren();
      appendRarityBadges(badges, pokemon);
      if (pokemon.is_baby) badges.append(element("span", "status-badge mythical", "幼年"));

      const image = document.querySelector("#detail-image");
      const imageUrl = pokemon.image_url || (Array.isArray(pokemon.images)
        ? pokemon.images.find((item) => item?.is_primary)?.image_url || pokemon.images[0]?.image_url
        : null);
      if (imageUrl) {
        image.src = imageUrl;
        image.alt = `${text(pokemon.name_zh)} 圖像`;
        image.hidden = false;
        image.addEventListener("error", () => {
          image.hidden = true;
        }, { once: true });
      }

      renderDescriptions(pokemon.descriptions);
      renderProfile(pokemon);
      renderStats(pokemon.stats);
      loading.hidden = true;
      root.hidden = false;
    };

    fetchJson(`${API_ROOT}/${encodeURIComponent(pokemonId)}`)
      .then(renderDetail)
      .catch((error) => {
        loading.hidden = true;
        errorPanel.hidden = false;
        errorMessage.textContent = error.message || "資料可能已停用，或網址不正確。";
      });
  };

  if (document.body.dataset.page === "catalog") catalogPage();
  if (document.body.dataset.page === "detail") detailPage();
})();
