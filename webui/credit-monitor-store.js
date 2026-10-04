import { createStore } from "/js/AlpineStore.js";
import { callJsonApi } from "/js/api.js";
import {
  toastFrontendError,
  toastFrontendWarning,
} from "/components/notifications/notification-store.js";

const API_PATH = "/plugins/openrouter_credit_monitor/status";

const USD = new Intl.NumberFormat("en-US", {
  style: "currency",
  currency: "USD",
});

let pollTimer = null;
let notifying = false; // one in-flight notification refresh

export const store = createStore("openrouterCreditStore", {
  status: "loading", // loading|normal|warning|critical|unavailable|not_configured
  remaining: null,
  keyLabel: null,
  showBalance: true,
  staleAgeSeconds: null,
  lastUpdatedLabel: "",
  refreshIntervalSeconds: 60,
  open: false,
  busy: false,
  lastFetchAt: 0,
  lastNotifiedStatus: "",

  init() {},

  onOpen() {
    this.schedulePoll(1500);
    document.addEventListener("modal-closed", this._onModalClosed);
  },

  cleanup() {
    if (pollTimer) {
      clearTimeout(pollTimer);
      pollTimer = null;
    }
    document.removeEventListener("modal-closed", this._onModalClosed);
  },

  _onModalClosed: null, // assigned below to keep stable reference

  schedulePoll(delayMs = 0) {
    if (pollTimer) clearTimeout(pollTimer);
    pollTimer = setTimeout(async () => {
      await this.refresh();
      if (this.refreshIntervalSeconds >= 30) {
        this.schedulePoll(this.refreshIntervalSeconds * 1000);
      } else {
        this.schedulePoll(60000);
      }
    }, delayMs);
  },

  async refresh({ force = false, notify = false } = {}) {
    if (this.busy) return;
    this.busy = true;
    try {
      const data = await callJsonApi(API_PATH, { force });
      if (data && typeof data === "object") {
        this.applyStatus(data);
        if (notify) this.notifyStatusChange(data, true);
      }
    } catch (e) {
      // Backend unreachable: keep last known state, show unavailable.
      this.status = "unavailable";
      if (notify) {
        toastFrontendError("Could not refresh OpenRouter balance.", "OpenRouter Credit Monitor");
      }
    } finally {
      this.busy = false;
    }
  },

  applyStatus(data) {
    const previous = this.status;
    this.status = String(data.status || "unavailable");
    this.remaining = typeof data.remaining === "number" ? data.remaining : null;
        this.keyLabel = "JPHsystems"
    this.showBalance = data.show_balance_in_ui !== false;
    this.staleAgeSeconds =
      typeof data.age_seconds === "number" ? data.age_seconds : null;
    this.refreshIntervalSeconds =
      typeof data.refresh_interval_seconds === "number" && data.refresh_interval_seconds >= 30
        ? data.refresh_interval_seconds
        : 60;
    this.lastUpdatedLabel = this._ageLabel(this.staleAgeSeconds);
    this.lastFetchAt = Date.now();

    // Threshold transition notifications (avoid spam on first load).
    if (previous !== this.status && this.status !== "loading") {
      this.notifyStatusChange(data, false);
    }
  },

  notifyStatusChange(data, manual) {
    const status = String(data.status || "");
    if (status === this.lastNotifiedStatus && !manual) return;
    this.lastNotifiedStatus = status;
    if (manual) {
      if (status === "normal") {
        // No toast for healthy manual refresh; popover shows the value.
      } else if (status === "not_configured") {
        toastFrontendWarning(
          "Add an OpenRouter Management Key in the plugin settings.",
          "OpenRouter Credit Monitor"
        );
      } else if (status === "unavailable") {
        toastFrontendError(
          "OpenRouter is not reachable. Showing last known balance if available.",
          "OpenRouter Credit Monitor"
        );
      }
      return;
    }
    if (status === "warning") {
      toastFrontendWarning(
        `OpenRouter credits are low (${this.balanceLabel}).`,
        "OpenRouter Credit Monitor"
      );
    } else if (status === "critical") {
      toastFrontendError(
        `OpenRouter credits are critical (${this.balanceLabel}).`,
        "OpenRouter Credit Monitor"
      );
    }
  },

  _ageLabel(seconds) {
    if (typeof seconds !== "number" || seconds < 0) return "";
    if (seconds < 60) return "just now";
    const minutes = Math.floor(seconds / 60);
    if (minutes < 60) return `${minutes} min ago`;
    const hours = Math.floor(minutes / 60);
    return `${hours} h ago`;
  },

  get balanceLabel() {
    if (this.status === "not_configured") return "Setup required";
    if (this.status === "unavailable" && this.remaining === null) return "Unavailable";
    if (this.remaining === null) return "–";
    return USD.format(this.remaining);
  },

  get statusLabel() {
    if (this.status === "warning") return "Low";
    if (this.status === "critical") return "Critical";
    if (this.status === "unavailable") return "Unavailable";
    return "";
  },



  get statusClass() {
    return `ocr-${this.status}`;
  },

  get indicatorVisible() {
    return this.status !== "loading" && this.showBalance;
  },

  toggle() {
    this.open = !this.open;
  },

  async manualRefresh() {
    await this.refresh({ force: true, notify: true });
  },

  async openSettings() {
    try {
      const { store: pluginSettingsStore } = await import(
        "/components/plugins/plugin-settings-store.js"
      );
      await pluginSettingsStore.openConfig("openrouter_credit_monitor", "", "", {tab: "config"});
      this.open = false; // close popover
    } catch (e) {
      console.error("openSettings error:", e);
      toastFrontendError("Could not open plugin settings.", "OpenRouter Credit Monitor");
    }
  },
});

store._onModalClosed = (event) => {
  const path = event?.detail?.modalPath || "";
  if (path.includes("plugin-settings")) {
    store.refresh({ force: true });
  }
};
