const SHOT_TYPES = ["ft", "two", "three"];
const COLORS = { ft: "#a78bfa", two: "#34d399", three: "#fbbf24" };

function classifyAttempt(idAction) {
  if (!idAction) return null;
  const action = String(idAction).trim().toUpperCase();
  if (action === "FTM" || action === "FTA") return "ft";
  if (action === "2FGM" || action === "2FGA") return "two";
  if (action === "3FGM" || action === "3FGA") return "three";
  return null;
}

function toMinute(row) {
  const base = Number(row.MINUTE || 0);
  const consoleClock = String(row.CONSOLE || "");
  const parts = consoleClock.split(":");
  if (parts.length !== 2) return base;
  const sec = Number(parts[1] || 0);
  if (!Number.isFinite(sec) || sec <= 0) return base;
  return base + (60 - sec) / 60;
}

function zeroCounts() {
  return { ft: 0, two: 0, three: 0, total: 0 };
}

function mean(values) {
  if (!values.length) return 0;
  return values.reduce((sum, value) => sum + value, 0) / values.length;
}

function stdDev(values) {
  if (values.length <= 1) return 0;
  const m = mean(values);
  const variance = values.reduce((sum, value) => sum + ((value - m) ** 2), 0) / (values.length - 1);
  return Math.sqrt(variance);
}

function cloneCountsMap(countsMap) {
  const out = {};
  for (const [team, counts] of Object.entries(countsMap)) {
    out[team] = { ...counts };
  }
  return out;
}

export function buildAttemptModel(rows) {
  const countsByTeam = {};
  const quartersByTeam = {};
  const teams = [];
  const events = [];

  function ensureTeam(team) {
    if (!team) return;
    if (!countsByTeam[team]) {
      countsByTeam[team] = zeroCounts();
      quartersByTeam[team] = [zeroCounts(), zeroCounts(), zeroCounts(), zeroCounts()];
      teams.push(team);
    }
  }

  for (const row of rows) {
    const type = classifyAttempt(row.ID_ACTION);
    if (!type) continue;
    const team = String(row.TEAM || "").trim();
    ensureTeam(team);

    countsByTeam[team][type] += 1;
    countsByTeam[team].total += 1;

    const minute = toMinute(row);
    const qIndex = Math.max(0, Math.min(3, Math.floor(minute / 10)));
    quartersByTeam[team][qIndex][type] += 1;
    quartersByTeam[team][qIndex].total += 1;

    events.push({
      minute,
      diff: Number(row.POINTS_B || 0) - Number(row.POINTS_A || 0),
      countsByTeam: cloneCountsMap(countsByTeam),
    });
  }

  events.unshift({ minute: 0, diff: 0, countsByTeam: cloneCountsMap({}) });

  return {
    teams,
    events,
    teamTotals: cloneCountsMap(countsByTeam),
    quartersByTeam,
  };
}

export function buildTeamSeries(model, teamCode) {
  return model.events.map((event) => {
    const counts = event.countsByTeam[teamCode] || zeroCounts();
    const total = counts.total || 1;
    return {
      minute: event.minute,
      diff: event.diff,
      ftShare: counts.ft / total,
      twoShare: counts.two / total,
      threeShare: counts.three / total,
      totalAttempts: counts.total,
    };
  });
}

export function buildGameAttemptVector(rows, teamCode) {
  const counts = zeroCounts();
  for (const row of rows) {
    const type = classifyAttempt(row.ID_ACTION);
    if (!type) continue;
    const team = String(row.TEAM || "").trim();
    if (team !== teamCode) continue;
    counts[type] += 1;
    counts.total += 1;
  }

  if (!counts.total) {
    return null;
  }

  return {
    ft: counts.ft,
    two: counts.two,
    three: counts.three,
    total: counts.total,
    ftShare: counts.ft / counts.total,
    twoShare: counts.two / counts.total,
    threeShare: counts.three / counts.total,
  };
}

function clear(el) {
  while (el.firstChild) el.removeChild(el.firstChild);
}

function emptyState(el, message) {
  clear(el);
  const div = document.createElement("div");
  div.style.color = "#9ab0d4";
  div.style.fontSize = "12px";
  div.style.padding = "16px";
  div.textContent = message;
  el.appendChild(div);
}

