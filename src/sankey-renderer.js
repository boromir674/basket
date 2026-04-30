(function (global) {
  function parseRenderMode(paramsString, defaults) {
    var out = {
      initialView: defaults && defaults.initialView ? defaults.initialView : "top",
      typeZoomVariant: defaults && defaults.typeZoomVariant ? defaults.typeZoomVariant : 4,
      skipTypeStage: !!(defaults && defaults.skipTypeStage)
    };
    if (!paramsString) return out;

    var p = new URLSearchParams(paramsString);
    var iv = p.get("initialView");
    if (iv) out.initialView = iv;

    var tz = parseInt(p.get("typeZoomVariant") || "", 10);
    if (Number.isFinite(tz)) out.typeZoomVariant = Math.max(3, Math.min(4, tz));

    out.skipTypeStage = p.get("skipTypeStage") === "1";
    return out;
  }

  function createSankeyRenderer(api) {
    return {
      render: function (viewKey, opts) {
        return api.setView(viewKey, opts || {});
      },
      renderInitial: function (requestedView) {
        var bundle = api.getBundle();
        if (!bundle) return;
        var next = api.resolveInitialView(bundle, requestedView || api.getCurrentView());
        api.setView(next, { animate: false });
      },
      applyMode: function (paramsString) {
        var mode = parseRenderMode(paramsString, {
          initialView: api.getCurrentView(),
          typeZoomVariant: api.getTypeZoomVariant(),
          skipTypeStage: api.getSkipTypeStage()
        });
        api.setRenderMode(mode);
        var bundle = api.getBundle();
        if (!bundle) return;
        var viewKey = api.resolveInitialView(bundle, mode.initialView || api.getCurrentView());
        api.setView(viewKey);
      }
    };
  }

  global.BasketSankeyRendererModule = {
    createSankeyRenderer: createSankeyRenderer,
    parseRenderMode: parseRenderMode
  };
})(window);
