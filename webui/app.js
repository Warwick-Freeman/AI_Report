/* The report review front end.
 *
 * One screen at a time, in the order a reader works through a report: analyse,
 * review each SCORE section, clear what is outstanding, then generate.
 *
 * The design's central idea is carried through everywhere: every value shows
 * where it came from. A measured number, a model's guess, a human's judgement
 * and an unanswered question look different, because a reader deciding whether
 * to accept a value needs to know which it is. The marks come from the server,
 * which declares them per field from what the analysis actually did.
 */
'use strict';

var RAIL = [
  { id: 'home', num: '01', label: 'Report home' },
  { id: 'analysis', num: '02', label: 'Analyses' },
  { id: 'recording', num: '03', label: 'Patient & recording' },
  { id: 'pdr', num: '04', label: 'Posterior dominant rhythm' },
  { id: 'interictal', num: '05', label: 'Interictal findings' },
  { id: 'episodes', num: '06', label: 'Episodes' },
  { id: 'sleep', num: '07', label: 'Sleep & drowsiness' },
  { id: 'artifacts', num: '08', label: 'Artifacts' },
  { id: 'events', num: '09', label: 'Events' },
  { id: 'conclusion', num: '10', label: 'Significance & conclusion' },
  { id: 'outstanding', num: '11', label: 'Outstanding items' },
  { id: 'generate', num: '12', label: 'Generate' },
  { id: 'settings', num: '13', label: 'Settings' }
];

// What this page needs from the API. The server reports its own; a lower number
// means the server is running code older than this file.
var API_EXPECTED = 2;

var PROV_LABEL = {
  measured: 'Measured',
  model: 'Model \u2014 unverified',
  human: 'Human-scored',
  none: 'Not scored'
};

var S = {
  route: 'home',
  session: null,
  status: 'idle',
  report: null,
  outstanding: [],
  log: '',
  theme: localStorage.getItem('theme') || 'dark',
  study: '',
  options: {},
  defaults: {},
  llm: null,
  stale: false,
  pdf: null,
  data: null,
  error: null,
  polling: null,
  busy: false
};

/* ------------------------------------------------------------------ helpers */

function esc(v) {
  if (v === null || v === undefined) return '';
  return String(v).replace(/[&<>"']/g, function (c) {
    return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
  });
}

function api(path, method, body) {
  return fetch(path, {
    method: method || 'GET',
    headers: body ? { 'Content-Type': 'application/json' } : undefined,
    body: body ? JSON.stringify(body) : undefined
  }).then(function (r) {
    return r.json().then(function (j) {
      if (!r.ok) throw new Error(j.error || ('HTTP ' + r.status));
      return j;
    });
  });
}

function prov(kind, extra) {
  var k = kind || 'none';
  return '<span class="prov" data-kind="' + esc(k) + '"><i></i><span>' +
    esc(extra || PROV_LABEL[k] || k) + '</span></span>';
}

function seconds(v) {
  if (v === null || v === undefined) return '';
  var s = Math.round(v);
  var h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60);
  if (h) return h + ':' + String(m).padStart(2, '0') + ':' + String(s % 60).padStart(2, '0');
  return m + ':' + String(s % 60).padStart(2, '0');
}

function section(id) {
  if (!S.report) return null;
  var found = S.report.sections.filter(function (s) { return s.id === id; });
  return found.length ? found[0] : null;
}

function go(route) {
  S.route = route;
  writeHash();
  render();
}

/* The session and the current screen live in the URL.
 *
 * An analysis takes minutes and lives in the server, not the page, so a reload
 * must not throw it away - and a reader who reloads mid-review would otherwise
 * be sent back to an empty Report home with no way back to their own findings.
 */
function writeHash() {
  var parts = [];
  if (S.session) parts.push('session=' + S.session);
  else if (S.study) parts.push('study=' + encodeURIComponent(S.study));
  if (S.route && S.route !== 'home') parts.push('route=' + S.route);
  if (S.theme !== 'dark') parts.push('theme=' + S.theme);
  var hash = parts.length ? '#' + parts.join('&') : '';
  if (location.hash !== hash) {
    history.replaceState(null, '', location.pathname + hash);
  }
}

function readHash() {
  var out = {};
  (location.hash || '').replace(/^#/, '').split('&').forEach(function (pair) {
    var bits = pair.split('=');
    if (bits[0]) out[bits[0]] = decodeURIComponent(bits[1] || '');
  });
  return out;
}

/* -------------------------------------------------------------------- chrome */

