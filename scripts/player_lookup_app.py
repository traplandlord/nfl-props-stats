#!/usr/bin/env python3
"""Local Flask UI: Search | Weekly Predictions | Build my card | Guide.

Runs locally on your machine. Bind defaults to 127.0.0.1:5056 via scripts/config.py
(NFL_PROPS_HOST / NFL_PROPS_PORT / NFL_PROPS_DATA).

For a browser-only version, visit https://traplandlord.github.io/nfl-props-stats/

Hardening: bounded loads, paginated teams, debounced search API,
error handlers, season rollups + week preds only (no 59k weekly dump).
Build-my-card is PrizePicks-style: N=2..6 from ANY mix of NFL teams.
"""

from __future__ import annotations

import json
import sys
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import pandas as pd
from flask import Flask, jsonify, redirect, render_template_string, request, session, url_for

from player_lookup_lib import full_profile, load_team_logos, search_players
import entry_builder_lib as entrylib
import guide_lib as guidelib
import guide_improve as guideimprove
import active_games as active_games
from config import (
    ROOT,
    DATA_DIR as DATA,
    PRED_DIR,
    HOST,
    PORT,
    access_message,
    pick_port,
)


app = Flask(__name__)
app.secret_key = "nfl-props-local-dev-only"  # local 127.0.0.1; not for public deploy

NAV = """
  <nav class="nav">
    <a href="{{ url_for('index') }}" class="{% if active=='search' %}active{% endif %}">Search</a>
    <a href="{{ url_for('weekly') }}" class="{% if active=='weekly' %}active{% endif %}">Weekly Predictions</a>
    <a href="{{ url_for('entry') }}" class="{% if active=='entry' %}active{% endif %}">Build my card</a>
    <a href="{{ url_for('guide') }}" class="{% if active=='guide' %}active{% endif %}">Guide</a>
  </nav>
  <div class="access-banner"><strong>Local Flask UI</strong> running on your machine.
    For a browser-only version, visit <a href="https://traplandlord.github.io/nfl-props-stats/" target="_blank" style="color:#3d8bfd">the web app</a>.</div>
"""

BASE_STYLE = """
  <style>
    :root { --bg:#0f1419; --card:#1a2332; --text:#e7ecf3; --muted:#9aa7b8; --accent:#3d8bfd;
            --border:#2a3545; --starter:#2ecc71; --rotation:#f1c40f; --bench:#95a5a6; --warn:#e67e22; }
    * { box-sizing: border-box; }
    body { font-family: system-ui, -apple-system, Segoe UI, Roboto, sans-serif; background: var(--bg);
           color: var(--text); margin: 0; padding: 24px; }
    h1 { font-size: 1.35rem; margin: 0 0 8px; }
    p.sub { color: var(--muted); margin: 0 0 16px; font-size: 0.9rem; }
    .nav { display:flex; gap:12px; margin-bottom:20px; flex-wrap:wrap; }
    .nav a { color: var(--muted); text-decoration:none; padding:8px 14px; border-radius:8px; border:1px solid var(--border); }
    .nav a.active, .nav a:hover { color:#fff; background:#152033; border-color: var(--accent); }
    form.search, form.weekpick, .toolbar { display:flex; gap:8px; flex-wrap:wrap; max-width:960px; margin-bottom:16px; align-items:center; }
    input[type=text], select { padding:10px 12px; border-radius:8px; border:1px solid var(--border);
           background:#0c1016; color:var(--text); font-size:1rem; }
    button, .btn { padding:10px 16px; border-radius:8px; border:0; background:var(--accent); color:#fff;
           font-weight:600; cursor:pointer; text-decoration:none; display:inline-block; }
    button.secondary { background:#2a3545; }
    button.danger { background:#8b3a3a; }
    button:hover, .btn:hover { filter: brightness(1.08); }
    button:disabled { opacity:0.5; cursor:not-allowed; }
    .card { background: var(--card); border:1px solid var(--border); border-radius:12px; padding:16px; margin-bottom:14px; }
    .hero { display:flex; gap:20px; align-items:flex-start; flex-wrap:wrap; }
    .hero img.headshot, img.headshot { width:120px; height:120px; object-fit:cover; border-radius:12px;
           background:#111; border:1px solid var(--border); }
    img.logo { width:36px; height:36px; vertical-align:middle; margin-right:8px; }
    img.logo-sm { width:28px; height:28px; vertical-align:middle; margin-right:8px; }
    .meta h2 { margin:0 0 6px; font-size:1.5rem; }
    .meta .line { color:var(--muted); margin:4px 0; }
    .jersey { display:inline-block; background:#0c1016; border:1px solid var(--border); padding:2px 10px;
           border-radius:6px; font-weight:700; margin-left:8px; }
    table { width:100%; border-collapse:collapse; margin-top:8px; font-size:0.85rem; }
    th, td { text-align:left; padding:8px 8px; border-bottom:1px solid var(--border); vertical-align:top; }
    th { color:var(--muted); font-weight:600; }
    a { color:var(--accent); text-decoration:none; }
    a:hover { text-decoration:underline; }
    .empty { color:var(--muted); }
    .section { margin-top:20px; }
    .section h3 { margin:0 0 8px; font-size:1.05rem; }
    .banner { background:#1e2a1e; border:1px solid #2d4a2d; color:#b8e0b8; padding:10px 14px;
           border-radius:8px; margin-bottom:16px; font-size:0.9rem; }
    .banner.warn { background:#2a2218; border-color:#5a4020; color:#f0d9a8; }
    .err { background:#3a1a1a; border:1px solid #6a3030; color:#f0b0b0; padding:10px 14px; border-radius:8px; margin-bottom:12px; display:none; }
    .badge { display:inline-block; font-size:0.7rem; font-weight:700; text-transform:uppercase;
           padding:2px 8px; border-radius:999px; margin-left:6px; }
    .badge.starter { background:rgba(46,204,113,.2); color:var(--starter); }
    .badge.rotation { background:rgba(241,196,15,.2); color:var(--rotation); }
    .badge.bench_warmer { background:rgba(149,165,166,.2); color:var(--bench); }
    .badge.model { background:rgba(61,139,253,.2); color:var(--accent); }
    .player-row { display:flex; gap:12px; align-items:flex-start; padding:12px 0; border-bottom:1px solid var(--border); }
    .player-row img, .slot img { width:56px; height:56px; border-radius:10px; object-fit:cover; background:#111; }
    .prop-table th { font-size:0.75rem; }
    .layer-miss { color:var(--muted); font-style:italic; }
    .flags { color:var(--warn); font-size:0.75rem; }
    details.team > summary { list-style:none; cursor:pointer; }
    details.team > summary::-webkit-details-marker { display:none; }
    .team-chip { display:inline-flex; align-items:center; gap:8px; background:#121a24; border:1px solid var(--border);
           border-radius:10px; padding:10px 14px; color:var(--text); }
    .grid2 { display:grid; grid-template-columns: 1fr 1fr; gap:16px; }
    @media (max-width: 900px) { .grid2 { grid-template-columns: 1fr; } }
    .slot { display:flex; gap:12px; padding:12px; border:1px solid var(--border); border-radius:10px; margin-bottom:8px; background:#121a24; }
    .slot .grow { flex:1; }
    .hit { display:flex; justify-content:space-between; gap:8px; padding:8px; border-bottom:1px solid var(--border); align-items:center; }
    .pager { display:flex; gap:8px; align-items:center; margin-top:8px; }
    .z-on_track { color: var(--starter); }
    .z-mild_miss { color: var(--rotation); }
    .z-off_track { color: var(--warn); }
    .z-large_residual { color: #e74c3c; }
    .z-no_actual_yet { color: var(--muted); }
    .sport-stub { opacity: 0.75; border-style: dashed; }
    .sug { border-left: 3px solid var(--accent); padding-left: 12px; margin-bottom: 12px; }
    .access-banner { background:#3a2410; border:1px solid #8a5a20; color:#ffd9a0; padding:10px 14px;
           border-radius:8px; margin-bottom:16px; font-size:0.88rem; line-height:1.4; }
    .access-banner strong { color:#fff; }
    .empty-state { text-align:center; padding:28px 16px; color:var(--muted); border:1px dashed var(--border);
           border-radius:12px; background:#121a24; }
    .role-legend { display:flex; gap:10px; flex-wrap:wrap; margin:8px 0 14px; font-size:0.8rem; color:var(--muted); }
  </style>
"""

