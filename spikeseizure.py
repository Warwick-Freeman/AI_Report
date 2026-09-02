############################################
# Spike and seizure detections, scored against SCORE.
#
# Maps the output of the Compumedics SpikeAndSeizure detector onto SCORE terms:
# spikes into Interictal findings (section 8, Table 5, epileptiform interictal
# activity) and electrographic seizures into Episodes (section 10, Table 9).
#
# The detector's own output structure is, from
# CMEEGAnalysis/EventDetection/EventDetection.h:
#
#   struct EventStruct {
#       long long nStart, nEnd, nLatency;   // nStart/nEnd are SAMPLE indices
#       int nIndex, nType;
#       wchar_t wAnnotation[_MAX_PATH];
#       std::vector<int> vnDetections;      // channel indices
#   };
#   struct Spike { float fValue; int nChannelIndex; };
#
# Two things about that structure drive the mapping, and both are worth stating
# because they bound what can honestly be reported:
#
#   nStart and nEnd are segment boundaries, not the extent of the graphoelement -
#   EventDetection.cpp derives nStart from m_nStartSamplePage plus a multiple of
#   the half-segment length. So the duration of a spike detection says nothing
#   about the spike, and morphology CANNOT be inferred from it. SCORE separates
#   Spike from Sharp-wave by duration (under 70 ms versus 70-200 ms); this
#   detector does not make that distinction and neither does this module.
#
#   The annotation for a spike is the comma-separated list of channel labels
#   carrying it, built from m_vSpikes[].nChannelIndex. So location survives even
#   when only the annotation text is available - which is the case when reading
#   detections back from a study through cmpeeg, whose Event object has no
#   channel list. A seizure annotation is only "Seizure (N)", a channel count.
############################################
import re

import eventtypes

import numpy as np

import interictal
import score_common as sc

# SCORE Table 5 - epileptiform interictal activity.
SPIKE = 'Spike'
SHARP_WAVE = 'Sharp-wave'
SPIKE_AND_SLOW_WAVE = 'Spike-and-slow-wave'
EPILEPTIFORM_MORPHOLOGY = 'Epileptiform interictal activity'

# SCORE Table 9 - names of episodes.
EEG_SEIZURE = 'Electroencephalographic seizure'

# SCORE Table 12 - ictal EEG activity. The detector reports that a seizure
# pattern was present, not which pattern, so this stays unscored.
NOT_DETERMINED = 'Not possible to determine'

# The detector's own event-type bases, from EventDetection.cpp:
#   Detection.nType = EVTY_SPIKE_DETECTION + m_nSequence + 1
# The sequence lets several detector instances coexist, so a type is matched by
# range rather than equality. Supply the real bases via typeBases= if they
# differ in your build; these are recognised by annotation as well, which is
# what actually distinguishes the two in practice.
SEIZURE_ANNOTATION = re.compile(r'^\s*seizure\b', re.I)
CHANNEL_LIST = re.compile(r'^[A-Za-z]{1,2}[0-9z]{1,2}(\s*,\s*[A-Za-z]{1,2}[0-9z]{1,2})*\s*$')


class Detection:
    """One detection, independent of how it was obtained.

    A plain mirror of EventStruct so the mapping can be built and tested without
    the detector DLL, and so detections read back from a study through cmpeeg
    land in the same shape.
    """

    def __init__(self, startSample=None, endSample=None, annotation='',
                 channels=None, typeCode=None, latencySamples=None, index=None,
                 startSeconds=None, endSeconds=None, amplitudes=None):
        self.startSample = startSample
        self.endSample = endSample
        self.startSeconds = startSeconds
        self.endSeconds = endSeconds
        self.annotation = annotation or ''
        # Channel names. Indices are resolved to names on construction so the
        # rest of the module never has to care which source it came from.
        self.channels = list(channels or [])
        self.typeCode = typeCode
        self.latencySamples = latencySamples
        self.index = index
        # {channel: magnitude} from Spike.fValue, for the location maximum.
        self.amplitudes = dict(amplitudes or {})

    def seconds(self, sampleRate):
        """(onset, duration) in seconds."""
        if self.startSeconds is not None:
            start = float(self.startSeconds)
            end = float(self.endSeconds) if self.endSeconds is not None else start
        elif self.startSample is not None and sampleRate:
            start = self.startSample / float(sampleRate)
            end = (self.endSample / float(sampleRate)
                   if self.endSample is not None else start)
        else:
            return None, None
        return start, max(0.0, end - start)

    @property
    def isSeizure(self):
        return bool(SEIZURE_ANNOTATION.match(self.annotation))


