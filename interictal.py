############################################
# Interictal findings, scored against SCORE.
#
# The pipeline has always computed focal slowing, diffuse slowing and band
# ratios, but reported them as free-standing conclusions and percentages that
# belong to no SCORE folder. They are interictal findings, and SCORE has terms
# for them (section 8, Table 5, "Abnormal interictal rhythmic activity"):
#
#   focal / regional slowing -> Delta activity or Theta activity, lateralised
#   diffuse slowing          -> Delta activity or Theta activity, diffuse
#   excess beta              -> Beta activity, diffuse
#
# The band ratios themselves are not findings. They are the measurements a
# finding rests on, so they are carried as its basis rather than reported as
# though a percentage were a diagnosis.
#
# The other half of the conversion is time. SCORE characterises rhythmic
# activity by how much of the recording it covers, and the existing analysis
# averages the whole record into one number - which cannot distinguish
# intermittent slowing (usually functional) from continuous slowing (usually
# structural), the distinction a reader acts on. So everything here is computed
# per epoch and reported with a prevalence band.
############################################
import numpy as np

import score_common as sc

NOT_DETERMINED = 'Not possible to determine'

# SCORE Table 5, the subset this analysis can populate.
DELTA_ACTIVITY = 'Delta activity'
THETA_ACTIVITY = 'Theta activity'
BETA_ACTIVITY = 'Beta activity'

# getFeatures reorders the epochs to this, and pairs them left/right in order.
CHANNEL_ORDER = ['Fp1', 'Fp2', 'F7', 'F8', 'F3', 'F4', 'C3', 'C4',
                 'T3', 'T4', 'T5', 'T6', 'P3', 'P4', 'O1', 'O2']
LEFT_CHANNELS = ['Fp1', 'F7', 'F3', 'C3', 'T3', 'T5', 'P3', 'O1']
RIGHT_CHANNELS = ['Fp2', 'F8', 'F4', 'C4', 'T4', 'T6', 'P4', 'O2']

BANDS = {'delta': (1.5, 4.0), 'theta': (4.0, 8.0),
         'alpha': (8.0, 13.0), 'beta': (13.0, 30.0)}
SLOW_BAND = (1.5, 8.0)
TOTAL_BAND = (1.5, 30.0)

# ------------------------------------------------------------------ thresholds
# Taken from the pipeline's own existing criteria so the clinical behaviour does
# not change, only the vocabulary it is reported in.
#
#   0.5  - the asymmetry at which slow_score() calls a channel slow
#   60%  - the "<60" slow-wave-ratio benchmark printed on the findings page
#   30%  - the "<30" beta-ratio benchmark on the same page
#
# CALIBRATION: conventional, not validated against expert scoring.
ASYMMETRY_THRESHOLD = 0.5
SLOW_RATIO_PERCENT = 60.0
BETA_RATIO_PERCENT = 30.0

# A finding is only reported when it is present in at least this fraction of
# epochs. Below it the prevalence band would be "Rare (<1%)", which for a
# thresholded measure is more likely noise than a finding.
MIN_PREVALENCE = 0.01

# Focal slowing is asymmetric by definition, so it needs a higher bar than the
# diffuse finding: it must be sustained, and it must actually favour one side.
# Without the dominance test, an asymmetry that flips between hemispheres
# epoch to epoch produces electrodes on both sides in one finding, which then
# renders as "diffuse" - a restatement of the diffuse finding rather than a
# focal one.
FOCAL_MIN_PREVALENCE = 0.20
FOCAL_DOMINANCE = 1.5

# --------------------------------------------------- mode of appearance
# SCORE Table 6 asks how a finding is distributed in time: random, periodic or
# variable. That is decided here from the coefficient of variation of the
# intervals between occurrences, which has a real anchor rather than being an
# arbitrary cut: for a Poisson process - events independent, i.e. random -
# inter-event intervals are exponentially distributed with CV = 1, and for a
# perfectly regular recurrence CV = 0.
MODE_RANDOM = 'Random'
MODE_PERIODIC = 'Periodic'
MODE_VARIABLE = 'Variable'
MODE_CONTINUOUS = 'Not applicable - continuous'

PATTERN_RHYTHMIC = 'Rhythmic trains or bursts'
PATTERN_ARRHYTHMIC = 'Arrhythmic trains or bursts'

