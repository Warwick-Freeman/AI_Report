############################################
# Native ProfusionEEG 4 study reader.
#
# Reads a Compumedics ProfusionEEG study (a "*.eeg" study folder) straight into
# an MNE Raw object, so the analysis pipeline no longer needs an EDF export as
# an intermediate step.
#
# Signal access goes through Compumedics' own Python extension, cmpeeg
# (cmpeeg.pyd, x64) from ProfusionEEGSDK/PythonSDK, which wraps the
# CMEEGStudyV4 COM server. ProfusionEEG's study format therefore stays the
# single source of truth - nothing here parses the raw .rda files directly.
#
# Channel montage and sample rate are additionally readable from the study's
# .sdy XML without the SDK, which readStudyMetadata() uses to report on a study
# even where cmpeeg is unavailable.
############################################
import os
import glob
import sys
import numpy as np
import mne

# study.read() returns float32 already in volts - measured against
# DemoStudies/Demo.eeg, whose EEG channels come back at ~1.5e-4 peak-to-peak,
# i.e. ~150 uV. MNE also works in volts, so no conversion is needed. Kept as a
# named constant because the SDK does not document the unit, and the AC
# channels report an empty unit string and zero sensitivity.
SDK_UNIT_TO_V = 1.0

# Reads are capped by the SDK at 50,000,000 points (samples x channels); stay
# well under it so a long study is fetched in several passes.
MAX_POINTS_PER_READ = 10_000_000


def isProfusionStudy(path):
    """True if path looks like a ProfusionEEG study (a .eeg folder or its .sdy)."""
    path = path.rstrip('\\/')
    if path.lower().endswith('.eeg'):
        return True
    return path.lower().endswith('.sdy') and os.path.isfile(path)


def _sdkSearchDirs():
    """Candidate directories holding cmpeeg.pyd, most specific first."""
    dirs = []
    envDir = os.environ.get('CMPEEG_PYD_DIR')
    if envDir:
        dirs.append(envDir)
    here = os.path.dirname(os.path.abspath(__file__))
    sdkBuild = os.path.join(here, 'ProfusionEEGSDK', 'PythonSDK', 'cmpeeg', 'cmpeeg', 'x64')
    # Release before Debug: prefer an optimised build when both exist.
    dirs += [os.path.join(sdkBuild, 'Release'), os.path.join(sdkBuild, 'Debug')]
    # An installed copy of the SDK drops cmpeeg.pyd next to its Samples folder.
    dirs.append(os.path.join(os.environ.get('PROGRAMFILES', r'C:\Program Files'),
                             'Compumedics', 'cmpeeg'))
    return dirs


def importCmpeeg():
    """Import the cmpeeg extension, adding the SDK build output to sys.path.

    Raises ImportError listing the directories searched, so a missing SDK is
    obvious rather than surfacing as a bare ImportError deep in the pipeline.
    """
    try:
        import cmpeeg
        return cmpeeg
    except ImportError:
        pass

    searched = []
    for d in _sdkSearchDirs():
        searched.append(d)
        if glob.glob(os.path.join(d, 'cmpeeg*.pyd')):
            if d not in sys.path:
                sys.path.insert(0, d)
            try:
                import cmpeeg
                return cmpeeg
            except ImportError as e:
                raise ImportError(
                    'Found cmpeeg.pyd in %s but it failed to load (%s).\n'
                    'cmpeeg is a 64-bit Python 3.12 extension - check that this '
                    'interpreter matches: %s' % (d, e, sys.version))

    raise ImportError(
        'Reading a native ProfusionEEG study needs the Compumedics cmpeeg '
        'extension (cmpeeg.pyd), which was not found in:\n  '
        + '\n  '.join(searched)
        + '\nBuild it from ProfusionEEGSDK/PythonSDK/cmpeeg (see that folder\'s '
          'README.md), or point CMPEEG_PYD_DIR at the directory holding cmpeeg.pyd.')


# Where a study's own outputs belong.
#
# Everything the analysis produces for one recording - the figures, the saved
# analysis, the structured SCORE data and the document - goes with the recording
# rather than into a shared reports folder. One study's outputs then travel with
# it, and two studies can never write over each other's.
#
# For a native ProfusionEEG study, which is itself a folder, they go into a
# subfolder rather than into the study root. The root belongs to ProfusionEEG:
# it holds EEGData, EEGStudyDB.mdb, the montages and the .sdy descriptor, and
# mixing report files in among them invites one particular accident - a tidy-up
# that matches on the study's name and takes a study file with it. That is not
# hypothetical. It is how 04HO, 05JC and 06MS lost their .sdy descriptors during
# development, because a study's descriptor can share the study's stem. A
# subfolder keeps the two sets of files apart and leaves the root as
# ProfusionEEG wrote it.
REPORT_SUBFOLDER = 'Report'