PAGE = """
<!doctype html>
<html lang="en"><head>
  <meta charset="utf-8"/><meta name="viewport" content="width=device-width, initial-scale=1"/>
  <title>NFL Player Lookup</title>""" + BASE_STYLE + """
</head><body>
  <h1>NFL Player Lookup</h1>
""" + NAV + """
  <p class="sub">Local parquet only — no invented stats.</p>
  <form class="search" method="get" action="{{ url_for('index') }}">
    <input type="text" name="q" value="{{ q or '' }}" placeholder="Player name (e.g. Mahomes, CMC)" autofocus/>
    <button type="submit">Search</button>
  </form>
  {% if q and not matches and not profile %}<p class="empty">No players matched <strong>{{ q }}</strong>.</p>{% endif %}
  {% if matches and not profile %}
    <div class="card matches"><h3>Multiple matches — pick one</h3>
      <table><thead><tr><th>Name</th><th>#</th><th>Pos</th><th>Team</th><th>Last</th><th>Score</th></tr></thead><tbody>
        {% for m in matches %}
          <tr>
            <td><a href="{{ url_for('player', gsis_id=m.gsis_id) }}">{{ m.display_name }}</a></td>
            <td>{{ m.jersey_number if m.jersey_number is not none else '—' }}</td>
            <td>{{ m.position or '—' }}</td><td>{{ m.latest_team or '—' }}</td>
            <td>{{ m.last_season or '—' }}</td><td>{{ m.match_score }}</td>
          </tr>
        {% endfor %}
      </tbody></table>
    </div>
  {% endif %}
  {% if profile %}
    <div class="card"><div class="hero">
      {% if profile.headshot %}<img class="headshot" src="{{ profile.headshot }}" alt="" referrerpolicy="no-referrer"/>
      {% else %}<div class="headshot" style="display:flex;align-items:center;justify-content:center;color:#666;width:120px;height:120px;border:1px solid var(--border);border-radius:12px;">No photo</div>{% endif %}
      <div class="meta">
        <h2>{{ profile.display_name }}<span class="jersey">{% if profile.jersey_number is not none %}#{{ profile.jersey_number }}{% else %}#?{% endif %}</span></h2>
        <div class="line">{% if profile.team_logo_url %}<img class="logo" src="{{ profile.team_logo_url }}" alt="" referrerpolicy="no-referrer"/>{% endif %}
          {{ profile.team_name or profile.latest_team or '—' }} · {{ profile.position or '?' }}</div>
        <div class="line">gsis_id: {{ profile.gsis_id }}</div>
      </div></div>
      <div class="section"><h3>Season summary</h3>
        {% if profile.season_stats %}
        <table><thead><tr><th>Season</th><th>Team</th><th>G</th><th>Pass</th><th>Rush</th><th>Rec</th><th>Touches</th></tr></thead><tbody>
          {% for s in profile.season_stats %}
            <tr><td>{{ s.season }}</td><td>{{ s.teams|join(',') if s.teams else '—' }}</td>
              <td>{{ s.games_played if s.games_played is not none else '—' }}</td>
              <td>{{ s.passing_yards }}/{{ s.passing_tds }}</td>
              <td>{{ s.rushing_yards }}/{{ s.rushing_tds }}</td>
              <td>{{ s.receiving_yards }}/{{ s.receiving_tds }}</td>
              <td>{{ s.sum_touches if s.sum_touches is not none else '—' }}</td></tr>
          {% endfor %}
        </tbody></table>
        {% else %}<p class="empty">No season stats.</p>{% endif %}
      </div>
      <div class="section"><h3>Recent weeks</h3>
        {% if profile.recent_weeks %}
        <table><thead><tr><th>Season</th><th>Wk</th><th>Opp</th><th>Pass</th><th>Rush</th><th>Rec</th></tr></thead><tbody>
          {% for w in profile.recent_weeks %}
            <tr><td>{{ w.season }}</td><td>{{ w.week }}</td><td>{{ w.team }} vs {{ w.opponent_team }}</td>
              <td>{{ w.passing_yards }}/{{ w.passing_tds }}TD</td>
              <td>{{ w.rushing_yards }}/{{ w.rushing_tds }}TD</td>
              <td>{{ w.receiving_yards }}/{{ w.receiving_tds }}TD</td></tr>
          {% endfor %}
        </tbody></table>
        {% else %}<p class="empty">No weekly rows.</p>{% endif %}
      </div>
    </div>
  {% endif %}
</body></html>
"""

