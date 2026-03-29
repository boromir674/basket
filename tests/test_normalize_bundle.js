/**
 * Unit tests for normalizeBundleForAnchor — the function responsible for
 * promoting the "anchor team" to the team_a (top-lane) position in a game
 * bundle before it is rendered in the 1-team-anchor view.
 *
 * Run with: node tests/test_normalize_bundle.js
 *
 * These tests validate the fix for the following bugs that existed when the
 * anchor team happened to be team_b in the raw bundle:
 *   1. Scoreboard showed swapped scores (team labels crossed).
 *   2. Sankey rendered the opponent's possession flows under the anchor's name/colour.
 *   3. KPI "starts" counts were mapped to the wrong team.
 *   4. Single-team focus filtered the wrong nodes.
 */

'use strict';

const assert = require('assert');

// ─── Constants (same values as in prod/game-explorer.html) ──────────────────
const ANCHOR_COLOR = '#3a86ff';
const OPP_COLOR = '#ff5a7a';

// ─── Copy of the fixed normalizeBundleForAnchor ──────────────────────────────
function normalizeBundleForAnchor(bundle, anchorTeam) {
  const copy = JSON.parse(JSON.stringify(bundle));
  const meta = copy.meta || {};
  const a = meta.team_a;
  const b = meta.team_b;
  if (!a || !b || anchorTeam !== b) {
    if (copy.colors) {
      copy.colors[anchorTeam] = ANCHOR_COLOR;
      const opp = anchorTeam === a ? b : a;
      if (opp) copy.colors[opp] = OPP_COLOR;
    }
    return copy;
  }

  meta.team_a = b;
  meta.team_b = a;
  copy.meta = meta;

  if (copy.colors && typeof copy.colors === 'object') {
    copy.colors[b] = ANCHOR_COLOR;
    copy.colors[a] = OPP_COLOR;
  }

  if (copy.views && typeof copy.views === 'object') {
    Object.values(copy.views).forEach((view) => {
      if (!view || !Array.isArray(view.nodes)) return;
      const anchorNodes = view.nodes.filter(n => n && n.team === b);
      const otherNodes = view.nodes.filter(n => !n || n.team !== b);
      view.nodes = anchorNodes.concat(otherNodes);
    });
  }

  return copy;
}

// ─── Test helpers ────────────────────────────────────────────────────────────
let passed = 0;
let failed = 0;

function test(name, fn) {
  try {
    fn();
    console.log(`  ✓ ${name}`);
    passed++;
  } catch (err) {
    console.error(`  ✗ ${name}`);
    console.error(`    ${err.message}`);
    failed++;
  }
}

// ─── Minimal bundle factory ──────────────────────────────────────────────────
function makeBundle(teamA, teamB) {
  return {
    meta: {
      seasoncode: 'E2021',
      gamecode: 54,
      team_a: teamA,
      team_b: teamB,
      gamedate: '2022-01-01',
      synced_at: '2022-01-01T00:00:00Z',
    },
    colors: { [teamA]: '#d62839', [teamB]: '#3a86ff' },
    players: {
      p1: { name: 'Alpha Player', team: teamA },
      p2: { name: 'Beta Player', team: teamB },
    },
    boxscore_players: [
      { player_id: 'p1', player_name: 'Alpha Player', team: teamA, points: 20 },
      { player_id: 'p2', player_name: 'Beta Player', team: teamB, points: 25 },
    ],
    views: {
      top: {
        starts: { [teamA]: 50, [teamB]: 45 },
        nodes: [
          { id: `${teamA}_start`, name: `${teamA} Start`, team: teamA, stage: 'start' },
          { id: `${teamA}_Half-court`, name: 'Half-court', team: teamA, stage: 'type' },
          { id: `${teamB}_start`, name: `${teamB} Start`, team: teamB, stage: 'start' },
          { id: `${teamB}_Half-court`, name: 'Half-court', team: teamB, stage: 'type' },
        ],
        links: [
          { source: `${teamA}_start`, target: `${teamA}_Half-court`, value: 50 },
          { source: `${teamB}_start`, target: `${teamB}_Half-court`, value: 45 },
          { source: `${teamA}_Half-court`, target: `${teamA}_2`, value: 15 },
          { source: `${teamB}_Half-court`, target: `${teamB}_3`, value: 10 },
        ],
        insights: [`${teamA} generated 1.05 PPP.`, `${teamB} scored 0.92 PPP.`],
        title: `${teamA} vs ${teamB}`,
        desc: 'Top-level view.',
        kpis: [[`${teamA} starts`, '50'], [`${teamB} starts`, '45']],
        player_flows: {
          [`${teamA}_start->${teamA}_Half-court`]: [
            { player_id: 'p1', player_name: 'Alpha Player', team: teamA, poss: 20 },
          ],
          [`${teamB}_start->${teamB}_Half-court`]: [
            { player_id: 'p2', player_name: 'Beta Player', team: teamB, poss: 18 },
          ],
        },
      },
    },
  };
}

