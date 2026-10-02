"use strict";

const STORE_KEY = "radar.activeDataset";
const LABELS = {
  action: {
    create_dataset: "Создание набора",
    plan_and_collect: "Планирование",
    collect: "Сбор",
    list_records: "Витрина",
    export: "Экспорт",
    ask: "Вопрос по данным",
  },
  status: { ok: "Успешно", needs_review: "На модерации", error: "Ошибка" },
  confidence: { high: "Высокая", medium: "Средняя", low: "Низкая" },
  field: {
    rank: "Ранг",
    name: "Название",
    symbol: "Тикер",
    coin: "Монета",
    date: "Дата",
    base: "Базовая валюта",
    currency: "Валюта",
    price: "Цена",
    rate: "Котировка",
    market_cap: "Капитализация",
    volume_24h: "Объём за 24 ч",
    volume: "Объём",
    change_24h: "Изменение за 24 ч, %",
    change_7d: "Изменение за 7 д, %",
    updated_at: "Обновлено источником",
  },
};

const el = (id) => document.getElementById(id);
const state = { dataset: readActive(), plan: null, planQuery: "" };

function readActive() {
  try { return JSON.parse(localStorage.getItem(STORE_KEY)); } catch { return null; }
}

function h(tag, attrs = {}, ...children) {
  const node = document.createElement(tag);
  Object.entries(attrs).forEach(([key, value]) => {
    if (key === "onclick") node.addEventListener("click", value);
    else if (key === "class") node.className = value;
    else node.setAttribute(key, value);
  });
  children.flat().forEach((child) => node.append(child instanceof Node ? child : String(child ?? "")));
  return node;
}

async function http(path, { method = "GET", body } = {}) {
  try {
    const response = await fetch(path, {
      method,
      headers: body ? { "Content-Type": "application/json" } : {},
      body: body ? JSON.stringify(body) : undefined,
    });
    const text = await response.text();
    let data = null;
    try { data = text ? JSON.parse(text) : null; } catch { data = { detail: text }; }
    return { ok: response.ok, status: response.status, data };
  } catch {
    return { ok: false, status: 0, data: { detail: "Сервер недоступен" } };
  }
}

function problem(res) {
  const d = res.data || {};
  if (typeof d.detail === "string") return d.detail;
  if (Array.isArray(d.detail)) return d.detail.map((x) => x.msg).join("; ");
  return d.reason || `HTTP ${res.status}`;
}

function message(id, text, kind = "ok") {
  const node = el(id);
  node.hidden = !text;
  node.textContent = text || "";
  node.className = "msg msg-" + kind;
}

function fmtTime(iso) {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleString("ru-RU", { day: "2-digit", month: "2-digit", year: "numeric", hour: "2-digit", minute: "2-digit", second: "2-digit" });
}

function fmtValue(value) {
  if (value === null || value === undefined || value === "") return "—";
  if (typeof value === "number") return value.toLocaleString("ru-RU", { maximumFractionDigits: 6 });
  return String(value);
}

function short(text, size) {
  const s = String(text ?? "");
  return s.length > size ? s.slice(0, size) + "…" : s;
}

function fillList(id, items) {
  el(id).replaceChildren(...(items || []).map((t) => h("li", {}, t)));
}

// ---------------- навигация ----------------

const views = {
  datasets: loadDatasets,
  collect: renderCollect,
  showcase: loadRecords,
  audit: loadAudit,
};

function route() {
  const view = views[location.hash.slice(1)] ? location.hash.slice(1) : "datasets";
  document.querySelectorAll("[data-section]").forEach((s) => { s.hidden = s.dataset.section !== view; });
  document.querySelectorAll(".nav a").forEach((a) => a.classList.toggle("active", a.dataset.view === view));
  views[view]();
}

function setActive(dataset) {
  state.dataset = dataset ? { dataset_id: dataset.dataset_id, name: dataset.name, source: dataset.source } : null;
  if (state.dataset) localStorage.setItem(STORE_KEY, JSON.stringify(state.dataset));
  else localStorage.removeItem(STORE_KEY);
  state.plan = null;
  el("plan").hidden = el("review").hidden = el("result").hidden = true;
  renderActive();
}

function renderActive() {
  const d = state.dataset;
  const tag = d ? `${d.name} · ${d.source}` : "Набор не выбран";
  el("collect-target").textContent = tag;
  el("showcase-target").textContent = tag;
}