WEEKLY_PAGE = """
<!doctype html>
<html lang="en"><head>
  <meta charset="utf-8"/><meta name="viewport" content="width=device-width, initial-scale=1"/>
  <title>Weekly Predictions</title>""" + BASE_STYLE + """
</head><body>
  <h1>Weekly Predictions Board</h1>
""" + NAV + """
  <div class="banner"><strong>MODEL ESTIMATES</strong> in Ours = empirical-Bayes from nflverse trailing usage.
    ESPN/Vegas show <em>not loaded</em> unless you fill <code>data/external/*.csv</code> (never fabricate).
  </div>
  <form class="weekpick" method="get" action="{{ url_for('weekly') }}">
    <label>Season <select name="season">{% for s in seasons %}<option value="{{ s }}" {% if s==season %}selected{% endif %}>{{ s }}</option>{% endfor %}</select></label>
    <label>Week <select name="week">{% for w in weeks %}<option value="{{ w }}" {% if w==week %}selected{% endif %}>{{ w }}</option>{% endfor %}</select></label>
    <button type="submit">Load</button>
  </form>
  {% if meta %}
    <p class="sub">season {{ meta.season }} week {{ meta.week }} · locked={{ meta.predictions_locked }}
      · {{ meta.player_count }} players · ESPN: {% if meta.espn_loaded %}loaded{% else %}<strong>not loaded</strong>{% endif %}
      · Vegas: {% if meta.vegas_loaded %}loaded{% else %}<strong>not loaded</strong>{% endif %}</p>
  {% endif %}
  <div class="role-legend"><span class="badge starter">starter</span><span class="badge rotation">rotation</span><span class="badge bench_warmer">bench_warmer</span><span class="empty">· starters listed before bench</span></div>
  {% if not teams %}<div class="card empty-state"><p>No predictions for this week.</p><p class="empty">To generate predictions, run:<br><code>./.venv/bin/python scripts/predict_week.py --season {{ season }} --week {{ week }}</code></p></div>{% endif %}
  {% for t in teams %}
  <details class="team card" {% if focus_team==t.abbr %}open{% endif %}>
    <summary><span class="team-chip">{% if t.logo %}<img class="logo-sm" src="{{ t.logo }}" alt="" referrerpolicy="no-referrer"/>{% endif %}
      <strong>{{ t.abbr }}</strong><span class="empty">vs {{ t.opponent }} · {{ t.player_count }}</span></span></summary>
    {% for role, label in [('starter','Starters'),('rotation','Rotation'),('bench_warmer','Bench warmers')] %}
      {% set group = t.players_by_role.get(role, []) %}
      {% if group %}
      <div class="section"><h3>{{ label }} <span class="badge {{ role }}">{{ role }}</span></h3>
        {% for p in group %}
        <div class="player-row">
          {% if p.photo_url %}<img src="{{ p.photo_url }}" alt="" referrerpolicy="no-referrer"/>{% else %}<div style="width:56px;height:56px;border-radius:10px;background:#111;border:1px solid var(--border);"></div>{% endif %}
          <div style="flex:1;">
            <div><strong>{{ p.player_name }}</strong>
              <span class="jersey">{% if p.jersey_number is not none %}#{{ p.jersey_number }}{% else %}#?{% endif %}</span>
              <span class="badge {{ p.role_bucket }}">{{ p.role_bucket }}</span>
              <span class="empty">{{ p.position }}</span>
              <button type="button" class="btn" style="padding:4px 10px;font-size:0.75rem;margin-left:8px"
                onclick="location.href='{{ url_for('entry') }}?add={{ p.gsis_id }}&season={{ season }}&week={{ week }}'">Add to card</button>
            </div>
            <table class="prop-table"><thead><tr><th>Prop</th><th>Actuals</th><th>ESPN</th><th>Vegas</th><th>Ours <span class="badge model">MODEL</span></th><th>Flags</th></tr></thead>
              <tbody>{% for pr in p.props %}<tr>
                <td>{{ pr.prop }}</td>
                <td>{% if pr.actuals_mean is not none %}mean {{ '%.1f'|format(pr.actuals_mean) }} · n={{ pr.actuals_n }}{% else %}<span class="layer-miss">no trailing</span>{% endif %}</td>
                <td>{% if pr.espn_projection is not none %}{{ '%.1f'|format(pr.espn_projection) }}{% else %}<span class="layer-miss">ESPN: not loaded</span>{% endif %}</td>
                <td>{% if pr.vegas_line is not none %}line {{ '%.1f'|format(pr.vegas_line) }}{% else %}<span class="layer-miss">Vegas: not loaded</span>{% endif %}</td>
                <td><strong>{{ '%.1f'|format(pr.ours_mean) }}</strong> ±{{ '%.1f'|format(pr.ours_sd) }}</td>
                <td class="flags">{{ pr.flags or '—' }}</td>
              </tr>{% endfor %}</tbody>
            </table>
          </div>
        </div>
        {% endfor %}
      </div>
      {% endif %}
    {% endfor %}
  </details>
  {% endfor %}
</body></html>
"""

