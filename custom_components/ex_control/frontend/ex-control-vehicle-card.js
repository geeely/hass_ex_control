/* EX Control vehicle card
 *
 * The car at a glance: its picture in its own paint, lock / charge / climate
 * indicators, battery and range, a mini map and quick-info tiles.
 *
 * Layout, tile markup, map handling and the render cache are adapted from
 * the BMW CarData vehicle card (github.com/kvanbiesen/bmw-cardata-ha),
 * BSD 2-clause, Copyright (c) 2025 Kris Van Biesen, Renaud Allard, Jonas
 * Huberts. Its licence and disclaimer are in LICENSE-bmw-cardata.txt beside
 * this file and must ship with it.
 *
 * The car picture is a photo of the EX2, recoloured in the browser: the
 * paint mask (ex2-mask.png, red = paint, green = roof) says which pixels are
 * body paint, and each is re-tinted to the chosen colour keeping the photo's
 * own shading and highlights. Any paint, factory or custom, is just a colour.
 * A photo of your own can replace it (image_url).
 */

const WS_TYPE = "ex_control/vehicles";
const CARD_TAG = "ex-control-vehicle-card";
const CACHE_MS = 30_000;
const CARD_SIZE_UNIT_PX = 50;
const MAP_HEIGHT_DEFAULT = 120;

/* EX2 factory paints. Names are the Australian / Malaysian / South African
 * ones; the UK calls the same six Mist White, Moonstone Silver, Magnetic
 * Grey, Sandstone Beige, Pistachio Green and Blush Pink. Hex values are
 * matched by eye to press photos: close, not paint codes. */
const PAINTS = {
  moon_white: { hex: "#e8e8e3", label: "Moon White" },
  star_silver: { hex: "#b8bcc0", label: "Star Silver" },
  comet_grey: { hex: "#5d6268", label: "Comet Grey" },
  nebula_beige: { hex: "#cdbca3", label: "Nebula Beige" },
  aurora_green: { hex: "#a3baa4", label: "Aurora Green" },
  nova_pink: { hex: "#ddb3b1", label: "Nova Pink" },
};
const DEFAULT_PAINT = "moon_white";
const BLACK_ROOF = "#1a1c1f";

const ensureCustomCardsArray = () => {
  window.customCards = window.customCards || [];
  return window.customCards;
};

const boolConfig = (cfg, key, fallback) => {
  const raw = cfg?.[key];
  return typeof raw === "boolean" ? raw : fallback;
};

const normalizeState = (stateObj) => {
  const raw = stateObj?.state;
  if (raw === undefined || raw === null) return "";
  if (raw === "unknown" || raw === "unavailable") return "";
  return String(raw).trim().toLowerCase();
};

const formatState = (stateObj, hass) => {
  if (!stateObj) return "—";
  const state = stateObj.state;
  if (state === "unknown" || state === "unavailable") return "—";
  if (hass?.formatEntityState) return hass.formatEntityState(stateObj);
  const unit = stateObj.attributes?.unit_of_measurement;
  return unit ? `${state} ${unit}` : `${state}`;
};

const toNumber = (stateObj) => {
  const state = normalizeState(stateObj);
  if (!state) return NaN;
  return Number(state);
};

const clamp = (value, min, max) => Math.min(max, Math.max(min, value));

const numberConfig = (cfg, key, fallback) => {
  // Accept "120px" as well as 120: hand-written YAML often keeps the unit.
  const value = Number.parseFloat(cfg?.[key]);
  return Number.isFinite(value) ? value : fallback;
};

const isOn = (stateObj) => {
  const state = normalizeState(stateObj);
  return state === "on" || state === "true" || state === "streaming" || state === "locked";
};

