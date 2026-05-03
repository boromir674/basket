// Central runtime asset-path resolver populated from runtime config for all prod pages.
// The key feature is deterministic processed/raw asset URL generation with no path fallbacks.
(function attachBasketRuntimeConfig(globalScope) {
  const runtimeRoot = globalScope || window;

  function normalizeSubdir(value, fallback) {
    const raw = String(value || fallback || "").trim();
    return raw.replace(/^\/+/, "").replace(/\/+$/, "");
  }

  function normalizePattern(value, fallback) {
    const raw = String(value || fallback || "").trim();
    return raw || fallback;
  }

  function fromToken(tokenValue, fallback) {
    const token = String(tokenValue || "");
    if (!token || /^__BASKET_[A-Z0-9_]+__$/.test(token)) return fallback;
    return token;
  }

  const merged = {
    processedSubdir: normalizeSubdir(
      fromToken("__BASKET_PROCESSED_SUBDIR__", "assets/processed"),
      "assets/processed"
    ),
    rawAssetsSubdir: normalizeSubdir(
      fromToken("__BASKET_RAW_ASSETS_SUBDIR__", "assets"),
      "assets"
    ),
    defaultBundleFile: fromToken("__BASKET_DEFAULT_BUNDLE_FILE__", ""),
    manifestFile: fromToken("__BASKET_MANIFEST_FILE__", "games_manifest.json"),
    rawPtsPattern: normalizePattern(
      fromToken("__BASKET_RAW_PTS_PATTERN__", "raw_pts_{season}_{game}.json"),
      "raw_pts_{season}_{game}.json"
    ),
    eloPattern: normalizePattern(
      fromToken("__BASKET_ELO_PATTERN__", "elo_{season}.json"),
      "elo_{season}.json"
    ),
    styleInsightsPattern: normalizePattern(
      fromToken("__BASKET_STYLE_INSIGHTS_PATTERN__", "style_insights_{season}.json"),
      "style_insights_{season}.json"
    ),
  };

  function inProdSubdir() {
    const pathname = String((runtimeRoot.location && runtimeRoot.location.pathname) || "");
    return pathname.includes("/prod/");
  }

  function relBaseForSubdir(subdir) {
    const normalized = normalizeSubdir(subdir, "");
    return inProdSubdir() ? `../${normalized}` : `./${normalized}`;
  }

  function applyPattern(pattern, replacements) {
    let out = String(pattern || "");
    Object.entries(replacements || {}).forEach(([key, value]) => {
      out = out.replaceAll(`{${key}}`, String(value == null ? "" : value));
    });
    return out;
  }

  function resolveFileStoreBase(fileBaseParam) {
    const envBase = String(runtimeRoot.BASKET_APP_FILE_STORE_URI || "").trim();
    const queryBase = String(fileBaseParam || "").trim();
    const runtimeBase = envBase || queryBase;
    if (!runtimeBase) return null;
    return runtimeBase.endsWith("/") ? runtimeBase.slice(0, -1) : runtimeBase;
  }

  function buildProcessedUrl(filename, opts) {
    const name = String(filename || "").replace(/^\/+/, "");
    const runtimeBase = resolveFileStoreBase(opts && opts.fileBase);
    if (runtimeBase) {
      if (runtimeBase.endsWith(`/${merged.processedSubdir}`)) return `${runtimeBase}/${name}`;
      return `${runtimeBase}/${merged.processedSubdir}/${name}`;
    }
    return `${relBaseForSubdir(merged.processedSubdir)}/${name}`;
  }

  function buildRawAssetUrl(filename, opts) {
    const name = String(filename || "").replace(/^\/+/, "");
    const runtimeBase = resolveFileStoreBase(opts && opts.fileBase);
    if (runtimeBase) return `${runtimeBase}/${merged.rawAssetsSubdir}/${name}`;
    return `${relBaseForSubdir(merged.rawAssetsSubdir)}/${name}`;
  }

  runtimeRoot.BasketRuntimeConfig = {
    ...merged,
    inProdSubdir,
    relBaseForSubdir,
    applyPattern,
    resolveFileStoreBase,
    buildProcessedUrl,
    buildRawAssetUrl,
  };
})(typeof window !== "undefined" ? window : this);