def studyOutputFolder(studyPath):
    """The folder a study's outputs belong in.

    A ProfusionEEG study is a folder, so its outputs go into a Report subfolder
    inside it - with the study, but not among its own files. A single file, an
    EDF, has no folder of its own, so its outputs go beside it; their names
    carry the study's stem, so two recordings in one folder stay distinct.
    """
    path = (studyPath or '').rstrip('\\/')
    if os.path.isdir(path):
        return os.path.join(path, REPORT_SUBFOLDER)
    return os.path.dirname(os.path.abspath(path)) or '.'


def resolveOutputFolder(destination, studyPath):
    """The output folder to use, honouring an explicit one.

    An empty destination, or the word 'study', means beside the study. Anything
    else is used as given, so a caller that wants everything collected in one
    place can still say so.
    """
    if destination and str(destination).strip().lower() not in ('study', 'auto'):
        return str(destination)
    return studyOutputFolder(studyPath)


def readStudyMetadata(studyPath):
    """Channel names, sample rate and length from the study's .sdy XML.

    Does not need the SDK or a registered COM server, so it works as a
    pre-flight check on any machine. Returns None if no .sdy can be read.
    """
    import xml.etree.ElementTree as ET
    studyPath = studyPath.rstrip('\\/')
    sdy = studyPath
    if not sdy.lower().endswith('.sdy'):
        matches = glob.glob(os.path.join(studyPath, '*.sdy'))
        if not matches:
            return None
        sdy = matches[0]
    try:
        root = ET.parse(sdy).getroot()
    except (ET.ParseError, OSError):
        return None
    study = root.find('Study')
    length = study.get('study_length') if study is not None else None
    return {
        'sdy': sdy,
        'ch_names': [c.get('name') for c in root.iter('Channel')],
        'sfreq': float(study.get('eeg_sample_rate')) if study is not None else None,
        # study_length is nanoseconds in the .sdy
        'study_length': int(length) / 1e9 if length else None,
        'recording_date': _parseSdyDate(study.get('creation_time')) if study is not None else None,
    }


def _parseSdyDate(text):
    """Parse the .sdy creation_time, e.g. '22 Nov 2000 15:14:23'.

    Unambiguous by construction (named month), unlike the numeric dates in
    EEG4PatientInfo.xml.
    """
    if not text:
        return None
    from datetime import datetime
    for fmt in ('%d %b %Y %H:%M:%S', '%d %b %Y', '%Y-%m-%dT%H:%M:%S', '%Y-%m-%d %H:%M:%S'):
        try:
            return datetime.strptime(text.strip(), fmt)
        except ValueError:
            continue
    return None


def readPatientInfo(studyPath):
    """Patient details from the study's EEG4PatientInfo.xml, or None.

    Needs no SDK or COM. Date of birth in that file is a bare numeric date whose
    day/month order is not marked, so it is returned with an 'dob_ambiguous'
    flag: for an adult the ordering rarely matters, but for an infant a
    month-level error moves the normal PDR floor, so a caller that has an
    unambiguous date of birth should prefer it.
    """
    import xml.etree.ElementTree as ET
    from datetime import datetime

    studyPath = studyPath.rstrip('\\/')
    path = os.path.join(studyPath, 'EEG4PatientInfo.xml')
    if not os.path.isfile(path):
        return None
    try:
        root = ET.parse(path).getroot()
    except (ET.ParseError, OSError):
        return None

    def text(tag):
        node = root.find(tag)
        return (node.text or '').strip() if node is not None else ''

    raw = text('DOB')
    dob, ambiguous = None, False
    if raw:
        parts = raw.replace('-', '/').split('/')
        # ProfusionEEG writes month first; the order is only recoverable when
        # one field exceeds 12.
        for fmt in ('%m/%d/%Y', '%d/%m/%Y'):
            try:
                dob = datetime.strptime(raw, fmt)
                break
            except ValueError:
                continue
        if dob and len(parts) == 3:
            try:
                ambiguous = int(parts[0]) <= 12 and int(parts[1]) <= 12
            except ValueError:
                ambiguous = True

    return {'surname': text('Surname'), 'given_name': text('GivenName'),
            'sex': text('Sex'), 'dob': dob, 'dob_raw': raw,
            'dob_ambiguous': ambiguous}


