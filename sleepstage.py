############################################
# Sleep staging and sleep graphoelements.
#
# Two backends, because they answer different questions:
#
#   U-Sleep  - staging. A fully convolutional network (Perslev et al.) whose
#              published NSRR checkpoints ship with SLEEPYLAND. The
#              architecture lives in vendor/usleep_model.py, kept as a faithful
#              copy because the checkpoints are weights-only.
#   YASA     - graphoelements. Spindle and slow-wave detection, which is what
#              SCORE's Sleep and drowsiness folder actually asks for beyond the
#              stages themselves, plus a fallback stager.
#
# A caveat that matters for this project: both were built for overnight PSG. A
# routine EEG is 20-30 minutes of a mostly awake patient with no EOG and no chin
# EMG, so a staging model trained on NSRR polysomnography is being applied out
# of distribution. That is fine for answering SCORE's question - was sleep
# reached, and which stages - but the confidence attached to any single epoch
# should be read accordingly, and REM in particular depends on EOG that a
# routine montage does not have.
############################################
import os
import glob

import numpy as np

# U-Sleep's own preprocessing, from the dataset configurations shipped with the
# checkpoints: 128 Hz, a central EEG derivation referenced to the contralateral
# mastoid, RobustScaler over the whole recording, values clipped at 20x IQR,
# 30 s periods, and 35 periods per forward pass.
USLEEP_SAMPLE_RATE = 128
USLEEP_PERIOD_S = 30
USLEEP_PERIODS_PER_WINDOW = 35
USLEEP_CLIP_IQR = 20.0

# Output class order, from sleep_stage_annotations in those configurations.
USLEEP_STAGES = ('W', 'N1', 'N2', 'N3', 'REM')

# Preferred derivations, best first. U-Sleep was trained on C4-A1 / C3-A2.
USLEEP_DERIVATIONS = (('C4', 'A2'), ('C3', 'A1'), ('C4', 'A1'), ('C3', 'A2'))
# Channels that are already a referenced derivation, as exported by SHHS and
# the other NSRR studies U-Sleep was trained on.
USLEEP_READY_CHANNELS = ('EEG', 'EEG(sec)', 'C4-A1', 'C3-A2', 'C4-M1', 'C3-M2')

USLEEP_BUILD = {'n_classes': 5, 'depth': 12, 'kernel_size': 9, 'dilation': 1,
                'transition_window': 1, 'complexity_factor': 1.67,
                'activation': 'elu', 'l2_reg': None}

# Where to look for the checkpoints. CMPEEG-style: an environment variable
# first, then a models/ folder in the project, then a SLEEPYLAND checkout.
USLEEP_MODEL_DIRS = ('u-sleep-nsrr-2024_eeg', 'u-sleep-nsrr-2022_eeg')


def _searchRoots():
    roots = []
    env = os.environ.get('USLEEP_MODEL_DIR')
    if env:
        roots.append(env)
    here = os.path.dirname(os.path.abspath(__file__))
    roots.append(os.path.join(here, 'models', 'usleep'))
    env = os.environ.get('SLEEPYLAND_DIR')
    if env:
        roots.append(os.path.join(env, 'usleepyland', 'model'))
    return roots


def findUsleepWeights(preferred=None):
    """Path to a U-Sleep weights file, or None.

    Returns (path, variant). Set USLEEP_MODEL_DIR to the folder holding the
    checkpoint, or SLEEPYLAND_DIR to a SLEEPYLAND checkout.
    """
    wanted = [preferred] if preferred else list(USLEEP_MODEL_DIRS)
    for root in _searchRoots():
        if not os.path.isdir(root):
            continue
        # Either the checkpoint sits directly in root, or in root/<variant>/model.
        direct = sorted(glob.glob(os.path.join(root, '*.h5')))
        if direct:
            return direct[0], os.path.basename(root)
        for variant in wanted:
            found = sorted(glob.glob(os.path.join(root, variant, 'model', '*.h5')))
            if found:
                return found[0], variant
    return None, None


def loadUsleep(weightsPath=None, periods=USLEEP_PERIODS_PER_WINDOW):
    """Build U-Sleep and load its published weights.

    The checkpoints are weights-only, so the architecture must match the
    original exactly; a mismatch raises here rather than quietly loading the
    weights into the wrong layers.
    """
    from vendor.usleep_model import USleep

    variant = None
    if weightsPath is None:
        weightsPath, variant = findUsleepWeights()
    if not weightsPath:
        raise FileNotFoundError(
            'No U-Sleep checkpoint found. Searched:\n  '
            + '\n  '.join(_searchRoots())
            + '\nSet USLEEP_MODEL_DIR to the folder holding the .h5, or '
              'SLEEPYLAND_DIR to a SLEEPYLAND checkout.')

    samples = USLEEP_SAMPLE_RATE * USLEEP_PERIOD_S
    model = USleep(batch_shape=[1, periods, samples, 1], **USLEEP_BUILD)
    model.load_weights(weightsPath)
    return model, weightsPath, variant