ENTRY_PAGE = """
<!doctype html>
<html lang="en"><head>
  <meta charset="utf-8"/><meta name="viewport" content="width=device-width, initial-scale=1"/>
  <title>Build my card</title>""" + BASE_STYLE + """
</head><body>
  <h1>Build my card / My Entry</h1>
""" + NAV + """
  <div class="banner">PrizePicks-style: pick <strong>N = 2–6</strong> players from <strong>any mix of NFL teams</strong>
    (same-team allowed, never required). Props shown are <strong>MODEL ESTIMATES</strong> from nflverse — never invented players.</div>
  <div id="err" class="err"></div>
  <div class="toolbar">
    <label>Season <select id="season">{% for s in seasons %}<option value="{{ s }}" {% if s==season %}selected{% endif %}>{{ s }}</option>{% endfor %}</select></label>
    <label>Week <select id="week">{% for w in weeks %}<option value="{{ w }}" {% if w==week %}selected{% endif %}>{{ w }}</option>{% endfor %}</select></label>
    <label>Entry size N
      <select id="n">{% for i in [2,3,4,5,6] %}<option value="{{ i }}" {% if i==n %}selected{% endif %}>{{ i }}</option>{% endfor %}</select>
    </label>
    <button type="button" id="btn-random">Randomize</button>
    <button type="button" class="secondary" id="btn-clear">Clear</button>
    <button type="button" class="secondary" id="btn-save">Save entry</button>
  </div>
  <p class="sub">Randomize samples league-wide, weighted toward starters/rotation + trailing-usage confidence.</p>

  <div class="grid2">
    <div>
      <div class="card">
        <h3>My Entry <span id="fill-count" class="empty"></span></h3>
        <div id="card-slots"></div>
      </div>
    </div>
    <div>
      <div class="card">
        <h3>Add players (league-wide search)</h3>
        <input type="text" id="q" placeholder="Search name or team abbr…" style="width:100%;margin-bottom:8px"/>
        <div id="search-hits"></div>
      </div>
      <div class="card">
        <h3>Browse by team <span class="empty">(paginated)</span></h3>
        <div id="team-browser"></div>
        <div class="pager">
          <button type="button" class="secondary" id="prev-page">Prev</button>
          <span id="page-label" class="empty"></span>
          <button type="button" class="secondary" id="next-page">Next</button>
        </div>
      </div>
    </div>
  </div>

<script>
(function(){
  const state = {
    season: {{ season }},
    week: {{ week }},
    n: {{ n }},
    players: {{ players_json|safe }},
    entryId: {{ entry_id_json|safe }},
    page: 0,
    debounce: null
  };
  const errEl = document.getElementById('err');
  function showErr(msg){ errEl.style.display='block'; errEl.textContent = msg || 'Something went wrong'; }
  function clearErr(){ errEl.style.display='none'; errEl.textContent=''; }
  function syncSelects(){
    state.season = +document.getElementById('season').value;
    state.week = +document.getElementById('week').value;
    state.n = +document.getElementById('n').value;
  }
  function renderCard(){
    const box = document.getElementById('card-slots');
    document.getElementById('fill-count').textContent = '(' + state.players.length + ' / ' + state.n + ')';
    if(!state.players.length){ box.innerHTML = '<p class="empty">Empty — search, browse, or Randomize (any teams).</p>'; return; }
    box.innerHTML = state.players.map(p => {
      const props = (p.props||[]).slice(0,6).map(pr =>
        '<div class="empty">' + pr.prop + ': <strong style="color:#e7ecf3">' +
        (pr.ours_mean!=null ? pr.ours_mean.toFixed(1) : '—') +
        '</strong> ±' + (pr.ours_sd!=null ? pr.ours_sd.toFixed(1) : '—') + '</div>'
      ).join('');
      const photo = p.photo_url ? '<img src="'+p.photo_url+'" referrerpolicy="no-referrer"/>' :
        '<div style="width:56px;height:56px;border-radius:10px;background:#111;border:1px solid var(--border)"></div>';
      const logo = p.team_logo ? '<img class="logo-sm" src="'+p.team_logo+'" referrerpolicy="no-referrer"/>' : '';
      return '<div class="slot">' + photo + '<div class="grow">' +
        logo + '<strong>' + (p.player_name||'') + '</strong>' +
        '<span class="jersey">#' + (p.jersey_number!=null?p.jersey_number:'?') + '</span>' +
        '<span class="badge '+(p.role_bucket||'')+'">'+(p.role_bucket||'')+'</span>' +
        '<div class="empty">' + (p.team||'') + ' ' + (p.position||'') +
        (p.opponent ? ' vs '+p.opponent : '') + ' <span class="badge model">MODEL</span></div>' +
        props + '</div>' +
        '<button type="button" class="danger" data-rm="'+p.gsis_id+'">Remove</button></div>';
    }).join('');
    box.querySelectorAll('[data-rm]').forEach(btn => btn.onclick = () => {
      state.players = state.players.filter(p => p.gsis_id !== btn.getAttribute('data-rm'));
      renderCard();
    });
  }
  async function api(url, opts){
    clearErr();
    try {
      const res = await fetch(url, opts);
      const data = await res.json();
      if(!res.ok || data.error){ showErr(data.error || ('HTTP '+res.status)); return null; }
      return data;
    } catch(e){ showErr(String(e)); return null; }
  }
  async function doSearch(){
    syncSelects();
    const q = document.getElementById('q').value.trim();
    const hits = document.getElementById('search-hits');
    if(q.length < 2){ hits.innerHTML=''; return; }
    const data = await api('/api/entry/search?season='+state.season+'&week='+state.week+'&q='+encodeURIComponent(q));
    if(!data) return;
    hits.innerHTML = (data.results||[]).map(p =>
      '<div class="hit"><span>'+(p.team||'')+' '+ (p.player_name||'')+' <span class="badge '+(p.role_bucket||'')+'">'+(p.role_bucket||'')+'</span></span>' +
      '<button type="button" data-add="'+p.gsis_id+'">Add</button></div>'
    ).join('') || '<p class="empty">No matches</p>';
    hits.querySelectorAll('[data-add]').forEach(btn => btn.onclick = () => addPlayer(btn.getAttribute('data-add')));
  }
  async function addPlayer(gsis){
    syncSelects();
    if(state.players.length >= state.n){ showErr('Entry full (N='+state.n+'). Remove someone or raise N.'); return; }
    if(state.players.some(p => p.gsis_id === gsis)){ showErr('Already on card'); return; }
    const data = await api('/api/entry/player?season='+state.season+'&week='+state.week+'&gsis_id='+encodeURIComponent(gsis));
    if(!data || !data.player) return;
    state.players.push(data.player);
    renderCard();
  }
  async function loadTeams(){
    syncSelects();
    const data = await api('/api/entry/teams?season='+state.season+'&week='+state.week+'&page='+state.page);
    if(!data) return;
    document.getElementById('page-label').textContent = 'page '+(data.page+1)+' / '+Math.max(1, Math.ceil(data.total_teams/data.page_size));
    document.getElementById('prev-page').disabled = !data.has_prev;
    document.getElementById('next-page').disabled = !data.has_next;
    const box = document.getElementById('team-browser');
    box.innerHTML = (data.teams||[]).map(t => {
      const rows = (t.players||[]).map(p =>
        '<div class="hit"><span>'+p.player_name+' <span class="badge '+(p.role_bucket||'')+'">'+(p.role_bucket||'')+'</span> '+
        '<span class="empty">'+(p.position||'')+'</span></span>' +
        '<button type="button" data-add="'+p.gsis_id+'">Add</button></div>'
      ).join('');
      return '<details style="margin-bottom:8px"><summary class="team-chip">' +
        (t.logo?'<img class="logo-sm" src="'+t.logo+'" referrerpolicy="no-referrer"/>':'') +
        '<strong>'+t.abbr+'</strong> <span class="empty">vs '+(t.opponent||'')+'</span></summary>'+rows+'</details>';
    }).join('') || '<p class="empty">No team preds — run predict_week.py</p>';
    box.querySelectorAll('[data-add]').forEach(btn => btn.onclick = () => addPlayer(btn.getAttribute('data-add')));
  }
  document.getElementById('q').addEventListener('input', () => {
    clearTimeout(state.debounce);
    state.debounce = setTimeout(doSearch, 300);
  });
  document.getElementById('btn-random').onclick = async () => {
    syncSelects();
    const data = await api('/api/entry/randomize', {
      method:'POST', headers:{'Content-Type':'application/json'},
      body: JSON.stringify({season:state.season, week:state.week, n:state.n})
    });
    if(!data) return;
    state.players = data.players || [];
    state.entryId = data.entry_id || state.entryId;
    renderCard();
    // sanity: mixed teams OK
    const teams = new Set(state.players.map(p => p.team));
    if(teams.size >= 1){ clearErr(); }
  };
  document.getElementById('btn-clear').onclick = () => { state.players=[]; renderCard(); };
  document.getElementById('btn-save').onclick = async () => {
    syncSelects();
    const data = await api('/api/entry/save', {
      method:'POST', headers:{'Content-Type':'application/json'},
      body: JSON.stringify({season:state.season, week:state.week, n:state.n, players:state.players, entry_id:state.entryId})
    });
    if(!data) return;
    state.entryId = data.entry_id;
    clearErr();
    errEl.style.display='block'; errEl.style.background='#1e2a1e'; errEl.style.borderColor='#2d4a2d'; errEl.style.color='#b8e0b8';
    errEl.textContent = 'Saved ' + data.path + ' (id=' + data.entry_id + ')';
  };
  document.getElementById('prev-page').onclick = () => { state.page=Math.max(0,state.page-1); loadTeams(); };
  document.getElementById('next-page').onclick = () => { state.page+=1; loadTeams(); };
  ['season','week','n'].forEach(id => document.getElementById(id).onchange = () => { syncSelects(); loadTeams(); renderCard(); });
  renderCard();
  loadTeams();
  {% if preadd %}addPlayer({{ preadd|tojson }});{% endif %}
})();
</script>
</body></html>
"""