function renderStudyBar() {
  var el = document.getElementById('studybar');
  var name = (S.report && S.report.study && S.report.study.name) ||
    (S.study ? S.study.replace(/[\\/]+$/, '').split(/[\\/]/).pop() : '\u2014');
  var facts = [];
  var rec = section('recording');
  if (rec) {
    rec.rows.forEach(function (r) {
      if (['patient_sex', 'patient_age_at_recording', 'conditions_date_and_time',
        'conditions_acquisition_sample_rate'].indexOf(r.id) >= 0) {
        facts.push({ k: r.label, v: r.value });
      }
    });
    if (rec.duration_lines && rec.duration_lines.length) {
      facts.push({ k: 'Analysed', v: rec.duration_lines[0].replace(/^[^:]*:\s*/, '') });
    }
  }
  var html = '<div class="fact" style="margin-right:6px">' +
    '<span class="eyebrow">SCORE report</span><h2>' + esc(name) + '</h2></div>';
  facts.slice(0, 5).forEach(function (f) {
    // A header fact is a glance, not a paragraph. Some of these values are a
    // full explanation - the missing-age one runs to a sentence about the
    // exporter's placeholder date - and left whole it pushes the rest of the
    // header off the row. The full text stays available on hover, and in full
    // on the Patient & recording screen.
    var value = String(f.v === null || f.v === undefined ? '' : f.v);
    var shown = value.length > 44 ? value.slice(0, 43).replace(/[\s,;:.]+$/, '') + '…' : value;
    html += '<div class="fact" title="' + esc(value) + '"><span class="fact-k">' +
      esc(f.k) + '</span><span class="fact-v">' + esc(shown) + '</span></div>';
  });
  html += '<div class="spacer"></div><div class="head-actions">' +
    '<button class="mini" id="themeBtn">' +
    (S.theme === 'dark' ? 'Light theme' : 'Dark theme') + '</button></div>';
  el.innerHTML = html;
  document.getElementById('themeBtn').onclick = function () {
    S.theme = S.theme === 'dark' ? 'light' : 'dark';
    localStorage.setItem('theme', S.theme);
    writeHash();
    render();
  };
}

function renderRail() {
  var el = document.getElementById('rail');
  var html = '';
  RAIL.forEach(function (r) {
    var sec = section(r.id);
    var badge = '';
    var excluded = false;
    if (sec) {
      excluded = sec.included === false;
      if (excluded) badge = 'Off';
      else if (sec.outstanding && sec.outstanding.length) badge = String(sec.outstanding.length);
      else if (sec.state === 'not-analysed') badge = '\u2014';
    }
    if (r.id === 'outstanding' && S.outstanding.length) badge = String(S.outstanding.length);
    if (r.id === 'analysis' && S.status === 'running') badge = '\u2026';
    html += '<button data-route="' + r.id + '"' +
      (S.route === r.id ? ' aria-current="true"' : '') +
      (excluded ? ' data-excluded="true"' : '') + '>' +
      '<span class="num">' + r.num + '</span>' +
      '<span class="label">' + esc(r.label) + '</span>' +
      '<span class="badge">' + esc(badge) + '</span></button>';
  });
  el.innerHTML = html;
  Array.prototype.forEach.call(el.querySelectorAll('button'), function (b) {
    b.onclick = function () { go(b.getAttribute('data-route')); };
  });
}

function renderStatusBar() {
  var el = document.getElementById('statusbar');
  var text = {
    idle: 'No analysis run yet',
    running: 'Analysing \u2014 this takes a few minutes',
    generating: 'Writing the document',
    ready: 'Analysis complete',
    failed: 'Analysis failed'
  }[S.status] || S.status;
  var html = '<span class="dot" data-status="' + esc(S.status) + '"></span><span>' +
    esc(text) + '</span>';
  if (S.study) html += '<span>&middot;</span><span>' + esc(S.study) + '</span>';
  if (S.outstanding.length) {
    html += '<span>&middot;</span><span>' + S.outstanding.length +
      ' item(s) outstanding</span>';
  }
  html += '<div class="spacer"></div>';
  if (S.report) {
    html += '<span>' + prov('measured') + '&nbsp;&nbsp;' + prov('model') +
      '&nbsp;&nbsp;' + prov('human') + '&nbsp;&nbsp;' + prov('none') + '</span>';
  }
  el.innerHTML = html;
}

/* -------------------------------------------------------------------- screens */

function headHtml(title, job, actions) {
  return '<div class="head"><div style="flex:1;min-width:180px">' +
    '<h1>' + esc(title) + '</h1>' +
    (job ? '<p class="job">' + esc(job) + '</p>' : '') +
    '</div><div class="head-actions">' + (actions || '') + '</div></div>';
}

