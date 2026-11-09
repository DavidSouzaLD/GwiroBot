const views = {
  home: "Visão geral",
  offers: "Ofertas encontradas",
  manual: "Oferta manual",
  shops: "Grupos",
  niches: "Nichos e filtros",
  stores: "Vitrines e tokens",
  channels: "Canais de envio",
  timing: "Tempos e busca automática",
  message: "Texto da oferta",
  logs: "Registro",
};

const currentTemplate = [
  "🔥 {title}",
  "",
  "❌ De: {original}",
  "✅ Por: {price}  🔻 -{discount}%",
  "{extra}",
  "",
  "{storeLine}",
].join("\n");

const templateVars = [
  ["title", "título"],
  ["original", "preço anterior"],
  ["price", "preço atual"],
  ["discount", "desconto"],
  ["extra", "extra"],
  ["storeLine", "vitrine"],
  ["store", "nome da vitrine"],
  ["niche", "nicho"],
  ["keyword", "palavra"],
];

const storeLines = {
  mercadolivre: "💛 Mercado Livre",
  amazon: "📦 Amazon",
  shopee: "🧡 Shopee",
  aliexpress: "🛒 AliExpress",
};

const storeNames = [
  ["mercadolivre", "Mercado Livre"],
  ["amazon", "Amazon"],
  ["shopee", "Shopee"],
  ["aliexpress", "AliExpress"],
];

const sample = {
  title: "Fone Bluetooth com estojo",
  price: "R$ 79,90",
  original: "R$ 149,90",
  discount: "47",
  store: "Mercado Livre",
  url: "https://exemplo.com/oferta",
  keyword: "fone bluetooth",
  niche: "Eletrônicos",
  extra: "⭐️ 4.8 · +50mil vendidos · 💠 preço no Pix",
  storeLine: "💛 Mercado Livre",
};

let token = sessionStorage.getItem("gwiro-token") || "";
let shops = [];
let openGroups = [];
let busyShopId = "";
let config = null;
let dashboard = { showHints: true, token: "" };
let dashboardHints = {};
let hints = {};
let groupHints = {};
let cleared = new Set();
let offerFilter = "todas";
let offers = [];
let statusTimer = 0;
let templateLines = [];
let focusedLine = 0;

const $ = (selector) => document.querySelector(selector);

function getPath(object, path) {
  return path.split(".").reduce((cursor, key) => (cursor == null ? "" : cursor[key]), object);
}

function setPath(object, path, value) {
  const keys = path.split(".");
  let cursor = object;
  keys.slice(0, -1).forEach((key) => {
    cursor = cursor[key];
  });
  cursor[keys.at(-1)] = value;
}

let confirmResolver = null;

function askConfirm({ kicker = "Confirmação", title, body, confirm = "Confirmar" }) {
  return new Promise((resolve) => {
    if (confirmResolver) {
      const pending = confirmResolver;
      confirmResolver = null;
      pending(false);
    }
    confirmResolver = resolve;
    $("#confirmKicker").textContent = kicker;
    $("#confirmTitle").textContent = title;
    $("#confirmBody").textContent = body;
    $("#confirmOk").textContent = confirm;
    $("#confirmLayer").classList.remove("d-none");
    $("#confirmCancel").focus();
  });
}

function closeConfirm(accepted) {
  if (!confirmResolver) return;
  const resolve = confirmResolver;
  confirmResolver = null;
  $("#confirmLayer").classList.add("d-none");
  resolve(accepted);
}

function toast(message, ok = true) {
  const holder = document.createElement("div");
  holder.className = "toast align-items-center border-0 show " + (ok ? "text-bg-dark" : "text-bg-secondary");
  holder.innerHTML = `<div class="d-flex"><div class="toast-body">${escapeHtml(message)}</div><button type="button" class="btn-close btn-close-white me-2 m-auto"></button></div>`;
  holder.querySelector("button").addEventListener("click", () => holder.remove());
  $("#toasts").append(holder);
  setTimeout(() => holder.remove(), 4200);
}

