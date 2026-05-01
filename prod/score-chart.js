const SEASONS = ['E2025', 'E2024', 'E2023', 'E2022', 'E2021'];
const GAME_COUNTS = { E2025: 380, E2024: 330, E2023: 333, E2022: 330, E2021: 192 };
const QUARTER_MINS = [0, 10, 20, 30, 40];

const COLORS = {
  home: { three: '#fbbf24', two: '#34d399', ft: '#a78bfa' },
  away: { three: '#f59e0b', two: '#10b981', ft: '#8b5cf6' },
};

function classifyAction(idAction) {
  if (!idAction) return null;
  const action = idAction.trim().toUpperCase();
  if (action === 'FTM' || action === 'FTA') {
    return { type: 'ft', isMake: action === 'FTM' };
  }
  if (action === '2FGM' || action === '2FGA') {
    return { type: 'two', isMake: action === '2FGM' };
  }
  if (action === '3FGM' || action === '3FGA') {
    return { type: 'three', isMake: action === '3FGM' };
  }
  return null;
}

function processRows(rows) {
  let homeTeam = null;
  let awayTeam = null;
  let prevA = 0;
  let prevB = 0;

  for (const row of rows) {
    if (!classifyAction(row.ID_ACTION)) continue;
    const ptsA = row.POINTS_A || 0;
    const ptsB = row.POINTS_B || 0;
    const team = (row.TEAM || '').trim();
    if (ptsA > prevA && homeTeam === null) homeTeam = team;
    if (ptsB > prevB && awayTeam === null) awayTeam = team;
    prevA = ptsA;
    prevB = ptsB;
    if (homeTeam && awayTeam) break;
  }

  const acc = {
    home: { ft: 0, two: 0, three: 0, total: 0, ftM: 0, twoM: 0, threeM: 0, ftA: 0, twoA: 0, threeA: 0 },
    away: { ft: 0, two: 0, three: 0, total: 0, ftM: 0, twoM: 0, threeM: 0, ftA: 0, twoA: 0, threeA: 0 },
  };

  const timeline = [];

  for (const row of rows) {
    const parsed = classifyAction(row.ID_ACTION);
    if (!parsed) continue;

    const teamKey = (row.TEAM || '').trim() === homeTeam ? 'home' : 'away';
    const type = parsed.type;
    const points = parsed.isMake ? (row.POINTS || 0) : 0;

    acc[teamKey][type + 'A'] += 1;
    if (parsed.isMake) {
      acc[teamKey][type] += points;
      acc[teamKey].total += points;
      acc[teamKey][type + 'M'] += 1;
    }

    const ptsA = row.POINTS_A || 0;
    const ptsB = row.POINTS_B || 0;
    const consoleClock = row.CONSOLE || '';
    const parts = consoleClock.split(':');
    let minute = row.MINUTE || 0;
    if (parts.length === 2) {
      const seconds = parseInt(parts[1], 10);
      minute = (row.MINUTE || 0) + (seconds > 0 ? (60 - seconds) / 60 : 0);
    }

    timeline.push({
      minute,
      console: consoleClock,
      team: teamKey,
      teamName: (row.TEAM || '').trim(),
      type,
      pts: points,
      ptsA,
      ptsB,
      diff: ptsB - ptsA,
      orientedDiff: ptsB - ptsA,
      home: { ...acc.home },
      away: { ...acc.away },
    });
  }

  timeline.unshift({
    minute: 0,
    console: '',
    team: null,
    type: null,
    pts: 0,
    ptsA: 0,
    ptsB: 0,
    diff: 0,
    orientedDiff: 0,
    home: { ft: 0, two: 0, three: 0, total: 0, ftM: 0, twoM: 0, threeM: 0, ftA: 0, twoA: 0, threeA: 0 },
    away: { ft: 0, two: 0, three: 0, total: 0, ftM: 0, twoM: 0, threeM: 0, ftA: 0, twoA: 0, threeA: 0 },
  });

  return { points: timeline, homeTeam, awayTeam };
}