function renderHome() {
  var d = S.defaults;
  var o = S.options;
  function checkbox(key, label, hint, disabledReason) {
    return '<label class="check"><input type="checkbox" data-opt="' + key + '"' +
      (o[key] && !disabledReason ? ' checked' : '') +
      (disabledReason ? ' disabled aria-disabled="true"' : '') + '><span' +
      (disabledReason ? ' style="color:var(--p-text-disabled)"' : '') + '>' +
      esc(label) +
      (hint ? '<span class="basis">' + esc(hint) + '</span>' : '') +
      (disabledReason ? '<span class="basis">' + esc(disabledReason) + '</span>' : '') +
      '</span></label>';
  }

  // The narrative is the one option that needs something outside this machine.
  // It is disabled with the reason rather than left tickable and failing, and
  // when it is available it names the provider that will answer - the front end
  // has no picker, so the choice is worth stating.
  var aiHint = 'Adds a drafted summary. Offered as a draft and never as a ' +
    'scored value.';
  var aiDisabled = null;
  if (S.llm) {
    var providers = S.llm.available || [];
    if (providers.length) {
      aiHint = 'Adds a drafted summary, using ' + providers[0].model + ' (' +
        providers[0].provider + '). Offered as a draft and never as a scored value.';
    } else {
      aiDisabled = 'No language-model key in config.env. Set one of ' +
        (S.llm.wanted || []).join(', ') +
        '. Everything else in the report is produced without a provider.';
    }
  }
  // S.llm null means the server did not say. Left selectable: the server will
  // refuse the request with a reason if it cannot honour it.
  var html = headHtml('Report home',
    'Start a new report for a study. The analysis runs once; everything after ' +
    'that is review.');

  if (S.stale) {
    html += emptyHtml('failed', 'Server out of date',
      'The report server is running older code than this page.',
      'The page was reloaded from disk but the server process was not ' +
      'restarted, so some options here may not work and may be shown ' +
      'incorrectly. Close the report server window and start it again.');
  }
  if (S.error) {
    html += emptyHtml('failed', 'Could not start', 'The analysis did not start.',
                      S.error);
  }

  html += '<div class="panel"><h3 class="sub">Study</h3>' +
    '<div class="grid"><label class="field" style="flex:1;min-width:340px">' +
    '<span>Study folder or EEG file</span>' +
    '<input type="text" id="studyPath" value="' + esc(S.study) + '" ' +
    'placeholder="C:\\Studies\\Patient.eeg  or  sample_data\\01RT.edf"></label>' +
    '<label class="field"><span>Output folder</span>' +
    '<input type="text" data-opt="dest_pdfPath" value="' + esc(o.dest_pdfPath || './reports') + '"></label>' +
    '</div></div>';

  html += '<div class="panel"><h3 class="sub">Analyses to run</h3><div class="grid">' +
    '<div style="min-width:320px;flex:1">' +
    checkbox('stageSleep', 'Sleep staging and graphoelements',
      'U-Sleep or YASA. A model, and marked as one throughout.') +
    checkbox('autoEyeState', 'Infer eye state from the signal',
      'Enables PDR reactivity scoring where the recording has no eye-state ' +
      'annotations, at the risk of a false reduced-reactivity finding.') +
    checkbox('useRepair', 'Repair bad channels') +
    '</div><div style="min-width:320px;flex:1">' +
    checkbox('aiReport', 'Draft the narrative with a language model',
      aiHint, aiDisabled) +
    '<label class="field" style="margin-top:8px"><span>Sleep backend</span>' +
    '<select data-opt="sleepBackend">' +
    ['usleep', 'yasa'].map(function (b) {
      return '<option value="' + b + '"' + (o.sleepBackend === b ? ' selected' : '') +
        '>' + b + '</option>';
    }).join('') + '</select></label>' +
    '<label class="field" style="margin-top:8px"><span>Patient date of birth (for age-normed PDR)</span>' +
    '<input type="text" data-opt="patientDob" placeholder="YYYY-MM-DD" value="' +
    esc(o.patientDob || '') + '"></label>' +
    '</div></div></div>';

  html += '<div class="head-actions" style="margin-top:4px">' +
    '<button class="btn" data-primary id="runBtn"' + (S.status === 'running' ? ' disabled' : '') +
    '>' + (S.status === 'running' ? 'Running\u2026' : 'Run analyses') + '</button>' +
    (S.status === 'ready' ? '<button class="btn" id="reviewBtn">Go to review</button>' : '') +
    '</div>';

  document.getElementById('main').innerHTML = html;

  var main = document.getElementById('main');
  Array.prototype.forEach.call(main.querySelectorAll('[data-opt]'), function (input) {
    input.onchange = function () {
      var key = input.getAttribute('data-opt');
      S.options[key] = input.type === 'checkbox' ? input.checked : input.value;
    };
  });
  document.getElementById('studyPath').onchange = function (e) {
    S.study = e.target.value.trim();
    writeHash();
  };
  document.getElementById('runBtn').onclick = startAnalysis;
  var review = document.getElementById('reviewBtn');
  if (review) review.onclick = function () { go('recording'); };
}

function renderAnalysis() {
  var actions = S.status === 'ready'
    ? '<button class="btn" id="againBtn">Run again</button>'
    : '';
  var html = headHtml('Analyses',
    'Show which analyses have results and run the ones that do not.', actions);

  if (S.status === 'idle') {
    html += emptyHtml('not-analysed', 'Not analysed',
      'Nothing has been analysed yet.',
      'Choose a study on Report home and run the analyses.');
  } else {
    var rows = [
      ['Recording and duration accounting', 'recording'],
      ['Posterior dominant rhythm', 'pdr'],
      ['Interictal findings', 'interictal'],
      ['Spike and seizure detections', 'episodes'],
      ['Sleep staging', 'sleep'],
      ['Artifacts', 'artifacts'],
      ['Study events', 'events']
    ];
    html += '<table><thead><tr><th scope="col">Analysis</th><th scope="col">Result</th>' +
      '<th scope="col" class="nowrap">Provenance</th></tr></thead><tbody>';
    rows.forEach(function (r) {
      var sec = section(r[1]);
      var state = sec ? sec.state : (S.status === 'running' ? 'running' : 'not-analysed');
      var count = sec ? ((sec.findings || []).length + (sec.rows || []).length +
        (sec.events || []).length) : 0;
      var result = {
        'populated': count + ' item(s)',
        'no-findings': 'No findings',
        'not-analysed': 'Not analysed',
        'running': 'Running\u2026'
      }[state] || state;
      var kind = state === 'not-analysed' ? 'none'
        : (r[1] === 'sleep' || r[1] === 'episodes') ? 'model'
          : r[1] === 'events' ? 'human' : 'measured';
      html += '<tr><td>' + esc(r[0]) + '</td><td class="value">' + esc(result) +
        '</td><td>' + prov(kind) + '</td></tr>';
    });
    html += '</tbody></table>';
  }

  if (S.error) {
    html += emptyHtml('failed', 'Error', 'The analysis reported a problem.',
                      S.error);
  }
  html += '<h3 class="sub">Analysis log</h3><pre class="log" id="logBox">' +
    esc(S.log || '(nothing yet)') + '</pre>';

  document.getElementById('main').innerHTML = html;
  var box = document.getElementById('logBox');
  if (box) box.scrollTop = box.scrollHeight;
  var again = document.getElementById('againBtn');
  if (again) again.onclick = startAnalysis;
}

