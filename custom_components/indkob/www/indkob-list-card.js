/*
 * Indkøb listekort
 * Viser indkøbslisten med − antal + pr. vare, tilføj-felt og "Send til nemlig".
 *
 *   type: custom:indkob-list-card
 *   entity: todo.indkob_shopping_list   # standard
 *   show_send: true                      # vis "Send til nemlig"
 *   title: Indkøbsliste
 *
 * Antal gemmes i varens navn ("3 × Mælk"), præcis som integrationen forventer,
 * så listen også kan redigeres fra HA's almindelige to-do-visning og Assist.
 */
const QTY_RE = /^\s*(\d{1,3})\s*[x×*]\s*(.+)$/i;

function parseSummary(summary) {
  const m = QTY_RE.exec(summary || "");
  return m ? { qty: Math.max(1, Number(m[1])), name: m[2].trim() } : { qty: 1, name: (summary || "").trim() };
}

function formatSummary(qty, name) {
  return qty > 1 ? `${qty} × ${name}` : name;
}

function productLine(description) {
  const first = (description || "").split("\n")[0];
  if (!/^nemlig/i.test(first)) return "";
  return first.replace(/^nemlig:\s*/i, "").replace(/\s*\[\d+\]\s*$/, "").trim() || "nemlig-vare valgt";
}

const esc = (s) => String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

const ICON = {
  check: "M9 16.17 4.83 12l-1.42 1.41L9 19 21 7l-1.41-1.41z",
  minus: "M19 13H5v-2h14z",
  plus: "M19 13h-6v6h-2v-6H5v-2h6V5h2v6h6z",
  trash: "M6 19a2 2 0 0 0 2 2h8a2 2 0 0 0 2-2V7H6zM19 4h-3.5l-1-1h-5l-1 1H5v2h14z",
};
const svg = (d) => `<svg viewBox="0 0 24 24" aria-hidden="true"><path fill="currentColor" d="${d}"/></svg>`;

class IndkobListCard extends HTMLElement {
  setConfig(config) {
    this._config = { entity: "todo.indkob_shopping_list", show_send: true, title: "Indkøbsliste", ...config };
  }

  static getStubConfig() {
    return { entity: "todo.indkob_shopping_list" };
  }

  getCardSize() {
    return 6;
  }

  set hass(hass) {
    this._hass = hass;
    if (!this._root) this._render();
    if (!this._unsub) this._subscribe();
  }

  connectedCallback() {
    if (this._hass && !this._unsub) this._subscribe();
  }

  disconnectedCallback() {
    if (this._unsub) {
      const unsub = this._unsub;
      this._unsub = null;
      try { unsub(); } catch (_) { /* allerede lukket */ }
    }
  }

  async _subscribe() {
    if (this._subscribing || this._unsub || !this._hass) return;
    this._subscribing = true;
    try {
      this._unsub = await this._hass.connection.subscribeMessage(
        (msg) => { this._items = msg.items || []; this._renderItems(); },
        { type: "todo/item/subscribe", entity_id: this._config.entity },
      );
    } catch (err) {
      this._message(`Listen kunne ikke hentes: ${err.message || err}`, "err");
    } finally {
      this._subscribing = false;
    }
  }

