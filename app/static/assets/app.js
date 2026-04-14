const state = {
  filters: {},
  images: [],
  selectedId: null,
  selectedFiles: [],
  fileMetadata: {},
  selectMode: false,
  selectedForDelete: new Set(),
};

const el = (id) => document.getElementById(id);

function prettyLabel(v) {
  if (v == null) return "";
  const s = String(v);
  if (!s) return s;
  // Title-case for display only (keep underlying values unchanged for filtering).
  // Preserve acronyms/codes like "SS26", "FW24", "USA" (all-caps or contains digits).
  if (/[0-9]/.test(s) || (s.toUpperCase() === s && /[A-Z]/.test(s))) return s;
  return s
    .split(/(\s+|[-_])/g)
    .map((part) => {
      if (part.trim() === "" || part === "-" || part === "_") return part;
      return part.charAt(0).toUpperCase() + part.slice(1);
    })
    .join("");
}

function fileKey(file) {
  return [file.name, file.size, file.lastModified].join("::");
}

function renderSelectedFiles() {
  const host = el("file-names");
  if (!host) return;
  const files = state.selectedFiles || [];
  host.innerHTML = "";
  if (!files.length) return;
  for (let i = 0; i < files.length; i++) {
    const f = files[i];
    const chip = document.createElement("span");
    chip.className = "name";

    const label = document.createElement("span");
    label.className = "name-label";
    label.textContent = f.name;

    const rm = document.createElement("button");
    rm.type = "button";
    rm.className = "remove";
    rm.title = "Remove from upload";
    rm.setAttribute("aria-label", `Remove ${f.name}`);
    rm.textContent = "×";
    rm.addEventListener("click", () => {
      state.selectedFiles.splice(i, 1);
      const live = new Set(state.selectedFiles.map((x) => fileKey(x)));
      for (const k of Object.keys(state.fileMetadata)) {
        if (!live.has(k)) delete state.fileMetadata[k];
      }
      try {
        const dt = new DataTransfer();
        for (const ff of state.selectedFiles) dt.items.add(ff);
        const fileInput = el("file");
        if (fileInput) fileInput.files = dt.files;
      } catch (_) {}
      renderSelectedFiles();
      renderBatchMetadataForms();
    });

    chip.appendChild(label);
    chip.appendChild(rm);
    host.appendChild(chip);
  }
}

function renderBatchMetadataForms() {
  const host = el("batch-meta");
  if (!host) return;
  host.innerHTML = "";
  const files = state.selectedFiles || [];
  if (!files.length) return;

  for (const file of files) {
    const key = fileKey(file);
    if (!state.fileMetadata[key]) {
      state.fileMetadata[key] = {
        designer: "",
        captured_year: "",
        captured_month: "",
        captured_season: "",
      };
    }
    const m = state.fileMetadata[key];
    const row = document.createElement("div");
    row.className = "meta-row";
    row.innerHTML = `
      <div class="title">${file.name}</div>
      <div class="optional-meta-grid">
        <input type="text" data-k="${key}" data-field="designer" placeholder="Designer / team" value="${m.designer || ""}" />
        <input type="number" data-k="${key}" data-field="captured_year" placeholder="Year" min="1990" max="2035" value="${m.captured_year || ""}" />
        <input type="number" data-k="${key}" data-field="captured_month" placeholder="Month" min="1" max="12" value="${m.captured_month || ""}" />
        <input type="text" data-k="${key}" data-field="captured_season" placeholder="Captured season (e.g. SS26)" value="${m.captured_season || ""}" />
      </div>
    `;
    host.appendChild(row);
  }

  for (const input of host.querySelectorAll("input[data-k][data-field]")) {
    input.addEventListener("input", () => {
      const k = input.dataset.k;
      const field = input.dataset.field;
      if (!state.fileMetadata[k]) state.fileMetadata[k] = {};
      state.fileMetadata[k][field] = input.value;
    });
  }
}