function renderGameInfo(gameInfo, data, season, game) {
  if (!data || !data.points.length) return;
  const last = data.points[data.points.length - 1];
  const homeShort = data.homeTeam || 'Home';
  const awayShort = data.awayTeam || 'Away';
  gameInfo.innerHTML = `
    <div class="teams">
      <span class="team-home">${homeShort}</span>
      <span style="color:var(--muted);margin:0 6px">vs</span>
      <span class="team-away">${awayShort}</span>
    </div>
    <div class="score">
      <span class="team-home">${last.ptsA}</span>
      <span style="color:var(--muted);margin:0 4px">–</span>
      <span class="team-away">${last.ptsB}</span>
    </div>
    <div class="date">${season} / Game ${game}</div>
  `;
}

function updateLegendLabels(variant, data) {
  const homeLabel = document.getElementById('legend-home-label');
  const awayLabel = document.getElementById('legend-away-label');
  if (!homeLabel || !awayLabel) return;

  if (variant === 'd52') {
    if (data.homeTeam) homeLabel.textContent = `▲ ${data.homeTeam} (home, top area) — composition by share`;
    if (data.awayTeam) awayLabel.textContent = `▼ ${data.awayTeam} (away, bottom area) — composition by share`;
    return;
  }

  if (data.homeTeam) homeLabel.textContent = `▲ ${data.homeTeam} (home) — cumulative points above zero`;
  if (data.awayTeam) awayLabel.textContent = `▼ ${data.awayTeam} (away) — cumulative points below zero`;
}

function renderSharedAxes(g, x, y, innerWidth, innerHeight, maxMinute) {
  g.append('g')
    .attr('transform', `translate(0,${innerHeight})`)
    .call(window.d3.axisBottom(x).ticks(Math.min(maxMinute, 8)).tickFormat((d) => `${d}'`))
    .call((ax) => ax.select('.domain').attr('stroke', '#1e3a5f'))
    .call((ax) => ax.selectAll('text').attr('fill', '#7a9cc4').attr('font-size', 11))
    .call((ax) => ax.selectAll('line').attr('stroke', '#1e3a5f'));

  g.append('g')
    .call(window.d3.axisLeft(y).ticks(6))
    .call((ax) => ax.select('.domain').attr('stroke', '#1e3a5f'))
    .call((ax) => ax.selectAll('text').attr('fill', '#7a9cc4').attr('font-size', 11))
    .call((ax) => ax.selectAll('line').attr('stroke', '#1e3a5f'));
}

function getStackModeValues(teamAcc, mode) {
  if (mode === 'makes') {
    return { ft: teamAcc.ftM || 0, two: teamAcc.twoM || 0, three: teamAcc.threeM || 0 };
  }
  if (mode === 'attempts') {
    return { ft: teamAcc.ftA || 0, two: teamAcc.twoA || 0, three: teamAcc.threeA || 0 };
  }
  return { ft: teamAcc.ft || 0, two: teamAcc.two || 0, three: teamAcc.three || 0 };
}