# The decision is made against the recording's own null rather than a fixed
# cut. Simulating random placements of the same number of occurrences over the
# same epochs shows the interval CV expected by chance runs from about 0.44 at
# 50% density to 0.85 at 5% - so any constant threshold would call dense random
# activity periodic and sparse regular activity random. Comparing each finding
# with its own null removes the constant, and gives the three SCORE terms their
# natural meaning: more regular than chance, like chance, less regular.
PERMUTATIONS = 400
PERIODIC_PERCENTILE = 5.0
VARIABLE_PERCENTILE = 95.0
# Fixed so a report is reproducible - the same recording must not score
# differently on a re-run.
PERMUTATION_SEED = 20240101
# Three intervals is the fewest from which a coefficient of variation says
# anything; below it the mode goes unscored rather than being guessed.
PERIODICITY_MIN_OCCURRENCES = 4
# A finding covering essentially the whole recording has no recurrence to
# characterise - SCORE scores that as continuous instead.
CONTINUOUS_PREVALENCE = 0.90
# Two flagged epochs belong to the same occurrence only if they are adjacent in
# time. Epochs discarded as artifact leave gaps, so adjacency has to be judged
# on the clock and not on epoch index.
RUN_GAP_TOLERANCE = 1.5


def _bandPower(power, freqs, band):
    """Per-epoch, per-channel power in a band: (n_epochs, n_channels)."""
    window = (freqs >= band[0]) & (freqs < band[1])
    if not window.any():
        return None
    return power[:, :, window].sum(axis=2)


def _asymmetry(left, right):
    """Relative left-right difference, positive when the left side is larger."""
    total = left + right
    with np.errstate(divide='ignore', invalid='ignore'):
        out = np.where(total > 0, 2.0 * (left - right) / total, 0.0)
    return out


def _describePrevalence(fraction):
    """Plain-language sense of how sustained a pattern is."""
    if fraction is None:
        return ''
    if fraction >= 0.9:
        return 'continuous'
    if fraction >= 0.5:
        return 'nearly continuous'
    return 'intermittent'


def _occurrences(mask, onsets, epochLength):
    """Group flagged epochs into occurrences, returning their start times.

    An occurrence continues across adjacent epochs only. Because artifact
    rejection removes epochs, two flagged epochs can be neighbours by index yet
    minutes apart on the clock, so adjacency is decided on time.
    """
    order = np.argsort(onsets)
    mask = np.asarray(mask)[order]
    times = np.asarray(onsets, dtype=float)[order]

    starts, ends = [], []
    for flagged, start in zip(mask, times):
        if not flagged:
            continue
        if starts and start - ends[-1] <= epochLength * (RUN_GAP_TOLERANCE - 1.0) + 1e-6:
            ends[-1] = start + epochLength
        else:
            starts.append(start)
            ends.append(start + epochLength)
    return np.array(starts), np.array(ends)