async function loadHealth() {
  const res = await http("/health");
  const box = el("service-status");
  if (!res.ok) {
    box.replaceChildren(h("div", { class: "st st-bad" }, "API недоступен"));
    return;
  }
  const s = res.data;
  box.replaceChildren(
    h("div", { class: "st " + (s.llm_configured ? "st-ok" : "st-bad") }, s.llm_configured ? `LLM: ${s.llm_model}, t=${s.llm_temperature}` : "LLM: не настроена"),
    h("div", { class: "st st-ok" }, "CoinGecko"),
    h("div", { class: "st " + (s.exchangerate_configured ? "st-ok" : "st-bad") }, "exchangerate.host" + (s.exchangerate_configured ? "" : ": нет ключа")),
    h("div", { class: "st muted" }, "v" + s.version),
  );
  const issues = [];
  if (!s.llm_configured) issues.push("OPENAI_API_KEY");
  if (!s.exchangerate_configured) issues.push("EXCHANGERATE_API_KEY");
  const alert = el("alert");
  alert.hidden = !issues.length;
  alert.textContent = issues.length ? "Не заданы переменные окружения: " + issues.join(", ") : "";
}

async function refreshBadge() {
  const res = await http("/audit/summary");
  if (!res.ok) return;
  const badge = el("nav-review");
  badge.hidden = !res.data.needs_review;
  badge.textContent = res.data.needs_review;
}

// ---------------- наборы данных ----------------

async function loadDatasets() {
  const res = await http("/datasets");
  if (!res.ok) return message("dataset-msg", problem(res), "bad");
  const rows = res.data;
  if (state.dataset && !rows.some((r) => r.dataset_id === state.dataset.dataset_id)) setActive(null);
  el("dataset-empty").hidden = rows.length > 0;
  el("dataset-rows").replaceChildren(...rows.map((r) => {
    const active = state.dataset && state.dataset.dataset_id === r.dataset_id;
    return h("tr", { class: active ? "selected" : "" },
      h("td", { class: "strong" }, r.name),
      h("td", {}, r.source),
      h("td", { class: "nowrap" }, fmtTime(r.created_at)),
      h("td", { class: "mono dim", title: r.dataset_id }, r.dataset_id.slice(0, 8)),
      h("td", { class: "num" }, r.records_count),
      h("td", {}, fmtTime(r.last_collected_at)),
      h("td", { class: "right" }, h("button", {
        type: "button",
        class: "btn btn-sm" + (active ? " btn-active" : ""),
        onclick: () => { setActive(r); loadDatasets(); },
      }, active ? "Выбран" : "Выбрать")),
    );
  }));
}

el("dataset-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const form = event.currentTarget;
  const body = { name: form.name.value.trim(), source: form.source.value };
  const res = await http("/datasets", { method: "POST", body });
  if (!res.ok) return message("dataset-msg", problem(res), "bad");
  form.name.value = "";
  setActive({ ...body, dataset_id: res.data.dataset_id });
  message("dataset-msg", `Создан набор «${body.name}»`);
  loadDatasets();
});

// ---------------- сбор ----------------

function renderCollect() {
  renderActive();
  syncCollect();
}

function syncCollect() {
  const btn = el("btn-collect");
  const status = el("collect-state");
  const sameQuery = state.plan && el("query").value.trim() === state.planQuery;
  let text = "";
  if (!state.dataset) text = "Набор не выбран";
  else if (!state.plan) text = "План не построен";
  else if (!sameQuery) text = "Запрос изменён после планирования";
  else if (state.plan.needs_review) text = "Сбор заблокирован до уточнения запроса";
  btn.disabled = Boolean(text);
  status.textContent = text;
  status.className = state.plan && state.plan.needs_review && sameQuery ? "c-warn" : "muted";
}

el("query").addEventListener("input", syncCollect);

el("btn-plan").addEventListener("click", async () => {
  const query = el("query").value.trim();
  const btn = el("btn-plan");
  btn.disabled = true;
  el("result").hidden = true;
  const body = { query };
  if (state.dataset) body.dataset_id = state.dataset.dataset_id;
  const res = await http("/ai/plan_and_collect", { method: "POST", body });
  btn.disabled = false;
  if (!res.ok) return message("collect-msg", problem(res), "bad");
  message("collect-msg", "");
  state.plan = res.data;
  state.planQuery = query;
  renderPlan(res.data);
  syncCollect();
  refreshBadge();
});