function emptyHtml(kind, label, title, why, actionLabel, actionId) {
  return '<div class="empty" data-kind="' + esc(kind) + '">' +
    '<span class="kind">' + esc(label) + '</span>' +
    '<span class="title">' + esc(title) + '</span>' +
    '<span class="why">' + esc(why) + '</span>' +
    (actionLabel ? '<div class="head-actions" style="margin-top:4px">' +
      '<button class="btn" id="' + esc(actionId || 'emptyAction') + '">' +
      esc(actionLabel) + '</button></div>' : '') +
    '</div>';
}

function sectionEmpty(sec) {
  if (sec.state === 'not-analysed') {
    return emptyHtml('not-analysed', 'Not analysed',
      'This section has not been analysed.',
      'No analysis has been run for ' + sec.label.toLowerCase() +
      '. This is not the same as an analysis that found nothing.',
      'Run analyses', 'runFromSection');
  }
  if (sec.state === 'no-findings') {
    var rec = section('recording');
    var over = (rec && rec.duration_lines && rec.duration_lines.length)
      ? ' over ' + rec.duration_lines[0].replace(/^[^:]*:\s*/, '') : '';
    return emptyHtml('no-findings', 'Analysed \u2014 no findings',
      'Analysed. No findings of this class were detected.',
      'The analysis completed' + over + ' and returned no findings. This is a ' +
      'clinical result and will be reported as such.');
  }
  if (sec.included === false) {
    return emptyHtml('excluded', 'Excluded by author',
      'This section is excluded from the report.',
      'Results are retained and stay in the structured SCORE data, but the ' +
      'section will not appear in the document.');
  }
  return '';
}

function rowsTable(sec) {
  if (!sec.rows || !sec.rows.length) return '';
  var html = '<table><thead><tr><th scope="col">Property</th><th scope="col">Scored value</th>' +
    '<th scope="col" class="nowrap">Provenance</th>' +
    '<th scope="col" class="nowrap">Override</th>' +
    '</tr></thead><tbody>';
  sec.rows.forEach(function (r) {
    html += '<tr><td>' + esc(r.label) + '</td>' +
      '<td class="value">' + esc(r.value) +
      (r.provisional ? '<span class="tag-provisional">Provisional</span>' : '') +
      (r.basis ? '<span class="basis">' + esc(r.basis) + '</span>' : '') + '</td>' +
      '<td>' + prov(r.provenance) +
      (r.confidence ? '<span class="basis">confidence: ' + esc(r.confidence) + '</span>' : '') +
      '</td><td class="nowrap">' +
      (r.editable
        ? '<input type="text" data-row="' + esc(r.id) + '" data-section="' + esc(sec.id) +
        '" value="' + esc(r.override || '') + '" placeholder="accept or type" style="min-width:150px">'
        : '<span class="basis">read from the study</span>') +
      '</td></tr>';
  });
  return html + '</tbody></table>';
}

