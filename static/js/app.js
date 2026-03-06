/**
 * NFL Mock Draft 2026 — Frontend Application
 *
 * Handles:
 *  - Round tab switching
 *  - Pick row expand/collapse (detail panel)
 *  - Stats tab switching per pick
 *  - Injury history toggle
 *  - Image fallback for broken logos
 */

"use strict";

// ============================================================
// Round Tabs
// ============================================================

/**
 * Activate a specific round tab and show its panel.
 * @param {number} round - Round number (1, 2, or 3)
 */
function activateRound(round) {
  // Update tab styling
  document.querySelectorAll(".round-tab").forEach((tab) => {
    tab.classList.toggle("active", parseInt(tab.dataset.round) === round);
  });

  // Show/hide panels
  document.querySelectorAll(".round-panel").forEach((panel) => {
    panel.classList.toggle("active", parseInt(panel.dataset.round) === round);
  });

  // Persist selection in session storage so refresh stays on same round
  sessionStorage.setItem("activeRound", round);
}

// ============================================================
// Pick Row Expand / Collapse
// ============================================================

/**
 * Toggle the detail panel for a given pick row.
 * @param {HTMLElement} row - The pick-row <tr> element that was clicked.
 */
function togglePickDetail(row) {
  const pickNum = row.dataset.pickNumber;
  const detailRow = document.getElementById(`detail-${pickNum}`);
  if (!detailRow) return;

  const isExpanded = row.classList.contains("expanded");

  // Collapse all currently open rows first (accordion-style optional;
  // currently we allow multiple open — remove the block below to enforce accordion)
  // document.querySelectorAll(".pick-row.expanded").forEach(r => {
  //   if (r !== row) collapsePickRow(r);
  // });

  if (isExpanded) {
    collapsePickRow(row, detailRow);
  } else {
    expandPickRow(row, detailRow);
  }
}

/**
 * Expand a pick row to show its detail panel.
 * @param {HTMLElement} row - The pick-row element.
 * @param {HTMLElement} detailRow - The corresponding detail-row element.
 */
function expandPickRow(row, detailRow) {
  row.classList.add("expanded");
  detailRow.classList.add("visible");
}

/**
 * Collapse a pick row and hide its detail panel.
 * @param {HTMLElement} row - The pick-row element.
 * @param {HTMLElement} detailRow - The corresponding detail-row element.
 */
function collapsePickRow(row, detailRow) {
  row.classList.remove("expanded");
  detailRow.classList.remove("visible");
}

// ============================================================
// Stats Tabs (per pick)
// ============================================================

/**
 * Switch the active stats view tab within a pick's detail panel.
 * @param {HTMLElement} tabEl - The clicked stats-tab element.
 * @param {string} pickNum - The pick number string.
 * @param {string} viewName - The stats view name to activate.
 */
function activateStatsTab(tabEl, pickNum, viewName) {
  // Deactivate all tabs in this pick's stats panel
  const panel = tabEl.closest(".detail-panel");
  panel.querySelectorAll(".stats-tab").forEach((t) => t.classList.remove("active"));
  panel.querySelectorAll(".stats-view").forEach((v) => v.classList.remove("active"));

  // Activate selected tab and view
  tabEl.classList.add("active");
  const view = panel.querySelector(`.stats-view[data-view="${viewName}"]`);
  if (view) view.classList.add("active");
}

// ============================================================
// Injury History Toggle
// ============================================================

/**
 * Toggle visibility of injury list for a pick.
 * @param {HTMLElement} toggleEl - The toggle button element.
 */
function toggleInjuryList(toggleEl) {
  const list = toggleEl.nextElementSibling;
  if (!list) return;
  const isOpen = list.classList.contains("open");
  list.classList.toggle("open", !isOpen);
  toggleEl.querySelector(".toggle-arrow").textContent = isOpen ? "▸" : "▾";
}

// ============================================================
// Logo Image Fallback
// ============================================================

/**
 * Replace a broken logo image src with a text fallback.
 * @param {HTMLImageElement} img - The broken img element.
 * @param {string} abbrev - Team abbreviation for fallback text.
 */