def parseAnnotationChannels(annotation):
    """Channel labels out of a spike annotation.

    The detector writes them comma-separated, e.g. "Fp1,F7,T3". A seizure
    annotation is "Seizure (3)" and yields nothing, which is correct - that is a
    channel count, not a list of names.
    """
    text = (annotation or '').strip()
    if not text or not CHANNEL_LIST.match(text):
        return []
    return [part.strip() for part in text.split(',') if part.strip()]


def detectionsFromEventStructs(events, channelLabels, sampleRate=None,
                               spikeAmplitudes=None):
    """Convert EventStruct records from the detector into Detections.

    events        : objects (or dicts) with nStart, nEnd, nType, wAnnotation and
                    vnDetections, as a cmspike extension would return.
    channelLabels : DataPage.vwChannelLabels, so vnDetections indices resolve.
    spikeAmplitudes: optional {eventIndex: {channel: magnitude}} from Spike.
    """
    labels = list(channelLabels or [])
    out = []
    for event in events or []:
        get = (event.get if isinstance(event, dict) else
               lambda k, d=None: getattr(event, k, d))
        indices = list(get('vnDetections', None) or [])
        names = [labels[i] for i in indices if 0 <= i < len(labels)]
        annotation = get('wAnnotation', '') or ''
        if not names:
            # Fall back to the annotation, which carries the labels for spikes.
            names = parseAnnotationChannels(annotation)
        index = get('nIndex', None)
        out.append(Detection(
            startSample=get('nStart', None), endSample=get('nEnd', None),
            annotation=annotation, channels=names, typeCode=get('nType', None),
            latencySamples=get('nLatency', None), index=index,
            amplitudes=(spikeAmplitudes or {}).get(index)))
    return out


def detectionsFromStudyEvents(events, spikeTypes=None):
    """Convert events read back from a study through cmpeeg into Detections.

    cmpeeg's Event carries type, type_str, start_ns, duration_ns, id and text -
    no channel list - but for spikes the detector put the channel labels in the
    text, so the location survives. Times are nanoseconds from study start.
    """
    wanted = tuple(t.upper() for t in (spikeTypes or
                                       ('SPIKE', 'REVEALSPIKE', 'REVEALSPIKEBURST',
                                        'REVEALRHYTHMBURST')))
    out = []
    for event in events or []:
        typeStr = (getattr(event, 'type_str', '') or '').upper()
        text = getattr(event, 'text', '') or ''
        if typeStr not in wanted and not SEIZURE_ANNOTATION.match(text):
            continue
        start = getattr(event, 'start_ns', 0) / 1e9
        duration = getattr(event, 'duration_ns', 0) / 1e9
        out.append(Detection(startSeconds=start, endSeconds=start + duration,
                             annotation=text,
                             channels=parseAnnotationChannels(text),
                             typeCode=typeStr, index=getattr(event, 'id', None)))
    return out


def _locationOver(detections):
    """Pooled SCORE location for a group of detections.

    Returns (location, counts, basisForMaximum). A maximum is only claimed when
    something actually discriminates between the electrodes: spike amplitudes if
    the detector supplied them, otherwise how often each electrode was
    implicated - and if every electrode ties, no maximum is named at all. SCORE
    records the location maximum as the electrode of peak negativity, so
    inventing one from a tie would assert more than the data says.
    """
    counts, magnitudes = {}, {}
    for detection in detections:
        for channel in detection.channels:
            counts[channel] = counts.get(channel, 0) + 1
        for channel, value in (detection.amplitudes or {}).items():
            magnitudes[channel] = max(magnitudes.get(channel, 0.0), abs(float(value)))

    def discriminates(values):
        return len(set(round(v, 6) for v in values.values())) > 1

    if magnitudes and discriminates(magnitudes):
        return (sc.locationFromChannels(list(counts), magnitudes), counts,
                'detected spike amplitude')
    if counts and discriminates(counts):
        return (sc.locationFromChannels(list(counts), counts), counts,
                'how often each electrode was implicated')
    # Nothing separates them - report the region without naming a maximum.
    return sc.locationFromChannels(list(counts)), counts, None