function findingsTable(sec) {
  if (!sec.findings || !sec.findings.length) return '';
  var isEpisode = sec.id === 'episodes';
  var html = '<table><thead><tr><th scope="col" style="width:24px"><span class="sr-only">Include</span></th><th scope="col">' +
    (isEpisode ? 'Episode' : 'Graphoelement') + '</th><th scope="col">Location</th><th scope="col">' +
    (isEpisode ? 'Onset / duration' : 'Prevalence') + '</th>' +
    '<th scope="col" class="nowrap">Provenance</th></tr></thead><tbody>';
  sec.findings.forEach(function (f) {
    var timing = isEpisode
      ? (seconds(f.onset_seconds) + (f.duration_band ? ' \u00b7 ' + f.duration_band : ''))
      : (f.prevalence + (f.count ? ' (' + f.count + ')' : ''));
    html += '<tr><td><input type="checkbox" data-finding="' + esc(f.id) +
      '" data-section="' + esc(sec.id) + '"' + (f.included !== false ? ' checked' : '') +
      ' title="include in the report" style="width:auto"></td>' +
      '<td class="value">' + esc(f.name) +
      (f.mode ? '<span class="basis">' + esc(f.mode) + '</span>' : '') + '</td>' +
      '<td>' + esc(f.location) + '</td>' +
      '<td>' + esc(timing) +
      (f.basis ? '<span class="basis">' + esc(f.basis) + '</span>' : '') +
      (f.timing_basis ? '<span class="basis">' + esc(f.timing_basis) + '</span>' : '') +
      '</td><td>' + prov(f.provenance) +
      (f.confidence ? '<span class="basis">confidence: ' + esc(f.confidence) + '</span>' : '') +
      '</td></tr>';
    if (sec.id === 'artifacts' && sec.significance_options) {
      // SCORE wants the significance of an artifact judged, not measured. The
      // coverage above is the measurement; whether it ruined the recording is
      // a judgement about what could still be read.
      html += '<tr><td></td><td colspan="4">' +
        '<span class="basis" style="margin:0 0 4px">Significance ' +
        '\u2014 human judgement</span><div class="head-actions">';
      sec.significance_options.forEach(function (option) {
        html += '<button class="mini" data-artifact-significance="' + esc(option) +
          '" data-target="' + esc(f.id) + '" aria-pressed="' +
          (f.significance === option ? 'true' : 'false') + '">' +
          esc(option) + '</button>';
      });
      html += '</div></td></tr>';
    }
    if (isEpisode && f.reader_fields) {
      html += '<tr><td></td><td colspan="4"><span class="basis">' +
        'For the reader, from the video and the clinical record: ' +
        esc(f.reader_fields.join('; ')) + '. An episode detected ' +
        'electrographically is not by itself an epileptic seizure.</span></td></tr>';
    }
  });
  return html + '</tbody></table>';
}

function eventsTable(sec) {
  if (!sec.events || !sec.events.length) return '';
  var html = '<p class="job">Every one of these is a human annotation or a ' +
    'system marker, so each is offered as context and none as a finding.</p>' +
    '<table><thead><tr><th style="width:24px"></th><th scope="col">Type</th><th scope="col">Time</th>' +
    '<th scope="col">Duration</th><th scope="col">Text</th><th scope="col">Channels</th></tr></thead><tbody>';
  sec.events.slice(0, 200).forEach(function (e) {
    html += '<tr><td><input type="checkbox" data-event="' + esc(e.id) +
      '" data-section="events"' + (e.included ? ' checked' : '') +
      ' style="width:auto"></td>' +
      '<td>' + esc(e.type) + '</td><td class="nowrap">' + esc(seconds(e.seconds)) +
      '</td><td class="nowrap">' + esc(e.duration_seconds ? seconds(e.duration_seconds) : '') +
      '</td><td>' + esc(e.text) + '</td><td>' + esc((e.channels || []).join(', ')) +
      '</td></tr>';
  });
  return html + '</tbody></table>';
}

function notesHtml(sec) {
  if (!sec.notes || !sec.notes.length) return '';
  var html = '<h3 class="sub">What the analysis decided not to report</h3>';
  sec.notes.forEach(function (n) { html += '<div class="note">' + esc(n) + '</div>'; });
  return html;
}

function renderSection(id) {
  var sec = section(id);
  var spec = RAIL.filter(function (r) { return r.id === id; })[0];
  if (!sec) {
    document.getElementById('main').innerHTML =
      headHtml(spec ? spec.label : id, '') +
      emptyHtml('not-analysed', 'Not analysed',
        'This section has not been analysed.',
        'Run the analyses from Report home first.', 'Run analyses', 'runFromSection');
    wireEmpty();
    return;
  }

  var actions = '<label class="check"><input type="checkbox" id="includeBox"' +
    (sec.included !== false ? ' checked' : '') + '><span>Include in report</span></label>';
  var html = headHtml(sec.label, sec.job, actions);

  var empty = sectionEmpty(sec);
  if (empty) {
    html += empty;
  } else {
    html += rowsTable(sec);
    html += findingsTable(sec);
    html += eventsTable(sec);
    if (id === 'conclusion') html += conclusionHtml(sec);
    if (id === 'recording' && sec.duration_lines && sec.duration_lines.length) {
      html += '<h3 class="sub">Duration accounting</h3>';
      sec.duration_lines.forEach(function (l) {
        html += '<div class="note">' + esc(l) + '</div>';
      });
    }
  }
  html += notesHtml(sec);

  document.getElementById('main').innerHTML = html;
  wireSection(sec);
  wireEmpty();
}