function escapeHtml(value) {
  return String(value).replace(/[&<>"']/g, (char) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  }[char]));
}

async function api(path, body) {
  const headers = {};
  if (token) headers.Authorization = "Bearer " + token;
  if (body !== undefined) headers["Content-Type"] = "application/json";
  const response = await fetch(path, {
    method: body === undefined ? "GET" : "POST",
    headers,
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  const data = await response.json().catch(() => ({}));
  if (response.status === 401) {
    showLogin();
    throw new Error("auth");
  }
  return data;
}

function showLogin() {
  $("#login").classList.remove("d-none");
}

function hideLogin() {
  $("#login").classList.add("d-none");
}

function fieldValue(path) {
  if (path.startsWith("dashboard.")) return getPath(dashboard, path.slice("dashboard.".length));
  return getPath(config, path);
}

function applyBundle(payload) {
  shops = payload.shops || [];
  dashboard = payload.dashboard || { showHints: true, token: "" };
  dashboardHints = payload.dashboardHints || {};
  config = shops.find((shop) => shop.id === payload.activeShop) || shops[0];
  groupHints = payload.hints || {};
  hints = groupHints[config?.id] || {};
  renderShopSwitch();
  renderShopManager();
  applyConfig();
}

function readOpenGroups() {
  try {
    const raw = JSON.parse(localStorage.getItem("gwiro-open-groups") || "[]");
    if (Array.isArray(raw)) openGroups = raw.filter((id) => typeof id === "string");
  } catch {
    openGroups = [];
  }
}

function rememberOpen() {
  const ids = new Set(shops.map((shop) => shop.id));
  openGroups = openGroups.filter((id) => ids.has(id));
  if (config && !openGroups.includes(config.id)) openGroups.push(config.id);
  localStorage.setItem("gwiro-open-groups", JSON.stringify(openGroups));
}

function pinGroup(id) {
  if (!id || openGroups.includes(id)) return;
  openGroups.push(id);
  localStorage.setItem("gwiro-open-groups", JSON.stringify(openGroups));
}

function renderShopSwitch() {
  if (!config) return;
  rememberOpen();
  renderOpenGroups();
}

function renderOpenGroups() {
  const bar = $("#openShops");
  if (!bar) return;
  bar.innerHTML = openGroups.map((id) => {
    const shop = shops.find((item) => item.id === id);
    if (!shop) return "";
    const active = shop.id === config?.id;
    return `
      <div class="group-tab ${active ? "is-active" : ""}">
        <button class="tab-main" type="button" data-open-shop="${escapeHtml(shop.id)}">
          <span class="tab-dot ${shop.enabled ? "on" : ""}"></span>
          <span>${escapeHtml(shop.name || "Grupo")}</span>
        </button>
        ${openGroups.length > 1 ? `<button class="tab-close" type="button" data-close-shop="${escapeHtml(shop.id)}" aria-label="Fechar ${escapeHtml(shop.name || "grupo")}">×</button>` : ""}
      </div>`;
  }).join("");
}

readOpenGroups();

function secretState(map, path) {
  const tail = map[path];
  return tail ? `····${tail}` : "vazio";
}

function shopTone(shop) {
  if (!shop?.enabled) return "off";
  if (busyShopId && busyShopId === shop.id) return "busy";
  return "on";
}

function shopStatusLabel(shop) {
  const tone = shopTone(shop);
  if (tone === "off") return "Pausado";
  if (tone === "busy") return "Buscando";
  return "Ligado";
}

function describeShop(shop) {
  const niches = (shop.niches || []).filter((niche) => niche.enabled).map((niche) => niche.name);
  const markets = storeNames.filter(([id]) => shop.marketplaces?.[id]?.enabled).map(([, label]) => label);
  return [
    `Canal ${labelMode(shop.channels?.mode)}`,
    niches.length ? niches.slice(0, 3).join(", ") : "sem nicho ativo",
    markets.length ? markets.join(", ") : "sem vitrine ligada",
  ].join(" · ");
}

function renderShopManager() {
  const list = $("#shopList");
  if (!list) return;
  if (!shops.length) {
    list.innerHTML = `<div class="col-12"><article class="panel panel-pad text-secondary">Nenhum grupo.</article></div>`;
    return;
  }
  list.innerHTML = shops.map((shop) => {
    const tone = shopTone(shop);
    const current = shop.id === config?.id;
    return `
    <div class="col-xl-6">
      <article class="panel panel-pad h-100 group-card is-${tone} ${current ? "is-current" : ""}" data-shop="${escapeHtml(shop.id)}">
        <div class="d-flex justify-content-between align-items-start gap-2 mb-2">
          <input class="group-name" data-shop-name value="${escapeHtml(shop.name || "")}" aria-label="Nome do grupo" maxlength="40">
          <span class="status-pill is-${tone}" data-shop-status>${shopStatusLabel(shop)}</span>
        </div>
        <textarea class="group-description" data-shop-description rows="2" maxlength="180" placeholder="Descreva este grupo. Ex.: relógios em oferta no Telegram.">${escapeHtml(shop.description || "")}</textarea>
        <p class="group-summary" data-shop-open>${escapeHtml(describeShop(shop))}${current ? " · aberto na barra" : " · clique para abrir"}</p>
        <div class="d-flex flex-wrap gap-2 mt-3">
          <button class="btn btn-sm ${shop.enabled ? "btn-outline-dark" : "btn-dark"}" data-shop-toggle type="button">${shop.enabled ? "Pausar" : "Ativar"}</button>
          <button class="btn btn-outline-dark btn-sm" data-shop-reset type="button">Resetar</button>
          <button class="btn btn-outline-dark btn-sm" data-shop-copy type="button">Duplicar</button>
          <button class="btn btn-outline-danger btn-sm" data-shop-delete type="button" ${shops.length < 2 ? "disabled" : ""}>Excluir</button>
        </div>
      </article>
    </div>`;
  }).join("");
}

function syncRosterFromDom() {
  document.querySelectorAll("[data-shop]").forEach((card) => {
    const shop = shops.find((item) => item.id === card.dataset.shop);
    if (!shop) return;
    const name = card.querySelector("[data-shop-name]");
    const description = card.querySelector("[data-shop-description]");
    if (name) shop.name = name.value.trim() || shop.name;
    if (description) shop.description = description.value.trim();
    if (config && shop.id === config.id) {
      config.name = shop.name;
      config.enabled = shop.enabled;
      config.description = shop.description || "";
    }
  });
}

function applyConfig() {
  document.querySelectorAll("[data-path]").forEach((field) => {
    if (field.dataset.secret) {
      field.value = "";
      return;
    }
    const value = fieldValue(field.dataset.path);
    if (field.type === "checkbox") field.checked = field.dataset.path === "dashboard.showHints" ? value !== false : Boolean(value);
    else field.value = value ?? "";
  });
  document.querySelectorAll("[data-hint]").forEach((node) => {
    const hint = node.dataset.hint.startsWith("dashboard.") ? dashboardHints[node.dataset.hint] : hints[node.dataset.hint];
    node.textContent = hint ? "Salvo · termina em " + hint : "";
  });
  syncChannelCards();
  renderNiches();
  renderManualNiches();
  renderTemplateEditor();
  renderPreview();
  renderManualPreview();
  syncHints();
}

function syncHints() {
  const enabled = dashboard?.showHints !== false;
  document.body.classList.toggle("hints-off", !enabled);
  document.querySelectorAll(".hint-btn").forEach((button) => {
    const current = bootstrap.Tooltip.getInstance(button);
    if (!enabled) {
      current?.dispose();
      return;
    }
    if (!current) {
      new bootstrap.Tooltip(button, {
        trigger: "hover focus",
        placement: "top",
        fallbackPlacements: ["bottom", "right"],
        offset: [0, 16],
        customClass: "og-tip",
        delay: { show: 240, hide: 80 },
        container: "body",
      });
    }
  });
}

function readConfig() {
  const next = structuredClone(config);
  document.querySelectorAll("[data-path]").forEach((field) => {
    if (field.dataset.path.startsWith("dashboard.")) return;
    if (field.dataset.secret) {
      if (cleared.has(field.dataset.path)) setPath(next, field.dataset.path, "__clear__");
      else if (field.value.trim()) setPath(next, field.dataset.path, field.value.trim());
      return;
    }
    const value = field.type === "checkbox"
      ? field.checked
      : field.dataset.type === "number"
        ? Number(field.value)
        : field.value;
    setPath(next, field.dataset.path, value);
  });
  next.niches = readNiches();
  return next;
}

function readDashboard() {
  const tokenField = document.querySelector('[data-path="dashboard.token"]');
  let nextToken = "";
  if (cleared.has("dashboard.token")) nextToken = "__clear__";
  else if (tokenField && tokenField.value.trim()) nextToken = tokenField.value.trim();
  return {
    showHints: $("#showHints") ? $("#showHints").checked : dashboard.showHints !== false,
    token: nextToken,
  };
}

function blankNiche() {
  const id = "nicho-" + Math.random().toString(36).slice(2, 8);
  return {
    id,
    name: "Novo nicho",
    enabled: true,
    keywords: "",
    minDiscount: 15,
    minPrice: 0,
    maxPrice: 0,
    stores: storeNames.map(([id]) => id),
  };
}

function renderNiches() {
  const niches = Array.isArray(config.niches) ? config.niches : [];
  const list = $("#nicheList");
  if (!niches.length) {
    list.innerHTML = `<div class="col-12"><article class="panel panel-pad text-secondary">Nenhum nicho. O bot usa as palavras-chave gravadas em cada vitrine.</article></div>`;
    return;
  }
  list.innerHTML = niches.map((niche) => `
    <div class="col-xl-6">
      <article class="panel panel-pad h-100" data-niche="${escapeHtml(niche.id)}">
        <div class="d-flex justify-content-between align-items-center gap-2 mb-3">
          <input class="form-control fw-semibold" data-field="name" value="${escapeHtml(niche.name || "")}">
          <div class="form-check form-switch m-0">
            <input class="form-check-input" type="checkbox" data-field="enabled" ${niche.enabled ? "checked" : ""}>
          </div>
        </div>
        <div class="row g-3">
          <div class="col-md-4"><label class="form-label">Desconto mínimo (%)</label><input class="form-control" type="number" min="0" data-field="minDiscount" value="${Number(niche.minDiscount) || 0}"></div>
          <div class="col-md-4"><label class="form-label">Preço mínimo</label><input class="form-control" type="number" min="0" data-field="minPrice" value="${Number(niche.minPrice) || 0}"></div>
          <div class="col-md-4"><label class="form-label">Preço máximo</label><input class="form-control" type="number" min="0" data-field="maxPrice" value="${Number(niche.maxPrice) || 0}"></div>
          <div class="col-12">
            <label class="form-label">Vitrines deste nicho</label>
            <div class="d-flex flex-wrap gap-3">
              ${storeNames.map(([id, label]) => `
                <label class="form-check m-0">
                  <input class="form-check-input" type="checkbox" data-store="${id}" ${(niche.stores || []).includes(id) ? "checked" : ""}>
                  <span class="form-check-label">${label}</span>
                </label>
              `).join("")}
            </div>
            <div class="form-text">Preço 0 deixa a ponta sem limite.</div>
          </div>
          <div class="col-12"><label class="form-label">Palavras-chave (uma por linha)</label><textarea class="form-control" rows="4" data-field="keywords">${escapeHtml(niche.keywords || "")}</textarea></div>
        </div>
        <button class="btn btn-outline-dark btn-sm mt-3" data-remove-niche type="button">Remover</button>
      </article>
    </div>
  `).join("");
}

function readNiches() {
  const cards = [...document.querySelectorAll("[data-niche]")];
  if (!cards.length && $("#nicheList") && !$("#nicheList").querySelector("[data-niche]")) {
    return Array.isArray(config?.niches) ? config.niches : [];
  }
  return cards.map((card) => ({
    id: card.dataset.niche,
    name: card.querySelector("[data-field=name]").value.trim(),
    enabled: card.querySelector("[data-field=enabled]").checked,
    keywords: card.querySelector("[data-field=keywords]").value,
    minDiscount: Number(card.querySelector("[data-field=minDiscount]").value),
    minPrice: Number(card.querySelector("[data-field=minPrice]").value),
    maxPrice: Number(card.querySelector("[data-field=maxPrice]").value),
    stores: [...card.querySelectorAll("[data-store]:checked")].map((field) => field.dataset.store),
  }));
}

async function saveConfig(silent = false) {
  syncRosterFromDom();
  const typedPassword = $('[data-path="dashboard.token"]').value.trim();
  const removingPassword = cleared.has("dashboard.token");
  const shop = readConfig();
  const payload = await api("/api/config", {
    shopId: shop.id,
    shop,
    dashboard: readDashboard(),
    roster: shops.map((item) => ({
      id: item.id,
      name: item.name,
      enabled: Boolean(item.enabled),
      description: item.description || "",
    })),
  });
  if (!Array.isArray(payload.shops)) throw new Error(payload.detail || "Não foi possível salvar.");
  cleared = new Set();
  if (removingPassword) {
    token = "";
    sessionStorage.removeItem("gwiro-token");
  } else if (typedPassword) {
    token = typedPassword;
    sessionStorage.setItem("gwiro-token", token);
  }
  applyBundle(payload);
  if (!silent) toast("Configuração salva.");
  await refresh();
}

const resetCopy = {
  all: {
    kicker: "Resetar grupo",
    title: (name) => `Resetar ${name}?`,
    body: () => "Nichos, vitrines, canais, tokens, tempos, mensagem e descrição voltam ao padrão. O nome e o estado ligado ou pausado permanecem.",
  },
  niches: {
    kicker: "Resetar",
    title: () => "Resetar os nichos?",
    body: (name) => `Palavras, desconto, preços e vitrines dos nichos de ${name} voltam ao padrão.`,
  },
  marketplaces: {
    kicker: "Resetar",
    title: () => "Resetar as vitrines?",
    body: (name) => `Vitrines, palavras e tokens de afiliado de ${name} voltam ao padrão.`,
  },
  channels: {
    kicker: "Resetar",
    title: () => "Resetar os canais?",
    body: (name) => `Canais e tokens de envio de ${name} voltam ao padrão.`,
  },
  timing: {
    kicker: "Resetar",
    title: () => "Resetar os tempos?",
    body: (name) => `Intervalos, limites e horário silencioso de ${name} voltam ao padrão.`,
  },
  message: {
    kicker: "Resetar",
    title: () => "Resetar a mensagem?",
    body: (name) => `O modelo de mensagem de ${name} volta ao padrão.`,
  },
};

async function resetSection(section, shopId) {
  const id = shopId || config?.id || "";
  const shop = shops.find((item) => item.id === id);
  const name = shop?.name || "grupo";
  const copy = resetCopy[section];
  if (!copy) throw new Error("Não há padrão para restaurar aqui.");
  const accepted = await askConfirm({
    kicker: copy.kicker,
    title: copy.title(name),
    body: copy.body(name),
    confirm: "Resetar",
  });
  if (!accepted) return;
  const payload = await api("/api/shops", { action: "reset", id, section });
  if (!Array.isArray(payload.shops)) throw new Error(payload.detail || "Não foi possível resetar.");
  applyBundle(payload);
  toast("Padrão restaurado.");
}

async function setGroupEnabled(id, enabled) {
  const payload = await api("/api/shops", { action: "enable", id, enabled });
  if (!Array.isArray(payload.shops)) throw new Error(payload.detail || "Não foi possível atualizar o grupo.");
  const saved = payload.shops.find((item) => item.id === id);
  const shop = shops.find((item) => item.id === id);
  if (shop && saved) shop.enabled = Boolean(saved.enabled);
  if (config?.id === id && saved) config.enabled = Boolean(saved.enabled);
  renderOpenGroups();
  paintGroupStatus();
  await refresh();
  return shop;
}

async function closeOpenGroup(id) {
  if (openGroups.length < 2) return;
  const remaining = openGroups.filter((item) => item !== id);
  openGroups = remaining;
  localStorage.setItem("gwiro-open-groups", JSON.stringify(openGroups));
  if (config?.id !== id) {
    renderOpenGroups();
    return;
  }
  await selectShop(remaining[remaining.length - 1]);
}

async function selectShop(id) {
  if (!config || !id || id === config.id) return;
  await saveConfig(true);
  const payload = await api("/api/shops", { action: "select", id });
  if (!Array.isArray(payload.shops)) throw new Error(payload.detail || "Não foi possível abrir o grupo.");
  cleared = new Set();
  applyBundle(payload);
  await refresh();
}

async function mutateShop(body) {
  await saveConfig(true);
  const payload = await api("/api/shops", body);
  if (!Array.isArray(payload.shops)) throw new Error(payload.detail || "Não foi possível atualizar os grupos.");
  cleared = new Set();
  applyBundle(payload);
  await refresh();
}

function renderTemplateEditor() {
  templateLines = String($("#template").value || "").split("\n");
  if (!templateLines.length) templateLines = [""];
  const current = templateLines.join("\n").includes("🔥 {title}")
    && templateLines.join("\n").includes("❌ De:")
    && templateLines.join("\n").includes("✅ Por:");
  $("#templateNotice").classList.toggle("d-none", current);
  $("#templateLines").innerHTML = templateLines.map((line, index) => `
    <div class="template-line" data-line="${index}">
      <input class="form-control" data-line-input value="${escapeHtml(line)}" placeholder="Linha em branco">
      <div class="template-actions">
        <button class="btn btn-outline-dark btn-sm" type="button" data-line-up ${index === 0 ? "disabled" : ""} aria-label="Subir">↑</button>
        <button class="btn btn-outline-dark btn-sm" type="button" data-line-down ${index === templateLines.length - 1 ? "disabled" : ""} aria-label="Descer">↓</button>
        <button class="btn btn-outline-dark btn-sm" type="button" data-line-remove aria-label="Remover">✕</button>
      </div>
    </div>
  `).join("");
  $("#templateVars").innerHTML = templateVars.map(([key, label]) => `
    <button class="var-btn" type="button" data-var="${key}">{${key}} <span class="text-secondary">${label}</span></button>
  `).join("");
}

function commitTemplate() {
  $("#template").value = templateLines.join("\n");
  const text = $("#template").value;
  const current = text.includes("🔥 {title}") && text.includes("❌ De:") && text.includes("✅ Por:");
  $("#templateNotice").classList.toggle("d-none", current);
  renderPreview();
}

function renderPreview() {
  $("#preview").innerHTML = previewHtml(fillTemplate($("#template").value || "", sample));
}

function fillTemplate(template, offer) {
  let text = template;
  Object.entries(offer).forEach(([key, value]) => {
    text = text.replaceAll("{" + key + "}", value ?? "");
  });
  return text.replace(/\n{3,}/g, "\n\n").trim();
}

function previewHtml(text) {
  if (!text) return "";
  return text.split("\n").map((line) => {
    if (line.startsWith("🔥 ")) return "🔥 <b>" + escapeHtml(line.slice(2)) + "</b>";
    if (line.startsWith("❌ De: ")) return "❌ De: <s>" + escapeHtml(line.slice(7)) + "</s>";
    if (line.startsWith("✅ Por: ")) {
      const body = line.slice(7);
      const splitAt = body.indexOf("  🔻");
      if (splitAt === -1) return "✅ Por: <b>" + escapeHtml(body) + "</b>";
      const price = body.slice(0, splitAt);
      const rest = body.slice(splitAt + 4).trim();
      return "✅ Por: <b>" + escapeHtml(price) + "</b>  🔻 <b>" + escapeHtml(rest) + "</b>";
    }
    return escapeHtml(line);
  }).join("\n");
}

function moneyLabel(value) {
  const amount = parseAmount(value);
  if (!Number.isFinite(amount) || amount <= 0) return "—";
  return amount.toLocaleString("pt-BR", { style: "currency", currency: "BRL" });
}

function parseAmount(value) {
  const text = String(value || "").trim().replace(/[^\d,.-]/g, "");
  if (!text) return NaN;
  const normalized = text.includes(",") ? text.replace(/\./g, "").replace(",", ".") : text;
  return Number(normalized);
}

function manualDraft() {
  const store = $("#manualStore").value;
  const names = Object.fromEntries(storeNames);
  const price = parseAmount($("#manualPrice").value);
  let original = parseAmount($("#manualOriginal").value);
  const typed = $("#manualDiscount").value.trim();
  let discount = typed === "" ? NaN : Number(typed);
  if (!Number.isFinite(original) && Number.isFinite(price) && price > 0 && discount > 0 && discount < 100) {
    original = price / (1 - discount / 100);
  }
  if (!Number.isFinite(discount)) {
    discount = Number.isFinite(price) && Number.isFinite(original) && original > price
      ? Math.round((original - price) / original * 100)
      : 0;
  }
  discount = Math.max(0, Math.min(95, Math.round(discount) || 0));
  const extra = [
    $("#manualRating").value.trim() ? "⭐️ " + $("#manualRating").value.trim().replace(/^⭐️\s*/, "") : "",
    $("#manualPix").checked ? "💠 preço no Pix" : "",
    $("#manualShipping").checked ? "🚚 Frete grátis" : "",
    $("#manualNote").value.trim(),
  ].filter(Boolean).join(" · ");
  return {
    title: $("#manualTitle").value.trim() || "Título da oferta",
    price: moneyLabel(price),
    original: moneyLabel(original),
    discount: String(discount),
    store: names[store] || "",
    url: $("#manualUrl").value.trim() || "https://",
    keyword: "manual",
    niche: $("#manualNiche").value,
    extra,
    storeLine: storeLines[store] || names[store] || "",
  };
}

function renderManualPreview() {
  $("#manualPreview").innerHTML = previewHtml(fillTemplate($("#template").value || "", manualDraft()));
}

function renderManualNiches() {
  const select = $("#manualNiche");
  const current = select.value;
  const niches = Array.isArray(config?.niches) ? config.niches : [];
  select.innerHTML = `<option value="">Sem nicho</option>` + niches.map((niche) => `
    <option value="${escapeHtml(niche.name || "")}">${escapeHtml(niche.name || "Nicho")}</option>
  `).join("");
  if ([...select.options].some((option) => option.value === current)) select.value = current;
}

function manualPayload(send) {
  const price = parseAmount($("#manualPrice").value);
  const original = parseAmount($("#manualOriginal").value);
  return {
    send,
    shopId: config?.id || "",
    store: $("#manualStore").value,
    niche: $("#manualNiche").value,
    title: $("#manualTitle").value.trim(),
    price: Number.isFinite(price) ? price : "",
    original: Number.isFinite(original) ? original : "",
    discount: $("#manualDiscount").value.trim(),
    url: $("#manualUrl").value.trim(),
    image: $("#manualImage").value.trim(),
    rating: $("#manualRating").value.trim(),
    pix: $("#manualPix").checked,
    shipping: $("#manualShipping").checked,
    note: $("#manualNote").value.trim(),
  };
}

async function submitManual(send) {
  const result = await api("/api/offers/manual", manualPayload(send));
  toast(result.detail || (result.ok ? "Oferta manual pronta." : "Não foi possível montar a oferta."), Boolean(result.ok));
  if (result.ok) await refresh();
}

function syncChannelCards() {
  const mode = $("#channelMode").value;
  $("#cardTelegram").classList.toggle("store-card", true);
  $("#cardTelegram").classList.toggle("inactive", mode === "whatsapp" || mode === "none");
  $("#cardWhatsapp").classList.toggle("inactive", mode === "telegram" || mode === "none");
  const templateMode = $("#waDelivery").value === "template";
  document.querySelectorAll(".wa-template").forEach((node) => node.classList.toggle("d-none", !templateMode));
}

function paintGroupStatus() {
  document.querySelectorAll("[data-shop]").forEach((card) => {
    const shop = shops.find((item) => item.id === card.dataset.shop);
    if (!shop) return;
    const tone = shopTone(shop);
    card.classList.remove("is-on", "is-off", "is-busy");
    card.classList.add(`is-${tone}`);
    const pill = card.querySelector("[data-shop-status]");
    if (pill) {
      pill.className = `status-pill is-${tone}`;
      pill.textContent = shopStatusLabel(shop);
    }
    const toggle = card.querySelector("[data-shop-toggle]");
    if (toggle) {
      toggle.textContent = shop.enabled ? "Pausar" : "Ativar";
      toggle.classList.toggle("btn-dark", !shop.enabled);
      toggle.classList.toggle("btn-outline-dark", shop.enabled);
    }
  });
}

function renderStatus(status) {
  busyShopId = "";
  (status.shops || []).forEach((item) => {
    const shop = shops.find((entry) => entry.id === item.id);
    if (shop) shop.enabled = Boolean(item.enabled);
    if (config?.id === item.id) config.enabled = Boolean(item.enabled);
    if (item.busy) busyShopId = item.id;
  });
  const running = Boolean(status.running);
  const busy = Boolean(status.busy);
  const pill = $("#livePill");
  pill.classList.toggle("is-on", running && !busy);
  pill.classList.toggle("is-busy", busy);
  pill.classList.toggle("is-off", !running);
  $("#liveLabel").textContent = busy ? "Buscando" : running ? "Ligado" : "Desligado";
  paintGroupStatus();
  renderOpenGroups();
  $("#btnToggle").textContent = running ? "Pausar" : "Ativar";
  $("#shopScope").textContent = status.shopName ? `Números, tokens e vitrines do grupo ${status.shopName}.` : "";
  const totals = status.totals || {};
  const cards = [
    ["Ciclos", totals.cycles || 0],
    ["Ofertas vistas", totals.found || 0],
    ["Enviadas", totals.sent || 0],
    ["Canal", labelMode(status.channels)],
  ];
  $("#stats").innerHTML = cards.map(([label, value]) => `
    <div class="col-6 col-xl-3"><article class="stat"><span class="kicker">${label}</span><b>${escapeHtml(value)}</b></article></div>
  `).join("");
  const niches = status.niches || [];
  $("#nicheChips").innerHTML = niches.length
    ? niches.map((niche) => `<span class="chip ${niche.enabled ? "" : "off"}">${escapeHtml(niche.name)} · ${niche.enabled ? "ativo" : "pausado"}</span>`).join("")
    : `<span class="chip off">Sem nichos ativos. A busca usa as palavras de cada vitrine.</span>`;
  const latest = offers.slice(0, 5);
  $("#homeOffers").innerHTML = latest.length
    ? latest.map((offer) => `
      <div class="home-offer">
        <div class="flex-grow-1">
          <div class="small text-secondary">${escapeHtml(offer.storeLabel)}${offer.niche ? " · " + escapeHtml(offer.niche) : ""}</div>
          <div class="fw-semibold">${escapeHtml(offer.title)}</div>
        </div>
        <span class="badge-off">${offer.discount || 0}%</span>
      </div>
    `).join("")
    : `<div class="panel-pad text-secondary">As ofertas coletadas aparecem aqui.</div>`;
  $("#marketStatus").innerHTML = Object.entries(status.marketplaces || {}).map(([name, info]) => `
    <div class="col-md-6">
      <article class="panel panel-pad ${info.enabled ? "" : "store-card inactive"}">
        <div class="d-flex justify-content-between">
          <strong>${escapeHtml(info.label)}</strong>
          <span class="small text-secondary">${info.enabled ? "ativa" : "desligada"}</span>
        </div>
        <div class="text-secondary small mt-2">Próxima busca: ${info.nextRun ? formatWhen(info.nextRun) : "—"}</div>
        <div class="mt-2">Última leva: ${info.lastFound || 0}</div>
        ${info.lastError ? `<div class="small mt-2">${escapeHtml(info.lastError)}</div>` : ""}
      </article>
    </div>
  `).join("");
}

function labelMode(mode) {
  return { telegram: "Telegram", whatsapp: "WhatsApp", both: "Os dois", none: "Nenhum" }[mode] || "—";
}

function formatWhen(iso) {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "—";
  return date.toLocaleString("pt-BR", { hour: "2-digit", minute: "2-digit", day: "2-digit", month: "2-digit" });
}

function renderOffers() {
  const stores = ["todas", ...new Set(offers.map((offer) => offer.storeLabel))];
  $("#offerFilters").innerHTML = stores.map((store) => `
    <button class="btn btn-sm ${store === offerFilter ? "btn-dark" : "btn-outline-dark"}" data-filter="${escapeHtml(store)}" type="button">${escapeHtml(store)}</button>
  `).join("");
  const visible = offers.filter((offer) => offerFilter === "todas" || offer.storeLabel === offerFilter);
  if (!visible.length) {
    $("#offerList").innerHTML = `<div class="panel-pad text-secondary">Nenhuma oferta nesta visão. Use Buscar para coletar agora.</div>`;
    return;
  }
  $("#offerList").innerHTML = visible.map((offer) => `
    <div class="d-flex gap-3 align-items-center panel-pad border-bottom">
      ${offer.image ? `<img class="offer-thumb" alt="" src="${escapeHtml(offer.image)}">` : `<div class="offer-thumb"></div>`}
      <div class="flex-grow-1">
        <div class="d-flex flex-wrap gap-2 align-items-center">
          <span class="badge-off">${offer.discount || 0}% OFF</span>
          <span class="small text-secondary">${escapeHtml(offer.storeLabel)}${offer.niche ? " · " + escapeHtml(offer.niche) : ""} · ${escapeHtml(offer.status || "coletada")}</span>
        </div>
        <div class="fw-semibold mt-1">${escapeHtml(offer.title)}</div>
        <div class="small text-secondary">${escapeHtml(offer.originalLabel)} → ${escapeHtml(offer.priceLabel)}</div>
      </div>
      <div class="d-grid gap-2">
        ${offer.url ? `<a class="btn btn-outline-dark btn-sm" href="${escapeHtml(offer.url)}" target="_blank" rel="noopener">Abrir</a>` : ""}
        <button class="btn btn-dark btn-sm" data-send="${escapeHtml(offer.id)}" type="button">Enviar</button>
      </div>
    </div>
  `).join("");
}

function renderLogs(logs) {
  if (!logs.length) {
    $("#logList").innerHTML = `<div class="text-secondary">O registro aparece quando o bot busca ou envia.</div>`;
    return;
  }
  $("#logList").innerHTML = logs.map((entry) => `
    <div class="log-line">
      <span class="text-secondary">${formatWhen(entry.at)}</span>
      <span>${escapeHtml(entry.level)}</span>
      <span>${escapeHtml(entry.message)}</span>
    </div>
  `).join("");
}

async function refresh() {
  const [current, currentOffers, currentLogs] = await Promise.all([
    api("/api/status"),
    api("/api/offers"),
    api("/api/logs"),
  ]);
  const shopId = config?.id || "principal";
  offers = (currentOffers.offers || []).filter((offer) => (offer.shopId || "principal") === shopId);
  const logs = (currentLogs.logs || []).filter((entry) => !entry.shopId || entry.shopId === shopId);
  renderStatus(current);
  renderOffers();
  renderLogs(logs);
}

function openView(name) {
  Object.keys(views).forEach((view) => {
    $("#view-" + view).classList.toggle("d-none", view !== name);
  });
  document.querySelectorAll(".nav-btn").forEach((button) => {
    button.classList.toggle("active", button.dataset.view === name);
  });
  $("#viewKicker").textContent = views[name];
  $("#sidebar").classList.remove("open");
  $("#backdrop").classList.remove("show");
}

document.querySelectorAll(".nav-btn").forEach((button) => {
  button.addEventListener("click", () => openView(button.dataset.view));
});
$("#openMenu").addEventListener("click", () => {
  $("#sidebar").classList.add("open");
  $("#backdrop").classList.add("show");
});
$("#backdrop").addEventListener("click", () => {
  $("#sidebar").classList.remove("open");
  $("#backdrop").classList.remove("show");
});

$("#confirmForm").addEventListener("submit", (event) => {
  event.preventDefault();
  closeConfirm(true);
});
$("#confirmCancel").addEventListener("click", () => closeConfirm(false));
$("#confirmLayer").addEventListener("click", (event) => {
  if (event.target === $("#confirmLayer")) closeConfirm(false);
});
$("#confirmLayer").addEventListener("keydown", (event) => {
  if (event.key === "Escape") {
    event.preventDefault();
    closeConfirm(false);
    return;
  }
  if (event.key !== "Tab") return;
  const items = [$("#confirmCancel"), $("#confirmOk")];
  const index = items.indexOf(document.activeElement);
  event.preventDefault();
  const next = event.shiftKey
    ? (index <= 0 ? items.length - 1 : index - 1)
    : (index < 0 || index === items.length - 1 ? 0 : index + 1);
  items[next].focus();
});

document.querySelectorAll("[data-reset]").forEach((button) => {
  button.addEventListener("click", () => {
    resetSection(button.dataset.reset).catch((error) => {
      if (error.message !== "auth") toast(error.message || "Não foi possível resetar.", false);
    });
  });
});
["#saveStores", "#saveChannels", "#saveTiming", "#saveMessage", "#saveNiches", "#saveShops"].forEach((id) => {
  $(id).addEventListener("click", () => saveConfig().catch((error) => {
    if (error.message !== "auth") toast("Não foi possível salvar.", false);
  }));
});

$("#templateLines").addEventListener("input", (event) => {
  const input = event.target.closest("[data-line-input]");
  if (!input) return;
  const index = Number(input.closest("[data-line]").dataset.line);
  templateLines[index] = input.value;
  commitTemplate();
  renderManualPreview();
});
$("#templateLines").addEventListener("focusin", (event) => {
  const row = event.target.closest("[data-line]");
  if (row) focusedLine = Number(row.dataset.line);
});
$("#templateLines").addEventListener("click", (event) => {
  const row = event.target.closest("[data-line]");
  if (!row) return;
  const index = Number(row.dataset.line);
  if (event.target.closest("[data-line-up]") && index > 0) {
    [templateLines[index - 1], templateLines[index]] = [templateLines[index], templateLines[index - 1]];
  } else if (event.target.closest("[data-line-down]") && index < templateLines.length - 1) {
    [templateLines[index + 1], templateLines[index]] = [templateLines[index], templateLines[index + 1]];
  } else if (event.target.closest("[data-line-remove]")) {
    templateLines.splice(index, 1);
    if (!templateLines.length) templateLines = [""];
  } else {
    return;
  }
  commitTemplate();
  renderTemplateEditor();
  renderManualPreview();
});
$("#templateVars").addEventListener("click", (event) => {
  const button = event.target.closest("[data-var]");
  if (!button) return;
  const token = "{" + button.dataset.var + "}";
  const input = document.querySelector(`[data-line="${focusedLine}"] [data-line-input]`);
  if (!input) return;
  const start = input.selectionStart ?? input.value.length;
  const end = input.selectionEnd ?? start;
  input.value = input.value.slice(0, start) + token + input.value.slice(end);
  templateLines[focusedLine] = input.value;
  commitTemplate();
  renderManualPreview();
  input.focus();
  const cursor = start + token.length;
  input.setSelectionRange(cursor, cursor);
});
$("#addTemplateLine").addEventListener("click", () => {
  templateLines.push("");
  commitTemplate();
  renderTemplateEditor();
  focusedLine = templateLines.length - 1;
  document.querySelector(`[data-line="${focusedLine}"] [data-line-input]`)?.focus();
});
$("#useCurrentTemplate").addEventListener("click", () => {
  $("#template").value = currentTemplate;
  renderTemplateEditor();
  renderPreview();
  renderManualPreview();
});
["#manualStore", "#manualNiche", "#manualTitle", "#manualPrice", "#manualOriginal", "#manualDiscount", "#manualUrl", "#manualImage", "#manualRating", "#manualNote"].forEach((id) => {
  $(id).addEventListener("input", renderManualPreview);
});
$("#manualPix").addEventListener("change", renderManualPreview);
$("#manualShipping").addEventListener("change", renderManualPreview);
$("#sendManual").addEventListener("click", () => {
  submitManual(true).catch((error) => {
    if (error.message !== "auth") toast("Não foi possível enviar.", false);
  });
});
$("#saveManual").addEventListener("click", () => {
  submitManual(false).catch((error) => {
    if (error.message !== "auth") toast("Não foi possível guardar.", false);
  });
});
$("#showHints").addEventListener("change", () => {
  dashboard.showHints = $("#showHints").checked;
  syncHints();
});
$("#openShops").addEventListener("click", (event) => {
  const close = event.target.closest("[data-close-shop]");
  if (close) {
    event.stopPropagation();
    closeOpenGroup(close.dataset.closeShop).catch((error) => {
      if (error.message !== "auth") toast("Não foi possível fechar a aba.", false);
    });
    return;
  }
  const tab = event.target.closest("[data-open-shop]");
  if (!tab || tab.dataset.openShop === config?.id) return;
  selectShop(tab.dataset.openShop).catch((error) => {
    if (error.message !== "auth") toast("Não foi possível trocar de grupo.", false);
  });
});
$("#addShop").addEventListener("click", () => {
  const field = $("#newShopName");
  const name = field.value.trim();
  if (!name) {
    toast("Dê um nome ao grupo.", false);
    field.focus();
    return;
  }
  mutateShop({ action: "create", name })
    .then(() => {
      field.value = "";
      toast("Grupo criado. Ele está aberto, com tokens vazios.");
    })
    .catch((error) => {
      if (error.message !== "auth") toast(error.message || "Não foi possível criar o grupo.", false);
    });
});
$("#newShopName").addEventListener("keydown", (event) => {
  if (event.key === "Enter") {
    event.preventDefault();
    $("#addShop").click();
  }
});
$("#shopList").addEventListener("click", (event) => {
  const card = event.target.closest("[data-shop]");
  if (!card) return;
  const id = card.dataset.shop;
  if (event.target.closest("[data-shop-toggle]")) {
    const shop = shops.find((item) => item.id === id);
    if (!shop) return;
    const next = !shop.enabled;
    setGroupEnabled(id, next)
      .then(() => toast(next ? "Grupo ativado." : "Grupo pausado."))
      .catch((error) => {
        if (error.message !== "auth") toast("Não foi possível atualizar o grupo.", false);
      });
    return;
  }
  if (event.target.closest("[data-shop-reset]")) {
    resetSection("all", id).catch((error) => {
      if (error.message !== "auth") toast(error.message || "Não foi possível resetar.", false);
    });
    return;
  }
  if (event.target.closest("[data-shop-open]")) {
    pinGroup(id);
    if (id === config?.id) {
      renderOpenGroups();
      return;
    }
    selectShop(id).catch((error) => {
      if (error.message !== "auth") toast("Não foi possível abrir o grupo.", false);
    });
    return;
  }
  if (event.target.closest("[data-shop-copy]")) {
    mutateShop({ action: "duplicate", id })
      .then(() => toast("Grupo duplicado, com os tokens da origem. Ele começa pausado."))
      .catch((error) => {
        if (error.message !== "auth") toast(error.message || "Não foi possível duplicar.", false);
      });
    return;
  }
  if (event.target.closest("[data-shop-delete]")) {
    const shop = shops.find((item) => item.id === id);
    askConfirm({
      kicker: "Excluir grupo",
      title: `Excluir ${shop?.name || "este grupo"}?`,
      body: "A configuração e os tokens dele saem do painel. Essa ação não volta.",
      confirm: "Excluir",
    }).then((accepted) => {
      if (!accepted) return null;
      return mutateShop({ action: "delete", id }).then(() => toast("Grupo excluído."));
    }).catch((error) => {
      if (error && error.message !== "auth") toast(error.message || "Não foi possível excluir.", false);
    });
  }
});
$("#channelMode").addEventListener("change", syncChannelCards);
$("#waDelivery").addEventListener("change", syncChannelCards);
$("#clearDash").addEventListener("click", () => {
  askConfirm({
    kicker: "Senha do painel",
    title: "Remover a senha?",
    body: "Ao salvar os canais, o painel fica aberto neste computador, sem pedir senha.",
    confirm: "Remover senha",
  }).then((accepted) => {
    if (!accepted) return;
    cleared.add("dashboard.token");
    $('[data-path="dashboard.token"]').value = "";
    toast("A senha será removida ao salvar.");
  });
});

$("#btnToggle").addEventListener("click", async () => {
  if (!config) return;
  const next = !config.enabled;
  try {
    await setGroupEnabled(config.id, next);
    toast(next ? "Grupo ativado." : "Grupo pausado.");
  } catch (error) {
    if (error.message !== "auth") toast("Não foi possível atualizar o grupo.", false);
  }
});

$("#btnFetch").addEventListener("click", async () => {
  toast("Busca iniciada.");
  const summary = await api("/api/cycle", { send: false, shopId: config?.id || "" });
  toast(summary.ok ? `${summary.found} oferta(s) encontrada(s).` : (summary.detail || "A busca não rodou."), Boolean(summary.ok));
  await refresh();
});

$("#btnTest").addEventListener("click", async () => {
  const result = await api("/api/test", { shopId: config?.id || "" });
  const detail = (result.results || []).map((item) => item.detail).join(" ") || result.detail || "Teste concluído.";
  toast(detail, Boolean(result.ok));
  await refresh();
});

$("#checkTelegram").addEventListener("click", async () => {
  await saveConfig();
  const result = await api("/api/check", { channel: "telegram", shopId: config?.id || "" });
  toast(result.detail || "Verificação concluída.", Boolean(result.ok));
});
$("#checkWhatsapp").addEventListener("click", async () => {
  await saveConfig();
  const result = await api("/api/check", { channel: "whatsapp", shopId: config?.id || "" });
  toast(result.detail || "Verificação concluída.", Boolean(result.ok));
});

$("#addNiche").addEventListener("click", () => {
  config.niches = readNiches();
  config.niches.push(blankNiche());
  renderNiches();
});
$("#nicheList").addEventListener("click", (event) => {
  const button = event.target.closest("[data-remove-niche]");
  if (!button) return;
  const card = button.closest("[data-niche]");
  const name = card.querySelector("[data-field=name]")?.value.trim() || "este nicho";
  askConfirm({
    kicker: "Nicho",
    title: `Remover ${name}?`,
    body: "O nicho sai desta lista. A mudança só fica gravada quando você salvar os nichos.",
    confirm: "Remover",
  }).then((accepted) => {
    if (!accepted) return;
    config.niches = readNiches().filter((niche) => niche.id !== card.dataset.niche);
    renderNiches();
  });
});

$("#offerFilters").addEventListener("click", (event) => {
  const button = event.target.closest("[data-filter]");
  if (!button) return;
  offerFilter = button.dataset.filter;
  renderOffers();
});
$("#offerList").addEventListener("click", async (event) => {
  const button = event.target.closest("[data-send]");
  if (!button) return;
  const result = await api("/api/offers/send", { id: button.dataset.send, shopId: config?.id || "" });
  toast(result.detail || (result.ok ? "Oferta enviada." : "Falha no envio."), Boolean(result.ok));
  await refresh();
});

$("#loginForm").addEventListener("submit", async (event) => {
  event.preventDefault();
  const given = $("#loginToken").value;
  const response = await fetch("/api/login", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ token: given }),
  });
  const data = await response.json();
  if (!data.ok) {
    $("#loginError").textContent = data.detail || "Senha incorreta.";
    return;
  }
  token = data.token || given;
  sessionStorage.setItem("gwiro-token", token);
  hideLogin();
  await boot();
});

async function boot() {
  const session = await fetch("/api/session").then((response) => response.json());
  if (session.authRequired && !token) {
    showLogin();
    return;
  }
  try {
    const payload = await api("/api/config");
    applyBundle(payload);
    hideLogin();
    await refresh();
    clearInterval(statusTimer);
    statusTimer = setInterval(() => refresh().catch(() => {}), 4000);
  } catch (error) {
    if (error.message !== "auth") toast("Não consegui abrir o painel.", false);
  }
}

boot();