const escapeHtml = (input) =>
  String(input ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");

const validHex = (value) => (typeof value === "string" && /^#[0-9a-f]{6}$/i.test(value.trim()) ? value.trim() : "");

const rgbToHex = (rgb) =>
  Array.isArray(rgb) && rgb.length === 3
    ? `#${rgb.map((n) => clamp(Math.round(Number(n) || 0), 0, 255).toString(16).padStart(2, "0")).join("")}`
    : "";

const paintFromState = (state) => {
  if (!state) return "";
  const key = String(state).trim().toLowerCase().replaceAll(" ", "_");
  return PAINTS[key]?.hex || validHex(state);
};

/** The paint and roof colours, first match wins: the card's paint_entity,
 *  the card's own paint, then the car's Paint and Roof selects (on the car's
 *  device when it talks to the integration), then Moon White. */
const resolvePaint = (cfg, hass, entities = {}) => {
  const stateOf = (id) => (id ? hass?.states?.[id]?.state : "");
  let paint = paintFromState(stateOf(cfg.paint_entity));
  if (!paint && cfg.paint === "custom") paint = rgbToHex(cfg.paint_custom) || validHex(cfg.paint_custom);
  if (!paint) paint = PAINTS[cfg.paint]?.hex || "";
  if (!paint) paint = paintFromState(stateOf(entities.paint));
  if (!paint) paint = PAINTS[DEFAULT_PAINT].hex;
  const roofChoice = cfg.roof || (String(stateOf(entities.roof)).toLowerCase() === "black" ? "black" : "body");
  const roof = roofChoice === "black" ? BLACK_ROOF : paint;
  return { paint, roof };
};

const iconBadge = (icon, statusClass = "", entityId = "", title = "") => `
  <button class="indicator ${statusClass}" data-entity-id="${escapeHtml(entityId)}" title="${escapeHtml(title)}" aria-label="${escapeHtml(title)}">
    <ha-ripple></ha-ripple>
    <ha-icon icon="${icon}"></ha-icon>
  </button>
`;

// One quick-info tile built from the same elements as the native tile card.
const tileItem = ({ icon, label, value, entity, cls = "" }) => {
  const entityAttr = escapeHtml(entity || "");
  return `
  <ha-card class="tile-item${cls ? ` ${cls}` : ""}">
    <div class="tile-item-bg" role="button" tabindex="0" data-entity-id="${entityAttr}" title="${entityAttr}"><ha-ripple></ha-ripple></div>
    <div class="tile-item-content">
      <ha-tile-icon interactive data-entity-id="${entityAttr}"><ha-icon slot="icon" icon="${escapeHtml(icon)}"></ha-icon></ha-tile-icon>
      <ha-tile-info primary="${escapeHtml(label)}" secondary="${escapeHtml(value)}"></ha-tile-info>
    </div>
  </ha-card>`;
};

const tileGrid = (items) => `<div class="tile-grid">${items.map(tileItem).join("")}</div>`;

// A control: toggles a helper the car listens to (HassCommands on the car).
const controlButton = ({ icon, label, entity, on }) => `
  <button class="control ${on ? "on" : ""}" data-toggle="${escapeHtml(entity)}" title="${escapeHtml(label)}" aria-pressed="${on}">
    <ha-ripple></ha-ripple>
    <ha-icon icon="${icon}"></ha-icon>
    <span>${escapeHtml(label)}</span>
  </button>
`;

const hasUsableState = (stateObj) => normalizeState(stateObj) !== "";

const sanitizePlate = (raw) => {
  if (typeof raw !== "string") return "";
  return raw.trim().replace(/[^\p{L}\p{N}\s-]/gu, "").substring(0, 15).toUpperCase();
};

const formatDuration = (hours, t) => {
  if (!Number.isFinite(hours) || hours <= 0 || hours > 72) return "";
  const total = Math.round(hours * 60);
  const h = Math.floor(total / 60);
  const m = total % 60;
  return h ? `${h} ${t("unit_h")} ${m} ${t("unit_min")}` : `${m} ${t("unit_min")}`;
};

const DEFAULT_LANG = "en";

const TRANSLATIONS = {
  en: {
    location: "Location",
    location_unavailable: "Location unavailable",
    away: "Away",
    home: "Home",
    range: "Range",
    motion: "Motion",
    moving: "Driving",
    parked: "Parked",
    charging: "Charging",
    not_charging: "Not charging",
    plugged_in: "Plugged in",
    unplugged: "Unplugged",
    to_full: "to full",
    mileage: "Odometer",
    outside: "Outside",
    battery_12v: "12V battery",
    battery_12v_low: "12V battery low",
    consumption: "Consumption",
    climate: "Climate",
    last_key: "Last key",
    lock: "Doors",
    locked: "Locked",
    unlocked: "Unlocked",
    ac: "A/C",
    ac_on: "on",
    ac_off: "off",
    camera: "Camera",
    camera_live: "live",
    camera_idle: "idle",
    camera_start: "Camera",
    camera_starting: "Starting…",
    camera_stop: "Stop camera",
    fob_watch: "Key fob watch",
    on: "on",
    off: "off",
    recirc: "Recirc",
    defrost: "Defrost",
    wheel_heat: "Wheel",
    unit_h: "h",
    unit_min: "min",
    select_vehicle: "No EX Control car found yet. Switch on Home Assistant on the car, or pick it in the card editor.",
    vehicle_not_found: "That car has not reported yet. Try again in a few seconds.",
    no_tracker: "No location from the car yet",
    tracker_unavailable: "Location entity unavailable",
    map_loading: "Loading map…",
    map_failed: "Unable to load Home Assistant map",
    "editor.device_id": "Car (mobile app device)",
    "editor.prefix": "Or entity prefix (e.g. ex)",
    "editor.license_plate": "Number plate",
    "editor.show_title": "Show car name / card header",
    "editor.paint": "Paint",
    "editor.paint_custom": "Custom paint colour",
    "editor.paint_entity": "Paint from entity (optional)",
    "editor.roof": "Roof",
    "editor.roof_body": "Body colour",
    "editor.roof_black": "Black (two-tone)",
    "editor.paint_custom_option": "Custom…",
    "editor.image_url": "Your own photo instead (URL, optional)",
    "editor.show_indicators": "Show indicator row",
    "editor.show_range": "Show battery and range bar",
    "editor.show_image": "Show car picture",
    "editor.image_crop_top": "Image crop top",
    "editor.image_crop_bottom": "Image crop bottom",
    "editor.image_zoom": "Image zoom",
    "editor.show_map": "Show mini map",
    "editor.map_height": "Mini map height",
    "editor.show_controls": "Show climate, lock and camera controls",
    "editor.camera_option": "Camera button shows",
    "editor.show_live": "Show the live camera in place of the photo",
    "editor.show_buttons": "Show quick info tiles",
  },
};

const resolveLang = (cfg, hass) => {
  const configured = typeof cfg?.language === "string" ? cfg.language.toLowerCase() : "auto";
  if (configured !== "auto" && TRANSLATIONS[configured]) return configured;
  const haLang = String(hass?.locale?.language || hass?.language || DEFAULT_LANG).toLowerCase().split("-")[0];
  return TRANSLATIONS[haLang] ? haLang : DEFAULT_LANG;
};

const localize = (lang, key) =>
  TRANSLATIONS[lang]?.[key] ?? TRANSLATIONS[DEFAULT_LANG][key] ?? key;

const humanizeLocationState = (rawState, t) => {
  const state = String(rawState || "").toLowerCase();
  if (!state || state === "unknown" || state === "unavailable") return t("location_unavailable");
  if (state === "not_home") return t("away");
  if (state === "home") return t("home");
  return String(rawState).replaceAll("_", " ");
};

/* The EX2 photo, repainted. Done once per colour in a canvas and cached as
 * a data URL, so a state update never redoes it. */
const CAR_IMG = "/ex_control/ex2.webp";
const CAR_MASK = "/ex_control/ex2-mask.png";
// The photo's paint is white: its median brightness. Below it is shade,
// above 0.93 is a highlight and stays white whatever the colour.
const PAINT_REF = 0.8;

const hexToRgb = (hex) => [1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16));
const smoothstep = (e0, e1, x) => {
  const t = Math.min(1, Math.max(0, (x - e0) / (e1 - e0)));
  return t * t * (3 - 2 * t);
};
const loadImage = (src) =>
  new Promise((resolve, reject) => {
    const img = new Image();
    img.onload = () => resolve(img);
    img.onerror = reject;
    img.src = src;
  });

let carSources = null;
const paintCache = new Map();

const paintedCar = (paint, roof) => {
  const key = `${paint}|${roof}`;
  if (!paintCache.has(key)) {
    paintCache.set(
      key,
      (async () => {
        carSources = carSources || Promise.all([loadImage(CAR_IMG), loadImage(CAR_MASK)]);
        const [img, mask] = await carSources;
        const w = img.naturalWidth;
        const h = img.naturalHeight;
        const canvas = document.createElement("canvas");
        canvas.width = w;
        canvas.height = h;
        const ctx = canvas.getContext("2d", { willReadFrequently: true });
        ctx.drawImage(mask, 0, 0);
        const m = ctx.getImageData(0, 0, w, h).data;
        ctx.clearRect(0, 0, w, h);
        ctx.drawImage(img, 0, 0);
        const frame = ctx.getImageData(0, 0, w, h);
        const d = frame.data;
        const p = hexToRgb(paint);
        const r = hexToRgb(roof);
        for (let i = 0; i < d.length; i += 4) {
          const mp = m[i] / 255;
          if (mp === 0) continue;
          const mr = m[i + 1] / 255;
          const L = (0.2126 * d[i] + 0.7152 * d[i + 1] + 0.0722 * d[i + 2]) / 255;
          const shade = Math.min(Math.max(L / PAINT_REF, 0), 1.15);
          const spec = smoothstep(0.93, 1, L) * 0.85;
          for (let k = 0; k < 3; k++) {
            const target = (p[k] * (1 - mr) + r[k] * mr) / 255;
            let v = target * shade;
            v = Math.min(1, v + (1 - v) * spec);
            d[i + k] = d[i + k] * (1 - mp) + v * 255 * mp;
          }
        }
        ctx.putImageData(frame, 0, 0);
        return canvas.toDataURL("image/webp", 0.92);
      })().catch(() => null)
    );
  }
  return paintCache.get(key);
};

const STYLE = `
  :host { display: block; }

  /* Sizes and radii mirror the native tile card and its features:
   * 56px tile rows, 42px feature controls, 36px icon circles, 20% tint. */
  .plate {
    color: var(--secondary-text-color);
    font-size: var(--ha-font-size-s, 12px);
    line-height: var(--ha-line-height-condensed, 1.2);
    letter-spacing: 0.4px;
  }
  .plate:empty { display: none; }
  #main-wrapper { display: grid; gap: var(--ha-space-3, 12px); }
  .plate:not(:empty) + #main-wrapper { margin-top: var(--ha-space-3, 12px); }
  #main-wrapper > :empty { display: none; }

  .indicators {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(48px, 1fr));
    gap: var(--ha-space-2, 8px);
  }
  .indicator, .control {
    --tile-color: var(--state-inactive-color);
    --ha-ripple-color: var(--tile-color);
    --mdc-icon-size: 20px;
    appearance: none;
    position: relative;
    overflow: hidden;
    cursor: pointer;
    display: flex;
    align-items: center;
    justify-content: center;
    gap: var(--ha-space-2, 8px);
    width: 100%;
    height: 42px;
    margin: 0;
    padding: 0 var(--ha-space-2, 8px);
    border: 0;
    border-radius: var(--ha-border-radius-lg, 12px);
    background: none;
    color: var(--tile-color);
    font: inherit;
    font-size: var(--ha-font-size-s, 12px);
    font-weight: var(--ha-font-weight-medium, 500);
    -webkit-tap-highlight-color: transparent;
    transition: color 180ms ease-in-out;
  }
  .indicator::before, .control::before {
    content: "";
    position: absolute;
    inset: 0;
    background-color: var(--tile-color);
    opacity: 0.2;
    transition: background-color 180ms ease-in-out, opacity 180ms ease-in-out;
    pointer-events: none;
  }
  .indicator ha-icon, .control ha-icon, .control span { position: relative; }
  .indicator:focus, .control:focus { outline: none; }
  .indicator:focus-visible, .control:focus-visible { box-shadow: 0 0 0 2px var(--tile-color); }
  .indicator.ok, .control.on { --tile-color: var(--state-icon-color); }
  .indicator.alert { --tile-color: var(--error-color); }
  .indicator.good { --tile-color: var(--success-color); }
  .indicator.charging { animation: chargingBadgePulse 1.4s ease-in-out infinite; }
  .controls {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(84px, 1fr));
    gap: var(--ha-space-2, 8px);
  }

  .range-box { display: grid; gap: var(--ha-space-2, 8px); }
  .range-top { display: flex; align-items: center; gap: var(--ha-space-3, 12px); }
  .bar-wrap {
    --tile-color: var(--state-icon-color);
    position: relative;
    flex: 1 1 auto;
    height: 42px;
    border-radius: var(--ha-border-radius-lg, 12px);
    overflow: hidden;
    cursor: pointer;
  }
  .bar-wrap.low { --tile-color: var(--error-color); }
  .bar-wrap.charging { --tile-color: var(--success-color, #4caf50); }
  .bar-wrap::before {
    content: "";
    position: absolute;
    inset: 0;
    background-color: var(--tile-color);
    opacity: 0.2;
  }
  .bar-level {
    position: relative;
    height: 100%;
    background: var(--tile-color);
    transition: width 180ms ease-in-out;
    overflow: hidden;
  }
  .bar-wrap.charging .bar-level { animation: chargingBarPulse 1.8s ease-in-out infinite; }
  .bar-wrap.charging .bar-level::after {
    content: "";
    position: absolute;
    inset: 0;
    background: linear-gradient(110deg, transparent 10%, rgba(255, 255, 255, 0.35) 45%, transparent 80%);
    transform: translateX(-120%);
    animation: chargingSweep 2.3s linear infinite;
    pointer-events: none;
  }
  .energy-text {
    position: absolute;
    left: var(--ha-space-3, 12px);
    top: 50%;
    transform: translateY(-50%);
    color: var(--text-primary-color, #fff);
    font-size: var(--ha-font-size-m, 14px);
    font-weight: var(--ha-font-weight-medium, 500);
    text-shadow: 0 1px 2px rgb(0 0 0 / 35%);
    white-space: nowrap;
  }
  .range-value {
    display: flex;
    align-items: center;
    gap: var(--ha-space-2, 8px);
    color: var(--primary-text-color);
    font-size: var(--ha-font-size-m, 14px);
    font-weight: var(--ha-font-weight-medium, 500);
    white-space: nowrap;
    cursor: pointer;
  }
  .charge-line {
    --mdc-icon-size: 18px;
    display: flex;
    align-items: center;
    gap: var(--ha-space-2, 8px);
    color: var(--success-color, #4caf50);
    font-size: var(--ha-font-size-s, 12px);
    cursor: pointer;
  }

  .image {
    width: 100%;
    border-radius: var(--ha-border-radius-lg, 12px);
    overflow: hidden;
    cursor: pointer;
  }
  .image img {
    width: 100%;
    display: block;
    object-fit: cover;
    object-position: center;
    transform-origin: center center;
    transform: scale(var(--image-zoom, 1));
    margin-top: calc(-1 * var(--image-crop-top, 0%));
    margin-bottom: calc(-1 * var(--image-crop-bottom, 0%));
  }
  .image.charging img { animation: chargingImagePulse 2.2s ease-in-out infinite; }
  .image.live { aspect-ratio: 16 / 9; background: #000; }
  .image.live > * { --ha-card-border-width: 0; --ha-card-border-radius: 0; --ha-card-background: #000; --card-background-color: #000; display: block; }
  /* Hidden until its paint is ready, so it never flashes white first. */
  .image img.car:not([src]) { visibility: hidden; aspect-ratio: 829 / 559; }

  .map {
    border-radius: var(--ha-border-radius-lg, 12px);
    overflow: hidden;
    background: var(--secondary-background-color);
  }
  .map-mount { height: var(--map-height, ${MAP_HEIGHT_DEFAULT}px); overflow: hidden; }
  .map-mount > * { height: 100%; }
  .map-fallback {
    height: var(--map-height, ${MAP_HEIGHT_DEFAULT}px);
    display: flex;
    align-items: center;
    justify-content: center;
    color: var(--secondary-text-color);
    font-size: var(--ha-font-size-s, 12px);
  }

  .tile-grid {
    display: grid;
    grid-template-columns: repeat(2, minmax(0, 1fr));
    gap: var(--ha-space-2, 8px);
  }
  .tile-item {
    --tile-color: var(--state-icon-color);
    --ha-ripple-color: var(--tile-color);
    --ha-ripple-hover-opacity: 0.04;
    --ha-ripple-pressed-opacity: 0.12;
    -webkit-tap-highlight-color: transparent;
    transition: box-shadow 180ms ease-in-out, border-color 180ms ease-in-out;
  }
  .tile-item.alert { --tile-color: var(--error-color); }
  .tile-item.good { --tile-color: var(--success-color); }
  .tile-item:has(.tile-item-bg:focus-visible) {
    border-color: var(--tile-color);
    box-shadow: var(--ha-card-box-shadow, 0 0 0 0 transparent), 0 0 0 1px var(--tile-color);
  }
  /* Both layers extend under the card border, like the native tile container. */
  .tile-item-bg {
    position: absolute;
    inset: 0;
    margin: calc(-1 * var(--ha-card-border-width, 1px));
    border-radius: inherit;
    overflow: hidden;
    cursor: pointer;
  }
  .tile-item-bg:focus { outline: none; }
  .tile-item-content {
    position: relative;
    display: flex;
    align-items: center;
    gap: 10px;
    padding: 0 10px;
    margin: calc(-1 * var(--ha-card-border-width, 1px));
    min-height: 56px;
    min-width: 0;
    box-sizing: border-box;
    pointer-events: none;
  }
  .tile-item-content ha-tile-icon {
    --tile-icon-color: var(--tile-color);
    position: relative;
    padding: 6px;
    margin: -6px;
    flex: none;
    pointer-events: auto;
  }
  .tile-item-content ha-tile-info { min-width: 0; }

  @media (max-width: 520px) {
    .tile-grid { grid-template-columns: 1fr; }
    .indicators { grid-template-columns: repeat(4, minmax(0, 1fr)); }
  }

  @keyframes chargingBadgePulse { 0%, 100% { filter: brightness(1); } 50% { filter: brightness(1.45); } }
  @keyframes chargingBarPulse { 0%, 100% { filter: brightness(1); } 50% { filter: brightness(1.18); } }
  @keyframes chargingSweep { 0% { transform: translateX(-120%); } 100% { transform: translateX(120%); } }
  @keyframes chargingImagePulse { 0%, 100% { filter: brightness(1) saturate(1); } 50% { filter: brightness(1.06) saturate(1.1); } }
  @media (prefers-reduced-motion: reduce) {
    .indicator.charging, .bar-wrap.charging .bar-level, .bar-wrap.charging .bar-level::after,
    .image.charging img { animation: none; }
  }
`;

class ExControlVehicleCard extends HTMLElement {
  setConfig(config) {
    const cfg = config || {};
    this._config = cfg.license_plate ? { ...cfg, license_plate: sanitizePlate(cfg.license_plate) } : cfg;
    this._vehicles = null;
    this._vehiclesFetchedAt = 0;
    this._fetchInFlight = null;
    if (this._hass) this._maybeFetchVehicles();
    if (this.shadowRoot) this._render();
  }

  getCardSize() {
    const cfg = this._config || {};
    let size = 4;
    if (boolConfig(cfg, "show_image", true)) size += 3;
    if (boolConfig(cfg, "show_map", true)) size += numberConfig(cfg, "map_height", MAP_HEIGHT_DEFAULT) / CARD_SIZE_UNIT_PX;
    if (boolConfig(cfg, "show_controls", true)) size += 1;
    if (boolConfig(cfg, "show_buttons", true)) size += 3;
    return size;
  }

  static getConfigForm() {
    // No hass here; read the UI language from the root element, as custom cards do.
    const lang = resolveLang({}, document.querySelector("home-assistant")?.hass);
    const t = (key) => localize(lang, key);
    const pct = (max) => ({ number: { mode: "box", min: 0, max, step: 1, unit_of_measurement: "%" } });
    return {
      schema: [
        { name: "device_id", selector: { device: { filter: { integration: "mobile_app" } } } },
        { name: "prefix", selector: { text: {} } },
        { name: "license_plate", selector: { text: {} } },
        { name: "show_title", selector: { boolean: {} } },
        {
          name: "paint",
          selector: {
            select: {
              mode: "dropdown",
              options: [
                ...Object.entries(PAINTS).map(([value, p]) => ({ value, label: p.label })),
                { value: "custom", label: t("editor.paint_custom_option") },
              ],
            },
          },
        },
        { name: "paint_custom", selector: { color_rgb: {} } },
        {
          name: "roof",
          selector: {
            select: {
              mode: "dropdown",
              options: [
                { value: "body", label: t("editor.roof_body") },
                { value: "black", label: t("editor.roof_black") },
              ],
            },
          },
        },
        { name: "paint_entity", selector: { entity: { domain: ["input_select", "input_text", "select", "sensor"] } } },
        { name: "show_image", selector: { boolean: {} } },
        { name: "image_url", selector: { text: {} } },
        { name: "image_crop_top", selector: pct(40) },
        { name: "image_crop_bottom", selector: pct(40) },
        { name: "image_zoom", selector: { number: { mode: "box", min: 50, max: 200, step: 5, unit_of_measurement: "%" } } },
        { name: "show_indicators", selector: { boolean: {} } },
        { name: "show_range", selector: { boolean: {} } },
        { name: "show_map", selector: { boolean: {} } },
        { name: "map_height", selector: { number: { mode: "box", unit_of_measurement: "px" } } },
        { name: "show_controls", selector: { boolean: {} } },
        {
          name: "camera_option",
          selector: {
            select: {
              mode: "dropdown",
              // The car's Camera select options (HassCamera.OPTIONS), minus Off.
              options: ["All", "Top left", "Top right", "Bottom left", "Bottom right"],
            },
          },
        },
        { name: "show_live", selector: { boolean: {} } },
        { name: "show_buttons", selector: { boolean: {} } },
      ],
      computeLabel: (schema) => {
        const key = `editor.${schema.name}`;
        const label = t(key);
        return label === key ? undefined : label;
      },
    };
  }

  static getStubConfig() {
    // No paint here: the car's own Paint select decides unless the card is told.
    return {
      show_title: true,
      show_indicators: true,
      show_range: true,
      show_image: true,
      show_map: true,
      map_height: MAP_HEIGHT_DEFAULT,
      show_controls: true,
      show_buttons: true,
    };
  }

  set hass(hass) {
    this._hass = hass;
    if (!this._config) return;
    if (!this.shadowRoot) {
      this.attachShadow({ mode: "open" });
      this.shadowRoot.innerHTML = `
        <style>${STYLE}</style>
        <ha-card>
          <h1 class="card-header" id="name"></h1>
          <div class="card-content">
            <div class="plate" id="plate"></div>
            <main id="main-wrapper">
              <div id="indicators"></div>
              <div id="images"></div>
              <div id="range_info"></div>
              <div id="controls"></div>
              <div id="mini_map"></div>
              <div id="buttons"></div>
            </main>
          </div>
        </ha-card>
      `;
      this._nameEl = this.shadowRoot.getElementById("name");
      this._bindInteractions();
    }
    this._maybeFetchVehicles();
    this._render();
  }

  _maybeFetchVehicles() {
    const hass = this._hass;
    if (!hass || typeof hass.callWS !== "function") return;
    if (this._vehicles && Date.now() - this._vehiclesFetchedAt < CACHE_MS) return;
    if (this._fetchInFlight) return;
    this._fetchInFlight = hass
      .callWS({ type: WS_TYPE })
      .then((payload) => {
        this._vehicles = Array.isArray(payload?.vehicles) ? payload.vehicles : [];
        this._vehiclesFetchedAt = Date.now();
      })
      .catch(() => {
        // The integration is not loaded (or is older); keep whatever we had.
        this._vehicles = this._vehicles || [];
        this._vehiclesFetchedAt = Date.now();
      })
      .finally(() => {
        this._fetchInFlight = null;
        this._render();
      });
  }

  /** device_id first, then prefix, then the only car there is. */
  _pickVehicle() {
    const cfg = this._config || {};
    const vehicles = this._vehicles || [];
    if (cfg.device_id) return vehicles.find((v) => v.device_id === cfg.device_id) || null;
    if (cfg.prefix) {
      const prefix = String(cfg.prefix).trim().toLowerCase();
      return vehicles.find((v) => v.prefix === prefix) || null;
    }
    return vehicles.length === 1 ? vehicles[0] : null;
  }

  _bindInteractions() {
    if (!this.shadowRoot || this._interactionsBound) return;
    this._interactionsBound = true;
    const entityIdFrom = (node) => {
      if (!(node instanceof Element)) return "";
      const target = node.closest("[data-entity-id]");
      return target ? target.getAttribute("data-entity-id") || "" : "";
    };
    const toggleFrom = (node) => {
      if (!(node instanceof Element)) return "";
      const target = node.closest("[data-toggle]");
      return target ? target.getAttribute("data-toggle") || "" : "";
    };
    const insideTileIcon = (node) => node instanceof Element && Boolean(node.closest("ha-tile-icon"));
    // ha-tile-icon runs Home Assistant's action handler, which cancels the
    // synthesized click on touch devices, so its taps arrive as "action" events.
    this.shadowRoot.addEventListener("click", (event) => {
      const toggle = toggleFrom(event.target);
      if (toggle) {
        this._toggle(toggle);
        return;
      }
      if (insideTileIcon(event.target)) return;
      this._openMoreInfo(entityIdFrom(event.target));
    });
    this.shadowRoot.addEventListener("action", (event) => {
      if (event.detail?.action !== "tap" || !insideTileIcon(event.target)) return;
      this._openMoreInfo(entityIdFrom(event.target));
    });
    this.shadowRoot.addEventListener("keydown", (event) => {
      if (event.key !== "Enter" && event.key !== " ") return;
      const node = event.target;
      if (!(node instanceof Element) || node.getAttribute("role") !== "button") return;
      const entityId = entityIdFrom(node);
      if (!entityId) return;
      event.preventDefault();
      this._openMoreInfo(entityId);
    });
  }

  _toggle(entityId) {
    const [domain] = entityId.split(".");
    if (!this._hass || !domain) return;
    if (domain === "select" || domain === "input_select") {
      // The car's Camera select: ask for a camera, or Off to stop. The car
      // only sends video while this is not Off.
      const current = String(this._hass.states?.[entityId]?.state || "Off");
      const want = current.toLowerCase() === "off" ? this._config?.camera_option || "All" : "Off";
      this._hass.callService(domain, "select_option", { entity_id: entityId, option: want });
      return;
    }
    if (domain === "lock") {
      // Locks have no toggle service.
      const locked = this._hass.states?.[entityId]?.state === "locked";
      this._hass.callService("lock", locked ? "unlock" : "lock", { entity_id: entityId });
      return;
    }
    this._hass.callService(domain, "toggle", { entity_id: entityId });
  }

  // The header must leave the DOM when hidden: ha-card spaces .card-content
  // by sibling position, so a hidden header would still pull the content up.
  _setTitleVisible(visible) {
    const nameEl = this._nameEl;
    if (!nameEl) return;
    if (visible) {
      if (!nameEl.isConnected) this.shadowRoot.querySelector("ha-card").prepend(nameEl);
    } else if (nameEl.isConnected) {
      nameEl.remove();
    }
  }

  _openMoreInfo(entityId) {
    if (!entityId) return;
    this.dispatchEvent(new CustomEvent("hass-more-info", { bubbles: true, composed: true, detail: { entityId } }));
  }

  async _createMapCard(hass, trackerEntityId) {
    try {
      if (!window.loadCardHelpers) return null;
      const helpers = await window.loadCardHelpers();
      if (!helpers?.createCardElement) return null;
      const hasPicture = !!hass?.states?.[trackerEntityId]?.attributes?.entity_picture;
      const mapCard = helpers.createCardElement({
        type: "map",
        entities: hasPicture ? [trackerEntityId] : [{ entity: trackerEntityId, label_mode: "icon" }],
        default_zoom: 14,
        hours_to_show: 24,
      });
      mapCard.layout = "grid";
      mapCard.hass = hass;
      return mapCard;
    } catch {
      return null;
    }
  }

  /** The car's camera, live, in place of the photo, through HA's own player. */
  _renderLive(target, hass, cameraEntityId) {
    if (this._liveCard && this._liveEntity === cameraEntityId && target.contains(this._liveCard)) {
      this._liveCard.hass = hass;
      return;
    }
    target._lastHtml = undefined;
    this._liveEntity = cameraEntityId;
    const token = (this._liveToken || 0) + 1;
    this._liveToken = token;
    const wrap = document.createElement("div");
    wrap.className = "image live";
    target.replaceChildren(wrap);
    (async () => {
      const helpers = window.loadCardHelpers ? await window.loadCardHelpers() : null;
      if (!helpers?.createCardElement || this._liveToken !== token) return;
      const card = helpers.createCardElement({
        type: "picture-entity",
        entity: cameraEntityId,
        camera_view: "live",
        show_name: false,
        show_state: false,
      });
      card.hass = this._hass;
      this._liveCard = card;
      wrap.replaceChildren(card);
    })();
  }

  _renderMap(target, hass, trackerEntityId, t) {
    if (!target) return;
    // This method writes the DOM directly, so the _setHtml cache is stale.
    target._lastHtml = undefined;
    const fallback = (text) => {
      this._cachedMapCard = null;
      this._cachedMapTracker = null;
      target.innerHTML = `<div class="map"><div class="map-fallback">${escapeHtml(text)}</div></div>`;
    };
    if (!trackerEntityId) return fallback(t("no_tracker"));
    if (!hass?.states?.[trackerEntityId]) return fallback(`${t("tracker_unavailable")}: ${trackerEntityId}`);

    // Reuse the map card; only its hass changes.
    if (this._cachedMapCard && this._cachedMapTracker === trackerEntityId && target.contains(this._cachedMapCard)) {
      this._cachedMapCard.hass = hass;
      return;
    }
    this._cachedMapCard = null;
    this._cachedMapTracker = null;
    const renderToken = (this._mapRenderToken || 0) + 1;
    this._mapRenderToken = renderToken;

    const wrapper = document.createElement("div");
    wrapper.className = "map";
    const mapMount = document.createElement("div");
    mapMount.className = "map-mount";
    mapMount.innerHTML = `<div class="map-fallback">${escapeHtml(t("map_loading"))}</div>`;
    wrapper.appendChild(mapMount);
    target.replaceChildren(wrapper);

    this._createMapCard(hass, trackerEntityId).then((mapCard) => {
      if (!target.isConnected || this._mapRenderToken !== renderToken) return;
      if (!mapCard) {
        mapMount.innerHTML = `<div class="map-fallback">${escapeHtml(t("map_failed"))}</div>`;
        return;
      }
      this._cachedMapCard = mapCard;
      this._cachedMapTracker = trackerEntityId;
      mapMount.replaceChildren(mapCard);
    });
  }

  // Compare against the string written last time, not against the live DOM:
  // the browser serializes attributes differently from the template, and a
  // false mismatch would rebuild the section on every state update, which
  // drops hover state and swallows clicks in progress.
  _setHtml(el, html) {
    if (!el || el._lastHtml === html) return;
    el._lastHtml = html;
    el.innerHTML = html;
  }

  _render() {
    if (!this.shadowRoot) return;
    const hass = this._hass;
    const cfg = this._config || {};
    const lang = resolveLang(cfg, hass);
    const t = (key) => localize(lang, key);

    if (this._vehicles === null) return; // first fetch still running
    const vehicle = this._pickVehicle();
    if (!vehicle) {
      this._renderMessage(cfg.device_id || cfg.prefix ? t("vehicle_not_found") : t("select_vehicle"));
      return;
    }

    const $ = (id) => this.shadowRoot.getElementById(id);
    const entities = vehicle.entities || {};
    const read = (key) => hass?.states?.[entities[key]];
    const ent = (key) => entities[key] || "";

    const showTitle = boolConfig(cfg, "show_title", true);
    this._setTitleVisible(showTitle);
    this._nameEl.textContent = showTitle ? vehicle.name || "EX2" : "";
    $("plate").textContent = cfg.license_plate || "";

    // ---- what the car is doing -------------------------------------------
    const soc = toNumber(read("soc"));
    const hasSoc = Number.isFinite(soc);
    const socPct = hasSoc ? clamp(Math.round(soc), 0, 100) : 0;
    const charging = isOn(read("charging"));
    const pluggedKnown = hasUsableState(read("charge_port_connected"));
    const plugged = isOn(read("charge_port_connected"));
    const chargeKw = toNumber(read("charge_power"));
    const dcFast = isOn(read("dc_fast"));
    const speed = toNumber(read("speed"));
    const gear = normalizeState(read("gear"));
    const moving = (Number.isFinite(speed) && speed > 2) || gear === "d" || gear === "r";
    const motionKnown = Number.isFinite(speed) || gear !== "";
    const lockedKnown = hasUsableState(read("helper_locked"));
    const locked = isOn(read("helper_locked"));
    const acOn = isOn(read("ac"));
    const camLive = normalizeState(read("camera")) === "streaming";
    // Asked for on the car's Camera select, but not necessarily sending yet.
    const camRequested = hasUsableState(read("helper_camera")) && normalizeState(read("helper_camera")) !== "off";
    const aux = toNumber(read("aux_12v"));
    const auxLow = Number.isFinite(aux) && aux > 0 && aux < 11.8;

    // ---- indicators ------------------------------------------------------
    const indicatorItems = [
      lockedKnown && {
        icon: locked ? "mdi:car-door-lock" : "mdi:car-door-lock-open",
        stateClass: locked ? "ok" : "alert",
        entity: ent("helper_locked"),
        title: `${t("lock")}: ${locked ? t("locked") : t("unlocked")}`,
      },
      (entities.charging || entities.charge_port_connected) && {
        icon: charging ? "mdi:ev-station" : plugged ? "mdi:ev-plug-type2" : "mdi:power-plug-off-outline",
        stateClass: charging ? "ok charging" : plugged ? "ok" : "",
        entity: ent("charging") || ent("charge_port_connected"),
        title: charging ? t("charging") : plugged ? t("plugged_in") : pluggedKnown ? t("unplugged") : t("not_charging"),
      },
      entities.ac && {
        icon: acOn ? "mdi:air-conditioner" : "mdi:fan-off",
        stateClass: acOn ? "ok" : "",
        entity: ent("ac"),
        title: `${t("ac")}: ${acOn ? t("ac_on") : t("ac_off")}`,
      },
      motionKnown && {
        icon: moving ? "mdi:car-arrow-right" : "mdi:car-brake-parking",
        stateClass: moving ? "ok" : "",
        entity: ent("gear") || ent("speed"),
        title: `${t("motion")}: ${moving ? t("moving") : t("parked")}`,
      },
      entities.aux_12v && Number.isFinite(aux) && {
        icon: "mdi:car-battery",
        stateClass: auxLow ? "alert" : "ok",
        entity: ent("aux_12v"),
        title: `${auxLow ? t("battery_12v_low") : t("battery_12v")}: ${formatState(read("aux_12v"), hass)}`,
      },
      entities.camera && {
        icon: camLive ? "mdi:cctv" : "mdi:cctv-off",
        stateClass: camLive ? "ok" : "",
        entity: ent("camera"),
        title: `${t("camera")}: ${camLive ? t("camera_live") : t("camera_idle")}`,
      },
      entities.fob_watch && {
        icon: "mdi:key-wireless",
        stateClass: isOn(read("fob_watch")) ? "ok" : "",
        entity: ent("fob_watch"),
        title: `${t("fob_watch")}: ${isOn(read("fob_watch")) ? t("on") : t("off")}`,
      },
    ].filter(Boolean);

    this._setHtml(
      $("indicators"),
      boolConfig(cfg, "show_indicators", true) && indicatorItems.length
        ? `<div class="indicators">${indicatorItems.map((i) => iconBadge(i.icon, i.stateClass, i.entity, i.title)).join("")}</div>`
        : ""
    );

    // ---- picture ---------------------------------------------------------
    const imageEl = $("images");
    imageEl.style.setProperty("--image-crop-top", `${numberConfig(cfg, "image_crop_top", 0)}%`);
    imageEl.style.setProperty("--image-crop-bottom", `${numberConfig(cfg, "image_crop_bottom", 0)}%`);
    imageEl.style.setProperty("--image-zoom", numberConfig(cfg, "image_zoom", 100) / 100);
    const showLive = boolConfig(cfg, "show_live", true) && camLive && entities.camera;
    if (showLive) {
      this._renderLive(imageEl, hass, entities.camera);
    } else if (boolConfig(cfg, "show_image", true)) {
      if (this._liveCard) {
        // Back from live video: the section was written directly, so the
        // render cache must not think the photo is still there.
        this._liveCard = null;
        imageEl._lastHtml = undefined;
      }
      const { paint, roof } = resolvePaint(cfg, hass, entities);
      const imageUrl = typeof cfg.image_url === "string" ? cfg.image_url.trim() : "";
      const target = ent("camera") || ent("soc");
      const cls = `image${charging ? " charging" : ""}${moving ? " moving" : ""}`;
      const inner = imageUrl
        ? `<img alt="${escapeHtml(vehicle.name || "EX2")}" src="${escapeHtml(imageUrl)}">`
        : `<img class="car" alt="Geely EX2">`;
      this._setHtml(imageEl, `<div class="${cls}" data-entity-id="${escapeHtml(target)}">${inner}</div>`);
      if (!imageUrl) {
        // The data URL is set on the element, not written into the HTML, so
        // the render cache never compares a 100 kB string per update.
        const key = `${paint}|${roof}`;
        if (this._carKey !== key) {
          this._carKey = key;
          this._carSrc = null;
          paintedCar(paint, roof).then((url) => {
            if (this._carKey !== key) return;
            this._carSrc = url || CAR_IMG;
            this._render();
          });
        }
        const img = imageEl.querySelector("img.car");
        if (img && this._carSrc && img.getAttribute("src") !== this._carSrc) img.setAttribute("src", this._carSrc);
      }
    } else {
      this._setHtml(imageEl, "");
    }

    // ---- battery and range -----------------------------------------------
    const rangeText = formatState(read("range"), hass);
    if (boolConfig(cfg, "show_range", true) && (hasSoc || entities.range)) {
      const energy = toNumber(read("battery_energy"));
      const label = `${hasSoc ? `${socPct}%` : "—"}${Number.isFinite(energy) && energy > 0 ? ` · ${energy.toFixed(1)} kWh` : ""}`;
      let chargeLine = "";
      if (charging) {
        const capacity = toNumber(read("battery_capacity"));
        const hours = Number.isFinite(capacity) && chargeKw > 0 && hasSoc ? (capacity * (100 - socPct)) / 100 / chargeKw : NaN;
        const eta = formatDuration(hours, t);
        const parts = [
          t("charging"),
          Number.isFinite(chargeKw) && chargeKw > 0 ? `${chargeKw.toFixed(1)} kW ${dcFast ? "DC" : "AC"}` : "",
          eta ? `~${eta} ${t("to_full")}` : "",
        ].filter(Boolean);
        chargeLine = `
          <div class="charge-line" data-entity-id="${escapeHtml(ent("charge_power") || ent("charging"))}">
            <ha-icon icon="mdi:lightning-bolt"></ha-icon><span>${escapeHtml(parts.join(" · "))}</span>
          </div>`;
      }
      const barCls = `bar-wrap${charging ? " charging" : ""}${hasSoc && socPct <= 15 && !charging ? " low" : ""}`;
      this._setHtml(
        $("range_info"),
        `<div class="range-box">
          <div class="range-top">
            ${hasSoc ? `<div class="${barCls}" data-entity-id="${escapeHtml(ent("soc"))}" title="${escapeHtml(ent("soc"))}">
              <div class="bar-level" style="width:${socPct}%;"></div>
              <div class="energy-text">${escapeHtml(label)}</div>
            </div>` : ""}
            ${entities.range ? `<div class="range-value" data-entity-id="${escapeHtml(ent("range"))}" title="${escapeHtml(t("range"))}">
              <ha-icon icon="mdi:map-marker-distance"></ha-icon><span>${escapeHtml(rangeText)}</span>
            </div>` : ""}
          </div>
          ${chargeLine}
        </div>`
      );
    } else {
      this._setHtml($("range_info"), "");
    }

    // ---- controls (helpers the car listens to) ---------------------------
    if (boolConfig(cfg, "show_controls", true)) {
      const controls = [
        ["helper_ac", "mdi:air-conditioner", t("ac")],
        ["helper_recirc", "mdi:autorenew", t("recirc")],
        ["helper_front_defrost", "mdi:car-defrost-front", t("defrost")],
        ["helper_wheel_heat", "mdi:steering", t("wheel_heat")],
        ["helper_locked", locked ? "mdi:lock" : "mdi:lock-open-variant", locked ? t("locked") : t("unlocked")],
      ]
        .filter(([key]) => entities[key])
        .map(([key, icon, label]) => ({ icon, label, entity: entities[key], on: isOn(read(key)) }));
      if (entities.helper_camera) {
        controls.push({
          icon: camLive ? "mdi:stop-circle-outline" : "mdi:cctv",
          label: camLive ? t("camera_stop") : camRequested ? t("camera_starting") : t("camera_start"),
          entity: entities.helper_camera,
          on: camRequested || camLive,
        });
      }
      this._setHtml($("controls"), controls.length ? `<div class="controls">${controls.map(controlButton).join("")}</div>` : "");
    } else {
      this._setHtml($("controls"), "");
    }

    // ---- map -------------------------------------------------------------
    const mapEl = $("mini_map");
    mapEl.style.setProperty("--map-height", `${numberConfig(cfg, "map_height", MAP_HEIGHT_DEFAULT)}px`);
    if (boolConfig(cfg, "show_map", true)) this._renderMap(mapEl, hass, entities.device_tracker, t);
    else this._setHtml(mapEl, "");

    // ---- quick info tiles ------------------------------------------------
    if (boolConfig(cfg, "show_buttons", true)) {
      const setpoint = read("hvac_temp");
      const quickItems = [
        entities.device_tracker && {
          icon: "mdi:map-marker",
          label: t("location"),
          value: humanizeLocationState(read("device_tracker")?.state, t),
          entity: ent("device_tracker"),
        },
        entities.range && { icon: "mdi:map-marker-distance", label: t("range"), value: rangeText, entity: ent("range") },
        motionKnown && {
          icon: moving ? "mdi:speedometer" : "mdi:car-brake-parking",
          label: t("motion"),
          value: moving && Number.isFinite(speed) ? formatState(read("speed"), hass) : t("parked"),
          entity: ent("speed") || ent("gear"),
        },
        (entities.charging || entities.charge_port_connected) && {
          icon: charging ? "mdi:ev-station" : "mdi:ev-plug-type2",
          label: t("charging"),
          value: charging
            ? Number.isFinite(chargeKw) && chargeKw > 0 ? `${chargeKw.toFixed(1)} kW` : t("charging")
            : plugged ? t("plugged_in") : t("not_charging"),
          entity: ent("charge_power") || ent("charging"),
          cls: charging ? "good" : "",
        },
        entities.odometer && { icon: "mdi:counter", label: t("mileage"), value: formatState(read("odometer"), hass), entity: ent("odometer") },
        entities.outside_temp && { icon: "mdi:thermometer", label: t("outside"), value: formatState(read("outside_temp"), hass), entity: ent("outside_temp") },
        entities.hvac_temp && hasUsableState(setpoint) && {
          icon: acOn ? "mdi:air-conditioner" : "mdi:thermostat",
          label: t("climate"),
          value: `${formatState(setpoint, hass)}${entities.ac ? ` · ${acOn ? t("ac_on") : t("ac_off")}` : ""}`,
          entity: ent("helper_temp") || ent("hvac_temp"),
        },
        entities.consumption && { icon: "mdi:lightning-bolt", label: t("consumption"), value: formatState(read("consumption"), hass), entity: ent("consumption") },
        entities.aux_12v && {
          icon: "mdi:car-battery",
          label: t("battery_12v"),
          value: formatState(read("aux_12v"), hass),
          entity: ent("aux_12v"),
          cls: auxLow ? "alert" : "",
        },
        entities.last_key_profile && hasUsableState(read("last_key_profile")) && normalizeState(read("last_key_profile")) !== "none" && {
          icon: "mdi:key-variant",
          label: t("last_key"),
          value: read("last_key_profile").state,
          entity: ent("last_key") || ent("last_key_profile"),
        },
      ].filter(Boolean);
      this._setHtml($("buttons"), tileGrid(quickItems));
    } else {
      this._setHtml($("buttons"), "");
    }
  }

  _renderMessage(message) {
    if (!this.shadowRoot) return;
    this._setTitleVisible(true);
    this._nameEl.textContent = "EX Control";
    this.shadowRoot.getElementById("plate").textContent = message;
    for (const id of ["indicators", "images", "range_info", "controls", "mini_map", "buttons"]) {
      this._setHtml(this.shadowRoot.getElementById(id), "");
    }
    this._cachedMapCard = null;
    this._liveCard = null;
  }
}

if (!customElements.get(CARD_TAG)) {
  customElements.define(CARD_TAG, ExControlVehicleCard);
}

const cards = ensureCustomCardsArray();
if (!cards.some((c) => c && c.type === CARD_TAG)) {
  cards.push({
    type: CARD_TAG,
    // The picker searches name and description: "geely", "ex2", "e2" and
    // "xingyuan" all have to find it.
    name: "Geely EX2 (EX Control)",
    description: "Geely EX2 / E2 / Xingyuan car card: picture in your paint colour, lock, charging and climate state, battery, range, map and quick info.",
    preview: true,
  });
}