def scoreSpikesAndSeizures(detections, analysedSeconds, sampleRate=None,
                           verbose=True):
    """Score detections as SCORE findings.

    Returns {'interictal': [...], 'episodes': [...], 'measures': {}, 'notes': []}
    where interictal entries render on the Interictal Findings page and episodes
    on the Episodes page.
    """
    out = {'interictal': [], 'episodes': [], 'measures': {}, 'notes': []}
    detections = list(detections or [])
    out['measures']['detections'] = len(detections)
    if not detections:
        if verbose:
            printSpikeSeizure(out)
        return out
    if not analysedSeconds or analysedSeconds <= 0:
        out['notes'].append('The analysed duration is unknown, so incidence and '
                            'prevalence cannot be banded.')
        analysedSeconds = None

    spikes = [d for d in detections if not d.isSeizure]
    seizures = [d for d in detections if d.isSeizure]
    out['measures']['spike_detections'] = len(spikes)
    out['measures']['seizure_detections'] = len(seizures)

    # --- spikes: epileptiform interictal activity -------------------------
    if spikes:
        times = []
        for detection in spikes:
            start, _ = detection.seconds(sampleRate)
            if start is not None:
                times.append(start)
        location, counts, maximumBasis = _locationOver(spikes)
        band, rate = sc.incidenceBand(len(spikes), analysedSeconds) \
            if analysedSeconds else (None, None)
        temporal = (interictal.temporalFeaturesFromTimes(times, analysedSeconds)
                    if times and analysedSeconds else {})

        basis = ('%d detection(s) from the spike detector over %s'
                 % (len(spikes),
                    '%.0f s examined' % analysedSeconds if analysedSeconds
                    else 'an unknown duration'))
        if counts:
            distinct = len(set(counts.values())) > 1
            top = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))[:4]
            if distinct:
                basis += '; most often on %s' % ', '.join(
                    '%s (%d)' % (c, n) for c, n in top)
            else:
                basis += '; on %s in every detection' % ', '.join(
                    c for c, _ in sorted(counts.items()))
        basis += ('. Location maximum from %s' % maximumBasis if maximumBasis else
                  '. No maximum is named - nothing distinguishes the implicated '
                  'electrodes')

        out['interictal'].append({
            'name': SPIKE, 'morphology': EPILEPTIFORM_MORPHOLOGY,
            'location': location, 'prevalence': None, 'fraction': None,
            'count': len(spikes), 'incidence': band,
            'mode_of_appearance': temporal.get('mode', NOT_DETERMINED),
            'discharge_pattern': 'Single discharges',
            'median_interval_s': temporal.get('median_interval_s'),
            'interval_cv': temporal.get('cv'),
            'timing_basis': temporal.get('reason', ''),
            'confidence': 'high', 'basis': basis})
        out['notes'].append(
            'The detector reports that a spike was detected, not its morphology. '
            'SCORE separates Spike from Sharp-wave and Spike-and-slow-wave by '
            'duration and shape, and the detection window is a segment boundary '
            'rather than the extent of the graphoelement, so the subtype is left '
            'for the reader.')

    # --- seizures: episodes ------------------------------------------------
    for detection in seizures:
        start, duration = detection.seconds(sampleRate)
        location, counts, _ = _locationOver([detection])
        channelCount = None
        match = re.search(r'\((\d+)\)', detection.annotation or '')
        if match:
            channelCount = int(match.group(1))
        basis = 'seizure detector'
        if channelCount is not None:
            basis += ', %d channel(s) active' % channelCount
        if not counts:
            basis += ('. The seizure annotation carries a channel count rather '
                      'than labels, so no location is scored')
        out['episodes'].append({
            'name': EEG_SEIZURE, 'location': location,
            'onset_seconds': None if start is None else round(start, 1),
            'duration_seconds': None if duration is None else round(duration, 1),
            'duration_band': sc.durationBand(duration),
            'ictal_pattern': NOT_DETERMINED,
            'semiology': NOT_DETERMINED,
            'confidence': 'high', 'basis': basis})

    if seizures:
        out['notes'].append(
            'Seizures are scored as electrographic only. SCORE requires the '
            'semiology, the electro-clinical correlation and the evolution of '
            'the ictal pattern, none of which the detector supplies and all of '
            'which need the video and the clinical record.')

    if verbose:
        printSpikeSeizure(out)
    return out