export function renderSplitContextDiet(container, series) {
  if (!series.length) {
    emptyState(container, "No attempt events found.");
    return;
  }
  clear(container);

  const d3 = window.d3;
  const W = 820;
  const H1 = 170;
  const H2 = 250;
  const margin = { top: 16, right: 14, bottom: 22, left: 38 };
  const innerW = W - margin.left - margin.right;
  const innerH1 = H1 - margin.top - margin.bottom;
  const innerH2 = H2 - margin.top - margin.bottom;

  const maxMinute = d3.max(series, (d) => d.minute) || 40;
  const maxDiff = Math.max(5, d3.max(series, (d) => Math.abs(d.diff)) || 5);

  const x = d3.scaleLinear().domain([0, maxMinute]).range([0, innerW]);

  const svg1 = d3.create("svg").attr("viewBox", `0 0 ${W} ${H1}`).style("width", "100%").style("display", "block");
  const g1 = svg1.append("g").attr("transform", `translate(${margin.left},${margin.top})`);
  const y1 = d3.scaleLinear().domain([-(maxDiff + 2), maxDiff + 2]).range([innerH1, 0]);

  const line = d3.line().x((d) => x(d.minute)).y((d) => y1(d.diff)).curve(d3.curveCatmullRom.alpha(0.5));

  g1.append("line").attr("x1", 0).attr("x2", innerW).attr("y1", y1(0)).attr("y2", y1(0)).attr("stroke", "#2a446a");
  g1.append("path").datum(series).attr("fill", "none").attr("stroke", "#ffffff").attr("stroke-width", 2).attr("d", line);
  g1.append("g").attr("transform", `translate(0,${innerH1})`).call(d3.axisBottom(x).ticks(8).tickFormat((d) => `${d}'`)).call((ax) => ax.selectAll("text").attr("fill", "#8ea6cb").attr("font-size", 11)).call((ax) => ax.selectAll("line,.domain").attr("stroke", "#2a446a"));
  g1.append("g").call(d3.axisLeft(y1).ticks(5)).call((ax) => ax.selectAll("text").attr("fill", "#8ea6cb").attr("font-size", 11)).call((ax) => ax.selectAll("line,.domain").attr("stroke", "#2a446a"));

  const lbl1 = document.createElement("div");
  lbl1.textContent = "Context lane: oriented score margin";
  lbl1.style.fontSize = "12px";
  lbl1.style.color = "#9ab0d4";
  lbl1.style.margin = "0 0 4px";
  container.appendChild(lbl1);
  container.appendChild(svg1.node());

  const svg2 = d3.create("svg").attr("viewBox", `0 0 ${W} ${H2}`).style("width", "100%").style("display", "block").style("marginTop", "8px");
  const g2 = svg2.append("g").attr("transform", `translate(${margin.left},${margin.top})`);
  const y2 = d3.scaleLinear().domain([0, 1]).range([innerH2, 0]);

  function toLayer(type, baseFn) {
    return series.map((d) => {
      const y0 = baseFn(d);
      const h = type === "ft" ? d.ftShare : type === "two" ? d.twoShare : d.threeShare;
      return { x: x(d.minute), y0: y2(y0), y1: y2(y0 + h) };
    });
  }

  const area = d3.area().x((d) => d.x).y0((d) => d.y0).y1((d) => d.y1).curve(d3.curveCatmullRom.alpha(0.45));
  const ftLayer = toLayer("ft", () => 0);
  const twoLayer = toLayer("two", (d) => d.ftShare);
  const threeLayer = toLayer("three", (d) => d.ftShare + d.twoShare);

  g2.append("path").datum(ftLayer).attr("d", area).attr("fill", COLORS.ft).attr("opacity", 0.85);
  g2.append("path").datum(twoLayer).attr("d", area).attr("fill", COLORS.two).attr("opacity", 0.85);
  g2.append("path").datum(threeLayer).attr("d", area).attr("fill", COLORS.three).attr("opacity", 0.85);

  g2.append("g").attr("transform", `translate(0,${innerH2})`).call(d3.axisBottom(x).ticks(8).tickFormat((d) => `${d}'`)).call((ax) => ax.selectAll("text").attr("fill", "#8ea6cb").attr("font-size", 11)).call((ax) => ax.selectAll("line,.domain").attr("stroke", "#2a446a"));
  g2.append("g").call(d3.axisLeft(y2).ticks(5).tickFormat((d) => `${Math.round(d * 100)}%`)).call((ax) => ax.selectAll("text").attr("fill", "#8ea6cb").attr("font-size", 11)).call((ax) => ax.selectAll("line,.domain").attr("stroke", "#2a446a"));

  const lbl2 = document.createElement("div");
  lbl2.textContent = "Diet lane: fixed-baseline 100% stacked attempts mix";
  lbl2.style.fontSize = "12px";
  lbl2.style.color = "#9ab0d4";
  lbl2.style.margin = "10px 0 4px";
  container.appendChild(lbl2);
  container.appendChild(svg2.node());
}