  _render() {
    this._root = this.attachShadow({ mode: "open" });
    this._root.innerHTML = `
      <style>
        :host { display: block; }
        ha-card { padding: 16px; display: grid; gap: 12px; }
        .head { display: flex; align-items: baseline; justify-content: space-between; }
        .title { font-size: 1.15em; font-weight: 500; color: var(--primary-text-color); }
        .count { color: var(--secondary-text-color); }
        .add { display: flex; gap: 8px; }
        input {
          flex: 1; min-width: 0; font: inherit; padding: 10px 14px; border-radius: 999px;
          border: 1px solid var(--divider-color); background: var(--card-background-color);
          color: var(--primary-text-color);
        }
        button { font: inherit; cursor: pointer; color: inherit; background: none; border: none; }
        button:focus-visible, input:focus-visible { outline: 2px solid var(--primary-color); outline-offset: 2px; }
        .pill { padding: 10px 16px; border-radius: 999px; font-weight: 500; }
        .pill.primary { background: var(--primary-color); color: var(--text-primary-color, #fff); }
        .pill.primary.armed { background: var(--warning-color, #ffa600); }
        .pill.quiet { border: 1px solid var(--divider-color); color: var(--primary-color); }
        ul { list-style: none; margin: 0; padding: 0; }
        li {
          display: grid; grid-template-columns: auto 1fr auto; align-items: center; gap: 10px;
          padding: 8px 0; border-bottom: 1px solid var(--divider-color);
        }
        li:last-child { border-bottom: none; }
        .check {
          width: 30px; height: 30px; border-radius: 50%; display: grid; place-items: center;
          border: 2px solid var(--divider-color); color: transparent; padding: 0;
        }
        .done-list .check { border-color: var(--success-color, #43a047); background: var(--success-color, #43a047); color: #fff; }
        .check svg, .qty svg { width: 18px; height: 18px; }
        .name { color: var(--primary-text-color); line-height: 1.3; word-break: break-word; }
        .done-list .name { color: var(--secondary-text-color); text-decoration: line-through; }
        .sub { color: var(--secondary-text-color); font-size: 0.85em; line-height: 1.3; margin-top: 2px; }
        .qty { display: flex; align-items: center; gap: 2px; }
        .qty button {
          width: 34px; height: 34px; border-radius: 50%; display: grid; place-items: center; padding: 0;
          background: color-mix(in srgb, var(--primary-color) 12%, transparent); color: var(--primary-color);
        }
        .qty .minus.remove { color: var(--error-color, #db4437); background: color-mix(in srgb, var(--error-color, #db4437) 12%, transparent); }
        .qty .n { min-width: 2ch; text-align: center; font-weight: 500; font-variant-numeric: tabular-nums; color: var(--primary-text-color); }
        .empty { color: var(--secondary-text-color); padding: 4px 0; }
        details summary { cursor: pointer; color: var(--secondary-text-color); padding: 4px 0; }
        details .actions { display: flex; justify-content: flex-end; padding-top: 8px; }
        .msg { min-height: 1.3em; color: var(--secondary-text-color); }
        .msg.err { color: var(--error-color, #db4437); }
        .msg.ok { color: var(--primary-text-color); }
      </style>
      <ha-card>
        <div class="head"><span class="title"></span><span class="count"></span></div>
        <div class="add">
          <input placeholder="Tilføj vare, fx 2 x mælk" aria-label="Tilføj vare" enterkeyhint="done">
          <button class="pill quiet add-btn">Tilføj</button>
        </div>
        <ul class="open-list"></ul>
        <div class="empty">Listen er tom. Scan en vare eller skriv den ovenfor.</div>
        <details class="done-wrap" hidden>
          <summary></summary>
          <ul class="done-list"></ul>
          <div class="actions"><button class="pill quiet clear">Ryd klarede</button></div>
        </details>
        <button class="pill primary send">Send til nemlig</button>
        <div class="msg" role="status" aria-live="polite"></div>
      </ha-card>`;
    const $ = (s) => this._root.querySelector(s);
    this._title = $(".title");
    this._count = $(".count");
    this._input = $("input");
    this._open = $(".open-list");
    this._doneWrap = $(".done-wrap");
    this._doneList = $(".done-list");
    this._doneSummary = $("summary");
    this._empty = $(".empty");
    this._send = $(".send");
    this._msg = $(".msg");

    this._title.textContent = this._config.title;
    this._send.hidden = !this._config.show_send;
    $(".add-btn").addEventListener("click", () => this._add());
    this._input.addEventListener("keydown", (e) => e.key === "Enter" && this._add());
    $(".clear").addEventListener("click", () => this._call("todo", "remove_completed_items", {}));
    this._send.addEventListener("click", () => this._sendToNemlig());
    this._root.addEventListener("click", (e) => this._onRowClick(e));
    this._renderItems();
  }

  _row(item, done) {
    const { qty, name } = parseSummary(item.summary);
    const sub = productLine(item.description);
    const label = esc(name);
    return `
      <li data-uid="${esc(item.uid)}">
        <button class="check" data-act="toggle" aria-label="${done ? "Fortryd" : "Markér"} ${label} ${done ? "" : "som klaret"}">${svg(ICON.check)}</button>
        <div><div class="name">${label}</div>${sub ? `<div class="sub">${esc(sub)}</div>` : ""}</div>
        ${done ? "" : `
        <div class="qty">
          <button class="minus ${qty <= 1 ? "remove" : ""}" data-act="minus" aria-label="${qty <= 1 ? `Fjern ${label}` : `Én mindre ${label}`}">${svg(qty <= 1 ? ICON.trash : ICON.minus)}</button>
          <span class="n" aria-label="Antal">${qty}</span>
          <button class="plus" data-act="plus" aria-label="Én mere ${label}">${svg(ICON.plus)}</button>
        </div>`}
      </li>`;
  }