def printSpikeSeizure(result):
    """Log the scored detections."""
    print('--- Spikes and seizures (SCORE) ---')
    if not result['interictal'] and not result['episodes']:
        print('  no detections')
    for f in result['interictal']:
        print('  %-22s %s' % (f['name'] + ':', f['location']['text']))
        print('  %-22s   %s' % ('', f.get('incidence') or ''))
        print('  %-22s   mode of appearance: %s' % ('', f.get('mode_of_appearance')))
        if f.get('timing_basis'):
            print('  %-22s     %s' % ('', f['timing_basis']))
        print('  %-22s   %s' % ('', f['basis']))
    for e in result['episodes']:
        print('  %-22s %s' % (e['name'] + ':', e['location']['text']))
        print('  %-22s   onset %ss, duration %ss (%s)'
              % ('', e.get('onset_seconds'), e.get('duration_seconds'),
                 e.get('duration_band')))
        print('  %-22s   %s' % ('', e['basis']))
    for note in result.get('notes', []):
        print('  NOTE: %s' % note)


def detectionsFromAnnotations(annotations, spikeHints=('spike', 'reveal'),
                              seizureHints=('seizure',)):
    """Detections from MNE annotations carried across from a study.

    profusion.py copies a study's events onto the Raw as annotations, in the form
    "<TYPE>: <text>". A spike detection's text is the comma-separated channel
    list, so the location survives that round trip.
    """
    out = []
    if annotations is None:
        return out
    for i in range(len(annotations)):
        description = annotations.description[i] or ''
        head, _, tail = description.partition(':')
        label = head.strip().lower()
        text = tail.strip() or head.strip()
        isSpike = any(h in label for h in spikeHints)
        isSeizure = any(h in label for h in seizureHints) or \
            SEIZURE_ANNOTATION.match(text)
        if not (isSpike or isSeizure):
            continue
        start = float(annotations.onset[i])
        duration = float(annotations.duration[i] or 0.0)
        out.append(Detection(
            startSeconds=start, endSeconds=start + duration,
            annotation=text if isSpike else (text or 'Seizure'),
            channels=parseAnnotationChannels(text), typeCode=head.strip()))
    return out


# Event TYPES a detector writes into a study.
#
# The reliable discriminator is the numeric EventTypeID, and nothing else. Two
# findings from the demo studies settled that:
#
#   Event text is whatever the person at the keyboard typed. Matching it turned
#   'Cz,F3/C3, F4/C4 spikes' (a technologist noting what they saw), and
#   'immediate post-ictal' and 'later post-ictal' (both on the substring
#   "ictal"), into scored epileptiform findings on Demo.eeg - a study no
#   detector has ever run on. 06MS.eeg has an operator note reading
#   '?sharp wave', which is a question, not a finding.
#
#   Type names mostly do not exist. EEGEventString is a pick-list of predefined
#   annotation texts, every row of it EventTypeID 1, and it is empty outright in
#   four of the seven studies. studyevents only reports a label where a type id
#   maps to exactly one string, so a pick-list yields nothing.
#
# Hence: pass typeIds with the detector's own EventTypeID values. The name
# patterns below are a secondary route for a detector that names its event type,
# and can no longer fire on a pick-list entry.
STUDY_SPIKE_TYPES = (r'\bspikes?\b', r'\breveal\b', r'\bepileptiform\b',
                     r'\bsharp[\s-]?waves?\b', r'\bspike[\s-]?detection\b')
STUDY_SEIZURE_TYPES = (r'\bseizures?\b', r'\bictal\b', r'\bseizure[\s-]?detection\b')
STUDY_TYPE_EXCLUSIONS = (r'post[\s-]?ictal', r'\binter[\s-]?ictal\b')