def _temporalFeatures(mask, onsets, epochLength):
    """SCORE's mode of appearance and discharge pattern for one finding.

    Returns the mode, the discharge pattern, the number of occurrences, the
    median interval between them - which SCORE records for periodic
    graphoelements - and the coefficient of variation the decision rests on.
    """
    fraction = float(np.mean(mask)) if len(mask) else 0.0
    out = {'mode': NOT_DETERMINED, 'pattern': None, 'occurrences': None,
           'median_interval_s': None, 'cv': None, 'reason': ''}

    if fraction >= CONTINUOUS_PREVALENCE:
        out['mode'] = MODE_CONTINUOUS
        out['pattern'] = PATTERN_RHYTHMIC
        out['reason'] = ('present in %.0f%% of epochs, so there is no recurrence '
                         'to characterise' % (100.0 * fraction))
        return out

    starts, _ = _occurrences(mask, onsets, epochLength)
    out['occurrences'] = int(len(starts))
    if len(starts) < PERIODICITY_MIN_OCCURRENCES:
        out['reason'] = ('%d separate occurrence(s); at least %d are needed before '
                         'the intervals between them mean anything'
                         % (len(starts), PERIODICITY_MIN_OCCURRENCES))
        return out

    cv = _intervalCv(starts)
    if cv is None:
        out['reason'] = 'occurrence times are not usable'
        return out
    out['cv'] = round(cv, 3)
    out['median_interval_s'] = round(float(np.median(np.diff(starts))), 1)

    # The null: the same number of flagged epochs scattered at random over the
    # same epochs, grouped into occurrences the same way.
    mask = np.asarray(mask, dtype=bool)
    flagged = int(mask.sum())
    rng = np.random.RandomState(PERMUTATION_SEED)
    nullCvs = []
    for _ in range(PERMUTATIONS):
        shuffled = np.zeros(len(mask), dtype=bool)
        shuffled[rng.choice(len(mask), flagged, replace=False)] = True
        nullStarts, _unused = _occurrences(shuffled, onsets, epochLength)
        value = _intervalCv(nullStarts)
        if value is not None:
            nullCvs.append(value)

    if len(nullCvs) < PERMUTATIONS // 4:
        out['reason'] = ('%d occurrences, median interval %.1f s, interval CV %.2f; '
                         'too few usable random comparisons to judge the mode'
                         % (len(starts), out['median_interval_s'], cv))
        return out

    low, high = np.percentile(nullCvs, [PERIODIC_PERCENTILE, VARIABLE_PERCENTILE])
    out['null_cv_median'] = round(float(np.median(nullCvs)), 3)
    percentile = float((np.asarray(nullCvs) < cv).mean() * 100.0)
    out['null_percentile'] = round(percentile, 1)

    if cv <= low:
        out['mode'] = MODE_PERIODIC
        out['pattern'] = PATTERN_RHYTHMIC
        comparison = 'more regular than chance'
    elif cv >= high:
        out['mode'] = MODE_VARIABLE
        out['pattern'] = PATTERN_ARRHYTHMIC
        comparison = 'less regular than chance - it waxes and wanes'
    else:
        out['mode'] = MODE_RANDOM
        out['pattern'] = PATTERN_ARRHYTHMIC
        comparison = 'indistinguishable from chance'

    out['reason'] = ('%d occurrences, median interval %.1f s; interval coefficient '
                     'of variation %.2f against %.2f expected for the same number '
                     'scattered at random - %s, at percentile %.0f of %d random '
                     'placements'
                     % (len(starts), out['median_interval_s'], cv,
                        out['null_cv_median'], comparison, percentile, len(nullCvs)))
    return out


def temporalFeaturesFromTimes(times, spanSeconds):
    """Mode of appearance for discrete events given their times in seconds.

    The epoch-mask version above suits a finding measured per epoch. Discrete
    detections - a spike detector's output, say - already have exact times, so
    the null here is the same number of events placed uniformly at random over
    the same span rather than shuffled across an epoch grid. For a uniform
    random placement the intervals are close to exponential, so the null CV sits
    near 1 for many events and lower for few, which is exactly the small-sample
    bias a fixed threshold would get wrong.
    """
    out = {'mode': NOT_DETERMINED, 'pattern': None, 'occurrences': None,
           'median_interval_s': None, 'cv': None, 'reason': ''}
    times = np.sort(np.asarray(times, dtype=float))
    out['occurrences'] = int(len(times))

    if len(times) < PERIODICITY_MIN_OCCURRENCES:
        out['reason'] = ('%d event(s); at least %d are needed before the intervals '
                         'between them mean anything'
                         % (len(times), PERIODICITY_MIN_OCCURRENCES))
        return out
    if not spanSeconds or spanSeconds <= 0:
        out['reason'] = 'the analysed duration is unknown'
        return out

    cv = _intervalCv(times)
    if cv is None:
        out['reason'] = 'event times are not usable'
        return out
    out['cv'] = round(cv, 3)
    out['median_interval_s'] = round(float(np.median(np.diff(times))), 1)

    rng = np.random.RandomState(PERMUTATION_SEED)
    nullCvs = []
    for _ in range(PERMUTATIONS):
        sample = np.sort(rng.uniform(0.0, spanSeconds, len(times)))
        value = _intervalCv(sample)
        if value is not None:
            nullCvs.append(value)
    if len(nullCvs) < PERMUTATIONS // 4:
        out['reason'] = 'too few usable random comparisons to judge the mode'
        return out

    low, high = np.percentile(nullCvs, [PERIODIC_PERCENTILE, VARIABLE_PERCENTILE])
    out['null_cv_median'] = round(float(np.median(nullCvs)), 3)
    percentile = float((np.asarray(nullCvs) < cv).mean() * 100.0)
    out['null_percentile'] = round(percentile, 1)

    if cv <= low:
        out['mode'], out['pattern'] = MODE_PERIODIC, PATTERN_RHYTHMIC
        comparison = 'more regular than chance'
    elif cv >= high:
        out['mode'], out['pattern'] = MODE_VARIABLE, PATTERN_ARRHYTHMIC
        comparison = 'less regular than chance - it comes in clusters'
    else:
        out['mode'], out['pattern'] = MODE_RANDOM, PATTERN_ARRHYTHMIC
        comparison = 'indistinguishable from chance'

    out['reason'] = ('%d events, median interval %.1f s; interval coefficient of '
                     'variation %.2f against %.2f expected for the same number '
                     'placed at random over %.0f s - %s, at percentile %.0f of %d '
                     'random placements'
                     % (len(times), out['median_interval_s'], cv,
                        out['null_cv_median'], spanSeconds, comparison, percentile,
                        len(nullCvs)))
    return out