GUIDE_PAGE = """
<!doctype html>
<html lang="en"><head>
  <meta charset="utf-8"/><meta name="viewport" content="width=device-width, initial-scale=1"/>
  <title>Guide</title>""" + BASE_STYLE + """
</head><body>
  <h1>Guide — active games &amp; challenge the card</h1>
""" + NAV + """
  <div class="banner"><strong>Real data only.</strong> Live progress = nflverse weekly parquet when present
    (not invented play-by-play). ESPN/Vegas show <em>not loaded</em> unless external CSVs are filled.
    Revisions are <strong>MODEL ESTIMATES</strong> (empirical Bayes / shrinkage).</div>
  <div id="err" class="err"></div>

  <div class="toolbar">
    <label>Season <select id="season">{% for s in seasons %}<option value="{{ s }}" {% if s==season %}selected{% endif %}>{{ s }}</option>{% endfor %}</select></label>
    <label>Week <select id="week">{% for w in weeks %}<option value="{{ w }}" {% if w==week %}selected{% endif %}>{{ w }}</option>{% endfor %}</select></label>
    <label>Entry
      <select id="entry_id">
        <option value="">(latest / locked week)</option>
        {% for e in entries %}
        <option value="{{ e.entry_id }}" {% if e.entry_id==entry_id %}selected{% endif %}>
          {{ e.entry_id[:8] }}… s{{ e.season }}w{{ e.week }} ({{ e.entry_size }})
        </option>
        {% endfor %}
      </select>
    </label>
    <button type="button" id="btn-reload">Reload</button>
    <button type="button" class="secondary" id="btn-improve">Propose improvements</button>
    <label><input type="checkbox" id="locked_only"/> Locked week pool (paginated)</label>
  </div>
  <p class="sub" id="meta-line"></p>

  <div class="grid2">
    <div>
      <div class="card">
        <h3>Active / today games</h3>
        <div id="active-games"></div>
      </div>
      <div class="card">
        <h3>Upcoming (72h window)</h3>
        <div id="upcoming-games"></div>
      </div>
      <div class="card sport-stub">
        <h3>Other sports</h3>
        <div id="other-sports"></div>
      </div>
    </div>
    <div>
      <div class="card">
        <h3>Challenge the card <span class="badge model">MODEL</span></h3>
        <div id="challenge"></div>
        <div class="pager">
          <button type="button" class="secondary" id="prev-page">Prev</button>
          <span id="page-label" class="empty"></span>
          <button type="button" class="secondary" id="next-page">Next</button>
        </div>
      </div>
      <div class="card">
        <h3>Improve with reasoning</h3>
        <p class="sub">Only when injury / role / usage-drift / huge residual signals fire. Logged to data/guide/improvement_log.jsonl</p>
        <div id="improve"></div>
      </div>
    </div>
  </div>

<script>
(function(){
  const state = {
    season: {{ season }},
    week: {{ week }},
    entryId: {{ entry_id_json|safe }},
    page: 0,
  };
  const errEl = document.getElementById('err');
  function showErr(msg){ errEl.style.display='block'; errEl.style.background='#3a1a1a'; errEl.style.borderColor='#6a3030'; errEl.style.color='#f0b0b0'; errEl.textContent = msg || 'Error'; }
  function clearErr(){ errEl.style.display='none'; errEl.textContent=''; }
  function sync(){
    state.season = +document.getElementById('season').value;
    state.week = +document.getElementById('week').value;
    state.entryId = document.getElementById('entry_id').value || null;
  }
  async function api(url, opts){
    clearErr();
    try {
      const res = await fetch(url, opts);
      const data = await res.json();
      if(!res.ok || data.error){ showErr(data.error || ('HTTP '+res.status)); return null; }
      return data;
    } catch(e){ showErr(String(e)); return null; }
  }
  function gameCard(g){
    const score = (g.away_score!=null && g.home_score!=null)
      ? (g.away_score+' – '+g.home_score)
      : 'score not in schedule';
    return '<div class="slot">' +
      (g.away_logo?'<img class="logo-sm" src="'+g.away_logo+'" referrerpolicy="no-referrer"/>':'') +
      '<strong>'+g.away_team+'</strong> @ <strong>'+g.home_team+'</strong>' +
      (g.home_logo?' <img class="logo-sm" src="'+g.home_logo+'" referrerpolicy="no-referrer"/>':'') +
      '<div class="grow empty">'+ (g.gameday||'')+' '+(g.gametime||'') +
      ' · <span class="badge model">'+g.status+'</span> · '+score +
      '<div style="font-size:0.75rem">'+ (g.status_note||'') +'</div></div></div>';
  }
  async function loadGames(){
    const data = await api('/api/guide/active?upcoming_hours=72');
    if(!data) return;
    const nfl = (data.sports||[]).find(s => s.sport==='nfl') || {};
    const act = nfl.active||[];
    const up = nfl.upcoming||[];
    document.getElementById('active-games').innerHTML = act.length
      ? act.map(gameCard).join('')
      : '<p class="empty">No NFL games today / in-progress in team_schedule (as_of '+ (nfl.as_of_date||'') +').</p>';
    document.getElementById('upcoming-games').innerHTML = up.length
      ? up.map(gameCard).join('')
      : '<p class="empty">No upcoming NFL games in the next 72h window.</p>';
    const others = (data.sports||[]).filter(s => s.sport!=='nfl');
    document.getElementById('other-sports').innerHTML = others.map(s =>
      '<div class="empty"><strong>'+ (s.label||s.sport).toUpperCase() +'</strong>: ' +
      (s.connected ? 'connected' : '<em>feed not connected</em>') +
      ' — '+(s.note||'')+'</div>'
    ).join('') || '<p class="empty">No other sports registered.</p>';
  }
  function fmtNum(x, d){
    if(x==null || x===undefined) return '—';
    return Number(x).toFixed(d==null?1:d);
  }
  function renderChallenge(data){
    document.getElementById('meta-line').textContent =
      'season '+data.season+' week '+data.week+' · source='+data.source+
      ' · weekly actuals: '+(data.has_weekly_actuals?'yes':'no')+
      ' · '+(data.weekly_note||'')+' · as_of '+ (data.as_of_pt||'');
    const box = document.getElementById('challenge');
    const players = data.players||[];
    if(!players.length){
      box.innerHTML = '<p class="empty">No card / predictions to challenge. Save an entry or run predict_week.py.</p>';
      return;
    }
    box.innerHTML = players.map(p => {
      const rows = (p.props||[]).map(pr => {
        const espn = (pr.espn_status==='loaded' && pr.espn_projection!=null)
          ? fmtNum(pr.espn_projection) : '<span class="layer-miss">not loaded</span>';
        const vegas = (pr.vegas_status==='loaded' && pr.vegas_line!=null)
          ? fmtNum(pr.vegas_line) : '<span class="layer-miss">not loaded</span>';
        const live = pr.live_actual!=null ? fmtNum(pr.live_actual) : '<span class="layer-miss">awaiting weekly</span>';
        const z = pr.challenge_z!=null ? fmtNum(pr.challenge_z, 2) : '—';
        return '<tr><td>'+pr.prop+'</td>' +
          '<td><strong>'+fmtNum(pr.ours_mean)+'</strong> ±'+fmtNum(pr.ours_sd)+'</td>' +
          '<td>'+espn+'</td><td>'+vegas+'</td><td>'+live+'</td>' +
          '<td class="z-'+(pr.challenge_label||'')+'">z='+z+' <span class="empty">'+ (pr.challenge_label||'') +'</span></td></tr>';
      }).join('');
      const photo = p.photo_url ? '<img src="'+p.photo_url+'" referrerpolicy="no-referrer"/>' :
        '<div style="width:56px;height:56px;border-radius:10px;background:#111;border:1px solid var(--border)"></div>';
      const logo = p.team_logo ? '<img class="logo-sm" src="'+p.team_logo+'" referrerpolicy="no-referrer"/>' : '';
      return '<div class="player-row">'+photo+'<div style="flex:1">'+ logo +
        '<strong>'+(p.player_name||'')+'</strong> <span class="empty">'+(p.team||'')+' '+ (p.position||'')+
        (p.opponent?' vs '+p.opponent:'')+'</span>' +
        '<span class="badge '+(p.role_bucket||'')+'">'+(p.role_bucket||'')+'</span>' +
        '<table class="prop-table"><thead><tr><th>Prop</th><th>Ours</th><th>ESPN</th><th>Vegas</th><th>Live/actual</th><th>Challenge</th></tr></thead><tbody>'+
        rows+'</tbody></table></div></div>';
    }).join('');
    document.getElementById('page-label').textContent =
      data.source==='locked_predictions'
        ? ('page '+(data.page+1)+' · '+data.total_players+' players')
        : (players.length+' on card');
    document.getElementById('prev-page').disabled = !data.has_prev;
    document.getElementById('next-page').disabled = !data.has_next;
  }
  async function loadChallenge(){
    sync();
    const locked = document.getElementById('locked_only').checked;
    let url = '/api/guide/challenge?season='+state.season+'&week='+state.week+'&page='+state.page;
    if(state.entryId) url += '&entry_id='+encodeURIComponent(state.entryId);
    if(locked) url += '&locked_only=1';
    const data = await api(url);
    if(!data) return;
    renderChallenge(data);
  }
  async function loadImprove(){
    sync();
    const data = await api('/api/guide/improve', {
      method:'POST', headers:{'Content-Type':'application/json'},
      body: JSON.stringify({season:state.season, week:state.week, entry_id:state.entryId, write_log:true})
    });
    if(!data) return;
    const box = document.getElementById('improve');
    const sugs = data.suggestions||[];
    if(!sugs.length){
      box.innerHTML = '<p class="empty">No justified revisions right now (no injury/role/usage/residual triggers).</p>';
      return;
    }
    box.innerHTML = sugs.map(s =>
      '<div class="sug"><strong>'+(s.player_name||s.gsis_id)+'</strong> · '+(s.prop||'—') +
      ' <span class="badge model">'+ (s.label||'MODEL') +'</span>' +
      '<div>'+(s.what_to_change||'')+'</div>' +
      '<div class="empty">why: '+(s.why||'')+'</div>' +
      '<div>expected lift: <strong>'+ (s.expected_lift!=null? Number(s.expected_lift).toFixed(2):'—') +'</strong></div></div>'
    ).join('');
  }
  document.getElementById('btn-reload').onclick = () => { state.page=0; loadGames(); loadChallenge(); };
  document.getElementById('btn-improve').onclick = loadImprove;
  document.getElementById('prev-page').onclick = () => { state.page=Math.max(0,state.page-1); loadChallenge(); };
  document.getElementById('next-page').onclick = () => { state.page+=1; loadChallenge(); };
  ['season','week','entry_id','locked_only'].forEach(id => {
    document.getElementById(id).onchange = () => { state.page=0; loadChallenge(); };
  });
  loadGames();
  loadChallenge();
})();
</script>
</body></html>
"""