export function renderQuarterProfile(container, model, teamCode) {
  clear(container);
  const d3 = window.d3;
  const quarters = model.quartersByTeam[teamCode] || [zeroCounts(), zeroCounts(), zeroCounts(), zeroCounts()];

  const data = quarters.map((q, idx) => {
    const total = q.total || 1;
    return {
      quarter: `Q${idx + 1}`,
      ft: q.ft / total,
      two: q.two / total,
      three: q.three / total,
    };
  });

  const W = 820;
  const H = 300;
  const margin = { top: 16, right: 12, bottom: 30, left: 38 };
  const innerW = W - margin.left - margin.right;
  const innerH = H - margin.top - margin.bottom;

  const svg = d3.create("svg").attr("viewBox", `0 0 ${W} ${H}`).style("width", "100%").style("display", "block");
  const g = svg.append("g").attr("transform", `translate(${margin.left},${margin.top})`);

  const x = d3.scaleBand().domain(data.map((d) => d.quarter)).range([0, innerW]).padding(0.28);
  const y = d3.scaleLinear().domain([0, 1]).range([innerH, 0]);

  data.forEach((d) => {
    const x0 = x(d.quarter);
    const width = x.bandwidth();
    const hFt = innerH - y(d.ft);
    const hTwo = innerH - y(d.two);
    const hThree = innerH - y(d.three);

    g.append("rect").attr("x", x0).attr("y", y(d.ft)).attr("width", width).attr("height", hFt).attr("fill", COLORS.ft).attr("opacity", 0.85);
    g.append("rect").attr("x", x0).attr("y", y(d.ft + d.two)).attr("width", width).attr("height", hTwo).attr("fill", COLORS.two).attr("opacity", 0.85);
    g.append("rect").attr("x", x0).attr("y", y(d.ft + d.two + d.three)).attr("width", width).attr("height", hThree).attr("fill", COLORS.three).attr("opacity", 0.85);
  });

  g.append("g").attr("transform", `translate(0,${innerH})`).call(d3.axisBottom(x)).call((ax) => ax.selectAll("text").attr("fill", "#8ea6cb").attr("font-size", 11)).call((ax) => ax.selectAll("line,.domain").attr("stroke", "#2a446a"));
  g.append("g").call(d3.axisLeft(y).ticks(5).tickFormat((d) => `${Math.round(d * 100)}%`)).call((ax) => ax.selectAll("text").attr("fill", "#8ea6cb").attr("font-size", 11)).call((ax) => ax.selectAll("line,.domain").attr("stroke", "#2a446a"));

  container.appendChild(svg.node());
}

function ternaryPoint(share, W, H, pad) {
  const a = share.ft;
  const b = share.two;
  const c = share.three;
  const pFt = [pad, H - pad];
  const pTwo = [W - pad, H - pad];
  const pThree = [W / 2, pad];
  return {
    x: a * pFt[0] + b * pTwo[0] + c * pThree[0],
    y: a * pFt[1] + b * pTwo[1] + c * pThree[1],
  };
}