def _intervalCv(starts):
    """Coefficient of variation of the intervals between occurrence starts."""
    if starts is None or len(starts) < PERIODICITY_MIN_OCCURRENCES:
        return None
    intervals = np.diff(np.asarray(starts, dtype=float))
    mean = float(np.mean(intervals))
    if mean <= 0:
        return None
    return float(np.std(intervals) / mean)


def _finding(name, location, prevalence, fraction, basis, temporal=None,
             confidence='medium'):
    """One interictal finding, in the shape the artifact and sleep folders use."""
    temporal = temporal or {}
    return {'name': name, 'morphology': 'Abnormal interictal rhythmic activity',
            'location': location, 'prevalence': prevalence, 'fraction': fraction,
            'mode_of_appearance': temporal.get('mode', NOT_DETERMINED),
            'discharge_pattern': temporal.get('pattern'),
            'occurrences': temporal.get('occurrences'),
            'median_interval_s': temporal.get('median_interval_s'),
            'interval_cv': temporal.get('cv'),
            'timing_basis': temporal.get('reason', ''),
            'confidence': confidence, 'basis': basis}


def scoreInterictal(epochs, results, epochLength=4.0, verbose=True):
    """Convert the background analysis into SCORE interictal findings.

    epochs      : the artifact-screened epochs, channels in CHANNEL_ORDER.
    results     : the results dict, for the bad-channel list.
    epochLength : seconds per epoch, for the prevalence denominator.

    The spectrum is recomputed per epoch here rather than reusing the one
    getFeatures produces, because that one is averaged over the recording -
    which is exactly the information this module needs and that one has thrown
    away. Same multitaper settings, so the two agree.

    Returns {'findings': [...], 'measures': {...}, 'notes': [...]}.
    """
    out = {'findings': [], 'measures': {}, 'notes': []}
    try:
        bandwidth = round(float(epochs.info['sfreq']) / epochs.get_data().shape[2], 2)
        spectrum = epochs.compute_psd(method='multitaper', fmin=1.5, fmax=30,
                                      bandwidth=bandwidth, verbose=False)
        power, freqs = spectrum.get_data(return_freqs=True)
    except Exception as e:
        out['notes'].append('Could not compute the per-epoch spectrum: %s' % e)
        return out
    if power.ndim != 3:
        out['notes'].append('Expected a per-epoch spectrum, got %d dimensions.'
                            % power.ndim)
        return out

    names = list(epochs.ch_names)
    nEpochs = power.shape[0]
    analysed = nEpochs * epochLength
    out['measures']['epochs'] = int(nEpochs)
    out['measures']['analysed_seconds'] = round(analysed, 1)

    if nEpochs < 2:
        out['notes'].append('Too few epochs to characterise interictal activity.')
        return out

    index = {name: i for i, name in enumerate(names)}
    badChannels = set(results.get('bad_channels') or [])

    # True epoch start times. extractAlphaEpochs sorts the epochs by their alpha
    # anterior-posterior ratio and drops artifact epochs first, so epoch index is
    # neither time order nor evenly spaced - but the original onsets survive in
    # the events array, and every interval below is measured from them.
    try:
        onsets = epochs.events[:, 0] / float(epochs.info['sfreq'])
    except Exception:
        onsets = None
    if onsets is None or len(onsets) != nEpochs:
        onsets = np.arange(nEpochs, dtype=float) * epochLength
        out['notes'].append('Epoch onset times were unavailable, so the mode of '
                            'appearance assumes the epochs are contiguous.')
    out['measures']['recording_span_seconds'] = round(
        float(onsets.max() - onsets.min() + epochLength), 1)

    bands = {}
    for label, band in BANDS.items():
        bands[label] = _bandPower(power, freqs, band)
    slow = _bandPower(power, freqs, SLOW_BAND)
    total = _bandPower(power, freqs, TOTAL_BAND)
    if slow is None or total is None:
        out['notes'].append('Spectrum does not cover the bands needed.')
        return out

    # --- diffuse slowing --------------------------------------------------
    # Per-epoch slow fraction across all electrodes, so the prevalence is real
    # rather than a whole-record average.
    usable = [i for name, i in index.items() if name not in badChannels]
    if usable:
        with np.errstate(divide='ignore', invalid='ignore'):
            slowFraction = np.where(total[:, usable].sum(axis=1) > 0,
                                    slow[:, usable].sum(axis=1)
                                    / total[:, usable].sum(axis=1), 0.0)
        mask = slowFraction >= SLOW_RATIO_PERCENT / 100.0
        fraction = float(mask.mean())
        out['measures']['diffuse_slow_percent'] = round(100.0 * float(slowFraction.mean()), 1)
        out['measures']['diffuse_slow_prevalence'] = round(fraction, 3)
        if fraction >= MIN_PREVALENCE:
            # Which band dominates the excess decides the SCORE term.
            deltaMean = float(bands['delta'][:, usable][mask].mean()) if mask.any() else 0.0
            thetaMean = float(bands['theta'][:, usable][mask].mean()) if mask.any() else 0.0
            name = DELTA_ACTIVITY if deltaMean >= thetaMean else THETA_ACTIVITY
            band, _ = sc.prevalenceBand(fraction * analysed, analysed)
            out['findings'].append(_finding(
                name, sc.locationFromChannels([n for n in names if n not in badChannels]),
                band, fraction,
                'slow (1.5-8 Hz) power was %.0f%% or more of 1.5-30 Hz in %.0f%% of '
                'epochs, %s; mean slow fraction %.1f%%'
                % (SLOW_RATIO_PERCENT, 100.0 * fraction, _describePrevalence(fraction),
                   out['measures']['diffuse_slow_percent']),
                temporal=_temporalFeatures(mask, onsets, epochLength)))

    # --- focal / regional slowing ----------------------------------------
    # Per pair, per epoch: is one side slower than the other by the margin the
    # pipeline already uses.
    focal = {'left': {}, 'right': {}}
    for leftName, rightName in zip(LEFT_CHANNELS, RIGHT_CHANNELS):
        if leftName not in index or rightName not in index:
            continue
        li, ri = index[leftName], index[rightName]
        for label in ('delta', 'theta'):
            values = _asymmetry(bands[label][:, li], bands[label][:, ri])
            for side, name, mask in (('left', leftName, values >= ASYMMETRY_THRESHOLD),
                                     ('right', rightName, values <= -ASYMMETRY_THRESHOLD)):
                if name in badChannels:
                    continue
                fraction = float(mask.mean())
                if fraction < MIN_PREVALENCE:
                    continue
                key = (name, label)
                if fraction > focal[side].get(key, (0.0, None))[0]:
                    focal[side][key] = (fraction, mask)

    # One entry per side per band. SCORE scores the same graphoelement seen
    # independently in two locations as two separate entries, and a finding
    # spanning both hemispheres is not focal in the first place.
    for label, term in (('delta', DELTA_ACTIVITY), ('theta', THETA_ACTIVITY)):
        peaks = {}
        for side in ('left', 'right'):
            channels = {name: value for (name, band), value in focal[side].items()
                        if band == label}
            fractions = {name: value[0] for name, value in channels.items()}
            peaks[side] = (channels, fractions,
                           max(fractions.values()) if fractions else 0.0)
        for side, opposite in (('left', 'right'), ('right', 'left')):
            channels, fractions, peak = peaks[side]
            otherPeak = peaks[opposite][2]
            if not channels or peak < FOCAL_MIN_PREVALENCE:
                continue
            if peak < otherPeak * FOCAL_DOMINANCE:
                out['notes'].append(
                    '%s excess on the %s appeared in %.0f%% of epochs but the %s '
                    'side reached %.0f%%, so it is not lateralised and was not '
                    'reported as focal.'
                    % (label.capitalize(), side, 100.0 * peak, opposite,
                       100.0 * otherPeak))
                continue
            band, _ = sc.prevalenceBand(peak * analysed, analysed)
            # Characterise the timing on the electrode carrying the finding.
            peakChannel = max(fractions, key=fractions.get)
            out['findings'].append(_finding(
                term, sc.locationFromChannels(list(channels), fractions),
                band, peak,
                'higher %s power than the contralateral electrode by a relative '
                'difference of %.1f or more, in up to %.0f%% of epochs, %s'
                % (label, ASYMMETRY_THRESHOLD, 100.0 * peak,
                   _describePrevalence(peak)),
                temporal=_temporalFeatures(channels[peakChannel][1], onsets,
                                           epochLength)))
    # Deliberately not recording every electrode that crossed the threshold in
    # any epoch: on this data that is 14 of 16, including the ones just rejected
    # as not lateralised, which contradicts the findings rather than supporting
    # them. The location and maximum on each finding say it properly.

    # --- excess beta -------------------------------------------------------
    if usable:
        with np.errstate(divide='ignore', invalid='ignore'):
            betaFraction = np.where(total[:, usable].sum(axis=1) > 0,
                                    bands['beta'][:, usable].sum(axis=1)
                                    / total[:, usable].sum(axis=1), 0.0)
        mask = betaFraction >= BETA_RATIO_PERCENT / 100.0
        fraction = float(mask.mean())
        out['measures']['beta_percent'] = round(100.0 * float(betaFraction.mean()), 1)
        out['measures']['beta_prevalence'] = round(fraction, 3)
        if fraction >= MIN_PREVALENCE:
            band, _ = sc.prevalenceBand(fraction * analysed, analysed)
            out['findings'].append(_finding(
                BETA_ACTIVITY,
                sc.locationFromChannels([n for n in names if n not in badChannels]),
                band, fraction,
                temporal=_temporalFeatures(mask, onsets, epochLength),
                basis=
                'beta (13-30 Hz) power was %.0f%% or more of 1.5-30 Hz in %.0f%% of '
                'epochs, %s; mean beta fraction %.1f%%. Excess beta is commonly '
                'medication-related - correlate with the drug history'
                % (BETA_RATIO_PERCENT, 100.0 * fraction, _describePrevalence(fraction),
                   out['measures']['beta_percent'])))

    out['findings'].sort(key=lambda f: f.get('fraction') or 0.0, reverse=True)
    if verbose:
        printInterictal(out)
    return out