def _pick_port(preferred: int | None = None) -> int:
    """Prefer config.PORT; fall back to nearby free ports on this box only."""
    return pick_port(preferred if preferred is not None else PORT)


def _list_prediction_weeks() -> list[tuple[int, int]]:
    return entrylib.list_pred_weeks()


def _default_season_week() -> tuple[int, int]:
    return entrylib.default_season_week()


def _load_pred(season: int, week: int):
    stem = f"season{season}_week{week}"
    pq = PRED_DIR / f"{stem}.parquet"
    js = PRED_DIR / f"{stem}.json"
    if not pq.is_file():
        return None, None
    df = pd.read_parquet(pq)
    meta = json.loads(js.read_text(encoding="utf-8")) if js.is_file() else {}
    return df, meta


def _board_teams(df: pd.DataFrame) -> list[dict]:
    logos = load_team_logos()
    teams = []
    for abbr, g in df.groupby("team", sort=True):
        abbr = str(abbr).upper()
        logo = (logos.get(abbr) or {}).get("logo_url") or ""
        opponent = str(g["opponent"].iloc[0]) if "opponent" in g.columns else ""
        players_by_role: dict[str, list] = {"starter": [], "rotation": [], "bench_warmer": []}
        for gsis, pg in g.groupby("gsis_id", sort=False):
            role = str(pg["role_bucket"].iloc[0])
            props = []
            for _, row in pg.iterrows():
                props.append({
                    "prop": row["prop"],
                    "actuals_n": int(row["actuals_n"]) if pd.notna(row.get("actuals_n")) else 0,
                    "actuals_mean": float(row["actuals_mean"]) if pd.notna(row.get("actuals_mean")) else None,
                    "espn_projection": float(row["espn_projection"]) if pd.notna(row.get("espn_projection")) else None,
                    "vegas_line": float(row["vegas_line"]) if pd.notna(row.get("vegas_line")) else None,
                    "ours_mean": float(row["ours_mean"]),
                    "ours_sd": float(row["ours_sd"]),
                    "flags": row.get("flags") or "",
                })
            photo = pg["photo_url"].iloc[0] if "photo_url" in pg.columns else None
            jersey = pg["jersey_number"].iloc[0] if "jersey_number" in pg.columns else None
            player = {
                "gsis_id": gsis,
                "player_name": pg["player_name"].iloc[0],
                "position": pg["position"].iloc[0],
                "role_bucket": role,
                "depth_order": pg["depth_order"].iloc[0] if "depth_order" in pg.columns else None,
                "jersey_number": None if pd.isna(jersey) else jersey,
                "photo_url": None if (photo is None or (isinstance(photo, float) and pd.isna(photo))) else photo,
                "props": props,
            }
            players_by_role.setdefault(role, []).append(player)
        teams.append({
            "abbr": abbr, "logo": logo, "opponent": opponent,
            "player_count": int(g["gsis_id"].nunique()),
            "players_by_role": players_by_role,
        })
    return teams