function renderHover({ variant, currentMode, g, x, y, yAccessor, pts, innerWidth, innerHeight, tooltip }) {
  const { ttTitle, ttScore, ttDiff, ttMode } = tooltip;
  const bisect = window.d3.bisector((d) => d.minute).left;

  const hoverLine = g.append('line')
    .attr('stroke', '#ffffff44')
    .attr('stroke-width', 1)
    .attr('y1', 0)
    .attr('y2', innerHeight)
    .style('display', 'none');

  const hoverDot = g.append('circle')
    .attr('r', 4)
    .attr('fill', 'white')
    .attr('stroke', '#081425')
    .attr('stroke-width', 2)
    .style('display', 'none');

  g.append('rect')
    .attr('width', innerWidth)
    .attr('height', innerHeight)
    .attr('fill', 'transparent')
    .on('mousemove', function onMouseMove(event) {
      const [mx] = window.d3.pointer(event, this);
      const minute = x.invert(mx);
      const idx = Math.min(bisect(pts, minute), pts.length - 1);
      const point = pts[idx];
      if (!point) return;

      hoverLine.attr('x1', x(point.minute)).attr('x2', x(point.minute)).style('display', null);
      hoverDot.attr('cx', x(point.minute)).attr('cy', y(yAccessor(point))).style('display', null);

      const homeVals = getStackModeValues(point.home, currentMode);
      const awayVals = getStackModeValues(point.away, currentMode);
      const homeTotal = homeVals.ft + homeVals.two + homeVals.three || 1;
      const awayTotal = awayVals.ft + awayVals.two + awayVals.three || 1;
      const homeMix = `FT ${((homeVals.ft / homeTotal) * 100).toFixed(0)}% · 2PT ${((homeVals.two / homeTotal) * 100).toFixed(0)}% · 3PT ${((homeVals.three / homeTotal) * 100).toFixed(0)}%`;
      const awayMix = `FT ${((awayVals.ft / awayTotal) * 100).toFixed(0)}% · 2PT ${((awayVals.two / awayTotal) * 100).toFixed(0)}% · 3PT ${((awayVals.three / awayTotal) * 100).toFixed(0)}%`;
      const minLabel = point.console ? point.console : `${Math.floor(point.minute)}'`;

      ttTitle.textContent = `Q${Math.min(4, Math.floor(point.minute / 10) + 1)} · ${minLabel}`;
      ttScore.innerHTML = `Score: <span>${point.ptsA} – ${point.ptsB}</span>`;
      if (variant === 'd52') {
        ttDiff.innerHTML = `Margin H−A: <span>${point.diff > 0 ? '+' : ''}${point.diff}</span> · Oriented A−H: <span>${point.orientedDiff > 0 ? '+' : ''}${point.orientedDiff}</span>`;
      } else {
        ttDiff.innerHTML = `Oriented diff A−H: <span>${point.diff > 0 ? '+' : ''}${point.diff}</span>`;
      }
      ttMode.innerHTML = `↑ ${homeMix}<br>↓ ${awayMix}`;

      tooltip.root.style.left = `${event.clientX + 14}px`;
      tooltip.root.style.top = `${event.clientY - 40}px`;
      tooltip.root.classList.add('visible');
    })
    .on('mouseleave', function onMouseLeave() {
      hoverLine.style('display', 'none');
      hoverDot.style('display', 'none');
      tooltip.root.classList.remove('visible');
    });
}

