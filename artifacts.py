############################################
# Artifact type classifier, reporting in SCORE's vocabulary.
#
# SCORE (Beniczky et al., Clin Neurophysiol 2017, Table 15) asks for the artifact
# *type* and its location, and scores the significance separately. The existing
# HBOS repair in RepairArtifacts.py answers a different question - "is this
# epoch/channel anomalous" - so it cannot fill that folder. This module names the
# type.
#
# The detectors here are deterministic and physically motivated rather than
# learned: each artifact type on SCORE's list that has an unambiguous signature
# gets a test for that signature, so a finding can be explained to a reader and
# points at a time and a set of electrodes. That matters more than breadth -
# an unexplainable artifact label is not reviewable.
#
# Deliberately NOT detected, because they need clinical context or are not
# separable from the signal alone: nystagmus, sucking, glossokinetic, rocking or
# patting, dialysis, artificial ventilation, induction. Those stay with the
# reader, as does the significance of every artifact found ("recording not
# interpretable" / "reduced diagnostic value" / "does not interfere"), which
# SCORE scores separately and this module never proposes.
#
# Runs on the recording as loaded - before the pipeline's 1-60 Hz filter,
# re-referencing, resampling and channel dropping. Several of these artifacts
# are invisible afterwards: sweat lives below 0.5 Hz, line noise at 50/60 Hz sits
# above the resampled Nyquist, and the ECG channel has been dropped.
############################################
import numpy as np
import mne

import score_common as sc

# ------------------------------------------------------------------ thresholds
# CALIBRATION: conventional / physically-argued values, not validated against
# expert-scored recordings. Gathered here for that reason.

# Narrowband power at 50 or 60 Hz over the neighbouring baseline.
LINE_NOISE_RATIO = 3.0

# A channel is flat when its amplitude stays under this for a whole window.
FLAT_UV = 1.0
FLAT_WINDOW_S = 2.0

# An electrode pop is a step in one channel much larger than the same instant in
# every other channel.
POP_UV = 100.0
POP_ISOLATION = 4.0

# Two electrodes bridged by conductive paste track each other almost exactly.
SALT_BRIDGE_CORRELATION = 0.99
SALT_BRIDGE_MAX_DIFF_UV = 5.0

# Blink amplitude at the frontopolar electrodes. A blink is a brief deflection,
# so a duration window and a refractory gap are needed as well - without them a
# slow drift crossing the threshold is counted many times over.
BLINK_UV = 75.0
BLINK_DURATION_S = (0.05, 0.5)
BLINK_REFRACTORY_S = 0.25

# Horizontal eye movement: F7 and F8 move in opposite directions.
HEOG_CORRELATION = -0.6
HEOG_MIN_UV = 40.0

# Muscle: z-score of high-frequency power, as used by MNE's own detector.
MUSCLE_Z = 4.0
# Chewing is rhythmic muscle activity; its envelope carries a peak in this range.
CHEW_ENVELOPE_HZ = (0.5, 3.0)
CHEW_ENVELOPE_RATIO = 3.0

# Sweat: sub-0.5 Hz power relative to the 1-30 Hz band. Unfiltered EEG is 1/f,
# so slow power always exceeds fast power and a ratio alone flags every
# recording - the absolute excursion is what separates sweat from ordinary
# baseline drift.
SWEAT_RATIO = 15.0
SWEAT_MIN_UV = 100.0

# Movement: a broadband excursion appearing in many channels at once. Measured
# on 1-40 Hz data so that slow baseline drift, which is not movement, does not
# trip the amplitude test.
#
# The test is relative to the recording's own median window amplitude, with an
# absolute floor. A fixed microvolt threshold cannot work here: amplitude
# depends on the reference and the acquisition gain, and on a legitimately
# high-amplitude recording a fixed 200 uV flags almost every window as movement.
# Movement is a transient departure from a recording's own baseline, so that is
# what gets measured.
MOVEMENT_UV = 200.0
MOVEMENT_RELATIVE = 4.0
MOVEMENT_MIN_CHANNELS = 6
MOVEMENT_BAND_HZ = (1.0, 40.0)

