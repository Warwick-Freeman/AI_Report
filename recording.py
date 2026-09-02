############################################
# Recording conditions and patient information - SCORE's first two report
# sections, both filled entirely from data the study already carries.
#
# SCORE (Beniczky et al., Clin Neurophysiol 2017) opens a report with "Patient
# information and referral" and "Recording conditions" before any finding. They
# are what a reader checks first to decide whether to trust the rest, and they
# are pure metadata - no interpretation, so nothing here needs confirming beyond
# the values themselves.
#
# Also here: the duration accountant. SCORE expresses how often something occurs
# as a rate over the recording, so every incidence and prevalence band depends on
# knowing what was actually examined. This pipeline discards a large fraction of
# epochs - 46% on the demo study - so the distinction between recorded, loaded
# and analysed duration is not bookkeeping, it is the denominator.
############################################
import os
import glob

import profusion

# What the technologist observes rather than what the signal shows. SCORE scores
# these and this module never guesses them.
TECHNOLOGIST_FIELDS = ('Alertness, orientation and cooperation', 'Time of last meal',
                       'Skull defect or previous brain surgery')

NOT_RECORDED = 'not recorded in the study'


def readFilterSettings(studyPath):
    """Display filter settings from the study's FilterSettings.xml.

    These are the filters the recording was *reviewed* through, which SCORE
    reports as part of the technical description. They are not the filters this
    analysis applies - that is stated separately.
    """
    import xml.etree.ElementTree as ET
    path = os.path.join(studyPath.rstrip('\\/'), 'FilterSettings.xml')
    if not os.path.isfile(path):
        return None
    try:
        root = ET.parse(path).getroot()
    except (ET.ParseError, OSError):
        return None

    groups = []
    for group in root.iter('Group'):
        def value(tag):
            node = group.find(tag)
            return node.text.strip() if node is not None and node.text else None
        groups.append({'group': value('GroupId'), 'low_pass': value('LoPassFilter'),
                       'high_pass': value('HiPassFilter'), 'notch': value('NotchFilter')})
    if not groups:
        return None

    # Collapse when every channel group shares the same settings, which is the
    # normal case and reads better than repeating one row per group.
    distinct = {(g['low_pass'], g['high_pass'], g['notch']) for g in groups}
    return {'groups': groups, 'uniform': len(distinct) == 1}


# Review settings, as the study records them changing.
#
# FilterSettings.xml holds one current set; these events hold what was actually
# applied and when it changed, and several studies carry no FilterSettings.xml
# at all. SCORE asks for the settings the recording was reviewed through, so the
# events are the better source where both exist.
SETTING_EVENT_TYPES = {
    29: ('High pass', 'Hz'),
    30: ('Notch', 'Hz'),
    31: ('Low pass', 'Hz'),
    32: ('Sensitivity', 'uV/mm'),
    33: ('Time base', ''),
}

# eetMontageChange (3) is deliberately absent. Its text in every study examined
# is 'Acquisition PC User' - whoever made the change, not the montage - so
# reporting it as the montage would state something false.
MONTAGE_EVENT_TYPES = {
    27: 'Electrode placement',
    28: 'Montage sequence',
}

# The activation procedures SCORE asks to be reported, and the event types that
# evidence them. Sleep is an activation too, but it comes from the sleep
# staging module rather than from an event, and sleep deprivation is a history
# item nothing in a study records.
ACTIVATION_PROCEDURES = (
    ('Hyperventilation', (8,), (46,)),
    ('Photic stimulation', (4, 45, 35), ()),
    ('Cortical stimulation', (50, 67), ()),
)


def _studyEvents(studyPath):
    """Every non-end event in a study, or [] if the database cannot be read.

    End events are dropped: ProfusionEEG stores a procedure as a start event
    carrying the duration plus an end event at start+duration, so counting both
    would double every procedure.
    """
    try:
        import studyevents
        events = studyevents.readEvents(studyPath, verbose=False)
    except Exception:
        return []
    return [e for e in events if not e.get('is_end_event')]


def _seconds(event, key='start_ns'):
    value = event.get(key)
    return None if value is None else value / 1e9