def usleepDerivation(raw, verbose=True):
    """A single U-Sleep input channel from whatever the recording carries.

    Returns (data, description) with data in the recording's own units, or
    (None, reason). Prefers an already-referenced central derivation, then
    builds C4-A2 / C3-A1 from the montage, then falls back to a bare central
    electrode - which is off-distribution for the model and is reported as such.
    """
    names = {c.upper(): c for c in raw.ch_names}

    for ready in USLEEP_READY_CHANNELS:
        if ready.upper() in names:
            channel = names[ready.upper()]
            return (raw.get_data(picks=[channel])[0],
                    'existing derivation %s' % channel)

    for active, reference in USLEEP_DERIVATIONS:
        if active.upper() in names and reference.upper() in names:
            data = raw.get_data(picks=[names[active.upper()], names[reference.upper()]])
            return data[0] - data[1], '%s-%s' % (active, reference)

    for active in ('C4', 'C3', 'Cz'):
        if active.upper() in names:
            return (raw.get_data(picks=[names[active.upper()]])[0],
                    '%s against the recording reference (no mastoid available - '
                    'off-distribution for U-Sleep)' % active)

    return None, 'no central EEG channel (C3, C4 or Cz) in the recording'


def _prepare(signal, sfreq):
    """U-Sleep's own preprocessing: 128 Hz, RobustScaler, clip at 20x IQR."""
    import mne

    if abs(sfreq - USLEEP_SAMPLE_RATE) > 1e-6:
        signal = mne.filter.resample(
            signal.astype(np.float64), up=USLEEP_SAMPLE_RATE, down=sfreq, verbose=False)

    median = np.median(signal)
    q25, q75 = np.percentile(signal, [25, 75])
    iqr = q75 - q25
    if iqr <= 0:
        return None
    scaled = (signal - median) / iqr
    # clip_noisy_values, min_max_times_global_iqr: 20. After robust scaling the
    # IQR is 1, so the bound is simply +/-20.
    return np.clip(scaled, -USLEEP_CLIP_IQR, USLEEP_CLIP_IQR)


def stageWithUsleep(raw, model=None, weightsPath=None, verbose=True):
    """Stage a recording with U-Sleep, in 30 s epochs.

    Returns a dict with 'stages' (list of stage names), 'probabilities'
    (n_epochs x 5), 'epoch_seconds', 'derivation' and 'backend'.
    """
    signal, description = usleepDerivation(raw, verbose=verbose)
    if signal is None:
        return {'stages': None, 'notes': [description], 'backend': 'u-sleep'}

    prepared = _prepare(signal, float(raw.info['sfreq']))
    if prepared is None:
        return {'stages': None, 'backend': 'u-sleep',
                'notes': ['the %s signal is flat, so it cannot be scaled' % description]}

    samples = USLEEP_SAMPLE_RATE * USLEEP_PERIOD_S
    nEpochs = len(prepared) // samples
    if nEpochs < 1:
        return {'stages': None, 'backend': 'u-sleep',
                'notes': ['recording is shorter than one %d s epoch' % USLEEP_PERIOD_S]}

    if model is None:
        model, weightsPath, variant = loadUsleep(weightsPath)
    else:
        variant = None

    epochs = prepared[:nEpochs * samples].reshape(nEpochs, samples, 1)

    # The network is trained on 35-epoch windows; feeding it that shape keeps
    # inference on the distribution it was fitted to. The tail window is
    # zero-padded and its padding discarded.
    window = USLEEP_PERIODS_PER_WINDOW
    probabilities = []
    for start in range(0, nEpochs, window):
        block = epochs[start:start + window]
        pad = window - len(block)
        if pad:
            block = np.concatenate([block, np.zeros((pad, samples, 1), np.float32)])
        out = model.predict(block[np.newaxis].astype('float32'), verbose=0)[0]
        probabilities.append(out[:window - pad] if pad else out)
    probabilities = np.concatenate(probabilities)[:nEpochs]

    stages = [USLEEP_STAGES[i] for i in probabilities.argmax(axis=1)]
    result = {'stages': stages, 'probabilities': probabilities,
              'epoch_seconds': USLEEP_PERIOD_S, 'derivation': description,
              'backend': 'u-sleep', 'weights': weightsPath, 'variant': variant,
              'notes': []}
    if 'off-distribution' in description:
        result['notes'].append(
            'Staged from %s. U-Sleep was trained on a central derivation '
            'referenced to the contralateral mastoid; without one, treat the '
            'stages as indicative.' % description)
    if verbose:
        printStages(result)
    return result