function renderPlan(p) {
  el("plan").hidden = false;
  el("p-confidence").textContent = LABELS.confidence[p.confidence] || p.confidence;
  el("p-confidence").className = "conf-" + p.confidence;
  el("p-review").textContent = p.needs_review ? "Заблокирован" : "Допущен";
  el("p-review").className = p.needs_review ? "c-warn" : "c-ok";
  fillList("p-steps", p.plan_steps);
  el("review").hidden = !p.needs_review;
  el("review-reason").textContent = p.reason || "";
  fillList("review-hints", p.hints);
}

el("btn-collect").addEventListener("click", async () => {
  if (el("btn-collect").disabled) return;
  const btn = el("btn-collect");
  btn.disabled = true;
  const res = await http(`/datasets/${state.dataset.dataset_id}/collect`, { method: "POST", body: { query: state.planQuery } });
  if (res.status === 422 && res.data && res.data.status === "needs_review") {
    state.plan = { ...state.plan, needs_review: true, confidence: "low", reason: res.data.reason, hints: res.data.hints };
    renderPlan(state.plan);
  } else if (!res.ok) {
    message("collect-msg", problem(res), "bad");
  } else {
    message("collect-msg", "");
    el("result").hidden = false;
    el("result-text").textContent = `Сохранено записей: ${res.data.records_saved}`;
  }
  syncCollect();
  refreshBadge();
});

// ---------------- витрина ----------------

async function loadRecords() {
  renderActive();
  const head = el("record-head");
  const body = el("record-rows");
  head.replaceChildren();
  body.replaceChildren();
  el("answer").hidden = true;
  if (!state.dataset) {
    el("record-empty").hidden = false;
    return message("showcase-msg", "Набор не выбран", "bad");
  }
  const res = await http(`/datasets/${state.dataset.dataset_id}/records?limit=${el("limit").value}`);
  if (!res.ok) return message("showcase-msg", problem(res), "bad");
  message("showcase-msg", "");
  const rows = res.data;
  el("record-empty").hidden = rows.length > 0;
  const fields = [...new Set(rows.flatMap((r) => Object.keys(r.record_json)))];
  head.append(h("tr", {},
    h("th", { class: "num" }, "№"), h("th", {}, "Время сбора"), h("th", {}, "ID"), h("th", {}, "Источник"),
    fields.map((f) => h("th", {}, f)), h("th", {}, "record_json"), h("th", {}),
  ));
  body.append(...rows.map((r) => h("tr", {},
    h("td", { class: "num" }, r.id),
    h("td", {}, fmtTime(r.created_at)),
    h("td", { class: "mono dim", title: r.dataset_id }, r.dataset_id.slice(0, 8)),
    h("td", {}, r.source),
    fields.map((f) => h("td", { class: typeof r.record_json[f] === "number" ? "num" : "" }, fmtValue(r.record_json[f]))),
    h("td", { class: "mono dim clip", title: JSON.stringify(r.record_json) }, short(JSON.stringify(r.record_json), 32)),
    h("td", { class: "right" }, h("button", { type: "button", class: "btn btn-sm", onclick: () => openRecord(r) }, "Открыть")),
  )));
}

function openRecord(r) {
  openCard(`Запись № ${r.id}`, [
    ...Object.entries(r.record_json).map(([key, value]) => [
      LABELS.field[key] || key,
      key === "updated_at" ? fmtTime(value) : value,
    ]),
    ["Источник", r.source],
    ["Дата сбора", fmtTime(r.created_at)],
  ], r.record_json, "record_json");
}

el("limit").addEventListener("change", loadRecords);
el("btn-reload").addEventListener("click", loadRecords);
el("btn-json").addEventListener("click", () => download("json"));
el("btn-csv").addEventListener("click", () => download("csv"));

async function download(format) {
  if (!state.dataset) return message("showcase-msg", "Набор не выбран", "bad");
  const url = `/datasets/${state.dataset.dataset_id}/export?format=${format}&limit=${el("limit").value}`;
  const response = await fetch(url);
  if (!response.ok) return message("showcase-msg", `Экспорт не выполнен: HTTP ${response.status}`, "bad");
  const link = h("a", { href: URL.createObjectURL(await response.blob()) });
  link.download = `${state.dataset.name.replace(/[^\wа-яё-]+/gi, "_")}_${new Date().toISOString().slice(0, 10)}.${format}`;
  link.click();
  URL.revokeObjectURL(link.href);
}