// ─── Scenario A: anchor is already team_a ────────────────────────────────────
console.log('\nScenario A — anchor is already team_a (no swap needed)');

test('meta.team_a stays as anchor', () => {
  const bundle = makeBundle('Efes', 'CSKA');
  const result = normalizeBundleForAnchor(bundle, 'Efes');
  assert.strictEqual(result.meta.team_a, 'Efes');
  assert.strictEqual(result.meta.team_b, 'CSKA');
});

test('anchor gets ANCHOR_COLOR', () => {
  const bundle = makeBundle('Efes', 'CSKA');
  const result = normalizeBundleForAnchor(bundle, 'Efes');
  assert.strictEqual(result.colors['Efes'], ANCHOR_COLOR);
});

test('opponent gets OPP_COLOR', () => {
  const bundle = makeBundle('Efes', 'CSKA');
  const result = normalizeBundleForAnchor(bundle, 'Efes');
  assert.strictEqual(result.colors['CSKA'], OPP_COLOR);
});

test('node team labels are unchanged', () => {
  const bundle = makeBundle('Efes', 'CSKA');
  const result = normalizeBundleForAnchor(bundle, 'Efes');
  const nodes = result.views.top.nodes;
  assert.ok(nodes.some(n => n.id === 'Efes_start' && n.team === 'Efes'));
  assert.ok(nodes.some(n => n.id === 'CSKA_start' && n.team === 'CSKA'));
});

test('player team labels are unchanged', () => {
  const bundle = makeBundle('Efes', 'CSKA');
  const result = normalizeBundleForAnchor(bundle, 'Efes');
  assert.strictEqual(result.players['p1'].team, 'Efes');
  assert.strictEqual(result.players['p2'].team, 'CSKA');
});

test('boxscore player team labels are unchanged', () => {
  const bundle = makeBundle('Efes', 'CSKA');
  const result = normalizeBundleForAnchor(bundle, 'Efes');
  assert.strictEqual(result.boxscore_players[0].team, 'Efes');
  assert.strictEqual(result.boxscore_players[1].team, 'CSKA');
});

test('starts values are unchanged', () => {
  const bundle = makeBundle('Efes', 'CSKA');
  const result = normalizeBundleForAnchor(bundle, 'Efes');
  assert.strictEqual(result.views.top.starts['Efes'], 50);
  assert.strictEqual(result.views.top.starts['CSKA'], 45);
});

// ─── Scenario B: anchor is team_b (swap needed) ──────────────────────────────
console.log('\nScenario B — anchor is team_b (swap needed)');

test('meta is swapped: anchor becomes team_a', () => {
  const bundle = makeBundle('Efes', 'CSKA');
  const result = normalizeBundleForAnchor(bundle, 'CSKA');
  assert.strictEqual(result.meta.team_a, 'CSKA', 'anchor should be team_a after swap');
  assert.strictEqual(result.meta.team_b, 'Efes', 'original team_a should be team_b after swap');
});

test('anchor (CSKA) gets ANCHOR_COLOR after swap', () => {
  const bundle = makeBundle('Efes', 'CSKA');
  const result = normalizeBundleForAnchor(bundle, 'CSKA');
  assert.strictEqual(result.colors['CSKA'], ANCHOR_COLOR);
});

test('opponent (Efes) gets OPP_COLOR after swap', () => {
  const bundle = makeBundle('Efes', 'CSKA');
  const result = normalizeBundleForAnchor(bundle, 'CSKA');
  assert.strictEqual(result.colors['Efes'], OPP_COLOR);
});

