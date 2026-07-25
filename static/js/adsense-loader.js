/**
 * Carrega unidades AdSense com mitigação:
 * - push lazy (IntersectionObserver) — menos 400 por rajada
 * - bloqueia fluid sem layout-key
 * - esconde unidades unfilled / inválidas
 * - evita double-push
 */
(function () {
  var MAX_PUSHES = 8;
  var pushed = 0;

  function hideUnit(ins) {
    if (!(ins instanceof Element)) return;
    var box = ins.closest(".ad-center, .ad-rail, .ad-skin");
    if (box) {
      box.style.display = "none";
      box.setAttribute("data-ad-hidden", "1");
    }
  }

  function isValidIns(ins) {
    var client = (ins.getAttribute("data-ad-client") || "").trim();
    var slot = (ins.getAttribute("data-ad-slot") || "").trim();
    if (!client || !slot) return false;
    var format = (ins.getAttribute("data-ad-format") || "").trim();
    if (format === "fluid") {
      var layout = (ins.getAttribute("data-ad-layout-key") || "").trim();
      if (!layout) return false;
    }
    return true;
  }

  function pushIns(ins) {
    if (!(ins instanceof HTMLElement)) return;
    if (ins.dataset.adPushed === "1") return;
    if (!isValidIns(ins)) {
      hideUnit(ins);
      return;
    }
    if (pushed >= MAX_PUSHES) {
      hideUnit(ins);
      return;
    }
    ins.dataset.adPushed = "1";
    pushed += 1;
    try {
      (window.adsbygoogle = window.adsbygoogle || []).push({});
    } catch (_err) {
      hideUnit(ins);
    }
  }

  function observeIns(ins) {
    if (!(ins instanceof HTMLElement) || ins.dataset.adObserved === "1") return;
    ins.dataset.adObserved = "1";
    if (!("IntersectionObserver" in window)) {
      pushIns(ins);
      return;
    }
    var io = new IntersectionObserver(
      function (entries) {
        entries.forEach(function (entry) {
          if (!entry.isIntersecting) return;
          io.disconnect();
          pushIns(ins);
        });
      },
      { rootMargin: "180px 0px", threshold: 0.01 }
    );
    io.observe(ins);
  }

  function scan(root) {
    var scope = root && root.querySelectorAll ? root : document;
    scope.querySelectorAll("ins.adsbygoogle").forEach(observeIns);
    scope.querySelectorAll('ins.adsbygoogle[data-ad-status="unfilled"]').forEach(hideUnit);
  }

  function watchStatuses() {
    if (!("MutationObserver" in window)) return;
    var mo = new MutationObserver(function (mutations) {
      mutations.forEach(function (m) {
        if (m.type === "attributes" && m.target && m.target.tagName === "INS") {
          if (m.target.getAttribute("data-ad-status") === "unfilled") {
            hideUnit(m.target);
          }
        }
        if (m.type === "childList") {
          m.addedNodes.forEach(function (node) {
            if (!(node instanceof Element)) return;
            if (node.matches && node.matches("ins.adsbygoogle")) observeIns(node);
            else scan(node);
          });
        }
      });
    });
    mo.observe(document.documentElement, {
      subtree: true,
      childList: true,
      attributes: true,
      attributeFilter: ["data-ad-status"],
    });
  }

  function init() {
    scan(document);
    watchStatuses();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }

  window.__financasAdsenseScan = scan;
})();
