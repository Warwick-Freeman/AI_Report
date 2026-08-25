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

    if filters:
        if filters['uniform']:
            g = filters['groups'][0]
            conditions['Review filters'] = _filterText(g)
        else:
            conditions['Review filters'] = '; '.join(
                'group %s: %s' % (g['group'], _filterText(g)) for g in filters['groups'])
    else:
        conditions['Review filters'] = NOT_RECORDED

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

    if not isStudy:
        out['notes'].append(
            'This input is not a native ProfusionEEG study, so it carries no device, '
            'montage, filter or patient metadata. Those fields are blank rather than '
            'assumed.')

    if verbose:
        printRecording(out)
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
