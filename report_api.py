############################################
# The report as data, for the review front end.
#
# The analysis already produces everything the front end shows; this turns it
# into one JSON document with a stable shape, and answers the question the
# design puts at the centre of every screen: where did this value come from?
#
# Provenance is the point. The front end marks every value as measured, model,
# human-scored or not scored, and a reader deciding whether to accept a value
# needs that to be true. So it is declared here, per field, from what the
# pipeline actually did - never inferred from the wording of a basis string.
# Sniffing text for 'model' would repeat the mistake that put 'Drowsy' on every
# event in Demo.eeg.
#
# The four marks mean:
#
#   measured  a deterministic measurement of the signal. Reproducible: the same
#             recording gives the same number.
#   model     the output of a trained model, unverified. Reproducible, but the
#             model can be wrong in ways the number does not show.
#   human     entered or overridden by the electroencephalographer. SCORE
#             reserves diagnostic significance and the conclusion for a human,
#             and nothing here writes them.
#   none      not scored, or not possible to determine. SCORE distinguishes
#             these from a negative finding and so does this.
############################################
import copy
import datetime
import json
import math
import os

MEASURED = 'measured'
MODEL = 'model'
HUMAN = 'human'
NONE = 'none'

# What the reader is being asked to do on each screen, and where its data comes
# from. Order is the order of the navigation rail.
SECTIONS = [
    {'id': 'recording', 'label': 'Patient & recording', 'key': 'recording',
     'job': 'Confirm the facts the study already knows, and supply the ones it does not.'},
    {'id': 'pdr', 'label': 'Posterior dominant rhythm', 'key': 'pdr',
     'job': 'Review the nine scored PDR properties and accept or override each.'},
    {'id': 'interictal', 'label': 'Interictal findings', 'key': 'interictal',
     'job': 'Choose which rhythmic-activity findings go in the report.'},
    {'id': 'episodes', 'label': 'Episodes', 'key': 'spikeseizure',
     'job': 'Select detected electrographic events and score what the signal cannot say.'},
    {'id': 'sleep', 'label': 'Sleep & drowsiness', 'key': 'sleep',
     'job': 'Report which stages were reached and which graphoelements were seen.'},
    {'id': 'artifacts', 'label': 'Artifacts', 'key': 'artifacts',
     'job': 'Name the artifact types present and let a human judge their significance.'},
    {'id': 'events', 'label': 'Events', 'key': None,
     'job': 'Pick individual study events to carry into the report.'},
    {'id': 'conclusion', 'label': 'Significance & conclusion', 'key': 'conclusion',
     'job': 'Score the conclusion - the one thing the software must not decide.'},
]

# PDR, property by property. Eight of the nine are measured off the signal; the
# frequency pair comes from the CNN/GoogleNet/ResNet ensemble, which is a model
# and is marked as one however confident it sounds.
PDR_PROVENANCE = {
    'frequency': MODEL,
    'frequency_asymmetry': MODEL,
    'amplitude': MEASURED,
    'amplitude_asymmetry': MEASURED,
    'reactivity': MEASURED,
    'organization': MEASURED,
    'caveat': MEASURED,
    'absence': MEASURED,
    # SCORE gives the significance of a finding to the electroencephalographer,
    # for the PDR as for everything else. pdr.py proposes a category; it is
    # offered as a proposal and the front end asks the reader to settle it.
    'significance': HUMAN,
}

# The nine SCORE PDR properties, in the order the standard lists them.
PDR_LABELS = {
    'frequency': 'Frequency',
    'frequency_asymmetry': 'Frequency asymmetry',
    'amplitude': 'Amplitude',
    'amplitude_asymmetry': 'Amplitude asymmetry',
    'reactivity': 'Reactivity',
    'organization': 'Organisation',
    'caveat': 'Caveat',
    'absence': 'Absence of the PDR',
    'significance': 'Significance',
}

# Phrases the analysis uses when a property could not be scored. SCORE separates
# these from a normal finding, and so does the front end.
NOT_DETERMINED = ('not possible to determine', 'not scored', 'not applicable',
                  'unavailable', 'not recorded in the study')


def _isUndetermined(text):
    lowered = (text or '').strip().lower()
    return any(lowered.startswith(p) for p in NOT_DETERMINED)