  _renderItems() {
    if (!this._root) return;
    const items = this._items || [];
    const open = items.filter((i) => i.status !== "completed");
    const done = items.filter((i) => i.status === "completed");
    const units = open.reduce((n, i) => n + parseSummary(i.summary).qty, 0);
    this._count.textContent = open.length ? `${units} stk.` : "";
    this._open.innerHTML = open.map((i) => this._row(i, false)).join("");
    this._empty.hidden = !!open.length || !this._items;
    this._doneWrap.hidden = !done.length;
    this._doneSummary.textContent = `Klaret (${done.length})`;
    this._doneList.innerHTML = done.map((i) => this._row(i, true)).join("");
    this._send.disabled = !open.length;
  }

  _message(text, kind = "") {
    this._msg.textContent = text;
    this._msg.className = `msg ${kind}`;
  }

  async _call(domain, service, data, withTarget = true) {
    try {
      return await this._hass.callService(
        domain, service, data, withTarget ? { entity_id: this._config.entity } : undefined, false, !withTarget,
      );
    } catch (err) {
      this._message(`Det lykkedes ikke: ${err.message || err}`, "err");
      return null;
    }
  }

  async _add() {
    const text = this._input.value.trim();
    if (!text) return;
    this._input.value = "";
    await this._call("todo", "add_item", { item: text });
  }

  _onRowClick(e) {
    const btn = e.target.closest("button[data-act]");
    if (!btn) return;
    const uid = btn.closest("li").dataset.uid;
    const item = (this._items || []).find((i) => i.uid === uid);
    if (!item) return;
    const { qty, name } = parseSummary(item.summary);
    const act = btn.dataset.act;

    if (act === "toggle") {
      const status = item.status === "completed" ? "needs_action" : "completed";
      item.status = status;
      this._renderItems();
      this._call("todo", "update_item", { item: uid, status });
    } else if (act === "plus" || (act === "minus" && qty > 1)) {
      const next = act === "plus" ? qty + 1 : qty - 1;
      item.summary = formatSummary(next, name); // vis med det samme
      this._renderItems();
      this._call("todo", "update_item", { item: uid, rename: item.summary });
    } else if (act === "minus") {
      this._items = this._items.filter((i) => i.uid !== uid);
      this._renderItems();
      this._call("todo", "remove_item", { item: uid });
    }
  }

  async _sendToNemlig() {
    // To tryk: første gang bliver knappen orange og spørger
    if (!this._armed) {
      this._armed = true;
      this._send.classList.add("armed");
      this._send.textContent = "Tryk igen for at sende";
      clearTimeout(this._armTimer);
      this._armTimer = setTimeout(() => this._disarm(), 3000);
      return;
    }
    this._disarm();
    this._send.disabled = true;
    this._message("Lægger varer i nemlig-kurven …");
    const res = await this._call("indkob", "send_to_nemlig", {}, false);
    this._send.disabled = false;
    if (!res) return;
    const r = res.response || {};
    const added = (r.added || []).length;
    const unresolved = (r.unresolved || []).length;
    const errors = (r.errors || []).length;
    const parts = [`${added} ${added === 1 ? "vare" : "varer"} lagt i kurven`];
    if (unresolved) parts.push(`${unresolved} kunne ikke findes på nemlig`);
    if (errors) parts.push(`${errors} fejlede`);
    this._message(`${parts.join(", ")}.`, unresolved || errors ? "err" : "ok");
  }

  _disarm() {
    this._armed = false;
    clearTimeout(this._armTimer);
    this._send.classList.remove("armed");
    this._send.textContent = "Send til nemlig";
  }
}

if (!customElements.get("indkob-list-card")) {
  customElements.define("indkob-list-card", IndkobListCard);
  window.customCards = window.customCards || [];
  window.customCards.push({
    type: "indkob-list-card",
    name: "Indkøb liste",
    description: "Indkøbslisten med antal-knapper og Send til nemlig.",
  });
}