export function renderTernaryTrajectory(container, series, seasonBaselineShare) {
  clear(container);
  if (!series.length) {
    emptyState(container, "No attempt events found.");
    return;
  }

  const d3 = window.d3;
  const sampled = [];
  const step = Math.max(1, Math.floor(series.length / 48));
  for (let i = 0; i < series.length; i += step) sampled.push(series[i]);
  if (sampled[sampled.length - 1] !== series[series.length - 1]) sampled.push(series[series.length - 1]);

  const W = 820;
  const H = 420;
  const pad = 58;

  const svg = d3.create("svg").attr("viewBox", `0 0 ${W} ${H}`).style("width", "100%").style("display", "block");
  const g = svg.append("g");

  const tri = [
    [pad, H - pad],
    [W - pad, H - pad],
    [W / 2, pad],
    [pad, H - pad],
  ];

  g.append("path").attr("d", d3.line()(tri)).attr("fill", "none").attr("stroke", "#355884").attr("stroke-width", 1.5);

  g.append("text").attr("x", pad - 22).attr("y", H - pad + 16).attr("fill", "#9ab0d4").attr("font-size", 12).text("FT");
  g.append("text").attr("x", W - pad + 8).attr("y", H - pad + 16).attr("fill", "#9ab0d4").attr("font-size", 12).text("2PT");
  g.append("text").attr("x", W / 2 - 12).attr("y", pad - 10).attr("fill", "#9ab0d4").attr("font-size", 12).text("3PT");

  const points = sampled.map((d) => ternaryPoint({ ft: d.ftShare, two: d.twoShare, three: d.threeShare }, W, H, pad));

  g.append("path")
    .attr("d", d3.line().x((d) => d.x).y((d) => d.y).curve(d3.curveCatmullRom.alpha(0.45))(points))
    .attr("fill", "none")
    .attr("stroke", "#6ec8ff")
    .attr("stroke-width", 2.2)
    .attr("opacity", 0.95);

  g.selectAll("circle.track")
    .data(points)
    .enter()
    .append("circle")
    .attr("class", "track")
    .attr("cx", (d) => d.x)
    .attr("cy", (d) => d.y)
    .attr("r", 2.8)
    .attr("fill", "#9effd5")
    .attr("opacity", 0.6);

  const start = points[0];
  const end = points[points.length - 1];
  g.append("circle").attr("cx", start.x).attr("cy", start.y).attr("r", 5).attr("fill", "#f59e0b");
  g.append("circle").attr("cx", end.x).attr("cy", end.y).attr("r", 5).attr("fill", "#34d399");

  if (seasonBaselineShare) {
    const bp = ternaryPoint(
      {
        ft: Number(seasonBaselineShare.ft || 0),
        two: Number(seasonBaselineShare.two || 0),
        three: Number(seasonBaselineShare.three || 0),
      },
      W,
      H,
      pad,
    );
    g.append("circle").attr("cx", bp.x).attr("cy", bp.y).attr("r", 6).attr("fill", "none").attr("stroke", "#ff5a7a").attr("stroke-width", 2);
    g.append("text").attr("x", bp.x + 8).attr("y", bp.y - 8).attr("fill", "#ffb6c8").attr("font-size", 11).text("Season baseline");
  }

  container.appendChild(svg.node());
}