function renderDiffChart(chartArea, tooltip, data, currentMode) {
  const pts = data.points;
  const W = 800;
  const H = 400;
  const margin = { top: 24, right: 20, bottom: 30, left: 44 };
  const innerWidth = W - margin.left - margin.right;
  const innerHeight = H - margin.top - margin.bottom;
  const maxMinute = window.d3.max(pts, (d) => d.minute) || 40;
  const last = pts[pts.length - 1];
  const maxScore = Math.max(last.ptsA, last.ptsB, 10);
  const yPad = Math.max(6, maxScore * 0.1);
  const x = window.d3.scaleLinear().domain([0, maxMinute]).range([0, innerWidth]);
  const y = window.d3.scaleLinear().domain([-(maxScore + yPad), maxScore + yPad]).range([innerHeight, 0]);
  const y0 = y(0);

  const svg = window.d3.create('svg')
    .attr('id', 'chart-svg')
    .attr('viewBox', `0 0 ${W} ${H}`)
    .attr('preserveAspectRatio', 'xMidYMid meet');

  const g = svg.append('g').attr('transform', `translate(${margin.left},${margin.top})`);

  QUARTER_MINS.forEach((quarterMinute, index) => {
    if (quarterMinute === 0 || quarterMinute > maxMinute) return;
    g.append('line')
      .attr('class', 'q-line')
      .attr('x1', x(quarterMinute))
      .attr('x2', x(quarterMinute))
      .attr('y1', 0)
      .attr('y2', innerHeight);
    g.append('text')
      .attr('class', 'q-label')
      .attr('x', x(quarterMinute) + 3)
      .attr('y', 12)
      .text(`Q${index + 1}`);
  });

  g.append('line')
    .attr('class', 'zero-line')
    .attr('x1', 0)
    .attr('x2', innerWidth)
    .attr('y1', y0)
    .attr('y2', y0);

  const types = ['ft', 'two', 'three'];

  function getScaledValues(teamAcc, mode, totalScore) {
    if (mode === 'points') {
      return { ft: teamAcc.ft, two: teamAcc.two, three: teamAcc.three };
    }
    const vals = getStackModeValues(teamAcc, mode);
    const total = vals.ft + vals.two + vals.three;
    if (!total || !totalScore) return { ft: 0, two: 0, three: 0 };
    const scale = totalScore / total;
    return { ft: vals.ft * scale, two: vals.two * scale, three: vals.three * scale };
  }

  function buildLayers(side, mode) {
    return types.map((type, layerIndex) => {
      const points = pts.map((point) => {
        const totalScore = side === 'home' ? point.ptsA : point.ptsB;
        const vals = getScaledValues(point[side], mode, totalScore);
        const base = types.slice(0, layerIndex).reduce((sum, key) => sum + (vals[key] || 0), 0);
        const top = base + (vals[type] || 0);
        if (side === 'home') {
          return { xv: x(point.minute), y0v: y(base), y1v: y(top) };
        }
        return { xv: x(point.minute), y0v: y(-base), y1v: y(-top) };
      });
      return { type, side, points };
    });
  }

  const areaGen = window.d3.area()
    .x((d) => d.xv)
    .y0((d) => d.y0v)
    .y1((d) => d.y1v)
    .curve(window.d3.curveCatmullRom.alpha(0.5));

  const typeOpacity = { home: 0.78, away: 0.60 };
  [...buildLayers('home', currentMode), ...buildLayers('away', currentMode)].forEach((layer) => {
    g.append('path')
      .datum(layer.points)
      .attr('d', areaGen)
      .attr('fill', COLORS[layer.side][layer.type])
      .attr('opacity', typeOpacity[layer.side]);
  });

  const lineGen = window.d3.line()
    .x((d) => x(d.minute))
    .y((d) => y(d.diff))
    .curve(window.d3.curveCatmullRom.alpha(0.5));

  g.append('path')
    .datum(pts)
    .attr('class', 'diff-path')
    .attr('d', lineGen);

  for (let index = 1; index < pts.length; index += 1) {
    if ((pts[index - 1].diff < 0 && pts[index].diff > 0) || (pts[index - 1].diff > 0 && pts[index].diff < 0)) {
      const t = pts[index - 1].diff / (pts[index - 1].diff - pts[index].diff);
      const xc = x(pts[index - 1].minute + t * (pts[index].minute - pts[index - 1].minute));
      g.append('circle').attr('cx', xc).attr('cy', y0).attr('r', 4).attr('fill', '#ffffff').attr('opacity', 0.7);
    }
  }

  renderSharedAxes(g, x, y, innerWidth, innerHeight, maxMinute);
  renderHover({ variant: 'diff', currentMode, g, x, y, yAccessor: (point) => point.diff, pts, innerWidth, innerHeight, tooltip });
  chartArea.appendChild(svg.node());
}