# ECG coupling into the EEG, measured at the R peaks.
ECG_COUPLING_UV = 15.0
# Coupling reaching more channels than this is reported as ECG artifact; fewer,
# and it is focal, which is the pulse artifact.
PULSE_MAX_CHANNELS = 2

WINDOW_S = 1.0

ECG_NAMES = ('ECG', 'EKG')
RESP_NAMES = ('Resp', 'Thor', 'Abdo', 'Airflow', 'Respiration', 'Therm')


def _finding(name, location, prevalence=None, fraction=None, count=None,
             incidence=None, confidence='medium', basis=''):
    """One artifact finding in SCORE shape.

    Significance is absent on purpose - SCORE scores an artifact's effect on
    interpretability separately, and that is the reader's judgement.
    """
    return {'name': name, 'location': location, 'prevalence': prevalence,
            'fraction': fraction, 'count': count, 'incidence': incidence,
            'confidence': confidence, 'basis': basis}


def _eegPicks(raw):
    """The 10-20 electrodes present, by name."""
    return [c for c in raw.ch_names if c in sc.ELECTRODE_REGION]


def _named(raw, names):
    """First channel whose name matches one of names, or None."""
    lookup = {c.upper(): c for c in raw.ch_names}
    for n in names:
        for upper, original in lookup.items():
            if upper.startswith(n.upper()):
                return original
    return None


