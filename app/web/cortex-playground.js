"use strict";

(() => {
  const STORAGE_KEY = "volcurve.cortex.playground.request.v1";

  const DEFAULT_REQUEST = {
    code: "HK_HSCEI",
    codeType: "bnpp",
    maturityRule: "fixed",
    strikeRule: "relative_to_forward",
    volatilityConvention: "bsVol",
    startDate: "2026-01-01",
    endDate: "2026-08-08",
    layout: "matrix",
    lowStrike: "100_0",
    highStrike: "100_0",
    lowFixedMaturity: "2026-09-29",
    highFixedMaturity: "2026-09-29"
  };

  function $(id) { return document.getElementById(id); }
  function pretty(value) { return JSON.stringify(value, null, 2); }

  function setStatus(text, isError = false) {
    const node = $("playgroundStatus");
    if (!node) return;
    node.textContent = text;
    node.classList.toggle("is-error", isError);
  }

  function setResponse(value) {
    const node = $("playgroundResponse");
    if (!node) return;
    node.textContent = typeof value === "string" ? value : pretty(value);
  }

  function parseEditor() {
    const raw = $("playgroundRequest").value.trim();
    if (!raw) throw new Error("Request JSON is empty.");
    const parsed = JSON.parse(raw);
    if (!parsed || Array.isArray(parsed) || typeof parsed !== "object") {
      throw new Error("Request JSON must be an object.");
    }
    return parsed;
  }

  function persistRequest() {
    try { localStorage.setItem(STORAGE_KEY, $("playgroundRequest").value); } catch (_error) {}
  }

  function restoreRequest() {
    let saved = null;
    try { saved = localStorage.getItem(STORAGE_KEY); } catch (_error) {}
    $("playgroundRequest").value = saved || pretty(DEFAULT_REQUEST);
  }

  function formatRequest() {
    try {
      const parsed = parseEditor();
      $("playgroundRequest").value = pretty(parsed);
      persistRequest();
      setStatus("JSON formatted.");
    } catch (error) {
      setStatus(`Invalid JSON · ${error.message}`, true);
    }
  }

  async function sendRequest() {
    let body;
    try {
      body = parseEditor();
    } catch (error) {
      setStatus(`Invalid JSON · ${error.message}`, true);
      return;
    }

    persistRequest();
    const button = $("playgroundSend");
    button.disabled = true;
    setStatus("Sending live request…");
    setResponse("");

    const localStart = performance.now();
    try {
      const response = await fetch("/api/cortex-playground/implied-volatility", {
        method: "POST",
        headers: { "Content-Type": "application/json", "Accept": "application/json" },
        body: JSON.stringify(body)
      });

      const requestId = response.headers.get("X-Request-ID") || "—";
      const text = await response.text();
      let data;
      try { data = text ? JSON.parse(text) : null; } catch (_error) { data = text; }

      const browserMs = Math.round(performance.now() - localStart);
      if (response.ok && data && Object.prototype.hasOwnProperty.call(data, "payload")) {
        const upstreamMs = Number.isFinite(Number(data.elapsedMs))
          ? `${data.elapsedMs} ms upstream`
          : `${browserMs} ms`;
        setStatus(`HTTP ${response.status} · ${upstreamMs} · cid ${data.correlationId || "—"} · request ${requestId}`);
        setResponse(data.payload);
      } else {
        setStatus(`HTTP ${response.status} · ${browserMs} ms · request ${requestId}`, true);
        setResponse(data);
      }
    } catch (error) {
      setStatus(`Request failed · ${error.message}`, true);
      setResponse("");
    } finally {
      button.disabled = false;
    }
  }

  async function copyResponse() {
    const text = $("playgroundResponse").textContent || "";
    if (!text) return setStatus("No response to copy.", true);
    try {
      await navigator.clipboard.writeText(text);
      setStatus("Response copied.");
    } catch (_error) {
      setStatus("Clipboard access failed.", true);
    }
  }

  function resetRequest() {
    $("playgroundRequest").value = pretty(DEFAULT_REQUEST);
    persistRequest();
    setStatus("Request reset.");
  }

  function init() {
    if (!$("cortexPlayground")) return;
    restoreRequest();
    $("playgroundFormat").addEventListener("click", formatRequest);
    $("playgroundSend").addEventListener("click", sendRequest);
    $("playgroundCopy").addEventListener("click", copyResponse);
    $("playgroundReset").addEventListener("click", resetRequest);
    $("playgroundRequest").addEventListener("input", persistRequest);
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init, { once: true });
  } else {
    init();
  }
})();