function conclusionHtml(sec) {
  var current = sec.rows.filter(function (r) { return r.id === 'significance'; })[0];
  var chosen = current && (current.override || current.value);

  var html = '<h3 class="sub">Diagnostic significance \u2014 forced choice</h3>' +
    '<p class="job">SCORE reserves this for the electroencephalographer. ' +
    'Nothing in the analysis writes it.</p><div class="head-actions">';
  (sec.categories || []).forEach(function (s) {
    html += '<button class="mini" data-significance="' + esc(s) + '" aria-pressed="' +
      (chosen === s ? 'true' : 'false') + '">' + esc(s) + '</button>';
  });
  html += '</div>';

  // The yield list, whole. What the analysis cannot argue is shown disabled
  // with the reason beside it rather than removed: a reader who cannot find
  // 'Epilepsy' has learnt nothing, one who sees why it is unavailable has.
  html += '<h3 class="sub">Diagnostic yield \u2014 SCORE list</h3>' +
    '<p class="job">Yields this analysis cannot support are shown with the ' +
    'reason, not hidden.</p>';
  var yieldRow = sec.rows.filter(function (r) { return r.id === 'yield'; })[0];
  var picked = (yieldRow && (yieldRow.override || yieldRow.value)) || '';
  html += '<table><caption class="sr-only">SCORE diagnostic yields</caption>' +
    '<thead><tr><th scope="col">Yield</th><th scope="col">Available</th>' +
    '<th scope="col">Why not</th></tr></thead><tbody>';
  (sec.yields || []).forEach(function (y) {
    html += '<tr><td class="value">' + esc(y.term) + '</td><td class="nowrap">' +
      (y.supportable
        ? '<button class="mini" data-yield="' + esc(y.term) + '" aria-pressed="' +
        (picked === y.term ? 'true' : 'false') + '">Select</button>'
        : '<button class="mini" disabled aria-disabled="true">Unavailable</button>') +
      '</td><td>' + (y.reason ? '<span class="basis" style="margin:0">' +
        esc(y.reason) + '</span>' : '') + '</td></tr>';
  });
  html += '</tbody></table>';
  html += '<h3 class="sub">Summary and clinical comments</h3>';
  if (sec.draft) {
    html += '<p class="job">' + prov('model') +
      ' &mdash; drafted by the language model. Edit it or replace it; it is not ' +
      'a scored value until you accept it.</p>';
  }
  html += '<textarea id="draftBox" placeholder="The reader\'s summary.">' +
    esc(sec.draft || '') + '</textarea>';
  return html;
}

function renderOutstanding() {
  var html = headHtml('Outstanding items',
    'One list of everything unanswered across all included sections.');
  if (!S.report) {
    html += emptyHtml('not-analysed', 'Not analysed', 'Nothing to list yet.',
      'Run the analyses first.', 'Run analyses', 'runFromSection');
  } else if (!S.outstanding.length) {
    html += emptyHtml('no-findings', 'Nothing outstanding',
      'Every scored item has a value.',
      'No section reports an unanswered or provisional item. The report can be generated.',
      'Go to Generate', 'toGenerate');
  } else {
    html += '<table><thead><tr><th scope="col">Section</th><th scope="col">Item</th><th scope="col">Why</th>' +
      '</tr></thead><tbody>';
    S.outstanding.forEach(function (o) {
      html += '<tr><td><a href="#" data-goto="' + esc(o.section) + '">' +
        esc(o.section_label) + '</a></td><td class="value">' + esc(o.label) +
        '</td><td><span class="basis" style="margin:0">' + esc(o.why) + '</span></td></tr>';
    });
    html += '</tbody></table>';
  }
  document.getElementById('main').innerHTML = html;
  var main = document.getElementById('main');
  Array.prototype.forEach.call(main.querySelectorAll('[data-goto]'), function (a) {
    a.onclick = function (e) { e.preventDefault(); go(a.getAttribute('data-goto')); };
  });
  var toGen = document.getElementById('toGenerate');
  if (toGen) toGen.onclick = function () { go('generate'); };
  wireEmpty();
}

function renderGenerate() {
  var ready = S.status === 'ready';
  var actions = ready
    ? '<button class="btn" data-primary id="genBtn"' + (S.busy ? ' disabled' : '') + '>' +
    (S.busy ? 'Writing\u2026' : 'Generate report') + '</button>'
    : '';
  var html = headHtml('Generate',
    'Produce the report document from the analysis as you have left it.', actions);

  if (!ready) {
    html += emptyHtml('not-analysed', 'Blocked',
      'There is no completed analysis to write.',
      S.status === 'running'
        ? 'The analysis is still running.'
        : 'Run the analyses from Report home first.',
      'Run analyses', 'runFromSection');
  } else {
    html += '<div class="panel"><h3 class="sub">Included sections</h3><ul class="plain">';
    S.report.sections.forEach(function (s) {
      html += '<li>' + esc(s.label) + ' \u2014 ' +
        (s.included === false ? 'excluded' : esc(s.state.replace('-', ' '))) + '</li>';
    });
    html += '</ul></div>';
    if (S.outstanding.length) {
      html += '<div class="note">' + S.outstanding.length + ' item(s) are still ' +
        'outstanding. The document can be written, and each will appear as ' +
        'not scored rather than as a negative finding.</div>';
    }
    if (S.error) {
      html += emptyHtml('failed', 'Not written',
        'The document was not written.', S.error);
    }
    if (S.pdf) {
      html += '<div class="panel sunk"><h3 class="sub">Written</h3>' +
        '<p style="margin:4px 0">' + esc(S.pdf) +
        '<span class="basis">the report document</span></p>' +
        (S.data ? '<p style="margin:4px 0">' + esc(S.data) +
          '<span class="basis">the same report as structured SCORE data, ' +
          'carrying the provenance of every value and your overrides</span></p>' : '') +
        '<div class="head-actions"><button class="btn" id="openBtn">' +
        'Open document</button></div></div>';
    }
  }
  html += '<h3 class="sub">Log</h3><pre class="log">' + esc(S.log || '(nothing yet)') + '</pre>';
  document.getElementById('main').innerHTML = html;
  var gen = document.getElementById('genBtn');
  if (gen) gen.onclick = generate;
  var open = document.getElementById('openBtn');
  if (open) open.onclick = function () { api('/api/session/' + S.session + '/open', 'POST', {}); };
  wireEmpty();
}

