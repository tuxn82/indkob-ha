/*
 * Indkøb scanner-kort
 * Scanner stregkoder med telefonens kamera og kalder indkob.add_by_barcode.
 *
 *   type: custom:indkob-scanner-card
 *   continuous: true     # bliv ved med at scanne efter et fund (standard: true)
 *   quantity: 1          # antal pr. scanning
 *
 * Bruger browserens indbyggede BarcodeDetector hvor den findes (Chrome/Android),
 * ellers ZXing fra jsDelivr (iOS/Safari). Kameraet kræver HTTPS.
 */
const ZXING_URL = "https://cdn.jsdelivr.net/npm/@zxing/library@0.21.3/umd/index.min.js";
const FORMATS = ["ean_13", "ean_8", "upc_a", "upc_e"];
const REPEAT_MS = 2500;

let zxingPromise = null;
function loadZxing() {
  if (window.ZXing) return Promise.resolve(window.ZXing);
  if (!zxingPromise) {
    zxingPromise = new Promise((resolve, reject) => {
      const s = document.createElement("script");
      s.src = ZXING_URL;
      s.onload = () => (window.ZXing ? resolve(window.ZXing) : reject(new Error("ZXing mangler")));
      s.onerror = () => reject(new Error("Kunne ikke hente stregkode-biblioteket"));
      document.head.appendChild(s);
    });
  }
  return zxingPromise;
}

class IndkobScannerCard extends HTMLElement {
  setConfig(config) {
    this._config = { continuous: true, quantity: 1, ...config };
  }

  static getStubConfig() {
    return { continuous: true };
  }

  getCardSize() {
    return 5;
  }

  set hass(hass) {
    this._hass = hass;
    if (!this._root) this._render();
  }

  disconnectedCallback() {
    this._stop();
  }

  _render() {
    this._root = this.attachShadow({ mode: "open" });
    this._root.innerHTML = `
      <style>
        :host { display: block; }
        .wrap { padding: 16px; display: grid; gap: 12px; }
        .viewer {
          position: relative; display: none; overflow: hidden;
          border-radius: var(--ha-card-border-radius, 12px);
          background: #000; aspect-ratio: 4 / 3;
        }
        .viewer.on { display: block; }
        video { width: 100%; height: 100%; object-fit: cover; display: block; }
        .aim {
          position: absolute; left: 12%; right: 12%; top: 50%; height: 2px;
          background: var(--primary-color); box-shadow: 0 0 8px var(--primary-color);
        }
        .viewer.hit .aim { background: var(--success-color, #43a047); box-shadow: 0 0 12px var(--success-color, #43a047); }
        @media (prefers-reduced-motion: no-preference) {
          .aim { animation: sweep 1.6s ease-in-out infinite alternate; }
        }
        @keyframes sweep { from { top: 35%; } to { top: 65%; } }
        .row { display: flex; gap: 8px; }
        button {
          flex: 1; font: inherit; font-weight: 500; padding: 12px 16px; cursor: pointer;
          border: none; border-radius: 999px;
          background: var(--primary-color); color: var(--text-primary-color, #fff);
        }
        button.secondary { background: transparent; color: var(--primary-color); border: 1px solid var(--divider-color); flex: 0 0 auto; }
        button:focus-visible, input:focus-visible { outline: 2px solid var(--primary-color); outline-offset: 2px; }
        input {
          flex: 1; min-width: 0; font: inherit; padding: 10px 14px; border-radius: 999px;
          border: 1px solid var(--divider-color); background: var(--card-background-color);
          color: var(--primary-text-color);
        }
        .status { min-height: 1.4em; color: var(--secondary-text-color); line-height: 1.4; }
        .status.ok { color: var(--primary-text-color); }
        .status.err { color: var(--error-color, #db4437); }
      </style>
      <ha-card header="${this._config.title || "Scan vare"}">
        <div class="wrap">
          <div class="viewer"><video playsinline muted autoplay></video><div class="aim"></div></div>
          <div class="row"><button class="toggle">Start kamera</button></div>
          <div class="row">
            <input inputmode="numeric" placeholder="Eller tast stregkoden" aria-label="Stregkode">
            <button class="secondary manual">Tilføj</button>
          </div>
          <div class="status" role="status" aria-live="polite"></div>
        </div>
      </ha-card>`;
    this._viewer = this._root.querySelector(".viewer");
    this._video = this._root.querySelector("video");
    this._toggleBtn = this._root.querySelector(".toggle");
    this._status = this._root.querySelector(".status");
    this._input = this._root.querySelector("input");
    this._toggleBtn.addEventListener("click", () => (this._running ? this._stop() : this._start()));
    this._root.querySelector(".manual").addEventListener("click", () => this._manual());
    this._input.addEventListener("keydown", (e) => e.key === "Enter" && this._manual());
    document.addEventListener("visibilitychange", () => document.hidden && this._stop());
  }