test('node IDs are unchanged after swap (data integrity)', () => {
  const bundle = makeBundle('Efes', 'CSKA');
  const result = normalizeBundleForAnchor(bundle, 'CSKA');
  const nodes = result.views.top.nodes;
  const ids = nodes.map(n => n.id);
  assert.ok(ids.includes('Efes_start'), 'Efes_start node ID must not be renamed');
  assert.ok(ids.includes('CSKA_start'), 'CSKA_start node ID must not be renamed');
});

test('node team labels are unchanged after swap (CSKA nodes still have team=CSKA)', () => {
  const bundle = makeBundle('Efes', 'CSKA');
  const result = normalizeBundleForAnchor(bundle, 'CSKA');
  const nodes = result.views.top.nodes;
  const cskaStart = nodes.find(n => n.id === 'CSKA_start');
  assert.ok(cskaStart, 'CSKA_start node must exist');
  assert.strictEqual(cskaStart.team, 'CSKA', 'CSKA node must keep team=CSKA');
  const efesStart = nodes.find(n => n.id === 'Efes_start');
  assert.ok(efesStart, 'Efes_start node must exist');
  assert.strictEqual(efesStart.team, 'Efes', 'Efes node must keep team=Efes');
});

test('link source/target IDs are unchanged after swap', () => {
  const bundle = makeBundle('Efes', 'CSKA');
  const result = normalizeBundleForAnchor(bundle, 'CSKA');
  const links = result.views.top.links;
  assert.ok(links.some(l => l.source === 'CSKA_start' && l.target === 'CSKA_Half-court'),
    'CSKA links must use original node IDs');
  assert.ok(links.some(l => l.source === 'Efes_start' && l.target === 'Efes_Half-court'),
    'Efes links must use original node IDs');
});

test('player team labels are unchanged after swap (scores stay correct)', () => {
  const bundle = makeBundle('Efes', 'CSKA');
  const result = normalizeBundleForAnchor(bundle, 'CSKA');
  // p1 is an Efes player; p2 is a CSKA player — teams must not be swapped
  assert.strictEqual(result.players['p1'].team, 'Efes',
    'Efes player must not be relabelled as CSKA');
  assert.strictEqual(result.players['p2'].team, 'CSKA',
    'CSKA player must not be relabelled as Efes');
});

test('boxscore team labels are unchanged after swap', () => {
  const bundle = makeBundle('Efes', 'CSKA');
  const result = normalizeBundleForAnchor(bundle, 'CSKA');
  assert.strictEqual(result.boxscore_players[0].team, 'Efes');
  assert.strictEqual(result.boxscore_players[1].team, 'CSKA');
});

test('scoreboard computes correctly: CSKA (anchor) gets CSKA pts, Efes gets Efes pts', () => {
  const bundle = makeBundle('Efes', 'CSKA');
  const result = normalizeBundleForAnchor(bundle, 'CSKA');
  const meta = result.meta;
  // Simulate updateScoreboard logic
  let scoreA = 0, scoreB = 0;
  const playersMap = result.players || {};
  (result.boxscore_players || []).forEach(r => {
    const pid = r.player_id;
    let teamName = null;
    if (pid && playersMap[pid] && playersMap[pid].team) teamName = playersMap[pid].team;
    if (!teamName && typeof r.team === 'string') teamName = r.team;
    if (teamName === meta.team_a) scoreA += (r.points || 0);
    else if (teamName === meta.team_b) scoreB += (r.points || 0);
  });
  // CSKA (anchor, meta.team_a) should show 25 pts; Efes should show 20 pts
  assert.strictEqual(scoreA, 25, `CSKA (anchor/team_a) score should be 25, got ${scoreA}`);
  assert.strictEqual(scoreB, 20, `Efes (team_b) score should be 20, got ${scoreB}`);
});

test('starts values are unchanged after swap (correct possession counts)', () => {
  const bundle = makeBundle('Efes', 'CSKA');
  const result = normalizeBundleForAnchor(bundle, 'CSKA');
  // Efes had 50 starts and CSKA had 45 starts — these must not be swapped
  assert.strictEqual(result.views.top.starts['CSKA'], 45,
    'CSKA starts must remain 45 (not swapped with Efes)');
  assert.strictEqual(result.views.top.starts['Efes'], 50,
    'Efes starts must remain 50 (not swapped with CSKA)');
});