def _clean(value):
    """A value json can serialise. numpy scalars and NaN both appear here."""
    if value is None or isinstance(value, (bool, str)):
        return value
    if isinstance(value, dict):
        return {str(k): _clean(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_clean(v) for v in value]
    if hasattr(value, 'item') and not isinstance(value, (int, float)):
        try:
            value = value.item()
        except (ValueError, AttributeError):
            return str(value)
    if isinstance(value, float):
        return None if math.isnan(value) or math.isinf(value) else value
    if isinstance(value, (int, float)):
        return value
    if isinstance(value, (datetime.date, datetime.datetime)):
        return value.isoformat()
    return str(value)


def _row(label, value, provenance, basis='', confidence='', provisional=False,
         editable=False, rowId=None):
    """One reviewable line: a value, where it came from, and what backs it."""
    if _isUndetermined(value):
        provenance = NONE
    return {
        'id': rowId or label.lower().replace(' ', '_'),
        'label': label,
        'value': value,
        'provenance': provenance,
        'basis': basis or '',
        'confidence': confidence or '',
        'provisional': bool(provisional),
        'editable': bool(editable),
        'override': None,
    }


def _outstanding(rows):
    """Rows a reader still has to answer: nothing scored, or a provisional one."""
    out = []
    for row in rows:
        if row['provenance'] == NONE:
            # The value often is the words 'Not scored', which repeated back
            # explains nothing; the basis says why it could not be scored.
            reason = row['value'] or 'no value'
            if _isUndetermined(reason) and row.get('basis'):
                reason = row['basis']
            out.append({'id': row['id'], 'label': row['label'],
                        'why': 'Not scored - %s' % reason})
        elif row['provisional']:
            out.append({'id': row['id'], 'label': row['label'],
                        'why': 'Provisional - %s' % (row['basis'] or 'needs confirmation')})
    return out


def _sectionState(rows, findings, analysed):
    """Which of the design's five section states applies.

    'Not analysed' and 'No findings' are different answers and the distinction
    is clinical: one means nobody looked, the other means somebody looked and
    there was nothing there.
    """
    if not analysed:
        return 'not-analysed'
    if not rows and not findings:
        return 'no-findings'
    return 'populated'


# --------------------------------------------------------------- the sections

def recordingSection(recording):
    rows = []
    if not recording:
        return rows, [], None
    for group, provenance in (('patient', MEASURED), ('conditions', MEASURED)):
        for label, value in (recording.get(group) or {}).items():
            rows.append(_row(label, value, provenance,
                             basis='read from the study' if not _isUndetermined(value) else '',
                             rowId='%s_%s' % (group, label.lower().replace(' ', '_'))))
    # Fields SCORE wants that no signal can supply.
    for label in (recording.get('technologist_fields') or []):
        rows.append(_row(label, 'Not scored', NONE,
                         basis='for the technologist or the reader to supply',
                         editable=True, rowId='tech_%s' % label.lower().replace(' ', '_')[:40]))
    return rows, [], recording.get('durations')


def activationBlock(activation):
    """SCORE's activation procedures, ready for display.

    A procedure the study evidences is measured - the events are a record of what
    was done. Whether it produced a change is the reader's, so that stays human
    and unscored.
    """
    if not activation:
        return None
    procedures = []
    for procedure in activation.get('procedures') or []:
        performed = procedure.get('performed')
        procedures.append({
            'name': procedure['name'],
            'state': procedure['state'],
            # Performed-or-not is read from the study; not-recorded is not a
            # finding either way, so it is marked as not scored.
            'provenance': MEASURED if performed else NONE,
            'onset_seconds': _clean(procedure.get('onset_seconds')),
            'span_seconds': _clean(procedure.get('span_seconds')),
            'frequencies_hz': _clean(procedure.get('frequencies_hz')),
            'detail': procedure.get('detail') or '',
            'basis': procedure.get('basis') or '',
            'response': procedure.get('response') or 'Not scored',
            'response_provenance': HUMAN,
        })
    return {'procedures': procedures,
            'notes': list(activation.get('notes') or []),
            'any_performed': bool(activation.get('any_performed'))}


def activationResponseId(name):
    return 'activation_%s_response' % name.lower().replace(' ', '_')


def activationRows(activation):
    """One row per performed procedure, for the reader to score its response.

    Made rows rather than something alongside them, because rows are what the
    override and outstanding machinery works on - anything kept beside them was
    recomputed away on the next read.

    Only performed procedures get a row. Asking for the response to a procedure
    the study does not record as having happened would be asking for a judgement
    about nothing.
    """
    rows = []
    for procedure in (activation or {}).get('procedures') or []:
        if procedure['provenance'] != MEASURED:
            continue
        rows.append(_row(
            '%s response' % procedure['name'], 'Not scored', HUMAN,
            basis='whether it produced a change is the reader\'s judgement - %s'
                  % (procedure.get('detail') or procedure.get('basis') or ''),
            editable=True, rowId=activationResponseId(procedure['name'])))
    return rows


def pdrSection(pdr):
    rows = []
    for key, label in PDR_LABELS.items():
        entry = (pdr or {}).get(key)
        if not entry:
            continue
        rows.append(_row(label, entry.get('term'), PDR_PROVENANCE.get(key, MEASURED),
                         basis=entry.get('basis'), confidence=entry.get('confidence'),
                         provisional=entry.get('provisional'), editable=True,
                         rowId='pdr_%s' % key))
    return rows


def _finding(finding, provenance, index, prefix):
    location = finding.get('location') or {}
    return {
        'id': '%s_%d' % (prefix, index),
        'name': finding.get('name'),
        'location': location.get('text') or '',
        'prevalence': finding.get('prevalence') or finding.get('incidence') or '',
        'count': finding.get('count') or finding.get('occurrences'),
        'mode': ', '.join(x for x in (finding.get('mode_of_appearance'),
                                      finding.get('discharge_pattern')) if x),
        'basis': finding.get('basis') or '',
        'timing_basis': finding.get('timing_basis') or '',
        'confidence': finding.get('confidence') or '',
        'provenance': provenance,
        # SCORE reserves significance for the electroencephalographer, so it is
        # empty here and the front end asks for it.
        'significance': None,
        'included': True,
    }


def findingSection(block, provenance, prefix):
    findings = [(_finding(f, provenance, i, prefix))
                for i, f in enumerate((block or {}).get('findings') or [])]
    return findings, list((block or {}).get('notes') or [])


def episodesSection(spikeseizure):
    episodes = []
    for i, e in enumerate((spikeseizure or {}).get('episodes') or []):
        location = e.get('location') or {}
        episodes.append({
            'id': 'episode_%d' % i,
            'name': e.get('name'),
            'location': location.get('text') or '',
            'onset_seconds': e.get('onset_seconds'),
            'duration_seconds': e.get('duration_seconds'),
            'duration_band': e.get('duration_band') or '',
            'basis': e.get('basis') or '',
            'confidence': e.get('confidence') or '',
            # A cleared detector is still a model, and an electrographic
            # detection is not by itself an epileptic seizure.
            'provenance': MODEL,
            'included': True,
            # The electro-clinical half, which needs the video and the record.
            'reader_fields': ['Seizure type (ILAE classification)',
                              'Semiology and its somatotopic modifiers',
                              'Ictal EEG pattern and its evolution',
                              'Clinical-EEG temporal relationship',
                              'Consciousness and awareness',
                              'Postictal findings'],
        })
    return episodes


def sleepSection(sleep):
    """Stages and graphoelements. U-Sleep and YASA are models and say so."""
    rows, findings = [], []
    if not sleep:
        return rows, findings
    backend = sleep.get('backend') or 'model'
    for label, key in (('Stages reached', 'stages_text'),
                       ('Sleep reached', 'sleep_reached'),
                       ('Drowsiness', 'drowsiness')):
        if sleep.get(key) is not None:
            rows.append(_row(label, _clean(sleep[key]), MODEL,
                             basis='%s hypnogram, unverified' % backend,
                             editable=True, rowId='sleep_%s' % key))
    for i, f in enumerate(sleep.get('findings') or []):
        findings.append(_finding(f, MODEL, i, 'sleep'))
    return rows, findings


# The three artifact significance judgements SCORE asks a human for. The
# analysis measures how much of the recording an artifact covers; whether that
# ruined the recording is a clinical judgement about what the reader could still
# read, so it is offered and never chosen.
ARTIFACT_SIGNIFICANCE = ('Does not interfere with interpretation',
                         'Reduced diagnostic value',
                         'Not interpretable')


def yieldOptions(results):
    """SCORE's diagnostic-yield list, each marked supportable or not, with why.

    The unsupportable ones are returned rather than filtered out: a reader who
    cannot find 'Epilepsy' in a list has learnt nothing, whereas one who sees it
    greyed with 'needs epileptiform findings' has learnt what this recording's
    analysis can and cannot argue.

    Supportability depends on what was actually analysed, not on a fixed list.
    score_common's static reason for Epilepsy - that this analysis does not
    detect epileptiform findings - stopped being true when the spike and seizure
    detector was wired in, so it is recomputed here from the findings present.
    """
    import score_common as sc

    supportable = set(sc.SUPPORTABLE_YIELDS)
    spikeseizure = results.get('spikeseizure') or {}
    hasSpikes = bool(spikeseizure.get('interictal'))
    hasSeizures = bool(spikeseizure.get('episodes'))
    if hasSpikes or hasSeizures:
        # A detector has supplied epileptiform findings, so the reason for
        # withholding this one no longer holds.
        supportable.add('Epilepsy')

    options = []
    for term in sc.SIGNIFICANCE_YIELDS:
        if term in supportable:
            options.append({'term': term, 'supportable': True, 'reason': ''})
            continue
        reason = sc.UNSUPPORTABLE_REASON.get(
            term, 'not supportable from background analysis alone')
        if term == 'Epilepsy':
            reason = 'needs epileptiform findings, and none were detected'
        options.append({'term': term, 'supportable': False, 'reason': reason})
    return options


def conclusionSection(conclusion):
    """SCORE sections 4 and 5. Human-scored by definition.

    Anything the LLM drafted is offered as a draft and marked as a model's
    words, never as a scored value.
    """
    rows = [
        _row('Diagnostic significance', 'Not scored', HUMAN,
             basis='forced choice, reserved for the electroencephalographer',
             editable=True, rowId='significance'),
        _row('Diagnostic yield', 'Not scored', HUMAN,
             basis='SCORE list', editable=True, rowId='yield'),
    ]
    draft = ''
    if conclusion:
        rows[0]['value'] = conclusion.get('significance') or 'Not scored'
        rows[1]['value'] = conclusion.get('yield') or 'Not scored'
        draft = conclusion.get('summary') or conclusion.get('text') or ''
        for row in rows:
            # A drafted value is still the model's suggestion until accepted.
            if not _isUndetermined(row['value']):
                row['provisional'] = True
                row['provenance'] = MODEL
                row['basis'] = 'drafted by the language model - accept or replace'
    return rows, draft


# How many events are carried to the front end.
#
# Capped per type as well as overall. A flat cap took the first 500 events of
# 05JC.eeg and 433 of them were spike bursts, which squeezed the technologist's
# annotations and the recording events down to a handful and cut 33 events
# entirely - on a screen whose whole purpose is picking individual events out of
# the record. A long-term study can hold tens of thousands, so some cap is
# needed; taking a share of each type means every kind of event is still there
# to be found.
EVENT_LIMIT = 2000
EVENTS_PER_TYPE = 200


def eventsSection(studyPath):
    """Study events the reader may carry into the report.

    Each is named with the word ProfusionEEG itself uses for its type, so the
    list reads the same way it does in the application rather than as a column
    of numbers. Detections are marked as such; SCORE provocations - photic,
    hyperventilation, cortical stimulation - are picked out because section 2
    wants them recorded.
    """
    events = []
    try:
        import studyevents
        raw = studyevents.readEvents(studyPath, verbose=False)
    except Exception:
        return events

    # End events are dropped here as they are everywhere else. ProfusionEEG
    # stores a timed event as a start carrying the duration plus an end at
    # start+duration, so keeping both listed each one twice - and made the
    # count of detector events on this screen twice what the Episodes page
    # showed for the same four seizures.
    raw = [e for e in raw if not e.get('is_end_event')]

    # Every type's own total, so the screen can say what it holds and what it
    # is showing, and offer a filter that means something.
    totals = {}
    for e in raw:
        label = e.get('type_label') or 'Unrecognised type'
        totals[label] = totals.get(label, 0) + 1

    kept, perType = [], {}
    for e in raw:
        label = e.get('type_label') or 'Unrecognised type'
        if perType.get(label, 0) >= EVENTS_PER_TYPE:
            continue
        if len(kept) >= EVENT_LIMIT:
            break
        perType[label] = perType.get(label, 0) + 1
        kept.append(e)

    for e in kept:
        start = e.get('start_ns')
        # A detection is a model's output; an annotation is a person's; a
        # setting change or a viewing record is neither, and is measured fact
        # about the recording. The mark follows what the event actually is.
        if e.get('is_detection'):
            provenance = MODEL
        elif e.get('is_annotation'):
            provenance = HUMAN
        else:
            provenance = MEASURED
        events.append({
            'id': 'ev_%s' % e.get('id'),
            # Always the name ProfusionEEG uses. labelFor never returns
            # nothing, so the numeric id stays out of the display and is
            # carried alongside for anyone who needs to match on it.
            'type': e.get('type_label') or 'Unrecognised type',
            'type_id': e.get('type_id'),
            'type_name': e.get('type_name'),
            'text': e.get('text') or '',
            'seconds': None if start is None else start / 1e9,
            'duration_seconds': (e.get('duration_ns') or 0) / 1e9,
            'channels': e.get('traces') or [],
            'provenance': provenance,
            'is_detection': bool(e.get('is_detection')),
            'provocation': e.get('provocation'),
            'included': False,
        })
    return events, {'total': len(raw),
                    'by_type': [{'type': k, 'total': v, 'shown': perType.get(k, 0)}
                                for k, v in sorted(totals.items(),
                                                   key=lambda kv: -kv[1])]}


# ------------------------------------------------------------------- assembly

def buildReport(results, studyPath, options=None):
    """The whole review document, as the front end consumes it."""
    results = results or {}
    recording = results.get('recording') or {}
    sections = []

    rows, _, durations = recordingSection(recording)
    activation = activationBlock(recording.get('activation'))
    rows.extend(activationRows(activation))
    sections.append({'id': 'recording', 'rows': rows, 'findings': [],
                     'notes': recording.get('notes') or [],
                     'durations': _clean(durations),
                     'duration_lines': recording.get('duration_lines') or [],
                     'activation': activation})

    pdrRows = pdrSection(results.get('pdr'))
    sections.append({'id': 'pdr', 'rows': pdrRows, 'findings': [], 'notes': []})

    findings, notes = findingSection(results.get('interictal'), MEASURED, 'interictal')
    # Spike findings inside the interictal block came from the detector.
    spikeNames = {f.get('name') for f in
                  ((results.get('spikeseizure') or {}).get('interictal') or [])}
    for f in findings:
        if f['name'] in spikeNames:
            f['provenance'] = MODEL
    sections.append({'id': 'interictal', 'rows': [], 'findings': findings,
                     'notes': notes,
                     'measures': _clean((results.get('interictal') or {}).get('measures'))})

    episodes = episodesSection(results.get('spikeseizure'))
    sections.append({'id': 'episodes', 'rows': [], 'findings': episodes,
                     'notes': (results.get('spikeseizure') or {}).get('notes') or []})

    sleepRows, sleepFindings = sleepSection(results.get('sleep'))
    sections.append({'id': 'sleep', 'rows': sleepRows, 'findings': sleepFindings,
                     'notes': []})

    artifactFindings, artifactNotes = findingSection(results.get('artifacts'),
                                                     MEASURED, 'artifact')
    sections.append({'id': 'artifacts', 'rows': [], 'findings': artifactFindings,
                     'notes': artifactNotes,
                     'significance_options': list(ARTIFACT_SIGNIFICANCE)})

    studyEvents, eventCounts = eventsSection(studyPath)
    sections.append({'id': 'events', 'rows': [], 'findings': [],
                     'events': studyEvents,
                     'event_total': eventCounts['total'],
                     'event_types': eventCounts['by_type'],
                     'notes': []})

    import score_common as sc
    conclusionRows, draft = conclusionSection(results.get('conclusion'))
    sections.append({'id': 'conclusion', 'rows': conclusionRows, 'findings': [],
                     'draft': draft, 'notes': [],
                     'categories': list(sc.SIGNIFICANCE_CATEGORIES),
                     'yields': yieldOptions(results)})

    # Merge the static description of each section over the data.
    byId = {s['id']: s for s in sections}
    ordered = []
    for spec in SECTIONS:
        section = byId.get(spec['id'], {'id': spec['id'], 'rows': [],
                                        'findings': [], 'notes': []})
        analysed = spec['key'] is None or results.get(spec['key']) is not None
        section.update({
            'label': spec['label'],
            'job': spec['job'],
            'included': True,
            'state': _sectionState(section.get('rows'), section.get('findings'),
                                   analysed),
            'outstanding': _outstanding(section.get('rows') or []),
        })
        if section['id'] == 'events':
            section['state'] = 'populated' if section.get('events') else 'no-findings'
        if section['id'] == 'conclusion':
            # Nothing analyses the conclusion, so it is never 'not analysed' -
            # it is waiting for the reader from the moment the report exists.
            section['state'] = 'populated'

        ordered.append(section)

    return {
        'study': {
            'path': studyPath,
            'name': os.path.basename(studyPath.rstrip('/\\')),
            'source': recording.get('source'),
            'is_study': recording.get('is_study'),
        },
        'generated': datetime.datetime.now().isoformat(timespec='seconds'),
        'options': _clean(options or {}),
        'sections': ordered,
        'provenance_key': {
            MEASURED: 'Measured from the signal',
            MODEL: 'Model output - unverified',
            HUMAN: 'Human-scored',
            NONE: 'Not scored',
        },
    }


def outstandingTotal(report):
    """Everything unanswered, across every included section."""
    out = []
    for section in report.get('sections') or []:
        if not section.get('included', True):
            continue
        for item in section.get('outstanding') or []:
            entry = dict(item)
            entry['section'] = section['id']
            entry['section_label'] = section['label']
            out.append(entry)
    return out


# The analysis, saved beside the report so it can be re-used.
#
# An analysis takes minutes; a document takes seconds once it exists. Saving the
# results means a study analysed yesterday can be reported today - with different
# sections included, or different values accepted - without paying for the
# analysis again.
ANALYSIS_SUFFIX = '.analysis.json'
ANALYSIS_FORMAT = 1


def analysisPath(destFolder, fileName):
    stem = os.path.splitext(os.path.basename(fileName))[0]
    return os.path.join(destFolder, stem + ANALYSIS_SUFFIX)


def saveAnalysis(results, destFolder, fileName, study=None, options=None):
    """Write the analysis results beside the report. Returns the path."""
    path = analysisPath(destFolder, fileName)
    payload = {
        'format': ANALYSIS_FORMAT,
        'saved': datetime.datetime.now().isoformat(timespec='seconds'),
        'study': study,
        'file_name': fileName,
        'options': _clean(options or {}),
        'results': _clean(results),
    }
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(payload, f, indent=1, default=str)
    return path


def loadAnalysis(destFolder, fileName):
    """A saved analysis, or None if there is none or it cannot be read."""
    path = analysisPath(destFolder, fileName)
    if not os.path.isfile(path):
        return None
    try:
        with open(path, encoding='utf-8') as f:
            payload = json.load(f)
    except (OSError, ValueError):
        return None
    if payload.get('format') != ANALYSIS_FORMAT:
        return None
    return payload


def describeSavedAnalysis(destFolder, fileName):
    """What is on disk for this study, for the front end to offer.

    Reports the figures too: without them the document cannot be rebuilt, and a
    reader offered a restore that then fails has been told something untrue.
    """
    payload = loadAnalysis(destFolder, fileName)
    if not payload:
        return None
    import createPDF
    missing = createPDF.missingFigures(destFolder, fileName)
    return {
        'path': analysisPath(destFolder, fileName),
        'saved': payload.get('saved'),
        'study': payload.get('study'),
        'options': payload.get('options') or {},
        'can_generate': not missing,
        'missing_figures': missing,
    }


def save(report, path):
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(report, f, indent=1, default=str)
    return path


def load(path):
    with open(path, encoding='utf-8') as f:
        return json.load(f)


def applyOverrides(report, overrides):
    """A reader's edits, folded back in.

    An overridden value becomes human-scored: that is the whole point of the
    override, and the mark has to follow the edit or the provenance is a lie.
    """
    report = copy.deepcopy(report)
    for section in report.get('sections') or []:
        edits = (overrides or {}).get(section['id']) or {}
        if 'included' in edits:
            section['included'] = bool(edits['included'])
        for row in section.get('rows') or []:
            if row['id'] in edits:
                row['override'] = edits[row['id']]
                row['value'] = edits[row['id']]
                row['provenance'] = HUMAN
                row['provisional'] = False
        for finding in section.get('findings') or []:
            edit = edits.get(finding['id'])
            if isinstance(edit, dict):
                finding.update(edit)
        for event in section.get('events') or []:
            if event['id'] in edits:
                event['included'] = bool(edits[event['id']])
        section['outstanding'] = _outstanding(section.get('rows') or [])
    return report