def ageYearsAt(dob, recordingDate):
    """Age in years at the recording, or None if either date is missing."""
    if dob is None or recordingDate is None:
        return None
    days = (recordingDate - dob).days
    return None if days < 0 else days / 365.2425


def _channelTypes(channels):
    """Map ProfusionEEG channels onto MNE channel types.

    Only the 10-20 EEG channels matter downstream, but every channel needs a
    type for mne.create_info, and typing ECG as EEG would let it into the
    montage and re-referencing steps.
    """
    types = []
    for ch in channels:
        name = (ch.name or '').strip().upper()
        if name in ('ECG', 'EKG'):
            types.append('ecg')
        elif name in ('EOG', 'LOC', 'ROC', 'E1', 'E2'):
            types.append('eog')
        elif name.startswith('EMG') or name in ('CHIN',):
            types.append('emg')
        elif name.startswith('PG') or not any(c.isalpha() for c in name):
            # PG is the photic/patient-event trace; purely numeric names are
            # unused device inputs. Neither is EEG.
            types.append('misc')
        else:
            types.append('eeg')
    return types


def _uniqueNames(channels):
    """Channel names, de-duplicated - mne.create_info rejects repeats."""
    names, seen = [], {}
    for i, ch in enumerate(channels):
        name = (ch.name or '').strip() or 'CH%d' % (i + 1)
        if name in seen:
            seen[name] += 1
            name = '%s-%d' % (name, seen[name])
        else:
            seen[name] = 0
        names.append(name)
    return names


def _pickSegments(segments, segmentMode):
    """Choose which data segments to read.

    A study can contain gaps (lost packets) and a read must never cross one.
    'longest' takes the single biggest contiguous block, 'concat' joins every
    block end-to-end.
    """
    if not segments:
        # The data reader builds this list from the study's raw-data index. An
        # empty list on a study that plainly holds signal (EEGData/*.rda files
        # present) points at a missing or stale index rather than an empty
        # recording - ProfusionEEG's own repair rebuilds it.
        raise RuntimeError(
            'The study reports no recorded data segments, so there is no signal '
            'to read. If the study does contain data, its raw-data index '
            '(EEGData/*.rdi) is missing or stale - open and repair the study in '
            'ProfusionEEG first.')
    if segmentMode == 'concat':
        return list(segments)
    if segmentMode == 'longest':
        return [max(segments, key=lambda s: s.sample_duration)]
    raise ValueError("segmentMode must be 'longest' or 'concat', got %r" % segmentMode)