function renderD52Chart(chartArea, tooltip, data, currentMode) {
  const pts = data.points;
  const W = 800;
  const H = 400;
  const margin = { top: 24, right: 20, bottom: 30, left: 44 };
  const innerWidth = W - margin.left - margin.right;
  const innerHeight = H - margin.top - margin.bottom;
  const maxMinute = window.d3.max(pts, (d) => d.minute) || 40;
  const maxDiff = window.d3.max(pts, (d) => Math.abs(d.orientedDiff)) || 10;
  const yPad = Math.max(5, maxDiff * 0.15);
  const x = window.d3.scaleLinear().domain([0, maxMinute]).range([0, innerWidth]);
  const y = window.d3.scaleLinear().domain([-(maxDiff + yPad), maxDiff + yPad]).range([innerHeight, 0]);
  const y0 = y(0);

  const svg = window.d3.create('svg')
    .attr('id', 'chart-svg')
    .attr('viewBox', `0 0 ${W} ${H}`)
    .attr('preserveAspectRatio', 'xMidYMid meet');

  const g = svg.append('g').attr('transform', `translate(${margin.left},${margin.top})`);

  QUARTER_MINS.forEach((quarterMinute, index) => {
    if (quarterMinute === 0 || quarterMinute > maxMinute) return;
    g.append('line')
      .attr('class', 'q-line')
      .attr('x1', x(quarterMinute))
      .attr('x2', x(quarterMinute))
      .attr('y1', 0)
      .attr('y2', innerHeight);
    g.append('text')
      .attr('class', 'q-label')
      .attr('x', x(quarterMinute) + 3)
      .attr('y', 12)
      .text(`Q${index + 1}`);
  });

  g.append('line')
    .attr('class', 'zero-line')
    .attr('x1', 0)
    .attr('x2', innerWidth)
    .attr('y1', y0)
    .attr('y2', y0);

  const types = ['ft', 'two', 'three'];

  function getShares(teamAcc, mode) {
    const vals = getStackModeValues(teamAcc, mode);
    const ft = vals.ft;
    const two = vals.two;
    const three = vals.three;
    const total = ft + two + three;
    if (!total) return { ft: 0, two: 0, three: 0 };
    return { ft: ft / total, two: two / total, three: three / total };
  }

  function buildLayers(side, mode) {
    return types.map((type, layerIndex) => {
      const points = pts.map((point) => {
        const shares = getShares(point[side], mode);
        const dividerY = y(point.orientedDiff);
        const prevShare = types.slice(0, layerIndex).reduce((sum, key) => sum + (shares[key] || 0), 0);
        const thisShare = shares[type] || 0;

        if (side === 'home') {
          const topSpace = Math.max(0, dividerY);
          return {
            xv: x(point.minute),
            y0v: prevShare * topSpace,
            y1v: (prevShare + thisShare) * topSpace,
          };
        }

        const bottomSpace = Math.max(0, innerHeight - dividerY);
        return {
          xv: x(point.minute),
          y0v: dividerY + prevShare * bottomSpace,
          y1v: dividerY + (prevShare + thisShare) * bottomSpace,
        };
      });
      return { type, side, points };
    });
  }

  const areaGen = window.d3.area()
    .x((d) => d.xv)
    .y0((d) => d.y0v)
    .y1((d) => d.y1v)
    .curve(window.d3.curveCatmullRom.alpha(0.5));

  const typeOpacity = { home: 0.78, away: 0.60 };
  [...buildLayers('home', currentMode), ...buildLayers('away', currentMode)].forEach((layer) => {
    g.append('path')
      .datum(layer.points)
      .attr('d', areaGen)
      .attr('fill', COLORS[layer.side][layer.type])
      .attr('opacity', typeOpacity[layer.side]);
  });

  const lineGen = window.d3.line()
    .x((d) => x(d.minute))
    .y((d) => y(d.orientedDiff))
    .curve(window.d3.curveCatmullRom.alpha(0.5));

  g.append('path')
    .datum(pts)
    .attr('class', 'diff-path')
    .attr('d', lineGen);

  for (let index = 1; index < pts.length; index += 1) {
    if ((pts[index - 1].orientedDiff < 0 && pts[index].orientedDiff > 0) || (pts[index - 1].orientedDiff > 0 && pts[index].orientedDiff < 0)) {
      const t = pts[index - 1].orientedDiff / (pts[index - 1].orientedDiff - pts[index].orientedDiff);
      const xc = x(pts[index - 1].minute + t * (pts[index].minute - pts[index - 1].minute));
      g.append('circle').attr('cx', xc).attr('cy', y0).attr('r', 4).attr('fill', '#ffffff').attr('opacity', 0.7);
    }
  }

  renderSharedAxes(g, x, y, innerWidth, innerHeight, maxMinute);
  renderHover({ variant: 'd52', currentMode, g, x, y, yAccessor: (point) => point.orientedDiff, pts, innerWidth, innerHeight, tooltip });
  chartArea.appendChild(svg.node());
}