el("ask-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  if (!state.dataset) return message("showcase-msg", "Набор не выбран", "bad");
  const btn = el("btn-ask");
  btn.disabled = true;
  const res = await http(`/datasets/${state.dataset.dataset_id}/ask`, { method: "POST", body: { question: el("question").value.trim() } });
  btn.disabled = false;
  const box = el("answer");
  box.hidden = false;
  if (!res.ok) {
    box.className = "answer answer-review";
    el("answer-text").textContent = problem(res);
    el("answer-meta").textContent = "";
    return;
  }
  const a = res.data;
  box.className = "answer" + (a.needs_review ? " answer-review" : "");
  el("answer-text").textContent = a.needs_review ? `Ответ не сформирован: ${a.reason}` : a.answer;
  el("answer-meta").textContent = a.needs_review
    ? `Записей в контексте: ${a.records_considered}`
    : `Уверенность: ${LABELS.confidence[a.confidence]} · Записи: ${a.used_record_ids.join(", ")} · ${a.reason}`;
  refreshBadge();
});

// ---------------- аудит ----------------

async function loadAudit() {
  const params = new URLSearchParams({ limit: "200" });
  if (el("f-status").value) params.set("status", el("f-status").value);
  if (el("f-action").value) params.set("action", el("f-action").value);
  const [summary, runs, reviews] = await Promise.all([
    http("/audit/summary"), http("/audit/runs?" + params), http("/agent_runs?limit=100&needs_review=true"),
  ]);
  if (summary.ok) {
    el("k-total").textContent = summary.data.total;
    el("k-ok").textContent = summary.data.ok;
    el("k-review").textContent = summary.data.needs_review;
    el("k-error").textContent = summary.data.error;
  }
  const reviewRows = reviews.data || [];
  el("review-empty").hidden = reviewRows.length > 0;
  el("review-rows").replaceChildren(...reviewRows.map((r) => h("tr", {},
    h("td", { class: "nowrap" }, fmtTime(r.created_at)),
    h("td", {}, short(r.query, 90)),
    h("td", { class: "c-warn" }, r.error || ""),
    h("td", { class: "right" }, h("button", { type: "button", class: "btn btn-sm", onclick: () => openCard(`Решение планировщика № ${r.id}`, [
      ["Время", fmtTime(r.created_at)], ["Запрос", r.query], ["Статус модерации", r.needs_review ? "Заблокирован" : "Допущен"], ["Причина", r.error || "—"],
    ], r.plan_json, "plan_json") }, "Открыть")),
  )));
  el("audit-rows").replaceChildren(...(runs.data || []).map((r) => h("tr", { class: "row-" + r.status },
    h("td", { class: "num" }, r.id),
    h("td", { class: "nowrap" }, fmtTime(r.created_at)),
    h("td", {}, LABELS.action[r.action] || r.action),
    h("td", {}, h("span", { class: "badge badge-" + r.status }, LABELS.status[r.status] || r.status)),
    h("td", { class: "num" }, r.duration_ms),
    h("td", {}, r.error || ""),
    h("td", { class: "right" }, h("button", { type: "button", class: "btn btn-sm", onclick: () => openCard(`Запуск № ${r.id}`, [
      ["Действие", LABELS.action[r.action] || r.action], ["Статус", LABELS.status[r.status] || r.status],
      ["Длительность, мс", r.duration_ms], ["Ошибка / причина", r.error || "—"], ["Время", fmtTime(r.created_at)],
    ], { input: r.input, output: r.output }, "input / output") }, "Открыть")),
  )));
  refreshBadge();
}

el("btn-audit").addEventListener("click", loadAudit);
el("f-status").addEventListener("change", loadAudit);
el("f-action").addEventListener("change", loadAudit);

// ---------------- карточка ----------------

function openCard(title, pairs, raw, rawTitle) {
  el("card-title").textContent = title;
  el("card-fields").replaceChildren(...pairs.flatMap(([k, v]) => [h("dt", {}, k), h("dd", {}, fmtValue(v))]));
  el("card-raw-title").textContent = rawTitle;
  el("card-raw").textContent = JSON.stringify(raw, null, 2);
  el("card-raw-box").open = false;
  el("card").showModal();
}

el("card-done").addEventListener("click", () => el("card").close());

window.addEventListener("hashchange", route);
renderActive();
loadHealth();
refreshBadge();
route();