def _matchesAny(label, patterns):
    return any(re.search(p, label, re.I) for p in patterns)


def detectionsFromStudy(studyPath, spikeTypes=None, seizureTypes=None,
                        typeIds=None, includeReveal=False, verbose=True):
    """Detections read straight out of a study's event database.

    This is the route to prefer: the detector can be run during acquisition
    inside ProfusionEEG, so its detections are already in the study when the
    recording finishes. Nothing here links against or recompiles the cleared
    detector - it reads a study, which is what any review tool does.

    Events are selected by TYPE, not by text. Pass typeIds={'spike': [...],
    'seizure': [...]} to select by numeric EventTypeID, which is the most
    reliable option once the detector's own type codes are known.

    Location comes from EEGEventGraphs where the study records it, since that is
    the channel association held as data; failing that from the event text,
    which for a spike is the comma-separated channel list the detector writes.
    """
    import studyevents

    spikePatterns = tuple(spikeTypes or STUDY_SPIKE_TYPES)
    seizurePatterns = tuple(seizureTypes or STUDY_SEIZURE_TYPES)
    spikeIds = set((typeIds or {}).get('spike') or ())
    seizureIds = set((typeIds or {}).get('seizure') or ())

    events = studyevents.readEvents(studyPath, verbose=False)
    out, fromTraces, excluded, reveal = [], 0, 0, 0
    for event in events:
        label = (event.get('type_label') or '').strip()
        typeId = event.get('type_id')

        if spikeIds or seizureIds:
            isSpike, isSeizure = typeId in spikeIds, typeId in seizureIds
        else:
            # The plug-in's own event types: eetEEGSpike (74) and eetEEGSeizure
            # (75). This is what identifies a detection - not the event text,
            # which is whoever was at the keyboard.
            isSpike = eventtypes.isSpike(typeId, includeReveal=includeReveal)
            isSeizure = eventtypes.isSeizure(typeId, includeReveal=includeReveal)
            if eventtypes.resolveTypeId(typeId)[0] in eventtypes.REVEAL_TYPES:
                reveal += 1
        if not (isSpike or isSeizure):
            continue

        start = (event['start_ns'] or 0) / 1e9
        duration = (event['duration_ns'] or 0) / 1e9
        channels = list(event.get('traces') or [])
        if channels:
            fromTraces += 1
        else:
            channels = parseAnnotationChannels(event.get('text'))
        out.append(Detection(
            startSeconds=start, endSeconds=start + duration,
            annotation=('Seizure' if isSeizure else (event.get('text') or '')),
            channels=channels, typeCode=typeId, index=event.get('id')))

    if verbose:
        print('--- Detections from the study event database ---')
        print('  %d of %d event(s) matched a detector event type'
              % (len(out), len(events)))
        if reveal and not includeReveal:
            # A different detector. Counting its output as the cleared
            # detector's would misattribute it, so it is named and left out.
            print('  %d Persyst Reveal event(s) present and NOT included - a '
                  'separate detector. Pass includeReveal=True to score them.'
                  % reveal)
        if out:
            print('  %d took location from EEGEventGraphs, %d from the event text'
                  % (fromTraces, len(out) - fromTraces))
        elif events:
            print('  Event types in this study:')
            for (tid, label), count in sorted(
                    studyevents.summariseTypes(events).items(), key=lambda kv: -kv[1]):
                print('     %5dx  type %-8s %s' % (count, tid, label or '(unlabelled)'))
            print('  This study carries no %s (%d) or %s (%d) events, so the '
                  'Spike and Seizure plug-in has not run on it.'
                  % (eventtypes.EVENT_TYPES[eventtypes.SPIKE_TYPES[0]][0],
                     eventtypes.SPIKE_TYPES[0],
                     eventtypes.EVENT_TYPES[eventtypes.SEIZURE_TYPES[0]][0],
                     eventtypes.SEIZURE_TYPES[0]))
            annotations = sum(1 for e in events
                              if eventtypes.isAnnotation(e.get('type_id')))
            if annotations:
                print('  %d event(s) are technologist annotations, which are not '
                      'detections however they are worded.' % annotations)
    return out