def _readSegment(study, segment, nChannels, maxSamples=None):
    """Read one data segment as (channels, samples) float32, in chunks."""
    total = int(segment.sample_duration)
    if maxSamples is not None:
        total = min(total, int(maxSamples))
    if total <= 0:
        return np.empty((nChannels, 0), dtype=np.float32)

    chunk = max(1, MAX_POINTS_PER_READ // max(1, nChannels))
    blocks = []
    offset = 0
    while offset < total:
        n = min(chunk, total - offset)
        block = study.read(int(segment.sample_start) + offset, int(n))
        blocks.append(np.asarray(block, dtype=np.float32))
        offset += n
    return blocks[0] if len(blocks) == 1 else np.concatenate(blocks, axis=1)


def readProfusionRaw(studyPath, segmentMode='longest', maxSeconds=None,
                     unitScale=SDK_UNIT_TO_V, annotate=True, verbose=True):
    """Open a ProfusionEEG study and return (raw, events).

    studyPath   : the study folder ("...\\Demo.eeg") or the .sdy inside it.
    segmentMode : 'longest' reads the biggest gap-free block (default);
                  'concat' joins every recorded block end-to-end, which
                  recovers more data from a fragmented study at the cost of a
                  discontinuity at each join.
    maxSeconds  : cap on how much signal to load, for long overnight studies.
    unitScale   : factor converting the SDK's samples to volts (the SDK already
                  returns volts, so 1.0).
    annotate    : copy ProfusionEEG events onto the Raw as MNE annotations.

    events is always [] - it mirrors the eyes-open/eyes-closed onset list that
    the .fif branch of eegProcess.getRawData builds, which ProfusionEEG studies
    do not carry.
    """
    cmpeeg = importCmpeeg()

    study = cmpeeg.open_study(studyPath.rstrip('\\/'))
    try:
        sfreq = float(study.sample_rate)
        channels = study.channels
        chNames = _uniqueNames(channels)
        chTypes = _channelTypes(channels)
        nChannels = len(chNames)

        segments = _pickSegments(study.data_segments, segmentMode)
        maxSamples = None if maxSeconds is None else int(round(maxSeconds * sfreq))

        if verbose:
            recorded = sum(s.duration for s in study.data_segments)
            print('ProfusionEEG study: %s' % study.study_path)
            print('  %g Hz, %g s metadata length, %g s recorded in %d segment(s)'
                  % (sfreq, study.study_length, recorded, len(study.data_segments)))
            print('  %d channels: %s' % (nChannels, ' '.join(chNames)))
            print('  reading %d segment(s) (%s)%s'
                  % (len(segments), segmentMode,
                     '' if maxSamples is None else ', capped at %g s' % maxSeconds))

        blocks, kept = [], []
        remaining = maxSamples
        for seg in segments:
            if remaining is not None and remaining <= 0:
                break
            block = _readSegment(study, seg, nChannels, remaining)
            if block.shape[1] == 0:
                continue
            blocks.append(block)
            kept.append((seg, block.shape[1]))
            if remaining is not None:
                remaining -= block.shape[1]

        if not blocks:
            raise RuntimeError('No samples could be read from %s' % study.study_path)

        data = blocks[0] if len(blocks) == 1 else np.concatenate(blocks, axis=1)
        # The SDK derives the channel count from the length of the array it gets
        # back; a mismatch here means montage and signal disagree.
        if data.shape[0] != nChannels:
            raise RuntimeError('Read returned %d channels but the montage lists %d'
                               % (data.shape[0], nChannels))

        # Guard against a silent unit mismatch: the SDK documents no unit for
        # AC channels, so check the converted amplitude is plausible EEG.
        eegRows = [i for i, t in enumerate(chTypes) if t == 'eeg']
        if verbose and eegRows:
            p2p_uV = float(np.median(np.ptp(data[eegRows], axis=1))) * unitScale / 1e-6
            print('  read %d samples (%g s); median EEG peak-to-peak %.1f uV'
                  % (data.shape[1], data.shape[1] / sfreq, p2p_uV))
            if not 1.0 <= p2p_uV <= 5000.0:
                print('  WARNING: %.3g uV is an implausible EEG amplitude - check the '
                      'unitScale argument of readProfusionRaw' % p2p_uV)

        info = mne.create_info(ch_names=chNames, sfreq=sfreq, ch_types=chTypes)
        raw = mne.io.RawArray(data * unitScale, info, verbose=False)

        if annotate:
            _annotate(raw, study, kept, sfreq)

        return raw, []
    finally:
        study.close()


def _annotate(raw, study, kept, sfreq):
    """Copy ProfusionEEG events onto raw, and mark the joins between segments.

    Event times in the study are absolute (nanoseconds from study start) while
    raw starts at the first sample actually read, so each event is shifted into
    the concatenated timeline of the segments that were kept.
    """
    onsets, durations, descriptions = [], [], []

    # Map absolute sample -> position in the concatenated raw.
    spans, cursor = [], 0
    for seg, nSamples in kept:
        start = int(seg.sample_start)
        spans.append((start, start + nSamples, cursor))
        cursor += nSamples

    for ev in study.events:
        absSample = (ev.start_ns / 1e9) * sfreq
        for start, end, offset in spans:
            if start <= absSample < end:
                onsets.append((absSample - start + offset) / sfreq)
                durations.append(ev.duration_ns / 1e9)
                label = ev.type_str or 'EVENT'
                descriptions.append('%s: %s' % (label, ev.text) if ev.text else label)
                break

    # A join between two segments is a discontinuity, not real signal - flag it
    # BAD_ so MNE's epoch rejection drops any epoch straddling it.
    for _, _, offset in spans[1:]:
        onsets.append(offset / sfreq)
        durations.append(0.0)
        descriptions.append('BAD_segment_join')

    if onsets:
        raw.set_annotations(mne.Annotations(onsets, durations, descriptions),
                            verbose=False)