def printStages(result):
    """Log a staging result."""
    stages = result.get('stages')
    print('--- Sleep staging (%s) ---' % result.get('backend', '?'))
    if not stages:
        for note in result.get('notes', []):
            print('  NOTE: %s' % note)
        return
    from collections import Counter
    counts = Counter(stages)
    total = len(stages)
    minutes = result.get('epoch_seconds', 30) / 60.0
    print('  derivation: %s' % result.get('derivation'))
    print('  %d epochs of %g s (%.1f min)'
          % (total, result.get('epoch_seconds', 30), total * minutes))
    for stage in USLEEP_STAGES:
        n = counts.get(stage, 0)
        if n:
            print('    %-4s %5d epochs  %5.1f min  %4.1f%%'
                  % (stage, n, n * minutes, 100.0 * n / total))
    for note in result.get('notes', []):
        print('  NOTE: %s' % note)


# ---------------------------------------------------------------------- YASA
# YASA (Vallat & Walker, BSD-3) detects the graphoelements SCORE asks for, which
# staging alone does not give, and provides a fallback stager.

# YASA's own integer stage codes.
YASA_CODES = {'W': 0, 'N1': 1, 'N2': 2, 'N3': 3, 'REM': 4}

# Spindles are scored in N2 and N3; slow waves likewise.
SPINDLE_STAGES = (2, 3)
SLOW_WAVE_STAGES = (2, 3)

# Central and frontal electrodes are where these are conventionally read.
SPINDLE_CHANNELS = ('C3', 'C4', 'Cz', 'P3', 'P4')
SLOW_WAVE_CHANNELS = ('F3', 'F4', 'Fz', 'C3', 'C4')


def stageWithYasa(raw, verbose=True):
    """Stage a recording with YASA's LightGBM stager.

    Needs a central EEG channel; EOG and EMG improve it but a routine EEG
    montage has neither.
    """
    try:
        import yasa
    except ImportError as e:
        return {'stages': None, 'backend': 'yasa',
                'notes': ['YASA is not installed (%s)' % e]}

    names = {c.upper(): c for c in raw.ch_names}
    eeg = next((names[c] for c in ('C4', 'C3', 'CZ') if c in names), None)
    if eeg is None:
        return {'stages': None, 'backend': 'yasa',
                'notes': ['no central EEG channel (C3, C4 or Cz) for YASA staging']}
    eog = next((names[c] for c in ('EOG', 'EOG(L)', 'E1', 'LOC') if c in names), None)
    emg = next((names[c] for c in ('EMG', 'CHIN', 'EMG1') if c in names), None)

    try:
        staging = yasa.SleepStaging(raw, eeg_name=eeg, eog_name=eog, emg_name=emg)
        predicted = list(staging.predict())
    except Exception as e:
        return {'stages': None, 'backend': 'yasa',
                'notes': ['YASA staging failed: %s' % e]}

    result = {'stages': predicted, 'epoch_seconds': 30, 'backend': 'yasa',
              'derivation': '%s%s%s' % (eeg, ' + %s' % eog if eog else '',
                                        ' + %s' % emg if emg else ''),
              'notes': []}
    if not eog:
        result['notes'].append('No EOG channel, so REM is poorly constrained.')
    if verbose:
        printStages(result)
    return result


def _upsampledHypnogram(stages, epochSeconds, raw):
    """Stage labels as YASA integer codes at the data sampling rate."""
    import yasa
    coded = np.array([YASA_CODES.get(s, -2) for s in stages], dtype=int)
    return yasa.hypno_upsample_to_data(
        hypno=coded, sf_hypno=1.0 / epochSeconds, data=raw, verbose=False)


