// Sugo's local page (ADR-055). Every text from the server, a document or a
// file name is inserted with textContent, never as HTML.
"use strict";

(function () {
  const TOKEN_KEY = "sugo-token";
  const texts = JSON.parse(document.querySelector('meta[name="sugo-texts"]').content);
  const $ = (id) => document.getElementById(id);

  // The token arrives in the fragment, which the browser never sends to a
  // server. It is kept for this tab only, so a reload still works, and taken
  // out of the address bar, so it is not copied along with the address.
  function sessionToken() {
    const match = /^#token=([A-Za-z0-9_-]+)$/.exec(window.location.hash);
    if (match) {
      try { window.sessionStorage.setItem(TOKEN_KEY, match[1]); } catch (e) { /* storage off */ }
      window.history.replaceState(null, "", window.location.pathname);
      return match[1];
    }
    try { return window.sessionStorage.getItem(TOKEN_KEY); } catch (e) { return null; }
  }

  function fill(template, values) {
    let text = template;
    for (const [name, value] of Object.entries(values)) {
      text = text.split("{" + name + "}").join(String(value));
    }
    return text;
  }

  function show(element, visible) { element.hidden = !visible; }

  function setStatus(text) { $("status").textContent = text; }

  function showError(error) {
    $("error-code").textContent = error.code ? texts.error + " " + error.code + ":" : texts.error + ":";
    $("error-message").textContent = error.message || "";
    $("error-hint").textContent = error.hint ? fill(texts.hint, { hint: error.hint }) : "";
    show($("error"), true);
  }

  function clearAll() {
    show($("error"), false);
    show($("result"), false);
    setStatus("");
  }

  for (const element of document.querySelectorAll("[data-text]")) {
    element.textContent = texts[element.dataset.text] || "";
  }

  const token = sessionToken();
  const drop = $("drop");
  const input = $("file");
  let markdownName = "document.md";
  let busy = false;

  if (!token) {
    showError({ message: texts.no_token });
    drop.classList.add("busy");
    input.disabled = true;
  }

  async function convert(file) {
    if (busy || !token || !file) return;
    clearAll();
    if (file.size === 0) { showError({ message: texts.empty }); return; }
    if (file.size > texts.max_bytes) { showError({ message: texts.too_large }); return; }
    busy = true;
    drop.classList.add("busy");
    setStatus(texts.converting);
    markdownName = (file.name.replace(/\.[^.]*$/, "") || "document") + ".md";
    try {
      const response = await fetch("/api/convert", {
        method: "POST",
        headers: { "X-Sugo-Token": token, "Content-Type": "application/octet-stream" },
        body: file,
        cache: "no-store",
        credentials: "omit",
        referrerPolicy: "no-referrer",
      });
      let body = null;
      try { body = await response.json(); } catch (e) { body = null; }
      setStatus("");
      if (response.ok && body) {
        showResult(body);
      } else if (body && body.error) {
        showError(body.error);
      } else {
        showError({ message: texts.unexpected });
      }
    } catch (e) {
      setStatus("");
      showError({ message: texts.unexpected });
    } finally {
      busy = false;
      drop.classList.remove("busy");
      input.value = "";
    }
  }

  function showResult(result) {
    $("markdown").value = result.markdown;
    $("pages").textContent = fill(texts.pages, { count: result.pages });
    const failed = result.failed_pages || [];
    $("failed").textContent = fill(texts.failed_pages, { pages: failed.join(", ") });
    show($("failed"), failed.length > 0);

    const text = result.text;
    $("text-savings").textContent = fill(texts.text_savings, {
      before: text.baseline_tokens, after: text.result_tokens, saved: text.saved_percent,
    });

    const rows = $("images").querySelector("tbody");
    rows.replaceChildren();
    for (const image of result.images) {
      const name = image.formula_verified ? image.provider : fill(texts.unverified, { provider: image.provider });
      rows.append(row([name, image.tier, image.baseline_tokens, image.result_tokens, image.saved_percent + "%"]));
    }
    for (const provider of result.rejected_by) {
      rows.append(row([provider, "-", texts.rejected, "-", "-"]));
    }
    show($("images"), result.images.length + result.rejected_by.length > 0);

    const removed = $("removed");
    removed.replaceChildren();
    const entries = Object.entries(result.removed).filter(([, count]) => count > 0);
    if (entries.length === 0) {
      const item = document.createElement("li");
      item.textContent = texts.removed_none;
      removed.append(item);
    }
    for (const [cleaner, count] of entries) {
      const item = document.createElement("li");
      item.textContent = cleaner + ": " + count;
      removed.append(item);
    }
    show($("result"), true);
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
      setStatus(texts.copied);
    } catch (e) {
      setStatus(texts.copy_failed);
    }
  });

  $("save").addEventListener("click", () => {
    const blob = new Blob([$("markdown").value], { type: "text/markdown;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = markdownName;
    link.rel = "noopener";
    document.body.append(link);
    link.click();
    link.remove();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  });
})();