def readEventSettings(studyPath, events=None):
    """Review filters, sensitivity, time base and montage, from the events.

    Returns {label: {'values': [...], 'changes': n, 'unit': str}} or None.
    """
    import eventtypes

    events = events if events is not None else _studyEvents(studyPath)
    if not events:
        return None

    out = {}
    for event in events:
        resolved, _ = eventtypes.resolveTypeId(event.get('type_id'))
        text = (event.get('text') or '').strip()
        if resolved in SETTING_EVENT_TYPES:
            label, unit = SETTING_EVENT_TYPES[resolved]
        elif resolved in MONTAGE_EVENT_TYPES:
            label, unit = MONTAGE_EVENT_TYPES[resolved], ''
        else:
            continue
        if not text:
            continue
        entry = out.setdefault(label, {'values': [], 'unit': unit})
        if text not in entry['values']:
            entry['values'].append(text)
        entry['changes'] = entry.get('changes', 0) + 1
    return out or None


def readActivation(studyPath, events=None, analysedSeconds=None):
    """SCORE's activation procedures, from what the study recorded.

    A procedure with events is reported as performed, with its timing and - for
    photic - the frequencies used. A procedure with no events is reported as not
    recorded rather than as not performed: the two are different, and a study can
    be annotated inconsistently.

    Whether a procedure produced a change is left to the reader. SCORE treats a
    photoparoxysmal response or a build-up on hyperventilation as a finding, and
    nothing here measures one; the times are given so they can be reviewed.
    """
    import eventtypes

    events = events if events is not None else _studyEvents(studyPath)
    if not events:
        return None

    byType = {}
    for event in events:
        resolved, _ = eventtypes.resolveTypeId(event.get('type_id'))
        byType.setdefault(resolved, []).append(event)

    procedures, anyPerformed = [], False
    for name, mainTypes, afterTypes in ACTIVATION_PROCEDURES:
        found = [e for typeId in mainTypes for e in byType.get(typeId, [])]
        after = [e for typeId in afterTypes for e in byType.get(typeId, [])]
        if not found:
            procedures.append({
                'name': name,
                'performed': None,
                'state': 'Not recorded in the study',
                'basis': 'no %s event in the study' % name.lower(),
                'response': 'Not scored',
            })
            continue

        anyPerformed = True
        found.sort(key=lambda e: e.get('start_ns') or 0)
        onset = _seconds(found[0])
        last = found[-1]
        end = (last.get('start_ns') or 0) + (last.get('duration_ns') or 0)
        span = (end / 1e9) - (onset or 0)
        totalMarked = sum((e.get('duration_ns') or 0) for e in found) / 1e9

        detail = []
        # Photic frequencies live in the text of eetPhoticFrequencyChange.
        frequencies = []
        for event in found:
            resolved, _ = eventtypes.resolveTypeId(event.get('type_id'))
            if resolved != 35:
                continue
            text = (event.get('text') or '').strip()
            try:
                frequencies.append(float(text))
            except ValueError:
                continue
        if frequencies:
            ordered = sorted(set(frequencies))
            detail.append('frequencies %s Hz'
                          % ', '.join(('%g' % f) for f in ordered))
        if totalMarked >= 1:
            detail.append('%.0f s of marked stimulation' % totalMarked)
        if after:
            after.sort(key=lambda e: e.get('start_ns') or 0)
            detail.append('post-procedure marked at %s'
                          % ', '.join(_hms(_seconds(e)) for e in after))

        procedures.append({
            'name': name,
            'performed': True,
            'state': 'Performed',
            'onset_seconds': onset,
            'span_seconds': span if span > 0 else None,
            'count': len(found),
            'frequencies_hz': sorted(set(frequencies)) or None,
            'detail': '; '.join(detail),
            'basis': '%d %s event(s) in the study' % (len(found), name.lower()),
            'response': 'Not scored',
        })

    notes = []
    if anyPerformed:
        notes.append('Whether a procedure produced a change is not scored here. '
                     'SCORE treats a photoparoxysmal response, or a build-up on '
                     'hyperventilation, as a finding for the reader to judge; the '
                     'times above are given so those periods can be reviewed.')
    notes.append('Sleep is an activation procedure too, and is reported on the '
                 'sleep page rather than here. Sleep deprivation is a history '
                 'item that no study records.')
    return {'procedures': procedures, 'notes': notes,
            'any_performed': anyPerformed}


