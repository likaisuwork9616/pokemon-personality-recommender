(() => {
  "use strict";

  const form = document.querySelector("#recommendation-form");
  if (!form) return;

  const input = document.querySelector("#personality-text");
  const explainToggle = document.querySelector("#generate-explanation");
  const submit = document.querySelector("#recommend-submit");
  const counter = document.querySelector("#character-count");
  const loading = document.querySelector("#recommendation-loading");
  const errorPanel = document.querySelector("#recommendation-error");
  const errorMessage = document.querySelector("#recommendation-error-message");
  const results = document.querySelector("#recommendation-results");
  const grid = document.querySelector("#recommendation-grid");
  const algorithm = document.querySelector("#recommendation-algorithm");
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

  const evidenceKindLabels = Object.freeze({
    profile: "寶可夢人格摘要",
    description_zh: "中文圖鑑敘述",
    flavor_text_en: "英文圖鑑敘述",
    analysis: "人格分析",
    analysis_text: "人格分析",
  });

  const languageLabels = Object.freeze({
    "zh-Hant": "繁體中文",
    zh: "中文",
    en: "英文",
    mul: "多語混合",
  });

  const evidenceKindLabel = (value) => evidenceKindLabels[value] || "知識文件";
  const languageLabel = (value) => languageLabels[value] || "其他語言";

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

  const metadataItem = (label, value) => {
    const item = element("div", "evidence-meta-item");
    item.append(element("dt", "", label), element("dd", "", value));
    return item;
  };

  const evidenceCard = (evidence, index) => {
    const details = element("details", "evidence-item");
    details.id = `evidence-${evidence.evidence_id}`;
    const summary = element(
      "summary",
      "",
      `證據 ${index + 1} · ${evidenceKindLabel(evidence.source)}`,
    );
    const body = element("div", "evidence-body");
    body.append(element("p", "evidence-text", evidence.text));

    const metadata = element("dl", "evidence-metadata");
    metadata.append(metadataItem("文件類型", evidenceKindLabel(evidence.document_kind)));
    metadata.append(metadataItem("語言", languageLabel(evidence.language_code)));
    metadata.append(metadataItem("RRF", Number(evidence.rrf_score).toFixed(5)));
    if (evidence.dense_rank !== null) {
      metadata.append(
        metadataItem(
          "Dense",
          `#${evidence.dense_rank} · ${Number(evidence.dense_score).toFixed(4)}`,
        ),
      );
    }
    if (evidence.lexical_rank !== null) {
      metadata.append(
        metadataItem(
          "全文搜尋",
          `#${evidence.lexical_rank} · ${Number(evidence.lexical_score).toFixed(4)}`,
        ),
      );
    }
    body.append(metadata);

    const lineage = element("div", "evidence-lineage");
    lineage.append(element("span", "", "Evidence ID"));
    lineage.append(element("code", "", evidence.evidence_id));
    lineage.append(element("span", "", "Document ID"));
    lineage.append(element("code", "", evidence.document_id));
    lineage.append(element("span", "", "Chunk ID"));
    lineage.append(element("code", "", evidence.chunk_id));
    body.append(lineage);

    if (Array.isArray(evidence.matched_traits) && evidence.matched_traits.length) {
      const traits = element("div", "evidence-traits");
      evidence.matched_traits.forEach((trait) => {
        traits.append(element("span", "trait-chip", trait));
      });
      body.append(traits);
    }
    details.append(summary, body);
    return details;
  };

  const explanationCard = (explanation) => {
    const section = element("section", "explanation-card");
    const heading = element("div", "explanation-heading");
    heading.append(element("h4", "", "證據式推薦解釋"));
    const provider = explanation.used_fallback
      ? "本地 fallback"
      : String(explanation.provider).toUpperCase();
    heading.append(element("span", "explanation-provider", provider));
    section.append(heading, element("p", "", explanation.text));

    const citations = element("div", "citation-list");
    citations.append(element("span", "", "引用："));
    explanation.citations.forEach((citation) => {
      const link = element("a", "", citation);
      link.href = `#evidence-${citation}`;
      citations.append(link);
    });
    section.append(citations);
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

    const evidenceSection = element("section", "evidence-section");
    evidenceSection.append(element("h4", "", "匹配證據"));
    result.evidence.forEach((evidence, index) => {
      evidenceSection.append(evidenceCard(evidence, index));
    });

    card.append(heading, typeList, scores, evidenceSection);
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
          generate_explanation: explainToggle.checked,
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
  document.querySelectorAll("[data-example]").forEach((button) => {
    button.addEventListener("click", () => {
      input.value = button.dataset.example || "";
      updateCounter();
      input.focus();
    });
  });
  document.querySelector("#recommendation-retry")?.addEventListener(
    "click",
    requestRecommendation,
  );
  updateCounter();
})();