def badElectrodeFinding(badChannels, analysedSeconds, threshold=None):
    """The bad-electrode list as a SCORE artifact finding.

    A channel the repair stage had to reconstruct in a large share of epochs is
    an electrode artifact, which belongs in SCORE's EEG artifacts folder with a
    location - not in a free-standing list beside the report.
    """
    channels = [c for c in (badChannels or []) if c in sc.ELECTRODE_REGION]
    if not channels:
        return None
    band, fraction = sc.prevalenceBand(analysedSeconds, analysedSeconds)
    detail = ('in more than %.0f%% of epochs' % (threshold * 100)
              if threshold else 'in a large share of epochs')
    return {'name': 'Other artifact (electrode artifact)',
            'location': sc.locationFromChannels(channels),
            'prevalence': band, 'fraction': fraction, 'count': None,
            'incidence': None, 'confidence': 'medium',
            'basis': 'artifact repair reconstructed %s %s, so %s carried '
                     'unreliable signal'
                     % (', '.join(sorted(channels)), detail,
                        'these electrodes' if len(channels) > 1 else 'this electrode')}


def printInterictal(result):
    """Log the interictal findings."""
    print('--- Interictal findings (SCORE) ---')
    if not result['findings']:
        print('  none reported')
    for f in result['findings']:
        print('  %-18s %s' % (f['name'] + ':', f['location']['text']))
        print('  %-18s   %s' % ('', f.get('prevalence') or ''))
        mode = f.get('mode_of_appearance')
        if f.get('discharge_pattern'):
            mode = '%s, %s' % (mode, f['discharge_pattern'])
        print('  %-18s   mode of appearance: %s' % ('', mode))
        if f.get('timing_basis'):
            print('  %-18s     %s' % ('', f['timing_basis']))
        print('  %-18s   %s' % ('', f['basis']))
    for note in result.get('notes', []):
        print('  NOTE: %s' % note)