export function renderSeasonTernaryCloud(container, gameVectors, seasonBaselineShare, highlights = null, interactions = {}) {
  clear(container);
  if (!gameVectors.length) {
    emptyState(container, "No season-level game vectors for this team.");
    return;
  }

  const d3 = window.d3;
  const W = 820;
  const H = 420;
  const pad = 58;

  const svg = d3.create("svg").attr("viewBox", `0 0 ${W} ${H}`).style("width", "100%").style("display", "block");
  const g = svg.append("g");

  const tri = [
    [pad, H - pad],
    [W - pad, H - pad],
    [W / 2, pad],
    [pad, H - pad],
  ];

  g.append("path").attr("d", d3.line()(tri)).attr("fill", "none").attr("stroke", "#355884").attr("stroke-width", 1.5);
  g.append("text").attr("x", pad - 22).attr("y", H - pad + 16).attr("fill", "#9ab0d4").attr("font-size", 12).text("1PT");
  g.append("text").attr("x", W - pad + 8).attr("y", H - pad + 16).attr("fill", "#9ab0d4").attr("font-size", 12).text("2PT");
  g.append("text").attr("x", W / 2 - 12).attr("y", pad - 10).attr("fill", "#9ab0d4").attr("font-size", 12).text("3PT");

  const points = gameVectors.map((d) => {
    const p = ternaryPoint({ ft: d.ftShare, two: d.twoShare, three: d.threeShare }, W, H, pad);
    return { ...d, x: p.x, y: p.y };
  });

  const mostCode = highlights && Number.isFinite(Number(highlights.mostGamecode)) ? Number(highlights.mostGamecode) : null;
  const leastCode = highlights && Number.isFinite(Number(highlights.leastGamecode)) ? Number(highlights.leastGamecode) : null;
  const regularPoints = points.filter((d) => d.gamecode !== mostCode && d.gamecode !== leastCode);
  const mostPoint = points.find((d) => d.gamecode === mostCode) || null;
  const leastPoint = points.find((d) => d.gamecode === leastCode) || null;

  function bindInteractions(selection) {
    selection
      .style("cursor", "pointer")
      .on("mouseenter", (event, d) => {
        if (typeof interactions.onPointHover === "function") interactions.onPointHover(event, d);
      })
      .on("mouseleave", (event, d) => {
        if (typeof interactions.onPointLeave === "function") interactions.onPointLeave(event, d);
      })
      .on("click", (event, d) => {
        if (typeof interactions.onPointClick === "function") interactions.onPointClick(event, d);
      });
  }

  const centroid = {
    ft: mean(gameVectors.map((d) => d.ftShare)),
    two: mean(gameVectors.map((d) => d.twoShare)),
    three: mean(gameVectors.map((d) => d.threeShare)),
  };
  const centroidPoint = ternaryPoint(centroid, W, H, pad);

  const regularSelection = g.selectAll("circle.game")
    .data(regularPoints)
    .enter()
    .append("circle")
    .attr("class", "game")
    .attr("cx", (d) => d.x)
    .attr("cy", (d) => d.y)
    .attr("r", 3.5)
    .attr("fill", "#6ec8ff")
    .attr("opacity", 0.6);
  bindInteractions(regularSelection);

  if (mostPoint) {
    const mostSelection = g.append("circle")
      .attr("cx", mostPoint.x)
      .attr("cy", mostPoint.y)
      .attr("r", 6.5)
      .attr("fill", "#8dffcb")
      .attr("stroke", "#0a5038")
      .attr("stroke-width", 1.2);
    bindInteractions(mostSelection.datum(mostPoint));
    g.append("text")
      .attr("x", mostPoint.x + 8)
      .attr("y", mostPoint.y - 8)
      .attr("fill", "#b7ffd9")
      .attr("font-size", 11)
      .text(`Most consistent G${mostPoint.gamecode}`);
  }

  if (leastPoint) {
    const leastSelection = g.append("circle")
      .attr("cx", leastPoint.x)
      .attr("cy", leastPoint.y)
      .attr("r", 6.5)
      .attr("fill", "#ff9fb1")
      .attr("stroke", "#6a1125")
      .attr("stroke-width", 1.2);
    bindInteractions(leastSelection.datum(leastPoint));
    g.append("text")
      .attr("x", leastPoint.x + 8)
      .attr("y", leastPoint.y + 14)
      .attr("fill", "#ffbcc8")
      .attr("font-size", 11)
      .text(`Least consistent G${leastPoint.gamecode}`);
  }

  g.append("circle")
    .attr("cx", centroidPoint.x)
    .attr("cy", centroidPoint.y)
    .attr("r", 7)
    .attr("fill", "none")
    .attr("stroke", "#9effd5")
    .attr("stroke-width", 2.3);
  g.append("text")
    .attr("x", centroidPoint.x + 8)
    .attr("y", centroidPoint.y - 8)
    .attr("fill", "#b7ffd9")
    .attr("font-size", 11)
    .text("Sample centroid");

  if (seasonBaselineShare) {
    const bp = ternaryPoint(
      {
        ft: Number(seasonBaselineShare.ft || 0),
        two: Number(seasonBaselineShare.two || 0),
        three: Number(seasonBaselineShare.three || 0),
      },
      W,
      H,
      pad,
    );
    g.append("circle").attr("cx", bp.x).attr("cy", bp.y).attr("r", 6).attr("fill", "none").attr("stroke", "#ff5a7a").attr("stroke-width", 2);
    g.append("text").attr("x", bp.x + 8).attr("y", bp.y + 14).attr("fill", "#ffb6c8").attr("font-size", 11).text("Season baseline");
  }

  container.appendChild(svg.node());
}