def detectGraphoelements(raw, stages, epochSeconds=30, verbose=True):
    """Sleep spindles and slow waves, via YASA.

    Returns {'spindles': summary or None, 'slow_waves': ..., 'notes': [...]}.
    Both are restricted to the epochs staged N2/N3, which is where they belong
    and which is what stops wake activity being counted as either.
    """
    out = {'spindles': None, 'slow_waves': None, 'notes': []}
    try:
        import yasa
    except ImportError as e:
        out['notes'].append('YASA is not installed (%s)' % e)
        return out

    if not stages:
        out['notes'].append('No hypnogram, so spindles and slow waves were not '
                            'looked for - both are scored within staged sleep.')
        return out

    try:
        hypno = _upsampledHypnogram(stages, epochSeconds, raw)
    except Exception as e:
        out['notes'].append('Could not align the hypnogram to the data: %s' % e)
        return out

    if not any(s in SPINDLE_STAGES for s in np.unique(hypno)):
        out['notes'].append('No N2 or N3 epochs, so no spindles or slow waves '
                            'were sought.')
        return out

    present = [c for c in SPINDLE_CHANNELS if c in raw.ch_names]
    if present:
        try:
            found = yasa.spindles_detect(raw.copy().pick(present), hypno=hypno,
                                         include=SPINDLE_STAGES, verbose=False)
            out['spindles'] = None if found is None else found.summary()
        except Exception as e:
            out['notes'].append('Spindle detection failed: %s' % e)
    else:
        out['notes'].append('No central or parietal channel for spindle detection.')

    present = [c for c in SLOW_WAVE_CHANNELS if c in raw.ch_names]
    if present:
        try:
            found = yasa.sw_detect(raw.copy().pick(present), hypno=hypno,
                                   include=SLOW_WAVE_STAGES, verbose=False)
            out['slow_waves'] = None if found is None else found.summary()
        except Exception as e:
            out['notes'].append('Slow-wave detection failed: %s' % e)
    else:
        out['notes'].append('No frontal or central channel for slow-wave detection.')

    if verbose:
        for key in ('spindles', 'slow_waves'):
            summary = out[key]
            print('  %-12s %s' % (key + ':',
                                  'none' if summary is None or not len(summary)
                                  else '%d detected' % len(summary)))
        for note in out['notes']:
            print('  NOTE: %s' % note)
    return out


# ----------------------------------------------------------- SCORE reporting
# SCORE's Sleep and drowsiness folder (Beniczky et al. 2017, section 7).

SCORE_STAGES = ('Drowsiness', 'N1', 'N2', 'N3', 'REM')
SCORE_GRAPHOELEMENTS = ('Sleep spindles', 'Vertex waves', 'K-complexes',
                        'Saw-tooth waves',
                        'Positive occipital sharp transients of sleep (POSTS)',
                        'Hypnagogic hypersynchrony')
# Of those, only the two YASA covers are attempted; the rest stay with the
# reader rather than being silently omitted.
UNDETECTED_GRAPHOELEMENTS = ('Vertex waves', 'Saw-tooth waves',
                             'Positive occipital sharp transients of sleep (POSTS)',
                             'Hypnagogic hypersynchrony')

SLEEP_NOT_RECORDED = 'Sleep was not recorded'

# Below this many staged epochs the hypnogram is reported with a warning rather
# than at face value - 10 epochs of 30 s is 5 minutes.
MIN_EPOCHS_FOR_HYPNOGRAM = 10