async function fetchJSON(path) {
  const res = await fetch(path);
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

function debounce(fn, ms) {
  let t;
  return (...args) => {
    clearTimeout(t);
    t = setTimeout(() => fn(...args), ms);
  };
}

async function loadFilters() {
  const data = await fetchJSON("/api/filters");
  const host = el("filter-groups");
  host.innerHTML = "";
  const defs = [
    ["garment_type", "Garment type"],
    ["style", "Style"],
    ["material", "Material"],
    ["pattern", "Pattern"],
    ["season", "Season"],
    ["occasion", "Occasion"],
    ["consumer_profile", "Consumer profile"],
    ["trend_notes", "Trend notes"],
    ["color_palette", "Color"],
    ["continent", "Continent"],
    ["country", "Country"],
    ["city", "City"],
    ["designer", "Designer"],
    ["captured_year", "Year"],
    ["captured_month", "Month"],
    ["captured_season", "Capture season"],
  ];
  for (const [key, label] of defs) {
    const values = data[key];
    if (!values || !values.length) continue;
    const wrap = document.createElement("label");
    wrap.textContent = label;
    const sel = document.createElement("select");
    sel.dataset.key = key;
    const opt0 = document.createElement("option");
    opt0.value = "";
    opt0.textContent = "Any";
    sel.appendChild(opt0);
    for (const v of values) {
      const o = document.createElement("option");
      o.value = String(v);
      o.textContent = typeof v === "string" ? prettyLabel(v) : String(v);
      sel.appendChild(o);
    }
    sel.addEventListener("change", () => {
      state.filters[key] = sel.value || null;
      loadImages();
    });
    wrap.appendChild(sel);
    host.appendChild(wrap);
  }
}

function buildQuery() {
  const params = new URLSearchParams();
  const q = el("q").value.trim();
  if (q) params.set("q", q);
  for (const [k, v] of Object.entries(state.filters)) {
    if (v) params.set(k, v);
  }
  const s = params.toString();
  return s ? `?${s}` : "";
}

async function loadImages() {
  const data = await fetchJSON(`/api/images${buildQuery()}`);
  state.images = data;
  el("count").textContent = `${data.length} image${data.length === 1 ? "" : "s"}`;
  const grid = el("grid");
  grid.innerHTML = "";

  // prune selected ids that disappeared
  const liveIds = new Set(data.map((x) => x.id));
  for (const id of Array.from(state.selectedForDelete)) {
    if (!liveIds.has(id)) state.selectedForDelete.delete(id);
  }
  updateSelectUI();

  for (const im of data) {
    const card = document.createElement("article");
    card.className = "card";
    card.tabIndex = 0;
    if (state.selectMode) card.classList.add("selectable");
    if (state.selectedForDelete.has(im.id)) card.classList.add("sel");
    if (state.selectMode) {
      const check = document.createElement("div");
      check.className = "check";
      check.textContent = state.selectedForDelete.has(im.id) ? "✓" : "";
      card.appendChild(check);
    }
    const img = document.createElement("img");
    img.src = im.file_path;
    img.alt = im.description || "Inspiration image";
    const cap = document.createElement("div");
    cap.className = "cap";
    const title = im.ai_title || im.ai_attributes?.garment_type || "Untagged";
    cap.textContent = prettyLabel(title);
    card.appendChild(img);
    card.appendChild(cap);
    card.addEventListener("click", () => {
      if (state.selectMode) {
        toggleSelected(im.id, card);
        return;
      }
      openModal(im.id);
    });
    card.addEventListener("keydown", (e) => {
      if (e.key === "Enter") {
        if (state.selectMode) {
          toggleSelected(im.id, card);
          return;
        }
        openModal(im.id);
      }
    });
    grid.appendChild(card);
  }
}

function updateSelectUI() {
  const toggle = el("toggle-select");
  const toggleAllBtn = el("toggle-select-all");
  const del = el("delete-selected");
  if (toggle) toggle.textContent = state.selectMode ? "Done" : "Select";
  if (toggleAllBtn) {
    const total = state.images?.length || 0;
    const selected = state.selectedForDelete.size || 0;
    const allSelected = total > 0 && selected >= total;
    toggleAllBtn.disabled = !state.selectMode || total === 0;
    toggleAllBtn.textContent = allSelected ? "Unselect all" : "Select all";
  }
  if (del) {
    const n = state.selectedForDelete.size;
    del.disabled = n === 0;
    del.textContent = n === 0 ? "Delete" : `Delete (${n})`;
  }
}

function toggleSelected(id, cardEl) {
  if (state.selectedForDelete.has(id)) {
    state.selectedForDelete.delete(id);
    cardEl.classList.remove("sel");
  } else {
    state.selectedForDelete.add(id);
    cardEl.classList.add("sel");
  }
  const check = cardEl.querySelector(".check");
  if (check) check.textContent = state.selectedForDelete.has(id) ? "✓" : "";
  updateSelectUI();
}

async function openModal(id) {
  state.selectedId = id;
  const im = await fetchJSON(`/api/images/${id}`);
  state.currentTags = (im.user_tags || []).map((t) => String(t).trim()).filter(Boolean);
  state.currentNotes = (im.user_notes || []).map((n) => String(n).trim()).filter(Boolean);
  el("modal-img").src = im.file_path;
  el("modal-title").textContent = im.ai_title || `Image #${im.id}`;
  el("modal-desc").textContent = im.description || "";
  const metaStatus = el("meta-status");
  if (metaStatus) metaStatus.textContent = "";
  const md = el("meta-designer");
  const my = el("meta-year");
  const mm = el("meta-month");
  const ms = el("meta-season");
  if (md) md.value = im.designer || "";
  if (my) my.value = im.captured_year != null ? String(im.captured_year) : "";
  if (mm) mm.value = im.captured_month != null ? String(im.captured_month) : "";
  if (ms) ms.value = im.captured_season || "";
  const existing = el("anno-existing");
  if (existing) {
    const tags = state.currentTags || [];
    const notes = state.currentNotes || [];
    const bits = [];
    if (tags.length) {
      bits.push(
        `<div class="row"><span class="k">Tags</span><span class="v">${tags
          .map(
            (t) =>
              `<span class="chip rem" data-kind="tag" data-value="${encodeURIComponent(
                t
              )}">${t}<button type="button" class="x" aria-label="Remove tag">×</button></span>`
          )
          .join("")}</span></div>`
      );
    }
    if (notes.length) {
      bits.push(
        `<div class="row"><span class="k">Notes</span><span class="v">${notes
          .map(
            (n) =>
              `<span class="chip note-chip rem" data-kind="note" data-value="${encodeURIComponent(
                n
              )}">${n}<button type="button" class="x" aria-label="Remove note">×</button></span>`
          )
          .join("")}</span></div>`
      );
    }
    existing.innerHTML = bits.length ? bits.join("") : `<p class="hint inline-hint">No saved tags or notes yet.</p>`;
  }
  const pill = document.querySelector(".pill.ai");
  if (pill) pill.textContent = `AI metadata (${im.ai_source || "unknown"})`;
  const kv = el("modal-ai");
  kv.innerHTML = "";
  const attrs = im.ai_attributes || {};
  const rows = [
    ["Garment type", attrs.garment_type ? prettyLabel(attrs.garment_type) : null],
    ["Style", attrs.style ? prettyLabel(attrs.style) : null],
    ["Material", attrs.material ? prettyLabel(attrs.material) : null],
    ["Pattern", attrs.pattern ? prettyLabel(attrs.pattern) : null],
    ["Season", attrs.season ? prettyLabel(attrs.season) : null],
    ["Occasion", attrs.occasion ? prettyLabel(attrs.occasion) : null],
    ["Consumer profile", attrs.consumer_profile ? prettyLabel(attrs.consumer_profile) : null],
    ["Trend notes", attrs.trend_notes ? prettyLabel(attrs.trend_notes) : null],
    [
      "Colors",
      (attrs.color_palette || [])
        .map((c) => (c ? prettyLabel(c) : ""))
        .filter(Boolean)
        .join(", "),
    ],
    [
      "Location",
      [attrs.location?.city, attrs.location?.country, attrs.location?.continent]
        .filter(Boolean)
        .map((x) => prettyLabel(x))
        .join(" · "),
    ],
    ["Designer", im.designer ? prettyLabel(im.designer) : null],
    ["Year", im.captured_year],
    ["Month", im.captured_month],
    ["Capture season", im.captured_season ? prettyLabel(im.captured_season) : null],
  ];
  for (const [k, v] of rows) {
    if (!v) continue;
    const dt = document.createElement("dt");
    dt.textContent = k;
    const dd = document.createElement("dd");
    dd.textContent = v;
    kv.appendChild(dt);
    kv.appendChild(dd);
  }
  const fs = el("feedback-summary");
  if (im.feedback_summary && im.feedback_summary.count > 0) {
    const avg = im.feedback_summary.avg_rating != null ? ` · avg ${im.feedback_summary.avg_rating.toFixed(1)} / 5` : "";
    fs.textContent = `${im.feedback_summary.count} feedback entr${im.feedback_summary.count === 1 ? "y" : "ies"}${avg}`;
    fs.classList.remove("hidden");
  } else {
    fs.textContent = "";
    fs.classList.add("hidden");
  }
  el("feedback-status").textContent = "";
  el("delete-status").textContent = "";
  el("modal").classList.remove("hidden");
}

function closeModal() {
  el("modal").classList.add("hidden");
  state.selectedId = null;
}

el("upload-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const status = el("upload-status");
  status.textContent = "Uploading…";
  if (!state.selectedFiles?.length) {
    status.textContent = "Choose a file first.";
    return;
  }
  const files = state.selectedFiles;
  const succeeded = [];
  try {
    for (let i = 0; i < files.length; i++) {
      const key = fileKey(files[i]);
      const meta = state.fileMetadata[key] || {};
      const fd = new FormData();
      fd.append("file", files[i]);
      if (meta.designer?.trim()) fd.append("designer", meta.designer.trim());
      if (meta.captured_year) fd.append("captured_year", meta.captured_year);
      if (meta.captured_month) fd.append("captured_month", meta.captured_month);
      if (meta.captured_season?.trim()) fd.append("captured_season", meta.captured_season.trim());
      status.textContent = `Uploading ${i + 1}/${files.length}: ${files[i].name}`;
      const res = await fetch("/api/images", { method: "POST", body: fd });
      if (!res.ok) throw new Error(await res.text());
      succeeded.push(files[i].name);
    }
    status.textContent =
      succeeded.length === 1
        ? `Uploaded: ${succeeded[0]}`
        : `Uploaded ${succeeded.length} images: ${succeeded.slice(0, 3).join(", ")}${succeeded.length > 3 ? "…" : ""}`;
    const fileInput = el("file");
    if (fileInput) fileInput.value = "";
    state.selectedFiles = [];
    state.fileMetadata = {};
    renderSelectedFiles();
    renderBatchMetadataForms();
    await loadFilters();
    await loadImages();
  } catch (err) {
    status.textContent = `Error: ${err.message || err}`;
  }
});

function onPickFiles(inputEl) {
  const picked = Array.from(inputEl.files || []);
  state.selectedFiles = picked;
  const keep = new Set(picked.map((f) => fileKey(f)));
  for (const k of Object.keys(state.fileMetadata)) {
    if (!keep.has(k)) delete state.fileMetadata[k];
  }
  renderSelectedFiles();
  renderBatchMetadataForms();
  const status = el("upload-status");
  if (status) status.textContent = picked.length ? `Selected ${picked.length} image${picked.length === 1 ? "" : "s"}.` : "";
}

el("file").addEventListener("change", (e) => onPickFiles(e.target));

el("anno-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  if (!state.selectedId) return;
  const tagsRaw = el("anno-tags").value;
  const newTags = tagsRaw.split(",").map((s) => s.trim()).filter(Boolean);
  const notesRaw = el("anno-notes").value.trim();
  const newNotes = notesRaw
    ? notesRaw
        .split(/\n|,/g)
        .map((s) => s.trim())
        .filter(Boolean)
    : [];
  const tags = Array.from(new Set([...(state.currentTags || []), ...newTags]));
  const notes = [...(state.currentNotes || []), ...newNotes];
  const res = await fetch(`/api/images/${state.selectedId}/annotations/state`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ tags, notes }),
  });
  if (!res.ok) {
    alert(await res.text());
    return;
  }
  el("anno-tags").value = "";
  el("anno-notes").value = "";
  await openModal(state.selectedId);
  await loadImages();
});

el("anno-existing").addEventListener("click", async (e) => {
  const btn = e.target?.closest?.("button.x");
  if (!btn) return;
  const chip = btn.closest(".chip.rem");
  if (!chip) return;
  if (!state.selectedId) return;
  const kind = chip.dataset.kind;
  const value = decodeURIComponent(chip.dataset.value || "");
  if (!value) return;
  const tags = (state.currentTags || []).filter((t) => t !== value);
  const notes = (state.currentNotes || []).filter((n) => n !== value);
  const payload = kind === "tag" ? { tags, notes: state.currentNotes || [] } : { tags: state.currentTags || [], notes };
  try {
    const res = await fetch(`/api/images/${state.selectedId}/annotations/state`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    if (!res.ok) {
      alert(await res.text());
      return;
    }
    await openModal(state.selectedId);
    await loadImages();
  } catch (err) {
    alert(`Error: ${err.message || err}`);
  }
});

el("meta-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  if (!state.selectedId) return;
  const status = el("meta-status");
  if (status) status.textContent = "Saving…";
  const designer = el("meta-designer").value.trim() || null;
  const yearRaw = el("meta-year").value.trim();
  const monthRaw = el("meta-month").value.trim();
  const season = el("meta-season").value.trim() || null;
  const payload = {
    designer,
    captured_year: yearRaw ? Number(yearRaw) : null,
    captured_month: monthRaw ? Number(monthRaw) : null,
    captured_season: season,
  };
  try {
    const res = await fetch(`/api/images/${state.selectedId}/metadata`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    if (!res.ok) {
      if (status) status.textContent = await res.text();
      return;
    }
    if (status) status.textContent = "Saved.";
    await loadFilters();
    await openModal(state.selectedId);
    await loadImages();
  } catch (err) {
    if (status) status.textContent = `Error: ${err.message || err}`;
  }
});

el("feedback-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  if (!state.selectedId) return;
  const status = el("feedback-status");
  const ratingRaw = el("fb-rating").value;
  const rating = ratingRaw === "" ? null : Number(ratingRaw);
  const comment = el("fb-comment").value.trim() || null;
  const fixType = el("fb-garment-fix").value.trim();
  let corrected_attributes = null;
  if (fixType) corrected_attributes = { garment_type: fixType };
  try {
    const res = await fetch(`/api/images/${state.selectedId}/feedback`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ rating, comment, corrected_attributes }),
    });
    if (!res.ok) {
      status.textContent = await res.text();
      return;
    }
    status.textContent = "Thanks — feedback saved.";
    el("fb-rating").value = "";
    el("fb-comment").value = "";
    el("fb-garment-fix").value = "";
    await openModal(state.selectedId);
  } catch (err) {
    status.textContent = `Error: ${err.message || err}`;
  }
});

const debouncedSearch = debounce(() => {
  const q = el("q").value.trim();
  if (!q || q.length >= 4) loadImages();
}, 220);
el("q").addEventListener("input", debouncedSearch);
el("search-btn").addEventListener("click", () => loadImages());

el("clear-filters").addEventListener("click", () => {
  state.filters = {};
  el("q").value = "";
  loadFilters().then(loadImages);
});

el("modal-close").addEventListener("click", closeModal);
el("modal").addEventListener("click", (e) => {
  if (e.target === el("modal")) closeModal();
});

el("toggle-select").addEventListener("click", async () => {
  state.selectMode = !state.selectMode;
  if (!state.selectMode) {
    state.selectedForDelete.clear();
  }
  await loadImages();
});

el("toggle-select-all").addEventListener("click", async () => {
  if (!state.selectMode) state.selectMode = true;
  const total = state.images?.length || 0;
  const selected = state.selectedForDelete.size || 0;
  const allSelected = total > 0 && selected >= total;
  if (allSelected) {
    state.selectedForDelete.clear();
  } else {
    state.selectedForDelete = new Set((state.images || []).map((x) => x.id));
  }
  await loadImages();
});

el("delete-selected").addEventListener("click", async () => {
  const ids = Array.from(state.selectedForDelete);
  if (!ids.length) return;
  // delete immediately as requested
  try {
    for (const id of ids) {
      await fetch(`/api/images/${id}`, { method: "DELETE" });
    }
    state.selectedForDelete.clear();
    state.selectMode = false;
    updateSelectUI();
    await loadFilters();
    await loadImages();
  } catch (err) {
    alert(`Error deleting: ${err.message || err}`);
    updateSelectUI();
  }
});

(async function init() {
  try {
    await loadFilters();
    await loadImages();
    renderSelectedFiles();
    renderBatchMetadataForms();
  } catch (e) {
    el("grid").textContent = `Could not load API: ${e}`;
  }
})();