  _setStatus(text, kind = "") {
    this._status.textContent = text;
    this._status.className = `status ${kind}`;
  }

  async _start() {
    if (!navigator.mediaDevices?.getUserMedia) {
      this._setStatus("Kameraet kan ikke bruges her. Åbn Home Assistant via HTTPS.", "err");
      return;
    }
    this._running = true;
    this._toggleBtn.textContent = "Stop kamera";
    this._viewer.classList.add("on");
    this._setStatus("Hold stregkoden ind i billedet.");
    try {
      if ("BarcodeDetector" in window) {
        await this._startNative();
      } else {
        await this._startZxing();
      }
    } catch (err) {
      this._stop();
      const denied = err && (err.name === "NotAllowedError" || err.name === "SecurityError");
      this._setStatus(
        denied ? "Adgang til kameraet blev afvist. Tillad kamera for appen eller browseren." : `Kameraet kunne ikke starte: ${err.message || err}`,
        "err",
      );
    }
  }

  async _startNative() {
    const supported = await window.BarcodeDetector.getSupportedFormats();
    const formats = FORMATS.filter((f) => supported.includes(f));
    if (!formats.length) return this._startZxing();
    const detector = new window.BarcodeDetector({ formats });
    this._stream = await navigator.mediaDevices.getUserMedia({
      video: { facingMode: { ideal: "environment" } }, audio: false,
    });
    this._video.srcObject = this._stream;
    await this._video.play();
    const tick = async () => {
      if (!this._running) return;
      try {
        const codes = await detector.detect(this._video);
        if (codes.length) await this._found(codes[0].rawValue);
      } catch (_) { /* enkelte frames kan fejle */ }
      if (this._running) this._timer = setTimeout(tick, 200);
    };
    tick();
  }

  async _startZxing() {
    const ZXing = await loadZxing();
    const hints = new Map();
    hints.set(ZXing.DecodeHintType.POSSIBLE_FORMATS, [
      ZXing.BarcodeFormat.EAN_13, ZXing.BarcodeFormat.EAN_8,
      ZXing.BarcodeFormat.UPC_A, ZXing.BarcodeFormat.UPC_E,
    ]);
    this._reader = new ZXing.BrowserMultiFormatReader(hints);
    await this._reader.decodeFromConstraints(
      { video: { facingMode: { ideal: "environment" } }, audio: false },
      this._video,
      (result) => { if (result && this._running) this._found(result.getText()); },
    );
  }

  _stop() {
    this._running = false;
    clearTimeout(this._timer);
    if (this._reader) { try { this._reader.reset(); } catch (_) {} this._reader = null; }
    if (this._stream) { this._stream.getTracks().forEach((t) => t.stop()); this._stream = null; }
    if (this._video) this._video.srcObject = null;
    if (this._viewer) this._viewer.classList.remove("on", "hit");
    if (this._toggleBtn) this._toggleBtn.textContent = "Start kamera";
  }

  async _found(code) {
    const now = Date.now();
    if (this._busy || (code === this._last && now - this._lastAt < REPEAT_MS)) return;
    this._last = code;
    this._lastAt = now;
    if (navigator.vibrate) navigator.vibrate(80);
    this._viewer.classList.add("hit");
    setTimeout(() => this._viewer && this._viewer.classList.remove("hit"), 600);
    await this._add(code);
    if (!this._config.continuous) this._stop();
  }

  async _manual() {
    const code = this._input.value.replace(/\D/g, "");
    if (code.length < 8) {
      this._setStatus("Stregkoden skal være mindst 8 cifre.", "err");
      return;
    }
    this._input.value = "";
    await this._add(code);
  }

  async _add(code) {
    this._busy = true;
    this._setStatus(`Slår ${code} op …`);
    try {
      const res = await this._hass.callService(
        "indkob", "add_by_barcode",
        { barcode: code, quantity: this._config.quantity },
        undefined, false, true,
      );
      const r = (res && res.response) || {};
      const qty = r.quantity > 1 ? ` (${r.quantity} stk.)` : "";
      const note = r.product_id ? "" : " Varen vælges ved afsendelse.";
      this._setStatus(`Tilføjet: ${r.name || code}${qty}.${note}`, "ok");
    } catch (err) {
      this._setStatus(`Kunne ikke tilføje ${code}: ${err.message || err}`, "err");
    } finally {
      this._busy = false;
    }
  }
}

if (!customElements.get("indkob-scanner-card")) {
  customElements.define("indkob-scanner-card", IndkobScannerCard);
  window.customCards = window.customCards || [];
  window.customCards.push({
    type: "indkob-scanner-card",
    name: "Indkøb scanner",
    description: "Scan stregkoder med kameraet og sæt varen på indkøbslisten.",
  });
}
