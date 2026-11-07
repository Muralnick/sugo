// Sugo's local page (ADR-055). Every text from the server, a document or a
// file name is inserted with textContent, never as HTML.
"use strict";

(function () {
  const TOKEN_KEY = "sugo-token";
  const SETTINGS_KEY = "sugo-settings";
  const VIEW_KEY = "sugo-view";
  const data = JSON.parse(document.querySelector('meta[name="sugo-data"]').content);
  const $ = (id) => document.getElementById(id);

  // --- Storage: per-browser conveniences; the page works without it. ---

  function load(storage, key) {
    try { return window[storage].getItem(key); } catch (e) { return null; }
  }
  function store(storage, key, value) {
    try { window[storage].setItem(key, value); } catch (e) { /* storage off */ }
  }

  // The token arrives in the fragment, which the browser never sends to a
  // server. It is kept for this tab only, so a reload still works, and taken
  // out of the address bar, so it is not copied along with the address.
  function sessionToken() {
    const match = /^#token=([A-Za-z0-9_-]+)$/.exec(window.location.hash);
    if (match) {
      store("sessionStorage", TOKEN_KEY, match[1]);
      window.history.replaceState(null, "", window.location.pathname);
      return match[1];
    }
    return load("sessionStorage", TOKEN_KEY);
  }

  // --- Settings: the user's configuration, changed here and remembered here. ---

  function validSettings(value) {
    const d = data.defaults;
    const s = value && typeof value === "object" ? value : {};
    const languages = Array.isArray(s.languages)
      ? s.languages.filter((code) => data.packs.includes(code)) : [];
    const size = Number.isInteger(s.chunk_tokens) ? s.chunk_tokens : d.chunk_tokens;
    return {
      ui_language: Object.hasOwn(data.texts, s.ui_language) ? s.ui_language : d.ui_language,
      languages: languages.length > 0 ? languages : d.languages.slice(),
      strip_tracking_urls: typeof s.strip_tracking_urls === "boolean" ? s.strip_tracking_urls : d.strip_tracking_urls,
      chunks: typeof s.chunks === "boolean" ? s.chunks : d.chunks,
      receipt: typeof s.receipt === "boolean" ? s.receipt : d.receipt,
      chunk_tokens: Math.min(data.chunk_max, Math.max(data.chunk_min, size)),
    };
  }

  function loadSettings() {
    try { return validSettings(JSON.parse(load("localStorage", SETTINGS_KEY))); } catch (e) {
      return validSettings(null);
    }
  }

  let settings = loadSettings();
  let texts = data.texts[settings.ui_language];

  function saveSettings() {
    store("localStorage", SETTINGS_KEY, JSON.stringify(settings));
  }

  // --- Text ---

  function fill(template, values) {
    let text = template;
    for (const [name, value] of Object.entries(values)) {
      text = text.split("{" + name + "}").join(String(value));
    }
    return text;
  }

  function number(value) {
    return Number(value).toLocaleString(settings.ui_language);
  }

  function applyTexts() {
    texts = data.texts[settings.ui_language];
    document.documentElement.lang = settings.ui_language;
    for (const element of document.querySelectorAll("[data-text]")) {
      element.textContent = texts[element.dataset.text] || "";
    }
    renderLanguages();
    renderQuestions();
    if (lastResult) showResult(lastResult);
  }

  function show(element, visible) { element.hidden = !visible; }

  function setStatus(text, busy) {
    $("status-text").textContent = text;
    $("status").classList.toggle("busy", Boolean(busy));
  }

  // --- Tabs ---

  function selectView(name) {
    for (const tab of document.querySelectorAll("[data-view]")) {
      const selected = tab.dataset.view === name;
      tab.setAttribute("aria-selected", String(selected));
      show($("view-" + tab.dataset.view), selected);
    }
    store("sessionStorage", VIEW_KEY, name);
  }

  for (const tab of document.querySelectorAll("[data-view]")) {
    tab.addEventListener("click", () => selectView(tab.dataset.view));
  }

  // --- Settings view ---

  function renderLanguages() {
    const box = $("text-languages");
    box.replaceChildren();
    for (const code of data.packs) {
      const label = document.createElement("label");
      label.className = "check";
      const input = document.createElement("input");
      input.type = "checkbox";
      input.value = code;
      input.checked = settings.languages.includes(code);
      input.addEventListener("change", () => {
        const chosen = data.packs.filter((pack) =>
          box.querySelector('input[value="' + pack + '"]').checked);
        if (chosen.length === 0) {
          input.checked = true;  // At least one language.
          return;
        }
        settings.languages = chosen;
        saveSettings();
      });
      const name = document.createElement("span");
      name.textContent = texts["lang_" + code] || code;
      label.append(input, name);
      box.append(label);
    }
  }

  function renderSettings() {
    $("ui-language").value = settings.ui_language;
    $("strip-tracking").checked = settings.strip_tracking_urls;
    $("make-chunks").checked = settings.chunks;
    const size = $("chunk-tokens");
    size.min = String(data.chunk_min);
    size.max = String(data.chunk_max);
    size.value = String(settings.chunk_tokens);
    size.disabled = !settings.chunks;
    $("make-receipt").checked = settings.receipt;
  }

  $("ui-language").addEventListener("change", (event) => {
    settings.ui_language = validSettings({ ...settings, ui_language: event.target.value }).ui_language;
    saveSettings();
    applyTexts();
  });
  $("strip-tracking").addEventListener("change", (event) => {
    settings.strip_tracking_urls = event.target.checked;
    saveSettings();
  });
  $("make-chunks").addEventListener("change", (event) => {
    settings.chunks = event.target.checked;
    $("chunk-tokens").disabled = !settings.chunks;
    saveSettings();
  });
  $("make-receipt").addEventListener("change", (event) => {
    settings.receipt = event.target.checked;
    saveSettings();
  });
  $("chunk-tokens").addEventListener("change", (event) => {
    const value = Math.round(Number(event.target.value));
    settings.chunk_tokens = validSettings({ ...settings, chunk_tokens: value }).chunk_tokens;
    event.target.value = String(settings.chunk_tokens);
    saveSettings();
  });
  $("reset").addEventListener("click", () => {
    settings = validSettings(null);
    saveSettings();
    renderSettings();
    applyTexts();
  });

  // --- Questions view ---

  function renderQuestions() {
    const box = $("questions");
    box.replaceChildren();
    for (const [question, answer] of texts.questions) {
      const details = document.createElement("details");
      const summary = document.createElement("summary");
      summary.textContent = question;
      const paragraph = document.createElement("p");
      paragraph.textContent = answer;
      details.append(summary, paragraph);
      box.append(details);
    }
  }

  // --- Converting ---

  const token = sessionToken();
  const drop = $("drop");
  const input = $("file");
  let baseName = "document";
  let busy = false;
  let lastResult = null;

  function showError(error) {
    $("error-code").textContent = error.code ? texts.error + " " + error.code + ":" : texts.error + ":";
    $("error-message").textContent = error.message || "";
    $("error-hint").textContent = error.hint ? fill(texts.hint, { hint: error.hint }) : "";
    show($("error"), true);
  }

  function clearAll() {
    show($("error"), false);
    show($("result"), false);
    lastResult = null;
    setStatus("", false);
  }

  function requestHeaders(name) {
    const headers = {
      "X-Sugo-Token": token,
      "Content-Type": "application/octet-stream",
      "X-Sugo-Language": settings.ui_language,
      "X-Sugo-Languages": settings.languages.join(","),
      "X-Sugo-Strip-Tracking": String(settings.strip_tracking_urls),
    };
    if (settings.chunks) headers["X-Sugo-Chunk-Tokens"] = String(settings.chunk_tokens);
    if (settings.receipt) headers["X-Sugo-Receipt"] = "true";
    if (name && plainName(name)) headers["X-Sugo-Name"] = encodeURIComponent(name);
    return headers;
  }

  // The file's name for the receipt, only if the server would accept it
  // (ADR-059); otherwise the receipt simply has no name.
  function plainName(name) {
    return name.length <= 255 && name !== "." && name !== ".." &&
      !/[/\\]/.test(name) && !/[\u0000-\u001f\u007f-\u009f]/.test(name);
  }

  async function convert(file) {
    if (busy || !token || !file) return;
    clearAll();
    $("file-name").textContent = file.name;
    if (file.size === 0) { showError({ message: texts.empty }); return; }
    if (file.size > data.max_bytes) { showError({ message: texts.too_large }); return; }
    busy = true;
    drop.classList.add("busy");
    setStatus(texts.converting, true);
    baseName = file.name.replace(/\.[^.]*$/, "") || "document";
    try {
      const response = await fetch("/api/convert", {
        method: "POST",
        headers: requestHeaders(file.name),
        body: file,
        cache: "no-store",
        credentials: "omit",
        referrerPolicy: "no-referrer",
      });
      let body = null;
      try { body = await response.json(); } catch (e) { body = null; }
      setStatus("", false);
      if (response.ok && body) {
        lastResult = body;
        showResult(body);
      } else if (body && body.error) {
        showError(body.error);
      } else {
        showError({ message: texts.unexpected });
      }
    } catch (e) {
      setStatus("", false);
      showError({ message: texts.unexpected });
    } finally {
      busy = false;
      drop.classList.remove("busy");
      input.value = "";
    }
  }

  function showResult(result) {
    const text = result.text;
    $("card-before").textContent = number(text.baseline_tokens);
    $("card-after").textContent = number(text.result_tokens);
    $("card-saved").textContent = number(text.saved_percent) + "%";
    $("card-pages").textContent = number(result.pages);
    const share = text.baseline_tokens > 0 ? (100 * text.result_tokens) / text.baseline_tokens : 100;
    $("meter-after").style.width = Math.min(100, Math.max(0, share)) + "%";
    $("text-savings").textContent = fill(texts.text_savings, {
      before: number(text.baseline_tokens), after: number(text.result_tokens), saved: number(text.saved_percent),
    });
    const failed = result.failed_pages || [];
    $("failed").textContent = fill(texts.failed_pages, { pages: failed.join(", ") });
    show($("failed"), failed.length > 0);

    $("markdown").value = result.markdown;

    const rows = $("images").querySelector("tbody");
    rows.replaceChildren();
    for (const image of result.images) {
      const name = image.formula_verified ? image.provider : fill(texts.unverified, { provider: image.provider });
      rows.append(row([name, image.tier, number(image.baseline_tokens), number(image.result_tokens), number(image.saved_percent) + "%"]));
    }
    for (const provider of result.rejected_by) {
      rows.append(row([provider, "-", texts.rejected, "-", "-"]));
    }
    show($("images-panel"), result.images.length + result.rejected_by.length > 0);

    showCounts($("removed"), result.removed, texts.removed_none);
    showCounts($("edited"), result.edited || {}, texts.edited_none);

    showChunks(result);
    showReceipt(result);
    show($("result"), true);
  }

  function showCounts(list, counts, none) {
    list.replaceChildren();
    const entries = Object.entries(counts).filter(([, count]) => count > 0);
    if (entries.length === 0) {
      const item = document.createElement("li");
      item.textContent = none;
      list.append(item);
    }
    for (const [cleaner, count] of entries) {
      const item = document.createElement("li");
      const name = document.createElement("code");
      name.textContent = cleaner;
      const amount = document.createElement("span");
      amount.className = "count";
      amount.textContent = number(count);
      item.append(name, amount);
      list.append(item);
    }
  }

  // --- Receipt (ADR-059): every value is text, never HTML. ---

  // A long receipt would make the page slow; the saved file has every entry.
  const RECEIPT_SHOWN = 500;

  function showReceipt(result) {
    const panel = $("receipt-panel");
    const receipt = result.receipt;
    if (!receipt || typeof result.receipt_file !== "string") { show(panel, false); return; }
    receiptPart("receipt-removed", texts.receipt_removed, receipt.removed, (entry) => [
      [texts.receipt_page.replace("{page}", number(entry.page)), entry.block_type, entry.removed_by, entry.reason],
      [entry.text || texts.receipt_no_text],
    ]);
    receiptPart("receipt-edited", texts.receipt_edited, receipt.edited, (entry) => [
      [texts.receipt_page.replace("{page}", number(entry.page)), entry.edited_by, entry.kind, entry.reason],
      [texts.edit_before + ": " + entry.original, texts.edit_after + ": " + entry.replacement],
    ]);
    receiptPart("receipt-flagged", texts.receipt_flagged, receipt.flagged, (entry) => {
      const meta = [texts.receipt_page.replace("{page}", number(entry.page)), entry.block_type, ...entry.flags];
      if (entry.confidence !== null) {
        meta.push(fill(texts.receipt_confidence, { confidence: number(entry.confidence) }));
      }
      return [meta, []];
    });
    show(panel, true);
  }

  function receiptPart(id, title, entries, describe) {
    const part = $(id);
    part.querySelector("summary").textContent = fill(title, { count: number(entries.length) });
    const list = part.querySelector("ol");
    list.replaceChildren();
    if (entries.length === 0) {
      const item = document.createElement("li");
      item.textContent = texts.receipt_none;
      list.append(item);
    }
    for (const entry of entries.slice(0, RECEIPT_SHOWN)) {
      const [meta, bodies] = describe(entry);
      const item = document.createElement("li");
      const head = document.createElement("div");
      head.className = "receipt-meta";
      meta.forEach((value, index) => {
        if (index > 0) head.append(" · ");
        const code = document.createElement("code");
        code.textContent = String(value);
        head.append(code);
      });
      item.append(head);
      for (const value of bodies) {
        const body = document.createElement("pre");
        body.className = "receipt-text";
        body.textContent = value;
        item.append(body);
      }
      list.append(item);
    }
    if (entries.length > RECEIPT_SHOWN) {
      const more = document.createElement("li");
      more.className = "muted small";
      more.textContent = fill(texts.receipt_more, { shown: number(RECEIPT_SHOWN), count: number(entries.length) });
      list.append(more);
    }
  }

  function showChunks(result) {
    const panel = $("chunks-panel");
    const list = $("chunks");
    list.replaceChildren();
    if (typeof result.jsonl !== "string") { show(panel, false); return; }
    const chunks = result.jsonl.split("\n").filter((line) => line).map((line) => JSON.parse(line));
    $("chunks-count").textContent = fill(texts.chunks_count, {
      count: number(chunks.length), tokens: number(result.chunk_tokens),
    });
    chunks.forEach((chunk, index) => {
      const item = document.createElement("li");
      item.className = "chunk";
      const head = document.createElement("div");
      head.className = "chunk-head";
      let label = fill(texts.chunk_label, { number: index + 1, tokens: number(chunk.tokens) });
      if (chunk.pages.length > 0) label += " · " + fill(texts.chunk_pages, { pages: chunk.pages.join(", ") });
      head.textContent = label;
      item.append(head);
      if (chunk.heading_path.length > 0) {
        const path = document.createElement("div");
        path.className = "chunk-path";
        path.textContent = chunk.heading_path.join(" › ");
        item.append(path);
      }
      const body = document.createElement("pre");
      body.className = "chunk-text";
      body.textContent = chunk.text;
      item.append(body);
      list.append(item);
    });
    show(panel, true);
  }

  function row(cells) {
    const tr = document.createElement("tr");
    cells.forEach((value, index) => {
      const td = document.createElement("td");
      td.textContent = String(value);
      if (index >= 2) td.className = "number";
      tr.append(td);
    });
    return tr;
  }

  function download(content, name, type) {
    const blob = new Blob([content], { type: type });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = name;
    link.rel = "noopener";
    document.body.append(link);
    link.click();
    link.remove();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  }

  input.addEventListener("change", () => convert(input.files[0]));

  // Stop the browser from opening a file dropped outside the drop area.
  for (const name of ["dragover", "drop"]) {
    window.addEventListener(name, (event) => event.preventDefault());
  }
  drop.addEventListener("dragover", () => drop.classList.add("over"));
  drop.addEventListener("dragleave", () => drop.classList.remove("over"));
  drop.addEventListener("drop", (event) => {
    drop.classList.remove("over");
    const files = event.dataTransfer && event.dataTransfer.files;
    if (files && files.length > 0) convert(files[0]);
  });

  $("copy").addEventListener("click", async () => {
    try {
      await navigator.clipboard.writeText($("markdown").value);
      setStatus(texts.copied, false);
    } catch (e) {
      setStatus(texts.copy_failed, false);
    }
  });
  $("save").addEventListener("click", () => {
    download($("markdown").value, baseName + ".md", "text/markdown;charset=utf-8");
  });
  $("save-receipt").addEventListener("click", () => {
    if (lastResult && typeof lastResult.receipt_file === "string") {
      download(lastResult.receipt_file, baseName + ".receipt.json", "application/json;charset=utf-8");
    }
  });
  $("save-jsonl").addEventListener("click", () => {
    if (lastResult && typeof lastResult.jsonl === "string") {
      download(lastResult.jsonl, baseName + ".jsonl", "application/jsonl;charset=utf-8");
    }
  });

  // --- Start ---

  renderSettings();
  applyTexts();
  const view = load("sessionStorage", VIEW_KEY);
  selectView(["convert", "settings", "questions"].includes(view) ? view : "convert");
  if (!token) {
    showError({ message: texts.no_token });
    drop.classList.add("busy");
    input.disabled = true;
  }
})();
