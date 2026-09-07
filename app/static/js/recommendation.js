(() => {
  "use strict";

  const form = document.querySelector("#recommendation-form");
  if (!form) return;

  const input = document.querySelector("#personality-text");
  const submit = document.querySelector("#recommend-submit");
  const counter = document.querySelector("#character-count");
  const loading = document.querySelector("#recommendation-loading");
  const errorPanel = document.querySelector("#recommendation-error");
  const errorMessage = document.querySelector("#recommendation-error-message");
  const results = document.querySelector("#recommendation-results");
  const grid = document.querySelector("#recommendation-grid");
  const algorithm = document.querySelector("#recommendation-algorithm");
  const publicTraitGrid = document.querySelector("#public-trait-grid");
  const publicTraitStatus = document.querySelector("#public-trait-status");
  const publicTraitRevision = document.querySelector("#public-trait-revision");
  let activeController = null;

  const element = (tagName, className, content) => {
    const node = document.createElement(tagName);
    if (className) node.className = className;
    if (content !== undefined) node.textContent = String(content);
    return node;
  };

  const percent = (value) => {
    const number = Number(value);
    return Number.isFinite(number)
      ? Math.round(Math.min(1, Math.max(0, number)) * 100)
      : 0;
  };

  const safeImageUrl = (value) => {
    if (!value) return null;
    try {
      const url = new URL(String(value), window.location.origin);
      return ["http:", "https:"].includes(url.protocol) ? url.href : null;
    } catch (_error) {
      return null;
    }
  };

  const officialArtworkUrl = (value) => {
    const pokedexNumber = Number(value);
    if (!Number.isInteger(pokedexNumber) || pokedexNumber < 1 || pokedexNumber > 1025) {
      return null;
    }
    return `https://raw.githubusercontent.com/PokeAPI/sprites/master/sprites/pokemon/other/official-artwork/${pokedexNumber}.png`;
  };

  const responseError = (payload, response) => {
    const message = payload?.detail?.message;
    if (typeof message === "string" && message) return message;
    if (response.status === 422) return "請輸入至少兩個字的具體個性描述。";
    if (response.status === 503) return "推薦服務仍在準備中，請稍後再試。";
    return `推薦服務回應異常（${response.status}）。`;
  };

  const scoreRow = (label, value, emphasized = false) => {
    const score = percent(value);
    const row = element("div", `score-row${emphasized ? " score-total" : ""}`);
    const heading = element("div", "score-heading");
    heading.append(element("span", "", label), element("strong", "", `${score}%`));
    const track = element("div", "score-track");
    const fill = element("span");
    fill.style.setProperty("--score", `${score}%`);
    track.append(fill);
    row.append(heading, track);
    return row;
  };

  const explanationCard = (explanation) => {
    const section = element("section", "explanation-card");
    const heading = element("div", "explanation-heading");
    heading.append(
      element("h4", "", explanation.used_fallback ? "契合分析" : "AI 契合分析"),
    );
    const providerLabels = {
      gemini: "Gemini 分析",
      openai: "OpenAI 分析",
      local: "本地分析",
    };
    const provider = providerLabels[explanation.provider] || "分析完成";
    heading.append(element("span", "explanation-provider", provider));
    section.append(heading, element("p", "", explanation.text));

    const citationCount = Array.isArray(explanation.citations)
      ? explanation.citations.length
      : 0;
    section.append(
      element(
        "p",
        "analysis-source",
        `已融合人格訊號與 ${citationCount} 段圖鑑依據`,
      ),
    );
    return section;
  };

  const resultCard = (result) => {
    const pokemon = result.pokemon;
    const card = element("article", `recommendation-card rank-${result.rank}`);
    const heading = element("div", "recommendation-card-heading");
    const rank = element("div", "rank-mark");
    rank.append(element("span", "", "RANK"), element("strong", "", result.rank));

    const identity = element("div", "recommendation-identity");
    const dex = String(pokemon.pokedex_number).padStart(4, "0");
    identity.append(element("p", "dex-number", `#${dex}`));
    const title = element("h3", "");
    const detailLink = element("a", "", pokemon.name_zh || "未命名寶可夢");
    detailLink.href = `/pokemon/${encodeURIComponent(pokemon.id)}`;
    title.append(detailLink);
    identity.append(title, element("p", "english-name", pokemon.name_en || "—"));

    const imageShell = element("div", "recommendation-image");
    imageShell.append(element("span", "image-placeholder", "?"));
    const fallbackImageUrl = officialArtworkUrl(pokemon.pokedex_number);
    const imageUrl = safeImageUrl(pokemon.image_url) || fallbackImageUrl;
    if (imageUrl) {
      const image = document.createElement("img");
      image.src = imageUrl;
      image.alt = `${pokemon.name_zh || "寶可夢"} 圖像`;
      image.loading = "lazy";
      image.decoding = "async";
      image.referrerPolicy = "no-referrer";
      image.addEventListener("error", () => {
        if (fallbackImageUrl && image.src !== fallbackImageUrl) {
          image.src = fallbackImageUrl;
          return;
        }
        image.remove();
      });
      imageShell.append(image);
    }
    heading.append(rank, identity, imageShell);

    const typeList = element("div", "recommendation-types");
    String(pokemon.types || "未知")
      .split(/[,，/]+/)
      .map((item) => item.trim())
      .filter(Boolean)
      .forEach((type) => typeList.append(element("span", "type-chip", type)));

    const scores = element("section", "score-panel");
    scores.setAttribute("aria-label", `${pokemon.name_zh} 匹配分數`);
    scores.append(
      scoreRow("總分", result.scores.total, true),
      scoreRow("語意分數", result.scores.semantic),
      scoreRow("人格分數", result.scores.personality),
    );

    card.append(heading, typeList, scores);
    if (result.explanation) card.append(explanationCard(result.explanation));
    return card;
  };

  const renderResults = (payload) => {
    if (
      !payload
      || !Array.isArray(payload.results)
      || payload.results.length !== 3
      || payload.results.some((item, index) => item.rank !== index + 1)
    ) {
      throw new Error("推薦結果格式不完整，請稍後再試。");
    }
    grid.replaceChildren(...payload.results.map(resultCard));
    algorithm.textContent = `演算法版本：${payload.algorithm_version || "unknown"}`;
    results.hidden = false;
    results.focus({ preventScroll: true });
    results.scrollIntoView({ behavior: "smooth", block: "start" });
  };

  const updateCounter = () => {
    counter.textContent = `${input.value.length} / 2000`;
  };

  const displayWeight = (value) => {
    const number = Number(value);
    if (!Number.isFinite(number)) return "—";
    return number.toLocaleString("zh-TW", { maximumFractionDigits: 2 });
  };

  const weightedTerm = (item) => {
    const chip = element("span", "public-weighted-term");
    chip.append(
      element("span", "", item.term),
      element("strong", "", `×${displayWeight(item.weight)}`),
    );
    return chip;
  };

  const publicTraitCard = (trait) => {
    const terms = Array.isArray(trait.weighted_terms)
      ? trait.weighted_terms.filter(
          (item) => item && typeof item.term === "string" && Number.isFinite(Number(item.weight)),
        )
      : [];
    const card = element("article", "public-trait-card");
    const heading = element("div", "public-trait-card-heading");
    heading.append(
      element("h3", "", trait.name_zh || "未命名特質"),
      element("span", "", `${terms.length} 個加權詞`),
    );

    const preview = element("div", "public-trait-preview");
    preview.append(...terms.slice(0, 3).map(weightedTerm));
    card.append(heading, preview);

    if (terms.length > 3) {
      const details = document.createElement("details");
      details.className = "public-trait-details";
      details.append(element("summary", "", "查看全部詞彙權重"));
      const allTerms = element("div", "public-trait-terms");
      allTerms.append(...terms.map(weightedTerm));
      details.append(allTerms);
      card.append(details);
    }
    return card;
  };

  const loadPublicTraits = async () => {
    if (!publicTraitGrid || !publicTraitStatus || !publicTraitRevision) return;
    try {
      const response = await fetch("/api/v1/personality/traits", {
        headers: { Accept: "application/json" },
      });
      const payload = await response.json().catch(() => ({}));
      if (!response.ok || !Array.isArray(payload.traits) || payload.traits.length === 0) {
        throw new Error("invalid personality vocabulary response");
      }
      publicTraitGrid.replaceChildren(...payload.traits.map(publicTraitCard));
      publicTraitGrid.hidden = false;
      publicTraitStatus.textContent = `目前啟用 ${payload.traits.length} 種人格特質；點開卡片可查看全部詞彙權重。`;
      publicTraitRevision.textContent = `SQL 詞庫 v${payload.revision || "—"}`;
    } catch (_error) {
      publicTraitGrid.replaceChildren();
      publicTraitGrid.hidden = true;
      publicTraitStatus.textContent = "目前無法載入人格詞庫；推薦功能仍可正常使用。";
      publicTraitStatus.classList.add("is-error");
      publicTraitRevision.textContent = "暫時無法讀取";
    }
  };

  const requestRecommendation = async () => {
    const text = input.value.trim();
    if (text.length < 2) {
      input.setCustomValidity("請輸入至少兩個字的個性描述。");
      input.reportValidity();
      return;
    }
    input.setCustomValidity("");
    activeController?.abort();
    activeController = new AbortController();
    submit.disabled = true;
    form.setAttribute("aria-busy", "true");
    loading.hidden = false;
    errorPanel.hidden = true;
    results.hidden = true;

    try {
      const response = await fetch("/api/v1/recommendations", {
        method: "POST",
        headers: {
          Accept: "application/json",
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          text,
          generate_explanation: true,
        }),
        signal: activeController.signal,
      });
      const payload = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(responseError(payload, response));
      renderResults(payload);
    } catch (error) {
      if (error.name === "AbortError") return;
      errorMessage.textContent = error.message || "請稍後再試。";
      errorPanel.hidden = false;
    } finally {
      loading.hidden = true;
      submit.disabled = false;
      form.setAttribute("aria-busy", "false");
    }
  };

  form.addEventListener("submit", (event) => {
    event.preventDefault();
    requestRecommendation();
  });
  input.addEventListener("input", () => {
    input.setCustomValidity("");
    updateCounter();
  });
  document.querySelector("#recommendation-retry")?.addEventListener(
    "click",
    requestRecommendation,
  );
  updateCounter();
  loadPublicTraits();
})();