def _windowed(data, sfreq, window=WINDOW_S):
    """Reshape (channels, times) into (channels, windows, samplesPerWindow)."""
    step = max(1, int(round(window * sfreq)))
    usable = (data.shape[1] // step) * step
    if usable < step:
        return None, step
    return data[:, :usable].reshape(data.shape[0], -1, step), step


# ------------------------------------------------------------------- detectors

def _lineNoise(raw, picks, duration):
    """50 or 60 Hz mains pickup, per channel."""
    sfreq = raw.info['sfreq']
    if sfreq <= 130:
        return [], ('sample rate %g Hz cannot resolve mains frequency'
                    '; line-noise detection skipped' % sfreq)
    data = raw.get_data(picks=picks, units='uV')
    from mne.time_frequency import psd_array_welch
    power, freqs = psd_array_welch(data, sfreq, fmin=20, fmax=min(90, sfreq / 2 - 1),
                                  n_fft=int(sfreq * 2), verbose=False)

    findings = []
    for mains in (50.0, 60.0):
        peak = (freqs > mains - 1.5) & (freqs < mains + 1.5)
        base = ((freqs > mains - 8) & (freqs < mains - 3)) | \
               ((freqs > mains + 3) & (freqs < mains + 8))
        if not peak.any() or not base.any():
            continue
        ratios = power[:, peak].max(axis=1) / np.maximum(
            np.median(power[:, base], axis=1), 1e-20)
        hits = [picks[i] for i, r in enumerate(ratios) if r >= LINE_NOISE_RATIO]
        if hits:
            amplitudes = {picks[i]: float(ratios[i]) for i in range(len(picks))}
            # Mains pickup is present throughout, not in bursts.
            band, fraction = sc.prevalenceBand(duration, duration)
            findings.append(_finding(
                '%.0f Hz' % mains, sc.locationFromChannels(hits, amplitudes),
                band, fraction, confidence='high',
                basis='narrowband %.0f Hz power >=%.0fx the neighbouring baseline '
                      'in %d channel(s), peak ratio %.0fx'
                      % (mains, LINE_NOISE_RATIO, len(hits), max(ratios))))
    return findings, None


def _flatChannels(raw, picks, duration):
    """Dead or disconnected electrodes."""
    data = raw.get_data(picks=picks, units='uV')
    windows, _ = _windowed(data, raw.info['sfreq'], FLAT_WINDOW_S)
    if windows is None:
        return [], None
    span = windows.max(axis=2) - windows.min(axis=2)
    flatFraction = (span < FLAT_UV).mean(axis=1)
    hits = [picks[i] for i, f in enumerate(flatFraction) if f > 0.5]
    if not hits:
        return [], None
    worst = float(flatFraction.max())
    band, fraction = sc.prevalenceBand(worst * duration, duration)
    return [_finding(
        'Other artifact (flat or disconnected electrode)',
        sc.locationFromChannels(hits), band, fraction, confidence='high',
        basis='amplitude below %.0f uV for %.0f%% of %.0f s windows in %d channel(s)'
              % (FLAT_UV, worst * 100, FLAT_WINDOW_S, len(hits)))], None


def _electrodePops(raw, picks, duration):
    """Abrupt steps isolated to a single electrode."""
    data = raw.get_data(picks=picks, units='uV')
    if data.shape[1] < 3:
        return [], None
    steps = np.abs(np.diff(data, axis=1))
    counts, amplitudes = {}, {}
    for i, channel in enumerate(picks):
        others = np.delete(steps, i, axis=0)
        # A pop is large in this channel and small everywhere else at that instant.
        isolated = (steps[i] > POP_UV) & (steps[i] > POP_ISOLATION * others.max(axis=0))
        n = int(isolated.sum())
        if n:
            counts[channel] = n
            amplitudes[channel] = float(steps[i][isolated].max())
    if not counts:
        return [], None
    total = sum(counts.values())
    band, rate = sc.incidenceBand(total, duration)
    return [_finding(
        'Electrode pops', sc.locationFromChannels(list(counts), amplitudes),
        count=total, incidence=band, confidence='medium',
        basis='%d step(s) over %.0f uV isolated to one electrode (%s)'
              % (total, POP_UV,
                 ', '.join('%s x%d' % (c, n) for c, n in sorted(counts.items()))))], None


def _saltBridge(raw, picks, duration):
    """Neighbouring electrodes bridged by conductive paste."""
    neighbours = [('Fp1', 'F3'), ('Fp2', 'F4'), ('Fp1', 'F7'), ('Fp2', 'F8'),
                  ('F3', 'C3'), ('F4', 'C4'), ('C3', 'P3'), ('C4', 'P4'),
                  ('P3', 'O1'), ('P4', 'O2'), ('T3', 'T5'), ('T4', 'T6'),
                  ('F7', 'T3'), ('F8', 'T4'), ('T5', 'O1'), ('T6', 'O2'),
                  ('Fz', 'Cz'), ('Cz', 'Pz'), ('F3', 'Fz'), ('F4', 'Fz'),
                  ('C3', 'Cz'), ('C4', 'Cz'), ('P3', 'Pz'), ('P4', 'Pz')]
    present = set(picks)
    bridged, amplitudes = [], {}
    for a, b in neighbours:
        if a not in present or b not in present:
            continue
        pair = raw.get_data(picks=[a, b], units='uV')
        if pair.std(axis=1).min() < 1e-6:
            continue
        correlation = float(np.corrcoef(pair[0], pair[1])[0, 1])
        difference = float(np.percentile(np.abs(pair[0] - pair[1]), 95))
        if correlation >= SALT_BRIDGE_CORRELATION and difference <= SALT_BRIDGE_MAX_DIFF_UV:
            bridged += [a, b]
            amplitudes[a] = amplitudes[b] = correlation
    if not bridged:
        return [], None
    band, fraction = sc.prevalenceBand(duration, duration)
    return [_finding(
        'Salt bridge artifact', sc.locationFromChannels(bridged, amplitudes),
        band, fraction, confidence='medium',
        basis='neighbouring electrodes correlated >=%.2f with <=%.0f uV difference: %s'
              % (SALT_BRIDGE_CORRELATION, SALT_BRIDGE_MAX_DIFF_UV,
                 ', '.join(sorted(set(bridged)))))], None


def _blinks(raw, picks, duration):
    """Eye blinks: large in-phase frontopolar transients."""
    frontopolar = [c for c in ('Fp1', 'Fp2') if c in picks]
    if not frontopolar:
        return [], None
    filtered = raw.copy().pick(frontopolar).filter(0.5, 8.0, verbose=False)
    data = filtered.get_data(units='uV')
    mean = data.mean(axis=0)
    sfreq = filtered.info['sfreq']

    # Count excursions of blink-like duration, merged across a refractory gap.
    # Without both, a slow drift sitting above the threshold is counted as many
    # blinks as it has wobbles.
    above = np.abs(mean) > BLINK_UV
    if not above.any():
        return [], None
    padded = np.concatenate(([0], above.astype(int), [0]))
    edges = np.diff(padded)
    starts = np.flatnonzero(edges == 1)
    ends = np.flatnonzero(edges == -1)

    minSamples = int(BLINK_DURATION_S[0] * sfreq)
    maxSamples = int(BLINK_DURATION_S[1] * sfreq)
    refractory = int(BLINK_REFRACTORY_S * sfreq)
    events, covered = [], 0.0
    for start, end in zip(starts, ends):
        if not minSamples <= (end - start) <= maxSamples:
            continue
        if events and start - events[-1] < refractory:
            continue
        events.append(start)
        covered += (end - start) / sfreq
    if not events:
        return [], None
    count = len(events)
    band, rate = sc.incidenceBand(count, duration)
    prevalence, fraction = sc.prevalenceBand(covered, duration)
    return [_finding(
        'Eye blinks',
        sc.locationFromChannels(frontopolar,
                                {c: float(np.abs(data[i]).max())
                                 for i, c in enumerate(frontopolar)}),
        prevalence, fraction, count=count, incidence=band, confidence='medium',
        basis='%d in-phase frontopolar excursion(s) over %.0f uV lasting '
              '%.2f-%.2f s (0.5-8 Hz)'
              % (count, BLINK_UV, BLINK_DURATION_S[0], BLINK_DURATION_S[1]))], None


def _horizontalEyeMovement(raw, picks, duration):
    """Lateral eye movement: F7 and F8 deflect in opposite directions."""
    if 'F7' not in picks or 'F8' not in picks:
        return [], None
    filtered = raw.copy().pick(['F7', 'F8']).filter(0.3, 3.0, verbose=False)
    data = filtered.get_data(units='uV')
    windows, step = _windowed(data, filtered.info['sfreq'])
    if windows is None:
        return [], None

    hits = 0
    for w in range(windows.shape[1]):
        left, right = windows[0, w], windows[1, w]
        if left.std() < 1e-9 or right.std() < 1e-9:
            continue
        span = max(left.max() - left.min(), right.max() - right.min())
        if span < HEOG_MIN_UV:
            continue
        if float(np.corrcoef(left, right)[0, 1]) <= HEOG_CORRELATION:
            hits += 1
    if not hits:
        return [], None
    covered = hits * step / filtered.info['sfreq']
    band, fraction = sc.prevalenceBand(covered, duration)
    return [_finding(
        'Eye movements (horizontal)', sc.locationFromChannels(['F7', 'F8']),
        band, fraction, confidence='medium',
        basis='%d window(s) with F7/F8 anti-correlated <=%.1f at >=%.0f uV'
              % (hits, HEOG_CORRELATION, HEOG_MIN_UV))], None


def _cardiac(raw, picks, duration):
    """ECG artifact when widespread, pulse artifact when focal to one electrode."""
    ecgChannel = _named(raw, ECG_NAMES)
    try:
        events, _, rate = mne.preprocessing.find_ecg_events(
            raw, ch_name=ecgChannel, verbose=False)
    except Exception as e:
        return [], 'cardiac detection unavailable (%s)' % e
    if events is None or len(events) < 5:
        return [], None

    sfreq = raw.info['sfreq']
    data = raw.get_data(picks=picks, units='uV')
    half = int(round(0.05 * sfreq)) or 1
    samples = [s for s in events[:, 0] if half <= s < data.shape[1] - half]
    if len(samples) < 5:
        return [], None

    # Average each channel around the R peaks: only a real coupling survives.
    stack = np.stack([data[:, s - half:s + half] for s in samples])
    evoked = stack.mean(axis=0)
    coupling = evoked.max(axis=1) - evoked.min(axis=1)
    hits = [picks[i] for i, c in enumerate(coupling) if c >= ECG_COUPLING_UV]
    if not hits:
        return [], None

    amplitudes = {picks[i]: float(coupling[i]) for i in range(len(picks))}
    focal = len(hits) <= PULSE_MAX_CHANNELS
    name = 'Pulse artifact' if focal else 'ECG artifact'
    band, rate_band = sc.incidenceBand(len(samples), duration)
    return [_finding(
        name, sc.locationFromChannels(hits, amplitudes),
        count=len(samples), incidence=band, confidence='medium',
        basis='R-peak-locked deflection >=%.0f uV in %d channel(s), heart rate '
              '~%.0f bpm%s' % (ECG_COUPLING_UV, len(hits), rate or 0,
                               ', focal - reported as pulse' if focal else ''))], None


def _muscle(raw, picks, duration):
    """EMG, and chewing where the muscle activity is rhythmic."""
    sfreq = raw.info['sfreq']
    high = min(100.0, 0.45 * sfreq)
    low = 30.0
    if high - low < 10:
        return [], ('sample rate %g Hz leaves no usable high-frequency band'
                    '; muscle detection skipped' % sfreq)
    try:
        annot, scores = mne.preprocessing.annotate_muscle_zscore(
            raw.copy().pick(picks), threshold=MUSCLE_Z, ch_type='eeg',
            filter_freq=(low, high), verbose=False)
    except Exception as e:
        return [], 'muscle detection unavailable (%s)' % e

    covered = float(sum(annot.duration)) if len(annot) else 0.0
    if covered <= 0:
        return [], None

    # Which electrodes carry it, from band-limited amplitude.
    band_raw = raw.copy().pick(picks).filter(low, high, verbose=False)
    amplitude = band_raw.get_data(units='uV').std(axis=1)
    threshold = float(np.median(amplitude) * 1.5)
    hits = [picks[i] for i, a in enumerate(amplitude) if a >= threshold] or list(picks)
    amplitudes = {picks[i]: float(amplitude[i]) for i in range(len(picks))}

    prevalence, fraction = sc.prevalenceBand(covered, duration)
    findings = [_finding(
        'EMG artifact', sc.locationFromChannels(hits, amplitudes),
        prevalence, fraction, confidence='medium',
        basis='%.0f-%.0f Hz power z>%.0f for %.1f s of %.1f s'
              % (low, high, MUSCLE_Z, covered, duration))]

    # Chewing: the muscle envelope itself beats at 0.5-3 Hz.
    rhythmic = _envelopePeak(scores, sfreq)
    if rhythmic:
        peakHz, ratio = rhythmic
        temporal = [c for c in hits if sc.ELECTRODE_REGION.get(c) == 'Temporal']
        if temporal and ratio >= CHEW_ENVELOPE_RATIO:
            findings.append(_finding(
                'Chewing artifact', sc.locationFromChannels(temporal, amplitudes),
                prevalence, fraction, confidence='low',
                basis='muscle envelope peaks at %.1f Hz (%.1fx baseline) over '
                      'temporal electrodes - rhythmic, consistent with chewing'
                      % (peakHz, ratio)))
    return findings, None


def _envelopePeak(scores, sfreq):
    """Dominant rhythm of the muscle envelope, if it has one."""
    try:
        from mne.time_frequency import psd_array_welch
        series = np.asarray(scores, dtype=float)
        series = series - series.mean()
        if series.size < int(sfreq * 4):
            return None
        power, freqs = psd_array_welch(series[np.newaxis, :], sfreq, fmin=0.2,
                                       fmax=6.0, n_fft=int(sfreq * 4), verbose=False)
        power = power[0]
        window = (freqs >= CHEW_ENVELOPE_HZ[0]) & (freqs <= CHEW_ENVELOPE_HZ[1])
        if not window.any():
            return None
        peak = float(power[window].max())
        baseline = float(np.median(power))
        if baseline <= 0:
            return None
        return float(freqs[window][np.argmax(power[window])]), peak / baseline
    except Exception:
        return None


def _sweat(raw, picks, duration):
    """Sweat: sustained sub-0.5 Hz drift. Invisible after a 1 Hz high-pass."""
    sfreq = raw.info['sfreq']
    data = raw.get_data(picks=picks, units='uV')
    from mne.time_frequency import psd_array_welch
    nfft = int(sfreq * 8)
    if data.shape[1] < nfft:
        return [], None
    power, freqs = psd_array_welch(data, sfreq, fmin=0.05, fmax=30.0, n_fft=nfft,
                                   verbose=False)
    slow = (freqs >= 0.05) & (freqs < 0.5)
    fast = (freqs >= 1.0) & (freqs <= 30.0)
    if not slow.any() or not fast.any():
        return [], None
    ratios = power[:, slow].mean(axis=1) / np.maximum(power[:, fast].mean(axis=1), 1e-20)

    # The absolute slow excursion, which is what distinguishes sweat from the
    # ordinary 1/f drift present in any unfiltered recording.
    slowRaw = raw.copy().pick(picks).filter(None, 0.5, verbose=False)
    slowData = slowRaw.get_data(units='uV')
    excursion = slowData.max(axis=1) - slowData.min(axis=1)

    hits = [picks[i] for i in range(len(picks))
            if ratios[i] >= SWEAT_RATIO and excursion[i] >= SWEAT_MIN_UV]
    if not hits:
        return [], None
    amplitudes = {picks[i]: float(excursion[i]) for i in range(len(picks))}
    band, fraction = sc.prevalenceBand(duration, duration)
    return [_finding(
        'Sweat artifact', sc.locationFromChannels(hits, amplitudes), band, fraction,
        confidence='low',
        basis='sub-0.5 Hz power >=%.0fx the 1-30 Hz band and excursion >=%.0f uV '
              'in %d channel(s), largest %.0f uV. Any hardware high-pass at '
              'acquisition will mask this'
              % (SWEAT_RATIO, SWEAT_MIN_UV, len(hits), max(excursion)))], None


def _movement(raw, picks, duration):
    """Movement: broadband high-amplitude excursions across many channels."""
    # Band-limited: a DC drift of several hundred microvolts is not movement.
    banded = raw.copy().pick(picks).filter(MOVEMENT_BAND_HZ[0], MOVEMENT_BAND_HZ[1],
                                          verbose=False)
    data = banded.get_data(units='uV')
    windows, step = _windowed(data, raw.info['sfreq'])
    if windows is None:
        return [], None
    span = windows.max(axis=2) - windows.min(axis=2)
    baseline = np.median(span, axis=1, keepdims=True)
    threshold = np.maximum(MOVEMENT_UV, MOVEMENT_RELATIVE * baseline)
    exceeded = span > threshold
    involved = exceeded.sum(axis=0)
    hits = int((involved >= MOVEMENT_MIN_CHANNELS).sum())
    if not hits:
        return [], None
    covered = hits * step / raw.info['sfreq']
    worst = span.max(axis=1)
    amplitudes = {picks[i]: float(worst[i]) for i in range(len(picks))}
    channels = [picks[i] for i in range(len(picks)) if exceeded[i].any()]
    band, fraction = sc.prevalenceBand(covered, duration)
    return [_finding(
        'Movement artifact', sc.locationFromChannels(channels, amplitudes),
        band, fraction, confidence='medium',
        basis='%d window(s) with >=%d channels exceeding %.0fx their own median '
              '%.0f-%.0f Hz amplitude (floor %.0f uV)'
              % (hits, MOVEMENT_MIN_CHANNELS, MOVEMENT_RELATIVE,
                 MOVEMENT_BAND_HZ[0], MOVEMENT_BAND_HZ[1], MOVEMENT_UV))], None


def _respiration(raw, picks, duration):
    """Respiration artifact - only claimed when a respiration channel confirms it."""
    channel = _named(raw, RESP_NAMES)
    if channel is None:
        return [], None
    try:
        pair = raw.copy().pick([channel] + list(picks)).filter(0.1, 0.5, verbose=False)
    except Exception:
        return [], None
    data = pair.get_data()
    reference, eeg = data[0], data[1:]
    if reference.std() < 1e-12:
        return [], None
    correlations = [abs(float(np.corrcoef(reference, row)[0, 1]))
                    if row.std() > 1e-12 else 0.0 for row in eeg]
    hits = [picks[i] for i, c in enumerate(correlations) if c >= 0.5]
    if not hits:
        return [], None
    amplitudes = {picks[i]: correlations[i] for i in range(len(picks))}
    band, fraction = sc.prevalenceBand(duration, duration)
    return [_finding(
        'Respiration artifact', sc.locationFromChannels(hits, amplitudes),
        band, fraction, confidence='medium',
        basis='0.1-0.5 Hz activity correlated >=0.5 with the %s channel in %d '
              'channel(s)' % (channel, len(hits)))], None


DETECTORS = (
    ('line noise', _lineNoise),
    ('flat electrode', _flatChannels),
    ('electrode pops', _electrodePops),
    ('salt bridge', _saltBridge),
    ('eye blinks', _blinks),
    ('horizontal eye movement', _horizontalEyeMovement),
    ('cardiac', _cardiac),
    ('muscle', _muscle),
    ('sweat', _sweat),
    ('movement', _movement),
    ('respiration', _respiration),
)


def classifyArtifacts(raw, verbose=True):
    """Name the artifact types present, in SCORE's vocabulary.

    Expects the recording as loaded - unfiltered, at its native sample rate,
    with the ECG and other polygraphic channels still attached.

    Returns {'findings': [...], 'analysed_seconds': float, 'notes': [...]}.
    Each finding carries a SCORE artifact name, a location, a prevalence or
    incidence band, a confidence and the measurement behind it. Significance is
    never proposed: SCORE scores an artifact's effect on interpretability
    separately, and that is a clinical judgement.
    """
    picks = _eegPicks(raw)
    duration = float(raw.n_times) / raw.info['sfreq']
    result = {'findings': [], 'analysed_seconds': round(duration, 1), 'notes': []}

    if len(picks) < 4:
        result['notes'].append('Too few 10-20 electrodes (%d) to classify artifacts.'
                               % len(picks))
        return result

    for label, detector in DETECTORS:
        try:
            findings, note = detector(raw, picks, duration)
        except Exception as e:
            result['notes'].append('%s detection failed: %s' % (label, e))
            continue
        if note:
            result['notes'].append(note)
        result['findings'] += findings or []

    # Most prevalent first: what dominates the recording matters most.
    result['findings'].sort(key=lambda f: f.get('fraction') or 0.0, reverse=True)

    if verbose:
        printArtifacts(result)
    return result


def printArtifacts(result):
    """Log the classified artifacts, for the run log."""
    print('--- Artifacts (SCORE) --- %.0f s analysed' % result['analysed_seconds'])
    if not result['findings']:
        print('  none detected')
    for f in result['findings']:
        timing = f.get('prevalence') or f.get('incidence') or ''
        print('  %-42s %s' % (f['name'], f['location']['text']))
        print('  %-42s   %s%s' % ('', timing,
                                  '  [%s]' % f['confidence'] if f['confidence'] else ''))
        if f.get('basis'):
            print('  %-42s   %s' % ('', f['basis']))
    for note in result['notes']:
        print('  NOTE: %s' % note)