function renderSettings() {
  var html = headHtml('Settings', 'Analysis defaults and appearance.');
  html += '<div class="panel"><h3 class="sub">Appearance</h3>' +
    '<div class="head-actions">' +
    ['dark', 'light'].map(function (t) {
      return '<button class="mini" data-theme-set="' + t + '" aria-pressed="' +
        (S.theme === t ? 'true' : 'false') + '">' + t + '</button>';
    }).join('') + '</div></div>';
  html += '<div class="panel"><h3 class="sub">Provenance key</h3><table><tbody>' +
    Object.keys(PROV_LABEL).map(function (k) {
      var why = {
        measured: 'A deterministic measurement of the signal. The same recording gives the same number.',
        model: 'The output of a trained model, unverified. It can be wrong in ways the number does not show.',
        human: 'Entered or overridden by the electroencephalographer.',
        none: 'Not scored, or not possible to determine. SCORE distinguishes this from a negative finding.'
      }[k];
      return '<tr><td class="nowrap">' + prov(k) + '</td><td><span class="basis" ' +
        'style="margin:0">' + esc(why) + '</span></td></tr>';
    }).join('') + '</tbody></table></div>';
  html += '<div class="panel"><h3 class="sub">Language model</h3>';
  if (!S.llm) {
    html += '<p class="job">The server did not report which providers are ' +
      'available. Restart it.</p>';
  } else if ((S.llm.available || []).length) {
    html += '<table><thead><tr><th scope="col">Provider</th>' +
      '<th scope="col">Model</th><th scope="col">Use</th></tr></thead><tbody>';
    S.llm.available.forEach(function (p, i) {
      html += '<tr><td class="value">' + esc(p.provider) + '</td><td>' +
        esc(p.model) + '</td><td>' + (i === 0 ? 'used for the narrative' :
          'available') + '</td></tr>';
    });
    html += '</tbody></table><p class="job">Keys live in config.env and are ' +
      'never sent to this page. There is no provider picker here by design.</p>';
  } else {
    html += '<p class="job">No usable key in config.env. Looked for ' +
      esc((S.llm.wanted || []).join(', ')) + '.</p>';
  }
  html += '</div>';

  html += '<div class="panel"><h3 class="sub">Analysis defaults</h3>' +
    '<pre class="log">' + esc(JSON.stringify(S.defaults, null, 1)) + '</pre></div>';
  document.getElementById('main').innerHTML = html;
  Array.prototype.forEach.call(
    document.querySelectorAll('[data-theme-set]'), function (b) {
      b.onclick = function () {
        S.theme = b.getAttribute('data-theme-set');
        localStorage.setItem('theme', S.theme);
        render();
      };
    });
}

/* ---------------------------------------------------------------------- wiring */

function wireEmpty() {
  var run = document.getElementById('runFromSection');
  if (run) run.onclick = function () { go('home'); };
}

function sendOverride(sectionId, edits) {
  if (!S.session) return;
  var payload = {};
  payload[sectionId] = edits;
  api('/api/session/' + S.session + '/overrides', 'POST', payload)
    .then(function (r) {
      S.outstanding = r.outstanding || [];
      return refresh();
    })
    .catch(function (e) { console.error(e); });
}

function wireSection(sec) {
  var main = document.getElementById('main');

  var include = document.getElementById('includeBox');
  if (include) {
    include.onchange = function () {
      sendOverride(sec.id, { included: include.checked });
    };
  }

  Array.prototype.forEach.call(main.querySelectorAll('[data-row]'), function (input) {
    input.onchange = function () {
      var edits = {};
      edits[input.getAttribute('data-row')] = input.value.trim();
      sendOverride(input.getAttribute('data-section'), edits);
    };
  });

  Array.prototype.forEach.call(main.querySelectorAll('[data-finding]'), function (box) {
    box.onchange = function () {
      var edits = {};
      edits[box.getAttribute('data-finding')] = { included: box.checked };
      sendOverride(box.getAttribute('data-section'), edits);
    };
  });

  Array.prototype.forEach.call(main.querySelectorAll('[data-event]'), function (box) {
    box.onchange = function () {
      var edits = {};
      edits[box.getAttribute('data-event')] = box.checked;
      sendOverride('events', edits);
    };
  });

  Array.prototype.forEach.call(main.querySelectorAll('[data-significance]'), function (b) {
    b.onclick = function () {
      sendOverride('conclusion', { significance: b.getAttribute('data-significance') });
    };
  });

  Array.prototype.forEach.call(main.querySelectorAll('[data-yield]'), function (b) {
    b.onclick = function () {
      sendOverride('conclusion', { 'yield': b.getAttribute('data-yield') });
    };
  });

  Array.prototype.forEach.call(
    main.querySelectorAll('[data-artifact-significance]'), function (b) {
      b.onclick = function () {
        var edits = {};
        edits[b.getAttribute('data-target')] = {
          significance: b.getAttribute('data-artifact-significance')
        };
        sendOverride('artifacts', edits);
      };
    });

  var draft = document.getElementById('draftBox');
  if (draft) {
    draft.onchange = function () { sendOverride('conclusion', { draft: draft.value }); };
  }
}