@app.errorhandler(Exception)
def _handle_err(e):
    # Never crash the UI process silently — return JSON for API, HTML for pages
    traceback.print_exc()
    from markupsafe import escape
    if request.path.startswith("/api/"):
        return jsonify({"error": str(e)}), 500
    msg = escape(str(e))
    return (
        "<!doctype html><html><body style='background:#0f1419;color:#f0b0b0;font-family:system-ui;padding:24px'>"
        f"<h1>Error</h1><p>{msg}</p>"
        "<p class='access-banner' style='max-width:640px'>Flask UI running on your local machine. "
        "For a browser-only version, visit <a href='https://traplandlord.github.io/nfl-props-stats/' target='_blank'>the web app</a>.</p>"
        "<p><a href='/' style='color:#3d8bfd'>Home</a></p></body></html>",
        500,
    )


@app.get("/")
def index():
    q = (request.args.get("q") or "").strip()
    if not q:
        return render_template_string(PAGE, q="", matches=None, profile=None, active="search")
    matches = search_players(q, limit=12)
    if not matches:
        return render_template_string(PAGE, q=q, matches=[], profile=None, active="search")
    if len(matches) == 1 or (
        matches[0].get("match_score", 0) >= 0.9
        and (len(matches) == 1 or matches[0]["match_score"] - matches[1]["match_score"] >= 0.05)
    ):
        return redirect(url_for("player", gsis_id=matches[0]["gsis_id"]))
    return render_template_string(PAGE, q=q, matches=matches, profile=None, active="search")


@app.get("/player/<gsis_id>")
def player(gsis_id: str):
    profile = full_profile(gsis_id)
    q = request.args.get("q") or (profile["display_name"] if profile else "")
    return render_template_string(PAGE, q=q, matches=None, profile=profile, active="search")


@app.get("/weekly")
def weekly():
    ds, dw = _default_season_week()
    season = int(request.args.get("season") or ds)
    week = int(request.args.get("week") or dw)
    focus_team = (request.args.get("team") or "").upper() or None
    available = _list_prediction_weeks()
    seasons = sorted({s for s, _ in available} | {season, ds})
    weeks = sorted({w for s, w in available if s == season} | {week, dw} | set(range(1, 19)))
    df, meta = _load_pred(season, week)
    teams = _board_teams(df) if df is not None and not df.empty else []
    return render_template_string(
        WEEKLY_PAGE, active="weekly", season=season, week=week,
        seasons=seasons, weeks=weeks, meta=meta, teams=teams, focus_team=focus_team,
    )


def _entry_context():
    ds, dw = _default_season_week()
    season = int(request.args.get("season") or session.get("entry_season") or ds)
    week = int(request.args.get("week") or session.get("entry_week") or dw)
    n = int(request.args.get("n") or session.get("entry_n") or 4)
    n = max(2, min(6, n))
    session["entry_season"] = season
    session["entry_week"] = week
    session["entry_n"] = n
    available = _list_prediction_weeks()
    seasons = sorted({s for s, _ in available} | {season, ds})
    weeks = sorted({w for s, w in available if s == season} | {week, dw} | set(range(1, 19)))
    card = None
    eid = session.get("entry_id")
    if eid:
        card = entrylib.load_entry(eid)
    if card is None:
        card = entrylib.load_entry(None)
    players = (card or {}).get("players") or []
    entry_id = (card or {}).get("entry_id")
    return season, week, n, seasons, weeks, players, entry_id