export function initScoreChart({ variant }) {
  const selSeason = document.getElementById('sel-season');
  const selGame = document.getElementById('sel-game');
  const chartArea = document.getElementById('chart-area');
  const gameInfo = document.getElementById('game-info');
  const legend = document.getElementById('legend');
  const tooltip = {
    root: document.getElementById('tooltip'),
    ttTitle: document.getElementById('tt-title'),
    ttScore: document.getElementById('tt-score'),
    ttDiff: document.getElementById('tt-diff'),
    ttMode: document.getElementById('tt-mode'),
  };

  let currentMode = 'points';
  let currentData = null;

  // Score chart pages can be served from either root (app mode: /score-diff-v2.html)
  // or /prod (lab mode: /prod/score-diff-v2.html). Resolve assets path accordingly.
  const inProdSubdir = window.location.pathname.includes('/prod/');
  const rawAssetsBase = inProdSubdir ? '../assets' : './assets';

  function populateGameSelect(season) {
    const count = GAME_COUNTS[season] || 200;
    selGame.innerHTML = '';
    for (let index = 1; index <= count; index += 1) {
      const option = document.createElement('option');
      option.value = index;
      option.textContent = `Game ${index}`;
      selGame.appendChild(option);
    }
  }

  function renderChart(data) {
    chartArea.innerHTML = '';
    if (!data || !data.points.length) return;
    if (variant === 'd52') {
      renderD52Chart(chartArea, tooltip, data, currentMode);
      return;
    }
    renderDiffChart(chartArea, tooltip, data, currentMode);
  }

  async function loadGame() {
    const season = selSeason.value;
    const game = selGame.value;
    const url = `${rawAssetsBase}/raw_pts_${season}_${game}.json`;

    chartArea.innerHTML = '<div class="status loading">Loading…</div>';
    legend.style.display = 'none';
    gameInfo.innerHTML = '<span class="info-placeholder">Loading…</span>';

    try {
      const res = await fetch(url);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const json = await res.json();
      currentData = processRows(json.Rows || []);
      renderGameInfo(gameInfo, currentData, season, game);
      renderChart(currentData);
      legend.style.display = 'flex';

      const selectedOption = selGame.options[selGame.selectedIndex];
      if (selectedOption && currentData.homeTeam && currentData.awayTeam) {
        selectedOption.textContent = `${currentData.homeTeam} vs ${currentData.awayTeam} (G${game})`;
      }
      updateLegendLabels(variant, currentData);
    } catch (error) {
      chartArea.innerHTML = `<div class="status error">Could not load game ${game} for ${season}. Try another game.</div>`;
      gameInfo.innerHTML = '<span class="info-placeholder">No data</span>';
    }
  }

  const qs = new URLSearchParams(window.location.search);
  const initSeason = qs.get('season') || 'E2025';
  const initGame = parseInt(qs.get('game') || '1', 10);
  const initMode = qs.get('mode') || 'points';
  const lockMode = qs.get('lockMode') === '1';

  if (SEASONS.includes(initSeason)) selSeason.value = initSeason;
  populateGameSelect(selSeason.value);
  selGame.value = initGame;

  if (initMode === 'makes' || initMode === 'attempts' || initMode === 'points') {
    currentMode = initMode;
  }

  if (lockMode) {
    const modeGroup = document.querySelector('.mode-pills');
    if (modeGroup) modeGroup.style.display = 'none';
    const labels = Array.from(document.querySelectorAll('.ctrl-label'));
    const modeLabel = labels.find((node) => (node.textContent || '').toLowerCase().includes('stack mode'));
    if (modeLabel) modeLabel.textContent = `Stack mode (locked: ${currentMode})`;
  }

  document.querySelectorAll('.pill').forEach((pill) => {
    pill.classList.toggle('active', pill.dataset.mode === currentMode);
  });

  selSeason.addEventListener('change', () => {
    populateGameSelect(selSeason.value);
    loadGame();
  });
  selGame.addEventListener('change', loadGame);

  document.querySelectorAll('.pill').forEach((button) => {
    button.addEventListener('click', () => {
      if (lockMode) return;
      currentMode = button.dataset.mode;
      document.querySelectorAll('.pill').forEach((pill) => {
        pill.classList.toggle('active', pill.dataset.mode === currentMode);
      });
      if (currentData) renderChart(currentData);
    });
  });

  loadGame();
}