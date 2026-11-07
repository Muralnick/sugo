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
      // The page can turn the cache off, never on against the configuration.
      cache: d.cache && (typeof s.cache === "boolean" ? s.cache : true),
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
    $("keep-cache").checked = settings.cache;
    $("keep-cache").disabled = !data.defaults.cache;
    show($("cache-off-config"), !data.defaults.cache);
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
  $("keep-cache").addEventListener("change", (event) => {
    settings.cache = event.target.checked && data.defaults.cache;
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
    if (!settings.cache) headers["X-Sugo-Cache"] = "off";
    const encoded = settings.receipt && name ? encodedName(name) : null;
    if (encoded) headers["X-Sugo-Name"] = encoded;
    return headers;
  }

  // The file's name for the receipt, sent only if the server would accept it
  // (ADR-059): otherwise the receipt simply has no name. The test mirrors
  // Python's str.isprintable(): no control, format, private-use, unassigned
  // or separator characters, except the plain space (U+202F, for example,
  // is in macOS screenshot names).
  function encodedName(name) {
    if ([...name].length > 255 || name === "." || name === "..") return null;
    if (/[/\\]/.test(name) || /(?! )[\p{C}\p{Z}]/u.test(name)) return null;
    try { return encodeURIComponent(name); } catch (e) { return null; }  // a lone surrogate
  }

  // One file, one request: {result} or {error}, never an exception.
  async function requestConversion(file) {
    if (file.size === 0) return { error: { message: texts.empty } };
    if (file.size > data.max_bytes) return { error: { message: texts.too_large } };
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
      if (response.ok && body) return { result: body };
      if (body && body.error) return { error: body.error };
    } catch (e) { /* reported below */ }
    return { error: { message: texts.unexpected } };
  }

  function convert(file) {
    if (file) convertFiles([file]);
  }

  // Several files (ADR-059): converted one after the other, each with its own
  // request, so the server's limits apply to each; a refused file does not
  // stop the others. Results live only in this page.
  let batch = [];
  let selected = -1;

  async function convertFiles(list) {
    const files = Array.from(list || []);
    if (busy || !token || files.length === 0) return;
    clearAll();
    batch = [];
    selected = -1;
    show($("batch"), false);
    if (files.length > data.max_batch_files) {
      showError({ message: texts.batch_too_many });
      input.value = "";
      return;
    }
    busy = true;
    drop.classList.add("busy");
    const several = files.length > 1;
    batch = files.map((file) => ({ file: file, state: "waiting", result: null, error: null }));
    if (several) { renderBatch(); show($("batch"), true); }
    try {
      for (let index = 0; index < batch.length; index += 1) {
        const entry = batch[index];
        entry.state = "converting";
        if (several) renderBatch();
        setStatus(several ? fill(texts.batch_title, batchCounts()) : texts.converting, true);
        const answer = await requestConversion(entry.file);
        entry.state = answer.result ? "done" : "refused";
        entry.result = answer.result || null;
        entry.error = answer.error || null;
        if (!several || selected === -1) {
          if (answer.result || !several) showEntry(index);
        }
        if (several) renderBatch();
      }
    } finally {
      busy = false;
      drop.classList.remove("busy");
      setStatus("", false);
      input.value = "";
      $("save-all").disabled = !batch.some((entry) => entry.result);
    }
  }

  function batchCounts() {
    return {
      done: number(batch.filter((entry) => entry.state === "done").length),
      count: number(batch.length),
    };
  }

  function renderBatch() {
    $("batch-title").textContent = fill(texts.batch_title, batchCounts());
    const list = $("batch-list");
    list.replaceChildren();
    batch.forEach((entry, index) => {
      const item = document.createElement("li");
      if (index === selected) item.className = "selected";
      const name = document.createElement("button");
      name.type = "button";
      name.textContent = entry.file.name;
      name.disabled = entry.state === "waiting" || entry.state === "converting";
      name.addEventListener("click", () => { showEntry(index); renderBatch(); });
      const state = document.createElement("span");
      state.className = "batch-state " + entry.state;
      state.textContent = texts["state_" + entry.state];
      if (entry.error && entry.error.code) state.textContent += " · " + entry.error.code;
      item.append(name, state);
      list.append(item);
    });
  }

  function showEntry(index) {
    const entry = batch[index];
    selected = index;
    show($("error"), false);
    show($("result"), false);
    lastResult = null;
    $("file-name").textContent = entry.file.name;
    baseName = entry.file.name.replace(/\.[^.]*$/, "") || "document";
    if (entry.result) {
      lastResult = entry.result;
      showResult(entry.result);
    } else if (entry.error) {
      showError(entry.error);
    }
  }

  // --- Save all: one uncompressed ZIP built here, no library (ADR-059). ---

  // A name safe in any folder: no path, no control or reserved characters.
  function safeStem(fileName) {
    const stem = fileName.replace(/\.[^.]*$/, "")
      .replace(/[\u0000-\u001f\u007f-\u009f\/\\:*?"<>|]/g, "_")
      .replace(/^[.\s]+|[.\s]+$/g, "");
    return [...stem].slice(0, 200).join("") || "document";
  }

  // report.pdf and report.png become report and report (2), never one file.
  function zipEntries() {
    const taken = new Set();
    const entries = [];
    for (const entry of batch) {
      if (!entry.result) continue;
      const stem = safeStem(entry.file.name);
      let name = stem;
      for (let n = 2; taken.has(name.toLowerCase()); n += 1) name = stem + " (" + n + ")";
      taken.add(name.toLowerCase());
      entries.push({ name: name + ".md", text: entry.result.markdown });
      if (typeof entry.result.jsonl === "string") entries.push({ name: name + ".jsonl", text: entry.result.jsonl });
      if (typeof entry.result.receipt_file === "string") {
        entries.push({ name: name + ".receipt.json", text: entry.result.receipt_file });
      }
    }
    return entries;
  }

  const CRC_TABLE = (() => {
    const table = new Uint32Array(256);
    for (let n = 0; n < 256; n += 1) {
      let c = n;
      for (let k = 0; k < 8; k += 1) c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1;
      table[n] = c >>> 0;
    }
    return table;
  })();

  function crc32(bytes) {
    let crc = 0xffffffff;
    for (let i = 0; i < bytes.length; i += 1) crc = CRC_TABLE[(crc ^ bytes[i]) & 0xff] ^ (crc >>> 8);
    return (crc ^ 0xffffffff) >>> 0;
  }

  // The "stored" method: no compression, local headers, central directory, end record.
  function makeZip(entries) {
    const encoder = new TextEncoder();
    const now = new Date();
    const time = (now.getHours() << 11) | (now.getMinutes() << 5) | (now.getSeconds() >> 1);
    const date = ((now.getFullYear() - 1980) << 9) | ((now.getMonth() + 1) << 5) | now.getDate();
    const parts = [];
    const central = [];
    let offset = 0;
    for (const entry of entries) {
      const name = encoder.encode(entry.name);
      const content = encoder.encode(entry.text);
      const crc = crc32(content);
      const local = new DataView(new ArrayBuffer(30));
      local.setUint32(0, 0x04034b50, true);
      local.setUint16(4, 20, true);
      local.setUint16(6, 0x0800, true);  // names are UTF-8
      local.setUint16(8, 0, true);  // stored
      local.setUint16(10, time, true);
      local.setUint16(12, date, true);
      local.setUint32(14, crc, true);
      local.setUint32(18, content.length, true);
      local.setUint32(22, content.length, true);
      local.setUint16(26, name.length, true);
      local.setUint16(28, 0, true);
      parts.push(local, name, content);
      const record = new DataView(new ArrayBuffer(46));
      record.setUint32(0, 0x02014b50, true);
      record.setUint16(4, 20, true);
      record.setUint16(6, 20, true);
      record.setUint16(8, 0x0800, true);
      record.setUint16(10, 0, true);
      record.setUint16(12, time, true);
      record.setUint16(14, date, true);
      record.setUint32(16, crc, true);
      record.setUint32(20, content.length, true);
      record.setUint32(24, content.length, true);
      record.setUint16(28, name.length, true);
      record.setUint32(42, offset, true);
      central.push(record, name);
      offset += 30 + name.length + content.length;
    }
    const size = central.reduce((total, part) => total + part.byteLength, 0);
    const end = new DataView(new ArrayBuffer(22));
    end.setUint32(0, 0x06054b50, true);
    end.setUint16(8, entries.length, true);
    end.setUint16(10, entries.length, true);
    end.setUint32(12, size, true);
    end.setUint32(16, offset, true);
    return new Blob([...parts, ...central, end], { type: "application/zip" });
  }

  $("save-all").addEventListener("click", () => {
    const entries = zipEntries();
    if (entries.length > 0) download(makeZip(entries), "sugo.zip", "application/zip");
  });

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

  input.addEventListener("change", () => convertFiles(input.files));

  // --- Pasting a screenshot (ADR-059), as sugo clip: only an image counts. ---

  const PASTED_NAME = "clipboard.png";

  function pastedFile(blob) {
    return new File([blob], PASTED_NAME, { type: blob.type });
  }

  // Ctrl+V needs no permission: the browser hands the page what was pasted.
  document.addEventListener("paste", (event) => {
    const target = event.target;
    // Pasting into a settings field stays an ordinary paste.
    if (target instanceof HTMLInputElement || target instanceof HTMLSelectElement) return;
    const items = event.clipboardData ? Array.from(event.clipboardData.items) : [];
    const image = items.find((item) => item.kind === "file" && item.type.startsWith("image/"));
    if (!image) return;  // Text is ignored, as sugo clip ignores it.
    const blob = image.getAsFile();
    if (!blob) return;
    event.preventDefault();
    selectView("convert");
    convert(pastedFile(blob));
  });

  // The button asks the browser, which may ask the user first.
  $("paste").addEventListener("click", async () => {
    if (busy || !token) return;
    if (!navigator.clipboard || typeof navigator.clipboard.read !== "function") {
      setStatus(texts.paste_denied, false);
      return;
    }
    let items;
    try { items = await navigator.clipboard.read(); } catch (e) {
      setStatus(texts.paste_denied, false);
      return;
    }
    for (const item of items) {
      const type = item.types.find((name) => name.startsWith("image/"));
      if (type) {
        convert(pastedFile(await item.getType(type)));
        return;
      }
    }
    setStatus(texts.paste_none, false);
  });

  // Stop the browser from opening a file dropped outside the drop area.
  for (const name of ["dragover", "drop"]) {
    window.addEventListener(name, (event) => event.preventDefault());
  }
  drop.addEventListener("dragover", () => drop.classList.add("over"));
  drop.addEventListener("dragleave", () => drop.classList.remove("over"));
  drop.addEventListener("drop", (event) => {
    drop.classList.remove("over");
    const files = event.dataTransfer && event.dataTransfer.files;
    if (files && files.length > 0) convertFiles(files);
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

  // --- Installation check (ADR-059): the checks of sugo doctor. ---

  async function runDoctor() {
    const rows = $("doctor-checks").querySelector("tbody");
    rows.replaceChildren();
    show($("doctor-checks"), false);
    $("doctor").disabled = true;
    $("doctor-status").textContent = texts.doctor_running;
    try {
      const response = await fetch("/api/doctor", {
        method: "POST",
        headers: { "X-Sugo-Token": token, "X-Sugo-Language": settings.ui_language },
        cache: "no-store",
        credentials: "omit",
        referrerPolicy: "no-referrer",
      });
      let body = null;
      try { body = await response.json(); } catch (e) { body = null; }
      if (!response.ok || !body || !Array.isArray(body.checks)) {
        $("doctor-status").textContent = body && body.error ? body.error.message : texts.doctor_failed;
        return;
      }
      for (const check of body.checks) {
        const tr = row([check.label, texts["status_" + check.status] || check.status, check.detail]);
        tr.children[1].className = "check-" + check.status;
        rows.append(tr);
      }
      $("doctor-status").textContent = "";
      show($("doctor-checks"), true);
    } catch (e) {
      $("doctor-status").textContent = texts.doctor_failed;
    } finally {
      $("doctor").disabled = !token;
    }
  }

  $("doctor").addEventListener("click", runDoctor);

  // --- Verifying a receipt (ADR-059), as sugo verify. ---

  function showVerifyError(error) {
    $("verify-error-code").textContent = error.code ? texts.error + " " + error.code + ":" : texts.error + ":";
    $("verify-error-message").textContent = error.message || "";
    $("verify-error-hint").textContent = error.hint ? fill(texts.hint, { hint: error.hint }) : "";
    show($("verify-error"), true);
  }

  function describeDifference(difference) {
    if (difference.category === "tokens_after") {
      return fill(texts.diff_tokens, { stored: number(difference.stored), fresh: number(difference.fresh) });
    }
    const what = texts["diff_" + difference.category] || String(difference.category);
    const where = fill(texts.diff_block, { page: number(difference.page), block: String(difference.block_id) });
    const kind = texts["diff_" + difference.kind] || String(difference.kind);
    return what + ", " + where + ": " + kind;
  }

  function showVerifyResult(result) {
    const verdict = $("verify-verdict");
    const differences = Array.isArray(result.differences) ? result.differences : [];
    verdict.className = "verdict " + (result.match ? "match" : "mismatch");
    verdict.textContent = result.match
      ? texts.verify_match
      : fill(texts.verify_mismatch, { count: number(differences.length) });
    show($("verify-drifted"), result.version_drifted === true);
    const list = $("verify-differences");
    list.replaceChildren();
    for (const difference of differences) {
      const item = document.createElement("li");
      item.textContent = describeDifference(difference);
      list.append(item);
    }
    show($("verify-result"), true);
  }

  async function verify() {
    if (busy || !token) return;
    const documentFile = $("verify-document").files[0];
    const receiptFile = $("verify-receipt").files[0];
    show($("verify-error"), false);
    show($("verify-result"), false);
    if (!documentFile || !receiptFile) { showVerifyError({ message: texts.verify_missing_files }); return; }
    if (documentFile.size === 0) { showVerifyError({ message: texts.empty }); return; }
    if (documentFile.size > data.max_bytes) { showVerifyError({ message: texts.too_large }); return; }
    if (receiptFile.size === 0 || receiptFile.size > data.max_receipt_bytes) {
      showVerifyError({ message: texts.receipt_too_large });
      return;
    }
    busy = true;
    $("verify-run").disabled = true;
    $("verify-status").textContent = texts.verifying;
    try {
      const response = await fetch("/api/verify", {
        method: "POST",
        headers: {
          "X-Sugo-Token": token,
          "Content-Type": "application/octet-stream",
          "X-Sugo-Language": settings.ui_language,
          "X-Sugo-Receipt-Length": String(receiptFile.size),
          ...(settings.cache ? {} : { "X-Sugo-Cache": "off" }),
        },
        // The receipt first, then the document: one body, no multipart.
        body: new Blob([receiptFile, documentFile]),
        cache: "no-store",
        credentials: "omit",
        referrerPolicy: "no-referrer",
      });
      let body = null;
      try { body = await response.json(); } catch (e) { body = null; }
      if (response.ok && body) {
        showVerifyResult(body);
      } else if (body && body.error) {
        showVerifyError(body.error);
      } else {
        showVerifyError({ message: texts.unexpected });
      }
    } catch (e) {
      showVerifyError({ message: texts.unexpected });
    } finally {
      busy = false;
      $("verify-run").disabled = !token;
      $("verify-status").textContent = "";
    }
  }

  $("verify-run").addEventListener("click", verify);

  // --- Start ---

  renderSettings();
  applyTexts();
  const view = load("sessionStorage", VIEW_KEY);
  selectView(["convert", "verify", "settings", "questions"].includes(view) ? view : "convert");
  if (!token) {
    showError({ message: texts.no_token });
    drop.classList.add("busy");
    input.disabled = true;
    $("paste").disabled = true;
    $("verify-run").disabled = true;
  }
})();