@app.get("/entry")
def entry():
    season, week, n, seasons, weeks, players, entry_id = _entry_context()
    preadd = request.args.get("add")
    return render_template_string(
        ENTRY_PAGE,
        active="entry",
        season=season,
        week=week,
        n=n,
        seasons=seasons,
        weeks=weeks,
        players_json=json.dumps(players),
        entry_id_json=json.dumps(entry_id),
        preadd=preadd,
    )


@app.get("/api/entry/search")
def api_entry_search():
    season = int(request.args.get("season") or 2026)
    week = int(request.args.get("week") or 3)
    q = (request.args.get("q") or "").strip()
    results = entrylib.search_candidates(season, week, q, limit=entrylib.MAX_SEARCH)
    return jsonify({"results": results})


@app.get("/api/entry/player")
def api_entry_player():
    season = int(request.args.get("season") or 2026)
    week = int(request.args.get("week") or 3)
    gsis = request.args.get("gsis_id") or ""
    pool = entrylib.candidate_pool(season, week)
    hit = pool[pool["gsis_id"].astype(str) == str(gsis)]
    if hit.empty:
        return jsonify({"error": "player not in week pool (run predict_week.py)"}), 404
    return jsonify({"player": entrylib.enrich_player(hit.iloc[0], season, week)})


@app.get("/api/entry/teams")
def api_entry_teams():
    season = int(request.args.get("season") or 2026)
    week = int(request.args.get("week") or 3)
    page = int(request.args.get("page") or 0)
    return jsonify(entrylib.paginate_teams(season, week, page=page))


@app.post("/api/entry/randomize")
def api_entry_randomize():
    body = request.get_json(force=True, silent=True) or {}
    season = int(body.get("season") or 2026)
    week = int(body.get("week") or 3)
    n = max(2, min(6, int(body.get("n") or 4)))
    # League-wide sample — no same-team filter
    players = entrylib.randomize_entry(season, week, n)
    card = entrylib.build_card(players, season, week, n, entry_id=session.get("entry_id"))
    path = entrylib.save_entry(card)
    session["entry_id"] = card["entry_id"]
    session["entry_season"] = season
    session["entry_week"] = week
    session["entry_n"] = n
    teams = sorted({p.get("team") for p in players})
    return jsonify({
        "players": players,
        "entry_id": card["entry_id"],
        "path": str(path.relative_to(ROOT)),
        "teams_on_card": teams,
        "note": "PrizePicks-style mix — same team not required",
    })


@app.post("/api/entry/save")
def api_entry_save():
    body = request.get_json(force=True, silent=True) or {}
    season = int(body.get("season") or 2026)
    week = int(body.get("week") or 3)
    n = max(2, min(6, int(body.get("n") or 4)))
    players = body.get("players") or []
    # harden: cap length, require real gsis from pool
    pool = entrylib.candidate_pool(season, week)
    by_id = {str(r["gsis_id"]): r for _, r in pool.iterrows()}
    clean = []
    for pl in players[:n]:
        gid = str(pl.get("gsis_id") or "")
        if gid in by_id:
            clean.append(entrylib.enrich_player(by_id[gid], season, week))
    card = entrylib.build_card(clean, season, week, n, entry_id=body.get("entry_id") or session.get("entry_id"))
    path = entrylib.save_entry(card)
    session["entry_id"] = card["entry_id"]
    return jsonify({"entry_id": card["entry_id"], "path": str(path.relative_to(ROOT)), "n": len(clean)})



@app.get("/guide")
def guide():
    ds, dw = _default_season_week()
    season = int(request.args.get("season") or ds)
    week = int(request.args.get("week") or dw)
    entry_id = request.args.get("entry_id") or None
    available = _list_prediction_weeks()
    seasons = sorted({s for s, _ in available} | {season, ds})
    weeks = sorted({w for s, w in available if s == season} | {week, dw} | set(range(1, 19)))
    entries = guidelib.list_entries(limit=30)
    return render_template_string(
        GUIDE_PAGE,
        active="guide",
        season=season,
        week=week,
        seasons=seasons,
        weeks=weeks,
        entries=entries,
        entry_id=entry_id,
        entry_id_json=json.dumps(entry_id),
    )


@app.get("/api/guide/active")
def api_guide_active():
    hours = int(request.args.get("upcoming_hours") or 72)
    as_of = request.args.get("as_of_date") or None
    try:
        snap = active_games.list_all_sports_snapshot(
            include_upcoming_hours=hours, as_of_date=as_of
        )
        return jsonify(snap)
    except Exception as e:
        return jsonify({"error": str(e), "sports": []}), 500


@app.get("/api/guide/challenge")
def api_guide_challenge():
    try:
        season = int(request.args.get("season") or 2026)
        week = int(request.args.get("week") or 3)
        entry_id = request.args.get("entry_id") or None
        page = int(request.args.get("page") or 0)
        locked_only = request.args.get("locked_only") in ("1", "true", "yes")
        data = guidelib.build_challenge(
            season, week, entry_id, page=page, page_size=12, locked_only=locked_only
        )
        return jsonify(data)
    except Exception as e:
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500


@app.post("/api/guide/improve")
def api_guide_improve():
    try:
        body = request.get_json(force=True, silent=True) or {}
        season = int(body.get("season") or 2026)
        week = int(body.get("week") or 3)
        entry_id = body.get("entry_id") or None
        write_log = bool(body.get("write_log", True))
        limit = max(1, min(40, int(body.get("limit") or 20)))
        out = guideimprove.propose_improvements(
            season, week, entry_id, write_log=write_log, limit=limit
        )
        return jsonify(out)
    except Exception as e:
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500


@app.get("/api/guide/log")
def api_guide_log():
    limit = max(1, min(200, int(request.args.get("limit") or 50)))
    return jsonify({"entries": guideimprove.read_log(limit=limit)})


def main() -> None:
    host = HOST
    port = _pick_port(PORT)
    print(access_message(host, port))
    if port != PORT:
        print(f"NOTE: preferred port {PORT} busy; using {port} on your local machine.")
    print(f"UI: http://{host}:{port}/")
    print(f"Weekly: http://{host}:{port}/weekly")
    print(f"Build my card: http://{host}:{port}/entry")
    print(f"Guide: http://{host}:{port}/guide")
    print("Health: ./.venv/bin/python scripts/ui_healthcheck.py --port", port)
    print("Ctrl+C to stop.")
    app.run(host=host, port=port, debug=False, use_reloader=False)


if __name__ == "__main__":
    main()