def readDevice(studyPath):
    """Acquisition device details from the study's .sdy, where they are filled in."""
    import xml.etree.ElementTree as ET
    studyPath = studyPath.rstrip('\\/')
    matches = glob.glob(os.path.join(studyPath, '*.sdy'))
    if not matches:
        return None
    try:
        root = ET.parse(matches[0]).getroot()
    except (ET.ParseError, OSError):
        return None
    device = root.find('Device')
    study = root.find('Study')
    if device is None:
        return None

    def clean(value):
        # ProfusionEEG writes '-' for an unset field.
        value = (value or '').strip()
        return None if value in ('', '-') else value

    return {'type': clean(device.get('DeviceType')),
            'name': clean(device.get('DeviceName')),
            'description': clean(device.get('DeviceDescription')),
            'serial': clean(device.get('SerialNumber')),
            'montage': clean(study.get('default_montage')) if study is not None else None,
            'electrode_placement': (clean(study.get('default_electrode_placement'))
                                    if study is not None else None),
            'file_version': clean(root.get('file_version'))}


def sensorGroup(channels):
    """Describe the electrode array, in the spirit of SCORE's sensor-group field."""
    import studylist
    present = {studylist.CHANNEL_ALIASES.get(c, c) for c in (channels or [])}
    required = [c for c in studylist.REQUIRED_CHANNELS if c in present]
    extra = len(present) - len(required)
    if len(required) == len(studylist.REQUIRED_CHANNELS):
        text = 'Full 10-20 array (%d electrodes)' % len(required)
    else:
        missing = [c for c in studylist.REQUIRED_CHANNELS if c not in present]
        text = ('Incomplete 10-20 array (%d of %d; missing %s)'
                % (len(required), len(studylist.REQUIRED_CHANNELS), ', '.join(missing)))
    if extra > 0:
        text += ', plus %d further channel(s)' % extra
    return text


class DurationAccount:
    """What was recorded, what was loaded, and what was actually analysed.

    Every SCORE incidence and prevalence band is a rate, and the denominator is
    the duration assessed - not the length of the recording. Keeping the three
    apart, and reporting them, is what stops a pipeline that discards half its
    epochs from silently halving every rate it produces.
    """

    def __init__(self, recordedSeconds=None, loadedSeconds=None,
                 analysedSeconds=None, epochLength=None, epochsRetained=None,
                 epochsTotal=None):
        self.recorded = recordedSeconds
        self.loaded = loadedSeconds
        self.analysed = analysedSeconds
        self.epochLength = epochLength
        self.epochsRetained = epochsRetained
        self.epochsTotal = epochsTotal
        # (identified bad, total) when rejection was skipped because too few
        # epochs would have survived it
        self.rejectionSkipped = None

    @property
    def retainedFraction(self):
        if not self.loaded or self.analysed is None:
            return None
        return max(0.0, min(1.0, self.analysed / float(self.loaded)))

    def lines(self):
        """Report lines, in the order a reader would want them."""
        out = []
        if self.recorded:
            out.append('Recorded in the study: %s' % _hms(self.recorded))
        if self.loaded:
            out.append('Loaded for analysis: %s' % _hms(self.loaded))
        if self.analysed is not None:
            detail = ''
            if self.epochsTotal:
                detail = ' (%d of %d epochs of %gs retained)' % (
                    self.epochsRetained or 0, self.epochsTotal, self.epochLength or 0)
            fraction = self.retainedFraction
            share = '' if fraction is None else ', %.0f%% of what was loaded' % (fraction * 100)
            out.append('Analysed after artifact rejection: %s%s%s'
                       % (_hms(self.analysed), share, detail))
        if self.rejectionSkipped:
            bad, total = self.rejectionSkipped
            out.append('WARNING: %d of %d epochs were identified as artifact but NOT '
                       'removed - rejecting them would have left too few to analyse. '
                       'The analysis ran on the full set, and the drop ratio reported '
                       'elsewhere counts epochs identified, not removed.' % (bad, total))
        return out

    def asDict(self):
        return {'recorded_seconds': self.recorded, 'loaded_seconds': self.loaded,
                'analysed_seconds': self.analysed,
                'retained_fraction': self.retainedFraction,
                'epochs_retained': self.epochsRetained, 'epochs_total': self.epochsTotal,
                'epoch_length': self.epochLength}