/* ------------------------------------------------------------------- actions */

function startAnalysis() {
  if (!S.study) {
    alert('Give a study folder or EEG file first.');
    return;
  }
  S.status = 'running';
  S.log = '';
  S.pdf = null;
  S.error = null;
  S.report = null;
  S.route = 'analysis';
  render();
  api('/api/analyse', 'POST', { study: S.study, options: S.options })
    .then(function (r) {
      S.session = r.id;
      writeHash();
      poll();
    })
    .catch(function (e) {
      S.status = 'idle';
      S.error = String(e.message || e);
      S.route = 'home';
      render();
    });
}

function refresh() {
  if (!S.session) return Promise.resolve();
  return api('/api/session/' + S.session).then(function (r) {
    S.status = r.status;
    S.log = r.log || '';
    S.pdf = r.pdf || null;
    S.data = r.data || null;
    S.busy = r.status === 'generating';
    if (r.report) S.report = r.report;
    if (r.outstanding) S.outstanding = r.outstanding;
    S.error = r.error || null;
    render();
  });
}

function poll() {
  if (S.polling) clearInterval(S.polling);
  S.polling = setInterval(function () {
    refresh().then(function () {
      if (S.status !== 'running' && S.status !== 'generating') {
        clearInterval(S.polling);
        S.polling = null;
        if (S.status === 'ready' && S.route === 'analysis') go('recording');
      }
    }).catch(function () { });
  }, 1500);
}

function generate() {
  S.busy = true;
  S.pdf = null;
  render();
  api('/api/session/' + S.session + '/generate', 'POST', {})
    .then(function () { poll(); })
    .catch(function (e) {
      S.busy = false;
      S.log += '\n' + (e.message || e);
      render();
    });
}

/* -------------------------------------------------------------------- render */

/* Wide content scrolls inside its own box, never the page.
 *
 * The brief requires the panel to be usable at 420 px. A dense SCORE table is
 * wider than that whatever is done to it, and if it is left to overflow then
 * the page itself scrolls sideways - which carries the navigation rail and the
 * regulatory notice off screen. Each table gets its own scroll container
 * instead, so the chrome stays put.
 */
function wrapWideContent(root) {
  Array.prototype.forEach.call(root.querySelectorAll('table'), function (table) {
    if (table.parentNode && table.parentNode.className === 'tablewrap') return;
    var wrap = document.createElement('div');
    wrap.className = 'tablewrap';
    table.parentNode.insertBefore(wrap, table);
    wrap.appendChild(table);
  });
}

function render() {
  // On the root element, not on #app: body sits outside #app and consumes
  // --p-text-primary, so a theme scoped to #app left body - and every
  // element inheriting its colour - on the other theme's text colour.
  document.documentElement.setAttribute('data-theme', S.theme);
  renderStudyBar();
  renderRail();
  renderStatusBar();

  if (S.route === 'home') renderHome();
  else if (S.route === 'analysis') renderAnalysis();
  else if (S.route === 'outstanding') renderOutstanding();
  else if (S.route === 'generate') renderGenerate();
  else if (S.route === 'settings') renderSettings();
  else renderSection(S.route);

  wrapWideContent(document.getElementById('main'));
}

api('/api/config').then(function (c) {
  S.defaults = c.defaults || {};
  S.options = Object.assign({}, c.defaults);
  delete S.options.study;
  // A field the server did not send is unknown, not empty. Reading an absent
  // llm block as 'no keys available' greyed out the narrative option against a
  // server that simply predated it - the page's files are reloaded from disk
  // while the process keeps its old code, so a new front end can meet an old
  // API. Staleness is reported instead of guessed at.
  S.stale = (c.api || 0) < API_EXPECTED;
  S.llm = c.llm || null;
  if (S.llm && !(S.llm.available || []).length) S.options.aiReport = false;
  if (c.study) S.study = c.study;

  // Rejoin a session named in the URL, so a reload keeps the analysis.
  var hash = readHash();

  // A study named in the URL wins. The server outlives any one study - the
  // study browser reuses a running one for whatever is selected next - so the
  // study travels with the request rather than being fixed at start-up.
  if (hash.study) {
    S.study = hash.study;
    S.session = null;
    S.report = null;
    S.status = 'idle';
  }
  if (hash.theme === 'light' || hash.theme === 'dark') S.theme = hash.theme;
  // The route is honoured whether or not a session is named, so a screen can be
  // bookmarked or linked to on its own.
  if (hash.route) S.route = hash.route;
  if (hash.session) {
    S.session = hash.session;
    return refresh().then(function () {
      if (S.status === 'running' || S.status === 'generating') poll();
    }).catch(function () {
      // The server was restarted and the session is gone. Say so rather than
      // showing an empty review as though nothing had been analysed.
      S.session = null;
      S.route = 'home';
      S.error = 'That analysis is no longer on the server - it was restarted. ' +
        'Run the analyses again.';
      render();
    });
  }
  render();
}).catch(function (e) {
  document.getElementById('main').innerHTML =
    '<div class="empty" data-kind="failed"><span class="kind">Error</span>' +
    '<span class="title">The report server is not answering.</span>' +
    '<span class="why">' + esc(e.message || e) + '</span></div>';
});