def scoreSleep(raw, backend='usleep', verbose=True):
    """Fill SCORE's Sleep and drowsiness folder for a recording.

    backend: 'usleep' (default) or 'yasa' for staging. Graphoelements always
    come from YASA, which is what detects them.

    Returns a dict with the achieved stages, the graphoelement findings, the
    hypnogram and per-stage timings. Sleep architecture (normal/abnormal) and
    the significance of any abnormal or absent graphoelement are not proposed -
    SCORE scores those, and they are clinical judgements.
    """
    import score_common as sc

    result = {'backend': backend, 'stages_achieved': [], 'graphoelements': [],
              'undetected': list(UNDETECTED_GRAPHOELEMENTS), 'hypnogram': None,
              'statistics': {}, 'notes': []}

    staging = (stageWithUsleep(raw, verbose=verbose) if backend == 'usleep'
               else stageWithYasa(raw, verbose=verbose))
    result['derivation'] = staging.get('derivation')
    result['weights'] = staging.get('weights')
    result['notes'] += staging.get('notes', [])

    stages = staging.get('stages')
    if not stages:
        result['notes'].append('Staging unavailable, so no sleep was scored.')
        result['term'] = SLEEP_NOT_RECORDED
        return result

    epochSeconds = staging.get('epoch_seconds', 30)
    result['hypnogram'] = stages
    result['epoch_seconds'] = epochSeconds

    # A handful of epochs cannot characterise sleep, and U-Sleep sees them
    # inside a 35-epoch window that is mostly zero padding, which biases the
    # prediction. Report the stages, but say the hypnogram is not usable.
    if len(stages) < MIN_EPOCHS_FOR_HYPNOGRAM:
        result['notes'].append(
            'Only %d epoch(s) of %g s were staged (%.1f min). That is too little '
            'to characterise sleep, and U-Sleep evaluates it inside a %d-epoch '
            'window padded with zeros, so treat the stages below as indicative '
            'of the epochs present rather than as a hypnogram.'
            % (len(stages), epochSeconds, len(stages) * epochSeconds / 60.0,
               USLEEP_PERIODS_PER_WINDOW))
        result['short_recording'] = True

    from collections import Counter
    counts = Counter(stages)
    total = len(stages)
    for stage in USLEEP_STAGES:
        n = counts.get(stage, 0)
        result['statistics'][stage] = {
            'epochs': n, 'minutes': round(n * epochSeconds / 60.0, 1),
            'percent': round(100.0 * n / total, 1) if total else 0.0}

    asleep = [s for s in stages if s != 'W']
    if not asleep:
        result['term'] = SLEEP_NOT_RECORDED
        result['notes'].append(
            'Every epoch staged as wake. Reporting that sleep was not recorded '
            'is itself a SCORE finding, and it limits the yield of the study.')
        if verbose:
            printSleepScore(result)
        return result

    result['term'] = 'Sleep recorded'
    # SCORE lists drowsiness alongside N1-N3 and REM; N1 is the closest
    # measurable equivalent, so it is reported as both rather than conflated.
    for stage in ('N1', 'N2', 'N3', 'REM'):
        if counts.get(stage):
            result['stages_achieved'].append(stage)
    if counts.get('N1'):
        result['stages_achieved'].insert(0, 'Drowsiness')

    # Time to the first non-wake epoch - reportable, and cheap.
    firstSleep = next((i for i, s in enumerate(stages) if s != 'W'), None)
    if firstSleep is not None:
        result['statistics']['sleep_onset_minutes'] = round(
            firstSleep * epochSeconds / 60.0, 1)

    analysed = total * epochSeconds
    grapho = detectGraphoelements(raw, stages, epochSeconds, verbose=verbose)
    result['notes'] += grapho.get('notes', [])

    for key, name, stagesUsed, confidence, provisional, note in (
            ('spindles', 'Sleep spindles', 'N2 and N3', 'medium', False, ''),
            ('slow_waves', 'K-complexes', 'N2 and N3', 'low', True,
             'YASA slow-wave detection restricted to staged N2/N3, which is a '
             'proxy for K-complexes rather than a K-complex detector')):
        summary = grapho.get(key)
        if summary is None or not len(summary):
            continue
        channels = sorted({str(c) for c in summary['Channel'].unique()}) \
            if 'Channel' in summary else []
        amplitudes = None
        if channels and 'Amplitude' in summary:
            amplitudes = {c: float(summary[summary['Channel'] == c]['Amplitude'].mean())
                          for c in channels}
        count = int(len(summary))
        band, rate = sc.incidenceBand(count, analysed)
        result['graphoelements'].append({
            'name': name, 'location': sc.locationFromChannels(channels, amplitudes),
            'count': count, 'incidence': band, 'confidence': confidence,
            'provisional': provisional,
            'basis': '%d detected by YASA in %s%s'
                     % (count, stagesUsed, '; ' + note if note else '')})

    if verbose:
        printSleepScore(result)
    return result


def printSleepScore(result):
    """Log the SCORE sleep findings."""
    print('--- Sleep and drowsiness (SCORE) ---')
    print('  %-26s %s' % ('Finding:', result.get('term', '')))
    if result.get('stages_achieved'):
        print('  %-26s %s' % ('Stages achieved:', ', '.join(result['stages_achieved'])))
    stats = result.get('statistics') or {}
    if 'sleep_onset_minutes' in stats:
        print('  %-26s %.1f min' % ('Time to first sleep:', stats['sleep_onset_minutes']))
    for stage in USLEEP_STAGES:
        s = stats.get(stage)
        if s and s['epochs']:
            print('    %-4s %5.1f min  %4.1f%%' % (stage, s['minutes'], s['percent']))
    for f in result.get('graphoelements', []):
        flag = ' [provisional]' if f.get('provisional') else ''
        print('  %-26s %s%s' % (f['name'] + ':', f['location']['text'], flag))
        print('  %-26s   %s  (%s)' % ('', f.get('incidence') or '', f['basis']))
    if result.get('undetected'):
        print('  %-26s %s' % ('Not detected:', ', '.join(result['undetected'])))
    for note in result.get('notes', []):
        print('  NOTE: %s' % note)