def _hms(seconds):
    if seconds is None:
        return '-'
    seconds = int(round(seconds))
    if seconds < 60:
        return '%d s' % seconds
    return '%d:%02d:%02d (%d s)' % (seconds // 3600, (seconds % 3600) // 60,
                                    seconds % 60, seconds)


def describeRecording(studyPath, raw=None, channels=None, ageYears=None,
                      ageSource=None, durations=None, sourceSampleRate=None,
                      analysisSampleRate=None, analysisFilter=None, verbose=True):
    """Assemble SCORE's patient and recording-conditions sections.

    studyPath : the study folder, for a native ProfusionEEG study. Other formats
                carry none of this metadata, and the fields say so rather than
                being filled with plausible defaults.
    """
    studyPath = (studyPath or '').rstrip('\\/')
    isStudy = profusion.isProfusionStudy(studyPath)

    meta = profusion.readStudyMetadata(studyPath) if isStudy else None
    patient = profusion.readPatientInfo(studyPath) if isStudy else None
    device = readDevice(studyPath) if isStudy else None
    filters = readFilterSettings(studyPath) if isStudy else None

    out = {
        'source': os.path.basename(studyPath) or studyPath,
        'is_study': isStudy,
        'patient': {},
        'conditions': {},
        'durations': (durations.asDict() if durations else None),
        'duration_lines': (durations.lines() if durations else []),
        'technologist_fields': list(TECHNOLOGIST_FIELDS),
        'notes': [],
    }

    # --- patient ---------------------------------------------------------
    if patient:
        name = ' '.join(x for x in (patient.get('given_name'), patient.get('surname')) if x)
        out['patient']['Name'] = name or NOT_RECORDED
        out['patient']['Sex'] = patient.get('sex') or NOT_RECORDED
        dob = patient.get('dob')
        out['patient']['Date of birth'] = dob.strftime('%Y-%m-%d') if dob else NOT_RECORDED
        if patient.get('dob_ambiguous'):
            out['notes'].append(
                'Date of birth "%s" in the study has no day/month marker and was read '
                'month-first. Confirm it - the normal limits of the posterior dominant '
                'rhythm depend on age.' % patient.get('dob_raw'))
    else:
        out['patient']['Name'] = NOT_RECORDED
        out['patient']['Sex'] = NOT_RECORDED
        out['patient']['Date of birth'] = NOT_RECORDED

    if ageYears is not None:
        out['patient']['Age at recording'] = ('%.1f years' % ageYears if ageYears >= 1
                                              else '%.0f months' % (ageYears * 12))
        if ageSource:
            out['patient']['Age at recording'] += ' (from %s)' % ageSource
    else:
        out['patient']['Age at recording'] = 'unavailable%s' % (
            ' - %s' % ageSource if ageSource else '')

    # --- recording conditions --------------------------------------------
    conditions = out['conditions']
    if meta and meta.get('recording_date'):
        conditions['Date and time'] = meta['recording_date'].strftime('%Y-%m-%d %H:%M:%S')
    else:
        conditions['Date and time'] = NOT_RECORDED

    # The rate as acquired, which is not raw.info['sfreq'] by the time the
    # pipeline is done with it - that has been resampled to 125 Hz.
    sfreq = sourceSampleRate or (meta or {}).get('sfreq')
    conditions['Acquisition sample rate'] = '%g Hz' % sfreq if sfreq else NOT_RECORDED
    if analysisSampleRate:
        resampled = ' (resampled)' if sfreq and analysisSampleRate != sfreq else ''
        conditions['Analysis sample rate'] = '%g Hz%s' % (analysisSampleRate, resampled)

    conditions['Sensor group'] = sensorGroup(
        channels if channels is not None else ((meta or {}).get('ch_names')))

    # The study's own setting-change events, which carry what was actually
    # applied. Several studies have no FilterSettings.xml at all, and these
    # events are the only record of the settings SCORE asks for.
    events = _studyEvents(studyPath) if isStudy else []
    eventSettings = readEventSettings(studyPath, events=events) if events else None

    if filters:
        if filters['uniform']:
            g = filters['groups'][0]
            conditions['Review filters'] = _filterText(g)
        else:
            conditions['Review filters'] = '; '.join(
                'group %s: %s' % (g['group'], _filterText(g)) for g in filters['groups'])
    elif eventSettings:
        parts = []
        for label in ('High pass', 'Low pass', 'Notch'):
            entry = eventSettings.get(label)
            if entry:
                parts.append('%s %s %s' % (label.lower(),
                                           ' / '.join(entry['values']),
                                           entry['unit']).strip())
        conditions['Review filters'] = (', '.join(parts) if parts else NOT_RECORDED)
        if parts:
            conditions['Review filters'] += ' (from the study\'s own setting events)'
    else:
        conditions['Review filters'] = NOT_RECORDED

    if eventSettings:
        for label in ('Sensitivity', 'Time base', 'Montage sequence',
                      'Electrode placement'):
            entry = eventSettings.get(label)
            if not entry or label in conditions:
                continue
            text = ' / '.join(entry['values'])
            if entry['unit']:
                text += ' ' + entry['unit']
            if entry.get('changes', 0) > len(entry['values']):
                text += ' (changed %d times)' % entry['changes']
            conditions[label] = text

    if analysisFilter:
        conditions['Analysis filter'] = analysisFilter

    if device:
        hardware = ' '.join(x for x in (device.get('type'), device.get('name')) if x)
        conditions['Device'] = hardware or NOT_RECORDED
        if device.get('serial'):
            conditions['Device'] += ' (serial %s)' % device['serial']
        conditions['Montage'] = device.get('montage') or NOT_RECORDED
        if device.get('electrode_placement'):
            conditions['Electrode placement'] = device['electrode_placement']
        if device.get('file_version'):
            conditions['Study format'] = 'ProfusionEEG %s' % device['file_version']
    else:
        conditions['Device'] = NOT_RECORDED

    out['activation'] = readActivation(studyPath, events=events) if events else None

    if not isStudy:
        out['notes'].append(
            'This input is not a native ProfusionEEG study, so it carries no device, '
            'montage, filter or patient metadata. Those fields are blank rather than '
            'assumed.')

    if verbose:
        printRecording(out)
        printActivation(out.get('activation'))
    return out


