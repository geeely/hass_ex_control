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
 * The car picture is our own drawing of the Geely EX2 (E2 / Xingyuan), not
 * Geely artwork: the body is one SVG path filled with a CSS variable, so any
 * paint, factory or custom, is just a colour. A photo can replace it
 * (image_url) for anyone who prefers their own.
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
    "editor.image_url": "Photo instead of the drawing (URL, optional)",
    "editor.show_indicators": "Show indicator row",
    "editor.show_range": "Show battery and range bar",
    "editor.show_image": "Show car picture",
    "editor.image_crop_top": "Image crop top",
    "editor.image_crop_bottom": "Image crop bottom",
    "editor.image_zoom": "Image zoom",
    "editor.show_map": "Show mini map",
    "editor.map_height": "Mini map height",
    "editor.show_controls": "Show climate and lock controls",
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

/* The Geely EX2 from the side, front to the right, drawn to its real
 * proportions (4135 mm long, 2650 mm wheelbase, 1573 mm tall). Paint and
 * roof come from --ex-paint / --ex-roof; the shading on top is fixed white
 * and black at low opacity, so it reads on any paint. */
const carSvg = (uid) => {
  const wheel = (cx) => `
    <g transform="translate(${cx} 245)">
      <circle r="57" fill="#141518"/>
      <circle r="51" fill="none" stroke="#25272c" stroke-width="2"/>
      <circle r="41" fill="url(#${uid}-rim)"/>
      ${[0, 72, 144, 216, 288].map((a) => `<path transform="rotate(${a}) scale(1.08)" d="M -7,-34 C -13,-22 -12,-13 -5,-11 L 5,-11 C 12,-13 13,-22 7,-34 Z" fill="#2b2e33"/>`).join("")}
      <circle r="41" fill="none" stroke="#5d636a" stroke-width="1.5"/>
      <circle r="8" fill="#c9cdd2" stroke="#6b7077" stroke-width="1.5"/>
    </g>`;
  const body = "M 60,275 C 54,262 50,240 50,214 C 50,192 52,172 57,156 C 62,128 70,86 80,56 C 84,46 92,41 106,40 C 200,35 320,34 392,38 C 408,39 418,44 428,52 C 470,84 512,112 556,128 C 620,136 680,144 714,158 C 736,168 748,184 751,206 C 753,226 752,250 746,268 C 744,273 740,275 734,275 L 671,275 A 64 64 0 1 0 559,275 L 223,275 A 64 64 0 1 0 111,275 Z";
  const roof = "M 80,56 C 84,46 92,41 106,40 C 200,35 320,34 392,38 C 408,39 418,44 428,52 C 470,84 512,112 556,128 L 540,130 L 424,64 C 418,58 410,54 398,54 L 130,56 C 114,56 104,64 100,76 L 92,108 L 76,110 Z";
  const dlo = "M 540,130 L 424,64 C 418,58 410,54 398,54 L 130,56 C 114,56 104,64 100,76 L 92,108 C 90,118 94,124 104,124 Z";
  return `
  <svg viewBox="30 20 740 295" xmlns="http://www.w3.org/2000/svg" role="img" aria-label="Geely EX2">
    <defs>
      <linearGradient id="${uid}-shade" x1="0" y1="34" x2="0" y2="275" gradientUnits="userSpaceOnUse">
        <stop offset="0" stop-color="#fff" stop-opacity=".34"/>
        <stop offset=".32" stop-color="#fff" stop-opacity=".14"/>
        <stop offset=".47" stop-color="#fff" stop-opacity="0"/>
        <stop offset=".6" stop-color="#000" stop-opacity="0"/>
        <stop offset="1" stop-color="#000" stop-opacity=".42"/>
      </linearGradient>
      <linearGradient id="${uid}-glass" x1="0" y1="52" x2="0" y2="130" gradientUnits="userSpaceOnUse">
        <stop offset="0" stop-color="#3a4250"/>
        <stop offset=".55" stop-color="#151a22"/>
        <stop offset="1" stop-color="#0c0f14"/>
      </linearGradient>
      <radialGradient id="${uid}-rim" cx=".4" cy=".35" r=".75">
        <stop offset="0" stop-color="#eef0f3"/>
        <stop offset=".7" stop-color="#a9aeb5"/>
        <stop offset="1" stop-color="#7d838b"/>
      </radialGradient>
      <filter id="${uid}-blur" x="-10%" y="-200%" width="120%" height="500%"><feGaussianBlur stdDeviation="6"/></filter>
      <filter id="${uid}-glow" x="-50%" y="-50%" width="200%" height="200%"><feGaussianBlur stdDeviation="2.5" result="b"/><feMerge><feMergeNode in="b"/><feMergeNode in="SourceGraphic"/></feMerge></filter>
      <clipPath id="${uid}-clip"><path d="${body}"/></clipPath>
    </defs>
    <ellipse cx="400" cy="301" rx="350" ry="9" fill="#000" opacity=".38" filter="url(#${uid}-blur)"/>
    <path class="paint" d="${body}" fill="var(--ex-paint, #e9e9e4)"/>
    <path class="roof" d="${roof}" fill="var(--ex-roof, var(--ex-paint, #e9e9e4))"/>
    <g clip-path="url(#${uid}-clip)">
      <rect x="40" y="30" width="720" height="250" fill="url(#${uid}-shade)"/>
      <path d="M 64,150 C 250,149 500,151 712,160" fill="none" stroke="#fff" stroke-opacity=".5" stroke-width="1.6"/>
      <path d="M 66,154 C 250,153 500,155 710,164" fill="none" stroke="#000" stroke-opacity=".12" stroke-width="2"/>
      <path d="M 232,236 C 350,232 460,232 556,236" fill="none" stroke="#000" stroke-opacity=".16" stroke-width="2.5"/>
      <path d="M 53,256 L 104,262 L 111,275 L 50,275 Z" fill="#1b1d21"/>
      <path d="M 704,262 L 752,254 L 752,275 L 671,275 Z" fill="#1b1d21"/>
      <path d="M 223,275 L 228,263 L 554,263 L 559,275 Z" fill="#1b1d21"/>
    </g>
    <path d="M 671,275 A 64 64 0 1 0 559,275" fill="none" stroke="#1b1d21" stroke-width="9"/>
    <path d="M 223,275 A 64 64 0 1 0 111,275" fill="none" stroke="#1b1d21" stroke-width="9"/>
    <path d="${dlo}" fill="url(#${uid}-glass)"/>
    <path d="M 64,142 C 68,112 74,84 82,60 L 94,58 C 88,84 82,112 76,140 Z" fill="#11151b"/>
    <path d="M 296,55 L 309,55 L 307,127 L 294,127 Z" fill="#101317"/>
    <path d="M 160,56 L 173,56 L 151,125 L 138,125 Z" fill="#101317"/>
    <path d="M 100,76 C 104,64 114,56 130,56 L 398,54 C 410,54 418,58 424,64" fill="none" stroke="#dfe3e8" stroke-opacity=".7" stroke-width="1.5"/>
    <g fill="none" stroke="#000" stroke-opacity=".32" stroke-width="1.2">
      <path d="M 301,128 L 303,262"/>
      <path d="M 538,132 C 545,170 546,212 540,234"/>
      <path d="M 150,126 C 156,160 170,188 198,194"/>
    </g>
    <rect x="256" y="160" width="30" height="5" rx="2.5" fill="#000" opacity=".3"/>
    <rect x="466" y="162" width="30" height="5" rx="2.5" fill="#000" opacity=".3"/>
    <path d="M 512,128 C 514,115 527,109 543,111 C 552,113 553,124 545,129 Z" fill="var(--ex-paint, #e9e9e4)"/>
    <path d="M 512,128 C 514,115 527,109 543,111 C 552,113 553,124 545,129 Z" fill="url(#${uid}-shade)"/>
    <path d="M 514,128 L 544,129" stroke="#1b1d21" stroke-width="3"/>
    <path class="headlight" d="M 698,157 C 720,164 738,175 748,193" fill="none" stroke="#eef6ff" stroke-width="3.5" stroke-linecap="round" filter="url(#${uid}-glow)"/>
    <path d="M 726,214 L 749,219" stroke="#26292e" stroke-width="6" stroke-linecap="round"/>
    <path class="taillight" d="M 51,166 C 54,160 60,155 70,152" fill="none" stroke="#e0212f" stroke-width="5" stroke-linecap="round" filter="url(#${uid}-glow)"/>
    <g class="port"><rect x="96" y="140" width="16" height="11" rx="3" fill="#1b1d21"/><circle class="port-glow" cx="104" cy="145.5" r="9" fill="var(--ex-charge, #4caf50)" opacity=".85" filter="url(#${uid}-glow)"/></g>
    <path d="M 671,275 A 64 64 0 1 0 559,275 Z M 223,275 A 64 64 0 1 0 111,275 Z" fill="#0b0c0e"/>
    ${wheel(167)}${wheel(615)}
  </svg>`;
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
  .image img, .image svg {
    width: 100%;
    display: block;
    object-fit: cover;
    object-position: center;
    transform-origin: center center;
    transform: scale(var(--image-zoom, 1));
    margin-top: calc(-1 * var(--image-crop-top, 0%));
    margin-bottom: calc(-1 * var(--image-crop-bottom, 0%));
  }
  .image.charging img, .image.charging svg { animation: chargingImagePulse 2.2s ease-in-out infinite; }
  .image svg .port { display: none; }
  .image.charging svg .port { display: inline; }
  .image.charging svg .port-glow { animation: portPulse 1.4s ease-in-out infinite; }
  .image svg .headlight { opacity: 0.55; }
  .image.moving svg .headlight, .image.moving svg .taillight { opacity: 1; }
  .image svg .taillight { opacity: 0.6; }

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
  @keyframes portPulse { 0%, 100% { opacity: 0.35; } 50% { opacity: 1; } }
  @media (prefers-reduced-motion: reduce) {
    .indicator.charging, .bar-wrap.charging .bar-level, .bar-wrap.charging .bar-level::after,
    .image.charging img, .image.charging svg, .image.charging svg .port-glow { animation: none; }
  }
`;

class ExControlVehicleCard extends HTMLElement {
  setConfig(config) {
    const cfg = config || {};
    this._config = cfg.license_plate ? { ...cfg, license_plate: sanitizePlate(cfg.license_plate) } : cfg;
    this._vehicles = null;
    this._vehiclesFetchedAt = 0;
    this._fetchInFlight = null;
    // One id per card, so two cards' SVG gradients never collide.
    this._uid = this._uid || `ex${Math.random().toString(36).slice(2, 8)}`;
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
    if (boolConfig(cfg, "show_image", true)) {
      const { paint, roof } = resolvePaint(cfg, hass, entities);
      const imageUrl = typeof cfg.image_url === "string" ? cfg.image_url.trim() : "";
      const target = ent("camera") || ent("soc");
      const cls = `image${charging ? " charging" : ""}${moving ? " moving" : ""}`;
      const inner = imageUrl
        ? `<img alt="${escapeHtml(vehicle.name || "EX2")}" src="${escapeHtml(imageUrl)}">`
        : carSvg(this._uid);
      this._setHtml(
        imageEl,
        `<div class="${cls}" style="--ex-paint:${paint};--ex-roof:${roof}" data-entity-id="${escapeHtml(target)}">${inner}</div>`
      );
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
  }
}

if (!customElements.get(CARD_TAG)) {
  customElements.define(CARD_TAG, ExControlVehicleCard);
}

const cards = ensureCustomCardsArray();
if (!cards.some((c) => c && c.type === CARD_TAG)) {
  cards.push({
    type: CARD_TAG,
    name: "EX Control Vehicle",
    description: "Your EX2 in its own paint, with lock, charge and climate state, battery, range, map and quick info",
    preview: true,
  });
}
