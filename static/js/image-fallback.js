/**
 * Troca capas quebradas (/media/articles/...) pelo SVG padrão da categoria (data-fallback).
 */
(function () {
  function applyFallback(img) {
    if (!(img instanceof HTMLImageElement)) return;
    var fallback = img.getAttribute("data-fallback");
    if (!fallback || img.dataset.fbApplied === "1") return;
    img.dataset.fbApplied = "1";
    img.removeAttribute("srcset");
    img.src = fallback;
  }

  document.addEventListener(
    "error",
    function (event) {
      var target = event.target;
      if (target && target.tagName === "IMG") applyFallback(target);
    },
    true
  );
})();