def _filterText(group):
    parts = []
    if group.get('high_pass'):
        parts.append('high pass %s Hz' % group['high_pass'])
    if group.get('low_pass'):
        parts.append('low pass %s Hz' % group['low_pass'])
    notch = group.get('notch')
    parts.append('notch %s Hz' % notch if notch and notch not in ('0', '0.00') else 'notch off')
    return ', '.join(parts)


def printActivation(activation):
    """Log the activation procedures."""
    if not activation:
        return
    print('--- Activation procedures (SCORE) ---')
    for procedure in activation['procedures']:
        print('  %-22s %s' % (procedure['name'], procedure['state']))
        if procedure.get('onset_seconds') is not None:
            print('  %-22s   from %s%s' % ('', _hms(procedure['onset_seconds']),
                                           (', %s' % procedure['detail'])
                                           if procedure.get('detail') else ''))
        print('  %-22s   response: %s (%s)'
              % ('', procedure['response'], procedure['basis']))
    for note in activation.get('notes') or []:
        print('  NOTE: %s' % note)


def printRecording(described):
    """Log the recording description, for the run log."""
    print('--- Patient and recording conditions (SCORE) ---')
    for label, value in described['patient'].items():
        print('  %-26s %s' % (label + ':', value))
    for label, value in described['conditions'].items():
        print('  %-26s %s' % (label + ':', value))
    for line in described['duration_lines']:
        print('  %-26s %s' % ('', line))
    for note in described['notes']:
        print('  NOTE: %s' % note)
