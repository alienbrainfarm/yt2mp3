(() => {
  "use strict";

  const TOKEN = window.APP_TOKEN || "";
  const $ = (selector, root = document) => root.querySelector(selector);
  const $$ = (selector, root = document) => Array.from(root.querySelectorAll(selector));

  const state = {
    settings: null,
    settingsLoaded: false,
    jobs: [],
    history: [],
    stats: {},
    preview: null,
    fetching: false,
    polling: false,
    failures: 0,
    saveTimer: null,
    queueSignature: "",
    librarySignature: "",
  };

  const els = {};

  document.addEventListener("DOMContentLoaded", init);

  async function init() {
    cacheElements();
    bindEvents();
    updateAccountUI();
    await refreshState();
    window.setInterval(() => {
      if (!document.hidden) refreshState();
    }, 1200);
    document.addEventListener("visibilitychange", () => {
      if (!document.hidden) refreshState();
    });
  }

  function cacheElements() {
    Object.assign(els, {
      urlForm: $("#url-form"),
      urlInput: $("#url-input"),
      pasteBtn: $("#paste-btn"),
      fetchBtn: $("#fetch-btn"),
      fetchLabel: $("#fetch-btn .button-label"),
      probeStatus: $("#probe-status"),
      preview: $("#preview"),
      previewEmpty: $("#preview-empty"),
      previewContent: $("#preview-content"),
      quality: $("#quality-control"),
      outputDir: $("#output-dir"),
      browseBtn: $("#browse-btn"),
      embedMetadata: $("#embed-metadata"),
      embedThumbnail: $("#embed-thumbnail"),
      playlist: $("#playlist"),
      useAccount: $("#use-account"),
      accountFields: $("#account-fields"),
      browser: $("#browser"),
      browserProfile: $("#browser-profile"),
      cookiesFile: $("#cookies-file"),
      enginePill: $("#engine-pill"),
      engineLabel: $("#engine-label"),
      statFiles: $("#stat-files"),
      statSize: $("#stat-size"),
      queueList: $("#queue-list"),
      queueCount: $("#queue-count"),
      clearFinished: $("#clear-finished-btn"),
      libraryList: $("#library-list"),
      libraryCount: $("#library-count"),
      openFolder: $("#open-folder-btn"),
      openOutput: $("#open-output-btn"),
      quitApp: $("#quit-app-btn"),
      toastStack: $("#toast-stack"),
      footerStatus: $("#footer-status"),
    });
  }

  function bindEvents() {
    els.urlForm.addEventListener("submit", (event) => {
      event.preventDefault();
      fetchPreview();
    });

    els.pasteBtn.addEventListener("click", async () => {
      try {
        const text = await navigator.clipboard.readText();
        if (!text.trim()) {
          toast("Your clipboard is empty.", "error");
          return;
        }
        els.urlInput.value = text.trim();
        resetPreview();
        fetchPreview();
      } catch {
        els.urlInput.focus();
        toast("Clipboard access was blocked. Paste with Ctrl+V instead.", "error");
      }
    });

    els.urlInput.addEventListener("input", () => {
      if (state.preview && els.urlInput.value.trim() !== state.preview.source_url) {
        resetPreview();
      }
    });

    els.quality.addEventListener("click", (event) => {
      const button = event.target.closest("button[data-quality]");
      if (!button) return;
      setQualityUI(button.dataset.quality);
      scheduleSave();
    });

    [els.outputDir, els.browserProfile, els.cookiesFile].forEach((element) => {
      element.addEventListener("change", scheduleSave);
    });

    els.browser.addEventListener("change", scheduleSave);

    [els.embedMetadata, els.embedThumbnail, els.playlist].forEach((element) => {
      element.addEventListener("change", scheduleSave);
    });

    els.useAccount.addEventListener("change", () => {
      updateAccountUI();
      scheduleSave();
    });

    els.browseBtn.addEventListener("click", pickFolder);
    els.openFolder.addEventListener("click", openOutputFolder);
    els.openOutput.addEventListener("click", openOutputFolder);
    els.quitApp.addEventListener("click", quitApp);
    els.clearFinished.addEventListener("click", clearFinished);

    els.previewContent.addEventListener("click", (event) => {
      const button = event.target.closest("[data-preview-action]");
      if (!button) return;
      const action = button.dataset.previewAction;
      if (action === "queue") queuePreview();
      if (action === "retry") fetchPreview();
      if (action === "clear") {
        resetPreview();
        els.urlInput.focus();
      }
      if (action === "scroll-queue") {
        $("#queue").scrollIntoView({ behavior: "smooth", block: "start" });
      }
    });

    els.queueList.addEventListener("click", handleQueueAction);
    els.libraryList.addEventListener("click", handleLibraryAction);

    $$(".nav-link").forEach((link) => {
      link.addEventListener("click", () => {
        $$(".nav-link").forEach((item) => item.classList.remove("is-active"));
        link.classList.add("is-active");
      });
    });

    document.addEventListener("keydown", (event) => {
      const tag = document.activeElement?.tagName;
      if (event.key === "/" && !["INPUT", "TEXTAREA", "SELECT"].includes(tag)) {
        event.preventDefault();
        els.urlInput.focus();
      }
    });
  }

  async function api(path, options = {}) {
    const headers = Object.assign(
      { "X-App-Token": TOKEN },
      options.body ? { "Content-Type": "application/json" } : {},
      options.headers || {}
    );

    let response;
    try {
      response = await fetch(path, Object.assign({}, options, { headers }));
    } catch {
      throw new Error("The local app is not responding. Is it still running?");
    }

    const text = await response.text();
    let data = {};
    try {
      data = text ? JSON.parse(text) : {};
    } catch {
      throw new Error(`Unexpected response from the app (${response.status}).`);
    }

    if (data.canceled) return data;
    if (!response.ok || data.ok === false) {
      throw new Error(data.error || `Request failed (${response.status}).`);
    }
    return data;
  }

  async function refreshState() {
    if (state.polling) return;
    state.polling = true;
    try {
      const data = await api("/api/state");
      state.jobs = Array.isArray(data.jobs) ? data.jobs : [];
      state.history = Array.isArray(data.history) ? data.history : [];
      state.stats = data.stats || {};
      state.settings = data.settings || state.settings;

      if (!state.settingsLoaded) {
        applySettings(data.settings || {}, true);
        state.settingsLoaded = true;
      }

      renderStats(data.ffmpeg || {});
      renderQueue();
      renderLibrary();
      state.failures = 0;
      els.enginePill.classList.remove("is-offline");
      els.engineLabel.textContent = data.ffmpeg?.ready ? "Engine ready" : "Engine offline";
      if (!data.ffmpeg?.ready) els.enginePill.classList.add("is-offline");
      els.footerStatus.textContent = data.ffmpeg?.ready ? "Local engine ready" : "Engine needs attention";
    } catch (error) {
      state.failures += 1;
      if (state.failures === 1) toast(error.message, "error");
      els.enginePill.classList.add("is-offline");
      els.engineLabel.textContent = "App offline";
      els.footerStatus.textContent = "App offline";
    } finally {
      state.polling = false;
    }
  }

  function applySettings(settings, force = false) {
    if (!settings) return;
    if (force) {
      els.outputDir.value = settings.output_dir || "";
      els.browser.value = settings.browser || "chrome";
      els.browserProfile.value = settings.browser_profile || "";
      els.cookiesFile.value = settings.cookies_file || "";
      els.embedMetadata.checked = Boolean(settings.embed_metadata);
      els.embedThumbnail.checked = Boolean(settings.embed_thumbnail);
      els.playlist.checked = Boolean(settings.playlist);
      els.useAccount.checked = Boolean(settings.use_account);
      setQualityUI(settings.quality || "320K");
      updateAccountUI();
    }
  }

  function collectSettings() {
    return {
      output_dir: els.outputDir.value.trim(),
      quality: currentQuality(),
      embed_metadata: els.embedMetadata.checked,
      embed_thumbnail: els.embedThumbnail.checked,
      playlist: els.playlist.checked,
      use_account: els.useAccount.checked,
      browser: els.browser.value,
      browser_profile: els.browserProfile.value.trim(),
      cookies_file: els.cookiesFile.value.trim(),
    };
  }

  function scheduleSave() {
    window.clearTimeout(state.saveTimer);
    state.saveTimer = window.setTimeout(saveSettings, 350);
  }

  async function saveSettings() {
    const payload = collectSettings();
    if (!payload.output_dir) {
      toast("Choose an output folder before downloading.", "error");
      return;
    }
    try {
      const data = await api("/api/settings", {
        method: "POST",
        body: JSON.stringify(payload),
      });
      state.settings = data.settings;
      if (document.activeElement !== els.outputDir && data.settings.output_dir !== els.outputDir.value) {
        els.outputDir.value = data.settings.output_dir;
      }
    } catch (error) {
      toast(error.message, "error");
    }
  }

  function currentQuality() {
    return $(".segmented button.is-active")?.dataset.quality || "320K";
  }

  function setQualityUI(quality) {
    $$(".segmented button", els.quality).forEach((button) => {
      button.classList.toggle("is-active", button.dataset.quality === quality);
    });
  }

  function updateAccountUI() {
    els.accountFields.classList.toggle("is-muted", !els.useAccount.checked);
  }

  async function fetchPreview() {
    const raw = els.urlInput.value.trim();
    if (!raw) {
      toast("Paste a YouTube link first.", "error");
      els.urlInput.focus();
      return;
    }
    if (state.fetching) return;

    state.fetching = true;
    els.fetchBtn.disabled = true;
    els.fetchBtn.classList.add("is-loading");
    els.fetchLabel.textContent = "Fetching";
    els.probeStatus.textContent = "Reading link";
    els.probeStatus.classList.add("is-busy");
    showPreviewLoading();

    try {
      const data = await api("/api/inspect", {
        method: "POST",
        body: JSON.stringify({ url: raw, ...collectSettings() }),
      });
      state.preview = {
        ...data.info,
        source_url: raw,
        queued: false,
      };
      renderPreview();
      els.probeStatus.textContent = data.info.is_playlist
        ? `${data.info.playlist_count} item${data.info.playlist_count === 1 ? "" : "s"} found`
        : "Ready to queue";
    } catch (error) {
      state.preview = null;
      renderPreviewError(error.message);
      els.probeStatus.textContent = "Could not read link";
      toast(error.message, "error");
    } finally {
      state.fetching = false;
      els.fetchBtn.disabled = false;
      els.fetchBtn.classList.remove("is-loading");
      els.fetchLabel.textContent = "Fetch audio";
      els.probeStatus.classList.remove("is-busy");
    }
  }

  function showPreviewLoading() {
    els.previewEmpty.hidden = true;
    els.previewContent.hidden = false;
    els.previewContent.innerHTML = `
      <div class="preview-loading" aria-label="Fetching track details">
        <div class="skeleton skeleton-thumb"></div>
        <div class="skeleton-lines">
          <div class="skeleton skeleton-line w-35"></div>
          <div class="skeleton skeleton-line w-80"></div>
          <div class="skeleton skeleton-line w-55"></div>
          <div class="skeleton skeleton-line w-35"></div>
        </div>
      </div>`;
  }

  function renderPreview() {
    if (!state.preview) {
      els.previewContent.hidden = true;
      els.previewContent.innerHTML = "";
      els.previewEmpty.hidden = false;
      return;
    }

    const info = state.preview;
    const thumbnail = safeImage(info.thumbnail);
    const playlist = Boolean(info.is_playlist);
    const count = Number(info.playlist_count) || 0;
    const duration = info.duration ? formatDuration(info.duration) : "";
    const meta = [
      escapeHtml(info.uploader || "Unknown channel"),
      duration ? `<span class="dot"></span>${escapeHtml(duration)}` : "",
      playlist && count ? `<span class="dot"></span>${count} track${count === 1 ? "" : "s"}` : "",
    ]
      .filter(Boolean)
      .join("");

    const entries = Array.isArray(info.entries) ? info.entries : [];
    const playlistLines = playlist && entries.length
      ? `<div class="preview-playlist">
          ${entries
            .map(
              (entry) => `<div class="playlist-line">
                <span>${escapeHtml(entry.title || "Untitled")}</span>
                <span>${escapeHtml(formatDuration(entry.duration) || "—")}</span>
              </div>`
            )
            .join("")}
          ${count > entries.length ? `<span class="playlist-more">+ ${count - entries.length} more in this playlist</span>` : ""}
        </div>`
      : "";

    const queueLabel = info.queued
      ? "In queue"
      : playlist
        ? `Queue ${count || ""} track${count === 1 ? "" : "s"}`.replace(/\s+/g, " ").trim()
        : "Add to queue";

    els.previewContent.innerHTML = `
      <div class="preview-grid">
        <div class="preview-thumb">
          ${
            thumbnail
              ? `<img src="${thumbnail}" alt="">`
              : `<div class="thumb-fallback"><svg class="icon"><use href="#i-music"></use></svg></div>`
          }
          <span class="preview-type">${playlist ? "Playlist" : "Video"}</span>
        </div>
        <div class="preview-info">
          <p class="preview-eyebrow">${playlist ? "Ready to batch" : "Ready to convert"}</p>
          <h3>${escapeHtml(info.title || "Untitled")}</h3>
          <div class="preview-meta">${meta}</div>
          <div class="preview-actions">
            <button class="secondary-button accent" type="button" data-preview-action="queue" ${info.queued ? "disabled" : ""}>
              <svg class="icon"><use href="#i-${info.queued ? "check" : "download"}"></use></svg>
              ${escapeHtml(queueLabel)}
            </button>
            ${
              info.queued
                ? `<button class="secondary-button" type="button" data-preview-action="scroll-queue">View queue</button>`
                : `<button class="secondary-button" type="button" data-preview-action="clear">Clear</button>`
            }
          </div>
        </div>
      </div>
      ${playlistLines}`;

    els.previewEmpty.hidden = true;
    els.previewContent.hidden = false;
  }

  function renderPreviewError(message) {
    els.previewEmpty.hidden = true;
    els.previewContent.hidden = false;
    els.previewContent.innerHTML = `
      <div class="preview-error">
        <span class="preview-error-icon"><svg class="icon"><use href="#i-alert"></use></svg></span>
        <div>
          <strong>That link did not work</strong>
          <p>${escapeHtml(message)}</p>
        </div>
        <button class="secondary-button" type="button" data-preview-action="retry">Try again</button>
      </div>`;
  }

  function resetPreview() {
    state.preview = null;
    els.previewContent.hidden = true;
    els.previewContent.innerHTML = "";
    els.previewEmpty.hidden = false;
    els.probeStatus.textContent = "Waiting for a link";
    els.probeStatus.classList.remove("is-busy");
  }

  async function queuePreview() {
    if (!state.preview || state.preview.queued) return;
    const button = $('[data-preview-action="queue"]', els.previewContent);
    if (button) {
      button.disabled = true;
      button.textContent = "Adding...";
    }

    try {
      const data = await api("/api/jobs", {
        method: "POST",
        body: JSON.stringify({ url: state.preview.source_url, ...collectSettings() }),
      });
      state.preview.queued = true;
      renderPreview();
      els.probeStatus.textContent = "In queue";
      toast(
        data.job.playlist ? "Playlist added to the queue." : "Track added to the queue.",
        "success"
      );
      await refreshState();
      $("#queue").scrollIntoView({ behavior: "smooth", block: "start" });
    } catch (error) {
      toast(error.message, "error");
      renderPreview();
    }
  }

  function renderStats(ffmpeg) {
    els.statFiles.textContent = String(state.stats.completed || 0);
    els.statSize.textContent = formatBytes(state.stats.total_bytes || 0);
    if (!ffmpeg.ready) {
      els.engineLabel.textContent = "Engine offline";
      els.enginePill.classList.add("is-offline");
    }
  }

  function renderQueue() {
    const jobs = [...state.jobs].reverse();
    const signature = JSON.stringify(
      jobs.map((job) => [
        job.id,
        job.status,
        job.progress,
        job.stage,
        job.message,
        job.title,
        job.thumbnail,
        job.file_count,
        job.item_index,
        job.item_count,
        job.speed,
        job.eta,
        job.path,
      ])
    );
    if (signature === state.queueSignature) return;
    state.queueSignature = signature;

    els.queueCount.textContent = `${jobs.length} job${jobs.length === 1 ? "" : "s"}`;
    els.clearFinished.disabled = !jobs.some((job) =>
      ["completed", "failed", "canceled", "partial"].includes(job.status)
    );

    if (!jobs.length) {
      els.queueList.innerHTML = `
        <div class="empty-row">
          <svg class="icon"><use href="#i-list"></use></svg>
          <p>Nothing queued yet. Fetch a link above to get started.</p>
        </div>`;
      return;
    }

    els.queueList.innerHTML = jobs.slice(0, 30).map(jobTemplate).join("");
  }

  function jobTemplate(job) {
    const status = job.status || "queued";
    const title = escapeHtml(job.title || job.url || "Untitled");
    const thumbnail = safeImage(job.thumbnail);
    const progress = Math.max(0, Math.min(100, Number(job.progress) || 0));
    const meta = [
      job.uploader ? escapeHtml(job.uploader) : "",
      job.duration ? escapeHtml(formatDuration(job.duration)) : "",
      qualityLabel(job.quality),
      job.file_count > 1 ? `${job.file_count} files` : "",
    ]
      .filter(Boolean)
      .map((item) => `<span>${item}</span>`)
      .join('<span class="dot"></span>');

    const detail =
      status === "running"
        ? [
            `${Math.round(progress)}%`,
            job.speed ? `${formatBytes(job.speed)}/s` : "",
            job.eta ? `ETA ${escapeHtml(job.eta)}` : "",
          ]
            .filter(Boolean)
            .join(" · ")
        : status === "queued"
          ? "Waiting for the worker"
          : status === "completed"
            ? `MP3 ready${job.file_count > 1 ? ` · ${job.file_count} files` : ""}`
            : status === "partial"
              ? "Some files finished"
              : status === "canceled"
                ? "Canceled"
                : "";

    const error =
      (status === "failed" || status === "partial") && job.message
        ? `<p class="job-error">${escapeHtml(job.message)}</p>`
        : "";

    const art = thumbnail
      ? `<img src="${thumbnail}" alt="">`
      : `<svg class="icon"><use href="#i-music"></use></svg>`;

    let actions = "";
    if (status === "queued" || status === "running") {
      actions = `<button class="job-action danger" type="button" data-action="cancel" data-id="${escapeHtml(
        job.id
      )}" title="Cancel" aria-label="Cancel"><svg class="icon"><use href="#i-x"></use></svg></button>`;
    } else if (status === "completed" || status === "partial") {
      actions = `
        <button class="job-action" type="button" data-action="open" data-path="${escapeHtml(
          job.path || ""
        )}" title="Open MP3" aria-label="Open MP3"><svg class="icon"><use href="#i-play"></use></svg></button>
        <button class="job-action" type="button" data-action="reveal" data-path="${escapeHtml(
          job.path || ""
        )}" title="Show in folder" aria-label="Show in folder"><svg class="icon"><use href="#i-folder"></use></svg></button>`;
    } else {
      actions = `<button class="job-action" type="button" data-action="retry" data-id="${escapeHtml(
        job.id
      )}" title="Retry" aria-label="Retry"><svg class="icon"><use href="#i-refresh"></use></svg></button>`;
    }

    return `
      <article class="job ${status === "failed" ? "is-failed" : ""}" data-status="${escapeHtml(status)}">
        <div class="job-art">${art}</div>
        <div class="job-main">
          <div class="job-top">
            <div class="job-heading">
              <h3 class="job-title" title="${title}">${title}</h3>
              <p class="job-meta">${meta || "<span>YouTube</span>"}</p>
            </div>
            <span class="status-pill status-${escapeHtml(status)}">${escapeHtml(statusLabel(status))}</span>
          </div>
          <div class="progress-track"><span class="progress-fill" style="width: ${progress}%"></span></div>
          <div class="job-bottom">
            <span>${escapeHtml(job.stage || statusLabel(status))}</span>
            <span>${detail ? escapeHtml(detail) : ""}</span>
          </div>
          ${error}
        </div>
        <div class="job-actions">${actions}</div>
      </article>`;
  }

  async function handleQueueAction(event) {
    const button = event.target.closest("[data-action]");
    if (!button) return;
    const action = button.dataset.action;
    const id = button.dataset.id;
    const path = button.dataset.path;
    button.disabled = true;

    try {
      if (action === "cancel") {
        await api(`/api/jobs/${encodeURIComponent(id)}/cancel`, { method: "POST", body: "{}" });
        toast("Job canceled.", "info");
      } else if (action === "retry") {
        await api(`/api/jobs/${encodeURIComponent(id)}/retry`, { method: "POST", body: "{}" });
        toast("Job queued again.", "success");
      } else if (action === "open") {
        await api("/api/open", { method: "POST", body: JSON.stringify({ path }) });
      } else if (action === "reveal") {
        await api("/api/reveal", { method: "POST", body: JSON.stringify({ path }) });
      }
      await refreshState();
    } catch (error) {
      toast(error.message, "error");
    } finally {
      button.disabled = false;
    }
  }

  function renderLibrary() {
    const items = state.history.slice(0, 12);
    const signature = JSON.stringify(
      items.map((item) => [item.id, item.title, item.path, item.size, item.exists, item.thumbnail])
    );
    if (signature === state.librarySignature) return;
    state.librarySignature = signature;

    els.libraryCount.textContent = `${state.history.length} file${state.history.length === 1 ? "" : "s"}`;

    if (!items.length) {
      els.libraryList.innerHTML = `
        <div class="empty-row">
          <svg class="icon"><use href="#i-music"></use></svg>
          <p>Finished MP3s will collect here.</p>
        </div>`;
      return;
    }

    els.libraryList.innerHTML = items.map(libraryTemplate).join("");
  }

  function libraryTemplate(item) {
    const thumbnail = safeImage(item.thumbnail);
    const missing = item.exists === false;
    const meta = [
      item.uploader ? escapeHtml(item.uploader) : "",
      formatBytes(item.size || 0),
      formatWhen(item.completed_at),
    ]
      .filter(Boolean)
      .join('<span class="dot"></span>');

    return `
      <article class="library-card ${missing ? "is-missing" : ""}">
        <div class="library-thumb">
          ${
            thumbnail
              ? `<img src="${thumbnail}" alt="">`
              : `<svg class="icon"><use href="#i-music"></use></svg>`
          }
          <span class="library-badge">MP3</span>
        </div>
        <div class="library-body">
          <p class="library-title" title="${escapeHtml(item.title || "Untitled")}">${escapeHtml(
            item.title || "Untitled"
          )}</p>
          <p class="library-meta">${missing ? "<span>File missing</span>" : meta}</p>
          <div class="library-actions">
            <button class="job-action" type="button" data-action="open" data-path="${escapeHtml(
              item.path || ""
            )}" title="${missing ? "File missing" : "Open MP3"}" aria-label="Open MP3" ${
              missing ? "disabled" : ""
            }><svg class="icon"><use href="#i-play"></use></svg></button>
            <button class="job-action" type="button" data-action="reveal" data-path="${escapeHtml(
              item.path || ""
            )}" title="Show in folder" aria-label="Show in folder" ${
              missing ? "disabled" : ""
            }><svg class="icon"><use href="#i-folder"></use></svg></button>
          </div>
        </div>
      </article>`;
  }

  async function handleLibraryAction(event) {
    const button = event.target.closest("[data-action]");
    if (!button || button.disabled) return;
    const path = button.dataset.path;
    button.disabled = true;
    try {
      if (button.dataset.action === "open") {
        await api("/api/open", { method: "POST", body: JSON.stringify({ path }) });
      } else {
        await api("/api/reveal", { method: "POST", body: JSON.stringify({ path }) });
      }
    } catch (error) {
      toast(error.message, "error");
    } finally {
      button.disabled = false;
    }
  }

  async function clearFinished() {
    els.clearFinished.disabled = true;
    try {
      await api("/api/jobs/clear-finished", { method: "POST", body: "{}" });
      toast("Finished jobs cleared.", "info");
      await refreshState();
    } catch (error) {
      toast(error.message, "error");
      els.clearFinished.disabled = false;
    }
  }

  async function pickFolder() {
    els.browseBtn.disabled = true;
    try {
      const data = await api("/api/pick-folder", { method: "POST", body: "{}" });
      if (data.path) {
        els.outputDir.value = data.path;
        await saveSettings();
        toast("Output folder updated.", "success");
      }
    } catch (error) {
      toast(error.message, "error");
    } finally {
      els.browseBtn.disabled = false;
    }
  }

  async function openOutputFolder() {
    try {
      await api("/api/open-output", { method: "POST", body: "{}" });
    } catch (error) {
      toast(error.message, "error");
    }
  }

  async function quitApp() {
    if (!window.confirm("Stop yt2mp3? The local app will close and this tab will stop working.")) {
      return;
    }
    try {
      await api("/api/quit", { method: "POST", body: "{}" });
      toast("yt2mp3 is stopping. You can close this tab.", "success");
      els.quitApp.disabled = true;
    } catch (error) {
      toast(error.message, "error");
    }
  }

  function toast(message, type = "info") {
    const icon = type === "error" ? "alert" : type === "success" ? "check" : "spark";
    const element = document.createElement("div");
    element.className = `toast is-${type}`;
    element.innerHTML = `<svg class="icon"><use href="#i-${icon}"></use></svg><span>${escapeHtml(
      message
    )}</span>`;
    els.toastStack.appendChild(element);
    window.setTimeout(() => {
      element.classList.add("is-leaving");
      window.setTimeout(() => element.remove(), 200);
    }, type === "error" ? 6200 : 3400);
  }

  function safeImage(value) {
    if (!value) return "";
    try {
      const url = new URL(value, window.location.href);
      if (!["http:", "https:"].includes(url.protocol)) return "";
      return escapeHtml(url.href);
    } catch {
      return "";
    }
  }

  function escapeHtml(value) {
    return String(value ?? "").replace(/[&<>"']/g, (character) => {
      return {
        "&": "&amp;",
        "<": "&lt;",
        ">": "&gt;",
        '"': "&quot;",
        "'": "&#39;",
      }[character];
    });
  }

  function formatDuration(seconds) {
    if (seconds === null || seconds === undefined || seconds === "") return "";
    const value = Number(seconds);
    if (!Number.isFinite(value) || value < 0) return "";
    const total = Math.round(value);
    const hours = Math.floor(total / 3600);
    const minutes = Math.floor((total % 3600) / 60);
    const secs = total % 60;
    if (hours > 0) {
      return `${hours}:${String(minutes).padStart(2, "0")}:${String(secs).padStart(2, "0")}`;
    }
    return `${minutes}:${String(secs).padStart(2, "0")}`;
  }

  function formatBytes(bytes) {
    const value = Number(bytes) || 0;
    if (value <= 0) return "0 MB";
    const units = ["B", "KB", "MB", "GB", "TB"];
    const index = Math.min(Math.floor(Math.log(value) / Math.log(1024)), units.length - 1);
    const amount = value / 1024 ** index;
    const digits = index >= 2 ? (amount >= 100 ? 0 : 1) : 0;
    return `${amount.toFixed(digits)} ${units[index]}`;
  }

  function formatWhen(value) {
    if (!value) return "";
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return "";
    const now = new Date();
    const sameDay =
      date.getFullYear() === now.getFullYear() &&
      date.getMonth() === now.getMonth() &&
      date.getDate() === now.getDate();
    if (sameDay) return "Today";
    return date.toLocaleDateString(undefined, { month: "short", day: "numeric" });
  }

  function qualityLabel(value) {
    return { "320K": "320 kbps", "256K": "256 kbps", "192K": "192 kbps", "128K": "128 kbps", "0": "VBR" }[
      value
    ] || "";
  }

  function statusLabel(status) {
    return {
      queued: "Queued",
      running: "Working",
      completed: "Done",
      partial: "Partial",
      failed: "Failed",
      canceled: "Canceled",
    }[status] || status;
  }
})();