function onLogoError(img, abbrev) {
  img.onerror = null; // Prevent infinite loop
  img.style.display = "none";

  // Insert a text abbrev badge next to the broken image
  const badge = document.createElement("span");
  badge.textContent = abbrev.toUpperCase();
  badge.style.cssText =
    "display:inline-flex;align-items:center;justify-content:center;" +
    "width:48px;height:48px;border-radius:50%;background:#21262d;" +
    "border:2px solid #30363d;font-size:0.65rem;font-weight:700;" +
    "color:#8b949e;letter-spacing:0.04em;";
  img.parentNode.insertBefore(badge, img.nextSibling);
}

// ============================================================
// Height Formatting
// ============================================================

/**
 * Convert height in total inches to feet-inches display string.
 * @param {number|null} totalInches - Height in inches.
 * @returns {string} Formatted string (e.g. "6'4\"") or "—".
 */
function formatHeight(totalInches) {
  if (!totalInches) return "—";
  const feet = Math.floor(totalInches / 12);
  const inches = totalInches % 12;
  return `${feet}'${inches}"`;
}

// ============================================================
// Predictions
// ============================================================

/**
 * Call the predictions API (scrape=false for speed), then reload the page.
 * Shows a loading spinner on the button and disables it during the run.
 */
async function runPredictions() {
  const btn = document.getElementById("predictions-btn");
  const icon = document.getElementById("predictions-btn-icon");
  const label = document.getElementById("predictions-btn-label");
  const ts = document.getElementById("predictions-timestamp");

  if (!btn) return;

  // Loading state
  btn.disabled = true;
  btn.classList.add("loading");
  if (icon) icon.textContent = "⏳";
  if (label) label.textContent = "Running…";

  try {
    const res = await fetch("/api/predictions/run?scrape=false", { method: "POST" });
    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: "Unknown error" }));
      throw new Error(err.detail || `HTTP ${res.status}`);
    }
    const data = await res.json();
    if (icon) icon.textContent = "✓";
    if (label) label.textContent = `Done — ${data.picks_assigned} picks`;
    // Reload after a brief pause so the user sees the success state
    setTimeout(() => window.location.reload(), 800);
  } catch (err) {
    btn.disabled = false;
    btn.classList.remove("loading");
    btn.classList.add("error");
    if (icon) icon.textContent = "✗";
    if (label) label.textContent = "Error — retry";
    console.error("Predictions run failed:", err);
    // Reset error state after 3 seconds
    setTimeout(() => {
      btn.classList.remove("error");
      if (icon) icon.textContent = "⟳";
      if (label) label.textContent = "Refresh Predictions";
    }, 3000);
  }
}

// ============================================================
// DOM Initialisation
// ============================================================

document.addEventListener("DOMContentLoaded", () => {
  // Restore last active round or default to round 1
  const savedRound = parseInt(sessionStorage.getItem("activeRound") || "1");
  activateRound(savedRound);

  // Wire round tab clicks
  document.querySelectorAll(".round-tab").forEach((tab) => {
    tab.addEventListener("click", () => activateRound(parseInt(tab.dataset.round)));
  });

  // Wire pick row clicks
  document.querySelectorAll(".pick-row").forEach((row) => {
    row.addEventListener("click", () => togglePickDetail(row));
  });

  // Wire stats tab clicks (event delegation on each detail panel)
  document.addEventListener("click", (e) => {
    const statsTab = e.target.closest(".stats-tab");
    if (!statsTab) return;
    const panel = statsTab.closest(".detail-panel");
    const viewName = statsTab.dataset.view;
    if (panel && viewName) {
      activateStatsTab(statsTab, null, viewName);
      e.stopPropagation(); // Don't collapse the row
    }
  });

  // Wire injury toggle clicks
  document.addEventListener("click", (e) => {
    const toggle = e.target.closest(".injury-toggle");
    if (!toggle) return;
    toggleInjuryList(toggle);
    e.stopPropagation();
  });

  // Render height values in bio cells
  document.querySelectorAll(".height-display").forEach((el) => {
    const inches = parseInt(el.dataset.inches);
    if (!isNaN(inches)) el.textContent = formatHeight(inches);
  });
});
