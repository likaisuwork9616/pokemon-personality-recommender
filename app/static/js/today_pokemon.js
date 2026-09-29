(() => {
  "use strict";

  const form = document.querySelector("#today-form");
  if (!form) return;

  const submit = document.querySelector("#today-submit");
  const loading = document.querySelector("#today-loading");
  const errorPanel = document.querySelector("#today-error");
  const errorMessage = document.querySelector("#today-error-message");
  const retry = document.querySelector("#today-retry");
  const results = document.querySelector("#today-results");
  const resultContent = document.querySelector("#today-result-content");
  const validity = document.querySelector("#today-validity");
  const zodiacValues = new Set([
    "aries", "taurus", "gemini", "cancer", "leo", "virgo",
    "libra", "scorpio", "sagittarius", "capricorn", "aquarius", "pisces",
  ]);
  let activeController = null;
  let lastZodiac = "";

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

  const safeImageUrl = (value) => {
    if (!value) return null;
    try {
      const url = new URL(String(value), window.location.origin);
      return ["http:", "https:"].includes(url.protocol) ? url.href : null;
    } catch (_error) {
      return null;
    }
  };

  const pokemonImage = (pokemon) => {
    const shell = element("div", "today-pokemon-image");
    shell.append(element("span", "image-placeholder", "?"));
    const source = safeImageUrl(pokemon.image_url);
    if (!source) return shell;
    const image = document.createElement("img");
    image.src = source;
    image.alt = `${text(pokemon.name_zh, "寶可夢")} 圖像`;
    image.loading = "lazy";
    image.decoding = "async";
    image.referrerPolicy = "no-referrer";
    image.addEventListener("error", () => image.remove(), { once: true });
    shell.append(image);
    return shell;
  };

  const chipList = (items, className = "today-chip-list") => {
    const list = element("div", className);
    (Array.isArray(items) ? items : []).forEach((item) => {
      list.append(element("span", "today-chip", item));
    });
    return list;
  };

  const calendarItem = (label, value) => {
    const item = element("div", "today-calendar-item");
    item.append(element("span", "", label), element("strong", "", value));
    return item;
  };

  const fortuneCard = (label, score) => {
    const bounded = Math.max(1, Math.min(5, Number(score) || 1));
    const card = element("article", "fortune-card");
    card.append(element("h4", "", label));
    const stars = element("p", "fortune-stars");
    stars.setAttribute("aria-label", `${bounded} / 5 星`);
    const visual = element("span", "", `${"★".repeat(bounded)}${"☆".repeat(5 - bounded)}`);
    visual.setAttribute("aria-hidden", "true");
    stars.append(visual);
    card.append(stars, element("strong", "", `${bounded} / 5`));
    return card;
  };

  const formatValidity = (value) => {
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return "";
    return new Intl.DateTimeFormat("zh-TW", {
      timeZone: "Asia/Taipei",
      hour: "2-digit",
      minute: "2-digit",
      hour12: false,
    }).format(date);
  };

  const providerLabel = (provider) => ({
    gemini: "Gemini 圖鑑分析",
    openai: "OpenAI 備援分析",
    local: "本地圖鑑分析",
  }[provider] || "圖鑑分析");

  const renderResult = (payload) => {
    const pokemon = payload.selection.pokemon;
    const calendar = payload.calendar;
    const zodiac = payload.zodiac;
    resultContent.replaceChildren();

    const calendarPanel = element("section", "today-calendar-panel card");
    calendarPanel.setAttribute("aria-label", "本次日期與時辰");
    calendarPanel.append(
      calendarItem("台北國曆", `${calendar.solar_date} ${calendar.weekday_zh}`),
      calendarItem("農曆", calendar.lunar_date_zh),
      calendarItem("節氣", `${calendar.solar_term}・${calendar.season}季`),
      calendarItem("時辰", `${calendar.time_ganzhi}時（${calendar.time_hm}）`),
    );

    const match = element("article", "today-match-card card");
    const visual = element("div", "today-match-visual");
    visual.append(pokemonImage(pokemon));
    const badge = element("span", "today-zodiac-badge", `${zodiac.symbol} ${zodiac.name_zh}`);
    visual.append(badge);

    const copy = element("div", "today-match-copy");
    copy.append(element("p", "dex-number", `#${String(Number(pokemon.pokedex_number) || 0).padStart(4, "0")}`));
    copy.append(element("h3", "", pokemon.name_zh));
    copy.append(element("p", "english-name", pokemon.name_en));
    copy.append(element("span", "type-chip", pokemon.types));

    const traitsHeading = element("h4", "", "今天為什麼是牠？");
    copy.append(traitsHeading);
    copy.append(chipList(zodiac.traits));
    copy.append(chipList(payload.calendar_signals, "today-chip-list calendar-chips"));

    const explanation = element("section", "today-explanation");
    const explanationHeading = element("div", "today-section-heading");
    explanationHeading.append(
      element("h4", "", providerLabel(payload.selection.explanation.provider)),
      element("span", "today-grounded-badge", "圖鑑證據限定"),
    );
    explanation.append(explanationHeading, element("p", "", payload.selection.explanation.text));
    copy.append(explanation);

    const detailLink = element("a", "button button-primary", "查看完整圖鑑");
    detailLink.href = `/pokemon/${encodeURIComponent(pokemon.id)}`;
    copy.append(detailLink);
    match.append(visual, copy);

    const evidenceSection = element("section", "today-evidence card");
    evidenceSection.append(element("h3", "", "本次圖鑑依據"));
    const evidenceList = element("div", "today-evidence-list");
    payload.selection.evidence.forEach((evidence, index) => {
      const item = element("article", "today-evidence-item");
      item.append(element("span", "", `依據 ${index + 1}`));
      item.append(element("p", "", evidence.text));
      evidenceList.append(item);
    });
    evidenceSection.append(evidenceList);

    const fortuneSection = element("section", "today-fortune card");
    const fortuneHeading = element("div", "today-section-heading");
    fortuneHeading.append(
      element("div", "", ""),
      element("span", "today-entertainment-badge", "娛樂內容"),
    );
    fortuneHeading.firstChild.append(
      element("p", "eyebrow", "TODAY'S FORTUNE"),
      element("h3", "", "今日四面向運勢"),
    );
    const fortuneGrid = element("div", "fortune-grid");
    fortuneGrid.append(
      fortuneCard("整體", payload.fortune.overall),
      fortuneCard("工作／學習", payload.fortune.work_study),
      fortuneCard("人際", payload.fortune.relationships),
      fortuneCard("活力", payload.fortune.vitality),
    );
    const guidance = element("div", "today-guidance");
    const action = element("div", "today-guidance-item");
    action.append(element("strong", "", "今日行動"), element("p", "", payload.fortune.action));
    const reminder = element("div", "today-guidance-item");
    reminder.append(element("strong", "", "溫柔提醒"), element("p", "", payload.fortune.reminder));
    guidance.append(action, reminder);
    fortuneSection.append(
      fortuneHeading,
      fortuneGrid,
      guidance,
      element("p", "today-disclaimer", payload.fortune.disclaimer),
    );

    resultContent.append(calendarPanel, match, evidenceSection, fortuneSection);
    validity.textContent = `結果有效至台北時間 ${formatValidity(payload.valid_until)}`;
  };

  const responseError = (payload, response) => {
    const message = payload?.detail?.message;
    if (typeof message === "string" && message) return message;
    return `服務回應異常（${response.status}），請稍後再試。`;
  };

  const setLocation = (zodiac) => {
    const url = new URL(window.location.href);
    url.searchParams.set("zodiac", zodiac);
    window.history.replaceState({}, "", url);
  };

  const setLoading = (isLoading) => {
    loading.hidden = !isLoading;
    submit.disabled = isLoading || !form.elements.zodiac.value;
    form.setAttribute("aria-busy", String(isLoading));
  };

  const loadTodayPokemon = async (zodiac, updateLocation = true) => {
    if (!zodiacValues.has(zodiac)) return;
    activeController?.abort();
    activeController = new AbortController();
    lastZodiac = zodiac;
    errorPanel.hidden = true;
    results.hidden = true;
    setLoading(true);
    if (updateLocation) setLocation(zodiac);
    try {
      const response = await fetch(`/api/v1/today-pokemon?zodiac=${encodeURIComponent(zodiac)}`, {
        headers: { Accept: "application/json" },
        signal: activeController.signal,
      });
      let payload = null;
      try {
        payload = await response.json();
      } catch (_error) {
        // A non-JSON response is handled with the status fallback below.
      }
      if (!response.ok) throw new Error(responseError(payload, response));
      renderResult(payload);
      results.hidden = false;
      results.focus({ preventScroll: true });
      results.scrollIntoView({ behavior: "smooth", block: "start" });
    } catch (error) {
      if (error.name === "AbortError") return;
      errorMessage.textContent = error instanceof Error ? error.message : "請稍後再試。";
      errorPanel.hidden = false;
    } finally {
      setLoading(false);
    }
  };

  form.addEventListener("change", () => {
    submit.disabled = !form.elements.zodiac.value;
  });
  form.addEventListener("submit", (event) => {
    event.preventDefault();
    loadTodayPokemon(form.elements.zodiac.value);
  });
  retry.addEventListener("click", () => loadTodayPokemon(lastZodiac));

  const initialZodiac = new URLSearchParams(window.location.search).get("zodiac") || "";
  if (zodiacValues.has(initialZodiac)) {
    const input = form.querySelector(`input[name="zodiac"][value="${initialZodiac}"]`);
    input.checked = true;
    submit.disabled = false;
    loadTodayPokemon(initialZodiac, false);
  }
})();