test('anchor nodes (CSKA) come first in the node array after swap', () => {
  const bundle = makeBundle('Efes', 'CSKA');
  const result = normalizeBundleForAnchor(bundle, 'CSKA');
  const nodes = result.views.top.nodes;
  // The first node in the array should be a CSKA node so d3-sankey places it at the top
  assert.strictEqual(nodes[0].team, 'CSKA',
    'First node after swap should belong to the anchor team (CSKA)');
  // And the Efes nodes should still be present, just after CSKA nodes
  const cskaNodes = nodes.filter(n => n.team === 'CSKA');
  const efesNodes = nodes.filter(n => n.team === 'Efes');
  assert.ok(cskaNodes.length > 0, 'CSKA nodes must be present');
  assert.ok(efesNodes.length > 0, 'Efes nodes must be present');
  const lastCskaIdx = nodes.lastIndexOf(cskaNodes[cskaNodes.length - 1]);
  const firstEfesIdx = nodes.indexOf(efesNodes[0]);
  assert.ok(lastCskaIdx < firstEfesIdx,
    'All CSKA (anchor) nodes must appear before Efes (opponent) nodes');
});

test('single-team focus on anchor (CSKA) would filter CSKA nodes correctly', () => {
  const bundle = makeBundle('Efes', 'CSKA');
  const result = normalizeBundleForAnchor(bundle, 'CSKA');
  // Simulate teamFocus = "CSKA"
  const focused = result.views.top.nodes.filter(n => n.team === 'CSKA');
  assert.ok(focused.length > 0, 'Must find CSKA nodes when focusing on CSKA');
  assert.ok(focused.every(n => n.id.startsWith('CSKA_')),
    'Focused nodes must have CSKA-prefixed IDs (actual CSKA data)');
});

test('player_flows keys are unchanged after swap', () => {
  const bundle = makeBundle('Efes', 'CSKA');
  const result = normalizeBundleForAnchor(bundle, 'CSKA');
  const pf = result.views.top.player_flows;
  assert.ok('CSKA_start->CSKA_Half-court' in pf,
    'CSKA player_flows key must be preserved');
  assert.ok('Efes_start->Efes_Half-court' in pf,
    'Efes player_flows key must be preserved');
});

test('insight text is unchanged after swap (still references real team names)', () => {
  const bundle = makeBundle('Efes', 'CSKA');
  const result = normalizeBundleForAnchor(bundle, 'CSKA');
  assert.ok(result.views.top.insights.some(s => s.includes('Efes')),
    'Efes still mentioned in insights');
  assert.ok(result.views.top.insights.some(s => s.includes('CSKA')),
    'CSKA still mentioned in insights');
});

// ─── Scenario C: edge cases ──────────────────────────────────────────────────
console.log('\nScenario C — edge cases');

test('missing team_a: no swap, colors still set for anchor', () => {
  const bundle = makeBundle('Efes', 'CSKA');
  bundle.meta.team_a = '';
  const result = normalizeBundleForAnchor(bundle, 'CSKA');
  assert.strictEqual(result.colors['CSKA'], ANCHOR_COLOR);
});

test('missing team_b: no swap, colors still set for anchor', () => {
  const bundle = makeBundle('Efes', 'CSKA');
  bundle.meta.team_b = '';
  const result = normalizeBundleForAnchor(bundle, 'CSKA');
  assert.strictEqual(result.colors['CSKA'], ANCHOR_COLOR);
});

test('original bundle is not mutated', () => {
  const bundle = makeBundle('Efes', 'CSKA');
  const originalTeamA = bundle.meta.team_a;
  normalizeBundleForAnchor(bundle, 'CSKA');
  assert.strictEqual(bundle.meta.team_a, originalTeamA,
    'Original bundle must not be mutated');
});

test('idempotent when anchor is team_a: applying normalization twice is stable', () => {
  const bundle = makeBundle('Efes', 'CSKA');
  const once = normalizeBundleForAnchor(bundle, 'Efes');
  const twice = normalizeBundleForAnchor(once, 'Efes');
  assert.strictEqual(twice.meta.team_a, 'Efes');
  assert.strictEqual(twice.colors['Efes'], ANCHOR_COLOR);
  assert.strictEqual(twice.colors['CSKA'], OPP_COLOR);
});

// ─── Summary ─────────────────────────────────────────────────────────────────
console.log(`\n${passed + failed} tests total: ${passed} passed, ${failed} failed`);
if (failed > 0) {
  process.exit(1);
}