export function renderShotPctVarianceStrip(container, gameVectors, highlights = null, interactions = {}) {
  clear(container);
  if (!gameVectors.length) {
    emptyState(container, "No season-level game vectors for this team.");
    return;
  }

  const d3 = window.d3;
  const W = 820;
  const H = 270;
  const margin = { top: 18, right: 14, bottom: 30, left: 72 };
  const innerW = W - margin.left - margin.right;
  const innerH = H - margin.top - margin.bottom;

  const metrics = [
    { key: "ftShare", label: "1PT pct", color: COLORS.ft },
    { key: "twoShare", label: "2PT pct", color: COLORS.two },
    { key: "threeShare", label: "3PT pct", color: COLORS.three },
  ];

  const mostCode = highlights && Number.isFinite(Number(highlights.mostGamecode)) ? Number(highlights.mostGamecode) : null;
  const leastCode = highlights && Number.isFinite(Number(highlights.leastGamecode)) ? Number(highlights.leastGamecode) : null;
  const mostVector = gameVectors.find((d) => d.gamecode === mostCode) || null;
  const leastVector = gameVectors.find((d) => d.gamecode === leastCode) || null;

  const svg = d3.create("svg").attr("viewBox", `0 0 ${W} ${H}`).style("width", "100%").style("display", "block");
  const g = svg.append("g").attr("transform", `translate(${margin.left},${margin.top})`);

  const x = d3.scaleLinear().domain([0, 1]).range([0, innerW]);
  const y = d3.scaleBand().domain(metrics.map((m) => m.label)).range([0, innerH]).padding(0.42);

  metrics.forEach((metric) => {
    const values = gameVectors.map((d) => d[metric.key]);
    const mu = mean(values);
    const sd = stdDev(values);
    const y0 = y(metric.label);
    const band = y.bandwidth();
    const center = y0 + band / 2;

    const low = Math.max(0, mu - sd);
    const high = Math.min(1, mu + sd);
    g.append("rect")
      .attr("x", x(low))
      .attr("y", y0 + band * 0.15)
      .attr("width", Math.max(1, x(high) - x(low)))
      .attr("height", band * 0.7)
      .attr("fill", metric.color)
      .attr("opacity", 0.22);

    g.append("line")
      .attr("x1", x(mu))
      .attr("x2", x(mu))
      .attr("y1", y0)
      .attr("y2", y0 + band)
      .attr("stroke", metric.color)
      .attr("stroke-width", 2.2);

    const dots = g.selectAll(`circle.dot-${metric.key}`)
      .data(gameVectors)
      .enter()
      .append("circle")
      .attr("cx", (d) => x(d[metric.key]))
      .attr("cy", (_, idx) => center + ((idx % 9) - 4) * 2.4)
      .attr("r", 3)
      .attr("fill", metric.color)
      .attr("opacity", 0.62);

    dots
      .style("cursor", "pointer")
      .on("mouseenter", (event, d) => {
        if (typeof interactions.onPointHover === "function") interactions.onPointHover(event, { ...d, metric: metric.label });
      })
      .on("mouseleave", (event, d) => {
        if (typeof interactions.onPointLeave === "function") interactions.onPointLeave(event, { ...d, metric: metric.label });
      })
      .on("click", (event, d) => {
        if (typeof interactions.onPointClick === "function") interactions.onPointClick(event, { ...d, metric: metric.label });
      });

    if (mostVector) {
      g.append("circle")
        .attr("cx", x(mostVector[metric.key]))
        .attr("cy", center)
        .attr("r", 6)
        .attr("fill", "#8dffcb")
        .attr("stroke", "#0a5038")
        .attr("stroke-width", 1.2);
    }

    if (leastVector) {
      g.append("circle")
        .attr("cx", x(leastVector[metric.key]))
        .attr("cy", center)
        .attr("r", 6)
        .attr("fill", "#ff9fb1")
        .attr("stroke", "#6a1125")
        .attr("stroke-width", 1.2);
    }

    g.append("text")
      .attr("x", x(Math.min(0.98, mu + 0.02)))
      .attr("y", y0 - 2)
      .attr("fill", "#9ab0d4")
      .attr("font-size", 10)
      .text(`mu=${Math.round(mu * 100)}%, sd=${Math.round(sd * 100)}pp`);
  });

  g.append("g")
    .attr("transform", `translate(0,${innerH})`)
    .call(d3.axisBottom(x).ticks(10).tickFormat((d) => `${Math.round(d * 100)}%`))
    .call((ax) => ax.selectAll("text").attr("fill", "#8ea6cb").attr("font-size", 11))
    .call((ax) => ax.selectAll("line,.domain").attr("stroke", "#2a446a"));

  g.append("g")
    .call(d3.axisLeft(y))
    .call((ax) => ax.selectAll("text").attr("fill", "#8ea6cb").attr("font-size", 11))
    .call((ax) => ax.selectAll("line,.domain").attr("stroke", "#2a446a"));

  if (mostVector) {
    g.append("text")
      .attr("x", innerW - 180)
      .attr("y", -2)
      .attr("fill", "#b7ffd9")
      .attr("font-size", 11)
      .text(`Most consistent: G${mostVector.gamecode}`);
  }
  if (leastVector) {
    g.append("text")
      .attr("x", innerW - 180)
      .attr("y", 12)
      .attr("fill", "#ffbcc8")
      .attr("font-size", 11)
      .text(`Least consistent: G${leastVector.gamecode}`);
  }

  container.appendChild(svg.node());
}
