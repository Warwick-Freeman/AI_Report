############################################
# Posterior dominant rhythm (PDR), scored against SCORE.
#
# SCORE (Beniczky et al., Clin Neurophysiol 2017;128:2334-2346, Table 4) scores
# the PDR on nine properties. This module produces all nine from the signal,
# each as a SCORE term plus the measurement it came from, so a reader can see
# what a proposal rests on before accepting it.
#
#   significance          Normal / No definite abnormality / Abnormal
#   frequency             numeric, per hemisphere
#   frequency_asymmetry   Symmetrical / n Hz lower on the left|right side
#   amplitude             Low <20 / Medium 20-70 / High >70 microvolts
#   amplitude_asymmetry   Symmetrical / Right < Left / Left < Right
#   reactivity            Yes / Reduced left|right|both
#   organization          Normal / Poorly organized / Disorganized / Markedly disorganized
#   caveat                No / Only open eyes / Sleep-deprived / Drowsy / Only following HV
#   absence               why no PDR was found, when none was
#
# Every property carries a confidence. SCORE distinguishes "not scored" from
# the active choice "not possible to determine", and so does this module: where
# the recording cannot answer a property, it says so rather than guessing.
#
# CALIBRATION: the numeric thresholds below are conventional values, not values
# validated against a scored reference set. They are gathered in one block on
# purpose. Before clinical use they need calibrating against expert scoring, and
# the properties marked provisional need it most.
############################################
import numpy as np

# ---------------------------------------------------------------- SCORE terms
NOT_DETERMINED = 'Not possible to determine'

SIGNIFICANCE = ('Normal', 'No definite abnormality', 'Abnormal')
AMPLITUDE = ('Low (<20 µV)', 'Medium (20-70 µV)', 'High (>70 µV)')
AMPLITUDE_ASYMMETRY = ('Symmetrical', 'Right < Left', 'Left < Right')
REACTIVITY = ('Yes', 'Reduced left side reactivity', 'Reduced right side reactivity',
              'Reduced reactivity on both sides')
ORGANIZATION = ('Normal', 'Poorly organized', 'Disorganized', 'Markedly disorganized')
CAVEAT = ('No', 'Only open eyes during the recording', 'Sleep-deprived', 'Drowsy',
          'Only following hyperventilation')
ABSENCE = ('Artifacts', 'Extreme low voltage', 'Eye-closure could not be achieved',
           'Lack of awake period', 'Lack of compliance', 'Other causes')

# ------------------------------------------------------------------ thresholds
# Lower limit of a normal PDR by age. The PDR matures through childhood, so a
# single adult threshold reports every young child as abnormally slow. Values
# are the conventional developmental floors; linear interpolation between them.
AGE_PDR_FLOOR_HZ = [
    (0.25, 2.5), (0.5, 3.5), (1.0, 5.0), (2.0, 5.5),
    (3.0, 6.0), (5.0, 7.0), (8.0, 8.0), (120.0, 8.0),
]

# SCORE takes a typed numeric asymmetry; this is only the point at which the
# term stops being "Symmetrical". 0.5 Hz matches the criterion already stated in
# prompt.py. Note eeg/auto_report's own symmetric_frequency_of_background used
# 1.0 Hz, which disagreed with that text - this module is the single source now.
FREQ_ASYMMETRY_HZ = 0.5

# Relative amplitude difference, 2*(L-R)/(L+R), at which a side is called lower.
AMP_ASYMMETRY_RATIO = 0.5

# Fraction by which posterior band power must fall on eye opening to count as
# a reactive PDR.
REACTIVITY_MIN_ATTENUATION = 0.5

# Automatic eye-state split: the high-alpha group must exceed the low-alpha
# group by this factor before the two are accepted as eyes-closed vs eyes-open.
EYE_STATE_MIN_RATIO = 2.0
# ...and blink activity should be the higher of the two in the low-alpha group.
EYE_STATE_BLINK_RATIO = 1.15
# Minimum epochs in each state before reactivity is measured at all.
EYE_STATE_MIN_EPOCHS = 3

# A posterior spectral peak must stand this far above the broadband median to
# count as a discernible rhythm. Ratios well into double figures are normal for
# a well-formed rhythm (Demo.eeg measures 25.7), so this is a floor for
# "something is there", not a normality threshold. Sanity-ranged against a
# single recording - not calibrated.
PEAK_MIN_PROMINENCE = 3.0

# Provisional organisation grading. Continuity is the fraction of eyes-closed
# epochs carrying the group rhythm; concentration is peak-to-broadband ratio.
ORG_CONTINUITY = (0.75, 0.50, 0.25)
ORG_CONCENTRATION_NORMAL = 10.0

# Provisional drowsiness proxy: theta/alpha power ratio in eyes-closed epochs.
DROWSY_THETA_ALPHA = 1.0

# Below this, posterior activity counts as SCORE's "extreme low voltage".
LOW_VOLTAGE_UV = 10.0
# Above this drop-epoch fraction, absence of a PDR is attributed to artifact.
ABSENCE_ARTIFACT_RATIO = 0.5

# Disagreement between the model's frequency and the posterior spectral peak
# that is worth putting in front of a reader. SCORE takes a single typed
# frequency, so when two methods disagree by about a band-width someone has to
# decide which to enter.
FREQ_AGREEMENT_HZ = 1.0

# Band half-width around the PDR frequency used for amplitude and reactivity.
# Centring on the measured frequency rather than a fixed 8-13 Hz band is what
# lets a genuinely slow PDR be measured instead of missed.
PDR_BAND_HALFWIDTH_HZ = 1.5

LEFT_POSTERIOR = ['O1', 'P3', 'T5']
RIGHT_POSTERIOR = ['O2', 'P4', 'T6']
FRONTOPOLAR = ['Fp1', 'Fp2']

_EYES_CLOSED_HINTS = ('eyes closed', 'eye closed', 'eyesclosed', 'ec')
_EYES_OPEN_HINTS = ('eyes open', 'eye open', 'eyesopen', 'eo')


def _prop(term, value=None, confidence='high', basis='', provisional=False):
    """One scored property: the SCORE term plus what it was derived from."""
    return {'term': term, 'value': value, 'confidence': confidence,
            'basis': basis, 'provisional': provisional}


def ageFloorHz(ageYears):
    """Lower limit of a normal PDR at this age, interpolated from the table."""
    if ageYears is None:
        return None
    ages = [a for a, _ in AGE_PDR_FLOOR_HZ]
    floors = [f for _, f in AGE_PDR_FLOOR_HZ]
    return float(np.interp(max(ageYears, 0.0), ages, floors))


def _picks(epochs, names):
    return [n for n in names if n in epochs.ch_names]


def _bandMeasures(epochs, low, high, picks):
    """Per-epoch band power and peak-to-peak amplitude for the given channels.

    Returns (power, amplitude) each shaped (n_epochs,) - averaged over channels.
    Amplitude is in microvolts, measured over the whole epoch: the previous
    implementation cropped to 0.5 s first, which is shorter than the filter it
    then applied, so its numbers were filter ringing rather than signal.
    """
    sel = _picks(epochs, picks)
    if not sel:
        return None, None
    low = max(float(low), 0.5)
    band = epochs.copy().pick(sel).filter(low, float(high), verbose=False)
    data = band.get_data(units='uV')                      # (epochs, chans, times)
    power = np.var(data, axis=2).mean(axis=1)
    amplitude = (data.max(axis=2) - data.min(axis=2)).mean(axis=1)
    return power, amplitude


def _epochOnsets(epochs):
    """Epoch start times in seconds, or None if they cannot be recovered."""
    try:
        return epochs.events[:, 0] / float(epochs.info['sfreq'])
    except Exception:
        return None


def _eyeStateFromAnnotations(epochs, raw):
    """Eye state per epoch from technologist annotations, or None.

    Annotations are authoritative when present - an automatic split is only a
    fallback. Returns an array of 'closed'/'open'/'' per epoch.
    """
    if raw is None or raw.annotations is None or len(raw.annotations) == 0:
        return None
    onsets = _epochOnsets(epochs)
    if onsets is None:
        return None

    marks = []
    for i in range(len(raw.annotations)):
        text = (raw.annotations.description[i] or '').strip().lower()
        state = ''
        if any(h in text for h in _EYES_CLOSED_HINTS):
            state = 'closed'
        elif any(h in text for h in _EYES_OPEN_HINTS):
            state = 'open'
        if state:
            marks.append((float(raw.annotations.onset[i]), state))
    if not marks:
        return None
    marks.sort()

    states = []
    for t in onsets:
        current = ''
        for onset, state in marks:
            if onset <= t:
                current = state
            else:
                break
        states.append(current)
    states = np.array(states)
    if (states == 'closed').sum() < EYE_STATE_MIN_EPOCHS:
        return None
    return states


def _eyeStateAutomatic(epochs, alphaPower):
    """Split epochs into eyes-closed and eyes-open by posterior alpha power.

    Eye closure raises posterior alpha several-fold and stops blinking, so the
    two states separate on those two measures together. Where they do not
    separate, this returns None and reactivity goes unscored rather than being
    invented.
    """
    n = len(alphaPower)
    if n < 2 * EYE_STATE_MIN_EPOCHS:
        return None, 'too few epochs to separate eye states'

    order = np.argsort(alphaPower)
    third = max(EYE_STATE_MIN_EPOCHS, n // 3)
    lowIdx, highIdx = order[:third], order[-third:]
    lowAlpha = float(np.median(alphaPower[lowIdx]))
    highAlpha = float(np.median(alphaPower[highIdx]))
    if lowAlpha <= 0 or highAlpha / lowAlpha < EYE_STATE_MIN_RATIO:
        return None, ('posterior alpha did not separate into two states '
                      '(ratio %.2f, needs %.1f)'
                      % (highAlpha / lowAlpha if lowAlpha else float('inf'),
                         EYE_STATE_MIN_RATIO))

    # Blink activity must positively confirm which group had the eyes open.
    # Requiring only that it not contradict is too weak: posterior alpha waxes
    # and wanes severalfold within a continuously eyes-closed recording, so the
    # ratio test alone splits such a record into two spurious "states" and
    # invents a reactivity finding. Demanding real blink evidence for the
    # eyes-open group means reactivity goes unscored unless eye opening actually
    # happened - the safer error, since a false "reduced reactivity" drives the
    # significance of the whole PDR to abnormal.
    blink, _ = _bandMeasures(epochs, 1.0, 4.0, FRONTOPOLAR)
    if blink is None:
        return None, 'no frontopolar channels to confirm which state had eyes open'
    lowBlink = float(np.median(blink[lowIdx]))
    highBlink = float(np.median(blink[highIdx]))
    if lowBlink <= highBlink * EYE_STATE_BLINK_RATIO:
        return None, ('frontal blink activity does not confirm an eyes-open state '
                      '(low-alpha %.1f vs high-alpha %.1f uV)' % (lowBlink, highBlink))

    threshold = (lowAlpha + highAlpha) / 2.0
    states = np.where(alphaPower >= threshold, 'closed', 'open')
    if (states == 'closed').sum() < EYE_STATE_MIN_EPOCHS or \
       (states == 'open').sum() < EYE_STATE_MIN_EPOCHS:
        return None, 'one eye state had too few epochs'
    return states, 'automatic split on posterior alpha power and blink activity'


def _posteriorSpectrum(epochs, picks, fmin=1.5, fmax=30.0):
    """Averaged posterior PSD as (freqs, power) in uV^2/Hz, or (None, None)."""
    sel = _picks(epochs, picks)
    if not sel or len(epochs) == 0:
        return None, None
    bandwidth = round(float(epochs.info['sfreq']) / epochs.get_data().shape[2], 2)
    psd = epochs.copy().pick(sel).compute_psd(
        method='multitaper', fmin=fmin, fmax=fmax, bandwidth=bandwidth,
        verbose=False)
    power, freqs = psd.average().get_data(return_freqs=True)
    return freqs, power.mean(axis=0) * 1e12


def _peak(freqs, power, lo, hi):
    """Dominant peak in a frequency window and its prominence over broadband."""
    if freqs is None:
        return None, None
    window = (freqs >= lo) & (freqs <= hi)
    if not window.any():
        return None, None
    idx = np.argmax(power[window])
    peakFreq = float(freqs[window][idx])
    broadband = float(np.median(power))
    prominence = float(power[window][idx] / broadband) if broadband > 0 else None
    return peakFreq, prominence


def _rhythmContinuity(epochs, picks, groupPeak, lo, hi):
    """Fraction of epochs whose own posterior peak sits near the group peak.

    One multitaper call over all epochs rather than one per epoch: the per-epoch
    version was both slow and emitted a warning for every epoch.
    """
    sel = _picks(epochs, picks)
    if not sel or len(epochs) == 0:
        return None
    bandwidth = round(float(epochs.info['sfreq']) / epochs.get_data().shape[2], 2)
    psd = epochs.copy().pick(sel).compute_psd(
        method='multitaper', fmin=1.5, fmax=30.0, bandwidth=bandwidth, verbose=False)
    power, freqs = psd.get_data(return_freqs=True)      # (epochs, chans, freqs)
    power = power.mean(axis=1)
    window = (freqs >= lo) & (freqs <= hi)
    if not window.any():
        return None

    hits = 0
    for row in power:
        broadband = np.median(row)
        if broadband <= 0:
            continue
        peakIdx = np.argmax(row[window])
        if row[window][peakIdx] / broadband >= PEAK_MIN_PROMINENCE and \
                abs(freqs[window][peakIdx] - groupPeak) <= PDR_BAND_HALFWIDTH_HZ:
            hits += 1
    return hits / float(power.shape[0])


def scorePdr(epochs, leftFrequency, rightFrequency, raw=None, ageYears=None,
             artifactRatio=None, modulators=None, autoEyeState=False,
             verbose=True):
    """Score the PDR on all nine SCORE properties.

    epochs         : the artifact-screened, 10-20 montage epochs the rest of the
                     analysis runs on.
    left/right     : posterior dominant frequency per hemisphere, in Hz, from
      Frequency      the model ensemble.
    raw            : optional, for eye-state annotations.
    ageYears       : age at recording. Without it, significance is not scored -
                     a fixed adult threshold would misreport every child.
    artifactRatio  : fraction of epochs dropped, 0-1, used to attribute an
                     absent PDR to artifact.
    modulators     : SCORE modulator names present in the recording.

    Returns a dict of the nine properties plus a 'measures' block of the
    underlying numbers and a 'notes' list.
    """
    modulators = [m.lower() for m in (modulators or [])]
    notes = []
    measures = {}
    out = {}

    freqs = [f for f in (leftFrequency, rightFrequency) if f is not None]
    meanFreq = float(np.mean(freqs)) if freqs else None

    # --- eye state -------------------------------------------------------
    # The band follows the measured frequency so a slow PDR is still measured.
    if meanFreq:
        bandLo = max(meanFreq - PDR_BAND_HALFWIDTH_HZ, 1.0)
        bandHi = meanFreq + PDR_BAND_HALFWIDTH_HZ
    else:
        bandLo, bandHi = 8.0, 13.0
    measures['pdr_band_hz'] = (round(bandLo, 2), round(bandHi, 2))

    posterior = LEFT_POSTERIOR + RIGHT_POSTERIOR
    alphaPower, _ = _bandMeasures(epochs, bandLo, bandHi, posterior)

    states, stateBasis = None, 'posterior channels unavailable'
    if alphaPower is not None:
        states = _eyeStateFromAnnotations(epochs, raw)
        if states is not None:
            stateBasis = 'eye-state annotations in the recording'
        elif autoEyeState:
            states, stateBasis = _eyeStateAutomatic(epochs, alphaPower)
        else:
            # Automatic detection is off by default, and deliberately. On a
            # PhysioNet recording that is entirely eyes-closed it split the
            # record in two and reported reduced left-sided reactivity: posterior
            # alpha waxes and wanes severalfold within a continuously
            # eyes-closed record, and frontal slow activity is not specific
            # enough to blinks to rule that in or out. A false "reduced
            # reactivity" drives the significance of the whole PDR to abnormal,
            # so reactivity is scored only where eye opening was actually marked.
            # Pass autoEyeState=True to use the heuristic anyway.
            stateBasis = ('no eye-state annotations; automatic detection is off '
                          '(mark eye opening and closure at acquisition to enable '
                          'reactivity scoring)')
    stateConfidence = 'high' if 'annotations' in stateBasis else 'medium'

    if states is not None:
        closed = np.where(states == 'closed')[0]
        opened = np.where(states == 'open')[0]
    else:
        # No usable split: treat every epoch as the best available estimate of
        # the eyes-closed state, which is what the rest of the pipeline assumes.
        closed = np.arange(len(epochs))
        opened = np.array([], dtype=int)
        notes.append('Eye state not resolved (%s); reactivity not scored.' % stateBasis)
    measures['epochs_total'] = int(len(epochs))
    measures['epochs_eyes_closed'] = int(len(closed))
    measures['epochs_eyes_open'] = int(len(opened))
    measures['eye_state_basis'] = stateBasis

    closedEpochs = epochs[closed] if len(closed) else epochs

    # --- is there a rhythm at all ----------------------------------------
    specFreqs, specPower = _posteriorSpectrum(closedEpochs, posterior)
    searchLo = 2.0 if (ageYears is not None and ageYears < 3) else 4.0
    peakFreq, prominence = _peak(specFreqs, specPower, searchLo, 14.0)
    measures['posterior_peak_hz'] = None if peakFreq is None else round(peakFreq, 2)
    measures['peak_prominence'] = None if prominence is None else round(prominence, 2)
    pdrPresent = prominence is not None and prominence >= PEAK_MIN_PROMINENCE

    # --- amplitude --------------------------------------------------------
    _, leftAmp = _bandMeasures(closedEpochs, bandLo, bandHi, LEFT_POSTERIOR)
    _, rightAmp = _bandMeasures(closedEpochs, bandLo, bandHi, RIGHT_POSTERIOR)
    leftAmpUv = float(np.median(leftAmp)) if leftAmp is not None else None
    rightAmpUv = float(np.median(rightAmp)) if rightAmp is not None else None
    amps = [a for a in (leftAmpUv, rightAmpUv) if a is not None]
    amplitudeUv = float(np.mean(amps)) if amps else None
    measures['amplitude_left_uv'] = None if leftAmpUv is None else round(leftAmpUv, 1)
    measures['amplitude_right_uv'] = None if rightAmpUv is None else round(rightAmpUv, 1)
    measures['amplitude_uv'] = None if amplitudeUv is None else round(amplitudeUv, 1)

    if amplitudeUv is None:
        out['amplitude'] = _prop(NOT_DETERMINED, basis='posterior channels unavailable')
    else:
        band = AMPLITUDE[0] if amplitudeUv < 20 else (
            AMPLITUDE[1] if amplitudeUv <= 70 else AMPLITUDE[2])
        out['amplitude'] = _prop(
            band, round(amplitudeUv, 1),
            basis='median peak-to-peak, %.1f-%.1f Hz, posterior channels, '
                  'eyes-closed epochs' % (bandLo, bandHi))

    # --- amplitude asymmetry ---------------------------------------------
    if leftAmpUv and rightAmpUv:
        relative = 2 * (leftAmpUv - rightAmpUv) / (leftAmpUv + rightAmpUv)
        measures['amplitude_asymmetry_ratio'] = round(relative, 3)
        if relative >= AMP_ASYMMETRY_RATIO:
            term = AMPLITUDE_ASYMMETRY[1]           # right lower than left
        elif relative <= -AMP_ASYMMETRY_RATIO:
            term = AMPLITUDE_ASYMMETRY[2]           # left lower than right
        else:
            term = AMPLITUDE_ASYMMETRY[0]
        out['amplitude_asymmetry'] = _prop(
            term, round(relative, 3),
            basis='relative difference of left and right posterior amplitude')
    else:
        out['amplitude_asymmetry'] = _prop(NOT_DETERMINED,
                                           basis='one side could not be measured')

    # --- frequency --------------------------------------------------------
    measures['frequency_left_hz'] = leftFrequency
    measures['frequency_right_hz'] = rightFrequency
    if meanFreq is None:
        out['frequency'] = _prop(NOT_DETERMINED, basis='no frequency estimate')
    else:
        agreement = ''
        if peakFreq is not None and abs(peakFreq - meanFreq) > FREQ_AGREEMENT_HZ:
            agreement = ('; spectral peak at %.1f Hz disagrees with the model '
                         'estimate' % peakFreq)
            notes.append('Model frequency %.1f Hz and posterior spectral peak '
                         '%.1f Hz differ by %.1f Hz - confirm which to report.'
                         % (meanFreq, peakFreq, abs(meanFreq - peakFreq)))
        out['frequency'] = _prop(
            '%.1f Hz' % meanFreq, round(meanFreq, 1),
            confidence='medium' if agreement else 'high',
            basis='model ensemble, left %.1f / right %.1f Hz%s'
                  % (leftFrequency, rightFrequency, agreement))

    # --- frequency asymmetry ---------------------------------------------
    if leftFrequency is None or rightFrequency is None:
        out['frequency_asymmetry'] = _prop(NOT_DETERMINED,
                                           basis='one side could not be measured')
    else:
        difference = float(rightFrequency) - float(leftFrequency)
        measures['frequency_asymmetry_hz'] = round(difference, 2)
        if difference >= FREQ_ASYMMETRY_HZ:
            term = '%.1f Hz lower on the left side' % abs(difference)
        elif -difference >= FREQ_ASYMMETRY_HZ:
            term = '%.1f Hz lower on the right side' % abs(difference)
        else:
            term = 'Symmetrical'
        out['frequency_asymmetry'] = _prop(term, round(abs(difference), 1),
                                          basis='difference of the per-hemisphere '
                                                'model estimates')

    # --- reactivity -------------------------------------------------------
    if len(opened) < EYE_STATE_MIN_EPOCHS or len(closed) < EYE_STATE_MIN_EPOCHS:
        out['reactivity'] = _prop(
            NOT_DETERMINED, confidence='high',
            basis='needs both eyes-closed and eyes-open epochs (%s)' % stateBasis)
    else:
        attenuation = {}
        for side, picks in (('left', LEFT_POSTERIOR), ('right', RIGHT_POSTERIOR)):
            power, _ = _bandMeasures(epochs, bandLo, bandHi, picks)
            if power is None:
                attenuation[side] = None
                continue
            shut = float(np.median(power[closed]))
            open_ = float(np.median(power[opened]))
            attenuation[side] = (shut - open_) / shut if shut > 0 else None
        measures['reactivity_attenuation'] = {
            k: (None if v is None else round(v, 3)) for k, v in attenuation.items()}

        reactive = {k: (v is not None and v >= REACTIVITY_MIN_ATTENUATION)
                    for k, v in attenuation.items()}
        if reactive.get('left') and reactive.get('right'):
            term = REACTIVITY[0]
        elif reactive.get('right') and not reactive.get('left'):
            term = REACTIVITY[1]
        elif reactive.get('left') and not reactive.get('right'):
            term = REACTIVITY[2]
        else:
            term = REACTIVITY[3]
        out['reactivity'] = _prop(
            term, measures['reactivity_attenuation'], confidence=stateConfidence,
            basis='posterior band-power drop on eye opening, threshold %.0f%% (%s)'
                  % (REACTIVITY_MIN_ATTENUATION * 100, stateBasis))

    # --- organisation (provisional) ---------------------------------------
    continuity = None
    if peakFreq is not None and len(closed) >= EYE_STATE_MIN_EPOCHS:
        # Fraction of eyes-closed epochs whose own posterior peak sits near the
        # group peak - a rhythm that comes and goes scores lower.
        continuity = _rhythmContinuity(closedEpochs, posterior, peakFreq,
                                       searchLo, 14.0)
    measures['rhythm_continuity'] = None if continuity is None else round(continuity, 3)

    if continuity is None or prominence is None:
        out['organization'] = _prop(NOT_DETERMINED,
                                    basis='no measurable posterior rhythm')
    else:
        if continuity >= ORG_CONTINUITY[0] and prominence >= ORG_CONCENTRATION_NORMAL:
            term = ORGANIZATION[0]
        elif continuity >= ORG_CONTINUITY[1]:
            term = ORGANIZATION[1]
        elif continuity >= ORG_CONTINUITY[2]:
            term = ORGANIZATION[2]
        else:
            term = ORGANIZATION[3]
        out['organization'] = _prop(
            term, {'continuity': round(continuity, 3),
                   'concentration': round(prominence, 2)},
            confidence='low', provisional=True,
            basis='provisional: rhythm continuity %.0f%% and peak-to-broadband '
                  '%.1f. Thresholds are uncalibrated - confirm visually'
                  % (continuity * 100, prominence))

    # --- caveat -----------------------------------------------------------
    # Only meaningful when the rhythm sits clear of the theta band. With a slow
    # PDR the measurement band overlaps 4-8 Hz almost entirely, so the ratio
    # reads ~1.0 by construction - and drowsiness and genuine background slowing
    # are not separable spectrally anyway. Say so rather than guess.
    thetaAlpha = None
    drowsinessMeasurable = bandLo >= 8.0
    if drowsinessMeasurable:
        thetaPower, _ = _bandMeasures(closedEpochs, 4.0, 8.0, posterior)
        closedAlpha, _ = _bandMeasures(closedEpochs, bandLo, bandHi, posterior)
        if thetaPower is not None and closedAlpha is not None:
            denominator = float(np.median(closedAlpha))
            if denominator > 0:
                thetaAlpha = float(np.median(thetaPower)) / denominator
    measures['theta_alpha_ratio'] = None if thetaAlpha is None else round(thetaAlpha, 2)

    if states is not None and len(closed) == 0:
        out['caveat'] = _prop(CAVEAT[1], basis='no eyes-closed epochs found')
    elif any('sleep depriv' in m for m in modulators):
        out['caveat'] = _prop(CAVEAT[2], basis='sleep deprivation recorded as a modulator')
    elif not drowsinessMeasurable:
        out['caveat'] = _prop(
            NOT_DETERMINED,
            basis='the %.1f-%.1f Hz rhythm overlaps the theta band, so drowsiness '
                  'cannot be separated from background slowing without vigilance '
                  'staging' % (bandLo, bandHi))
    elif thetaAlpha is not None and thetaAlpha >= DROWSY_THETA_ALPHA:
        out['caveat'] = _prop(
            CAVEAT[3], round(thetaAlpha, 2), confidence='low', provisional=True,
            basis='provisional: posterior theta/alpha %.2f suggests drowsiness. '
                  'No vigilance staging yet - confirm visually' % thetaAlpha)
    else:
        out['caveat'] = _prop(CAVEAT[0], basis='no caveat detected')

    # --- absence ----------------------------------------------------------
    if pdrPresent:
        out['absence'] = _prop('', basis='a posterior rhythm was identified')
    else:
        if artifactRatio is not None and artifactRatio >= ABSENCE_ARTIFACT_RATIO:
            term, basis = ABSENCE[0], ('%.0f%% of epochs rejected as artifact'
                                       % (artifactRatio * 100))
        elif amplitudeUv is not None and amplitudeUv < LOW_VOLTAGE_UV:
            term, basis = ABSENCE[1], ('posterior amplitude %.1f µV is below '
                                       '%.0f µV' % (amplitudeUv, LOW_VOLTAGE_UV))
        elif states is not None and len(closed) == 0:
            term, basis = ABSENCE[2], 'no eyes-closed epochs found'
        else:
            term, basis = ABSENCE[5], ('no posterior peak above prominence %.1f'
                                       % PEAK_MIN_PROMINENCE)
        out['absence'] = _prop(term, confidence='medium', basis=basis)
        notes.append('No posterior dominant rhythm identified (%s).' % basis)

    # --- significance -----------------------------------------------------
    floor = ageFloorHz(ageYears)
    measures['age_years'] = None if ageYears is None else round(ageYears, 2)
    measures['age_floor_hz'] = None if floor is None else round(floor, 2)

    if ageYears is None:
        out['significance'] = _prop(
            NOT_DETERMINED, confidence='high',
            basis='no age available; the normal lower limit of the PDR is '
                  'age-dependent, so no threshold can be applied')
        notes.append('Patient age unavailable - PDR significance not scored. '
                     'Supply date of birth to enable it.')
    elif not pdrPresent:
        out['significance'] = _prop(
            SIGNIFICANCE[2], confidence='medium',
            basis='no identifiable posterior dominant rhythm')
    else:
        reasons = []
        slowest = min(freqs) if freqs else None
        if slowest is not None and slowest < floor:
            reasons.append('%.1f Hz is below the %.1f Hz floor for age %.1f'
                           % (slowest, floor, ageYears))
        asymmetry = measures.get('frequency_asymmetry_hz')
        if asymmetry is not None and abs(asymmetry) >= FREQ_ASYMMETRY_HZ:
            reasons.append('frequency asymmetry %.1f Hz' % abs(asymmetry))
        if out['reactivity']['term'] in REACTIVITY[1:]:
            reasons.append('reduced reactivity')
        if out['amplitude_asymmetry']['term'] in AMPLITUDE_ASYMMETRY[1:]:
            reasons.append('amplitude asymmetry')

        if reasons:
            out['significance'] = _prop(SIGNIFICANCE[2], confidence='medium',
                                        basis='; '.join(reasons))
        elif slowest is not None and slowest < floor + FREQ_ASYMMETRY_HZ:
            out['significance'] = _prop(
                SIGNIFICANCE[1], confidence='medium',
                basis='%.1f Hz is within %.1f Hz of the %.1f Hz floor for age'
                      % (slowest, FREQ_ASYMMETRY_HZ, floor))
        else:
            out['significance'] = _prop(
                SIGNIFICANCE[0], confidence='medium',
                basis='frequency, symmetry and reactivity all within normal '
                      'limits for age %.1f' % ageYears)

    out['measures'] = measures
    out['notes'] = notes

    if verbose:
        printPdr(out)
    return out


PROPERTY_ORDER = [
    ('significance', 'Significance'),
    ('frequency', 'Frequency'),
    ('frequency_asymmetry', 'Frequency asymmetry'),
    ('amplitude', 'Amplitude'),
    ('amplitude_asymmetry', 'Amplitude asymmetry'),
    ('reactivity', 'Reactivity to eye opening'),
    ('organization', 'Organization'),
    ('caveat', 'Caveat'),
    ('absence', 'Absence of PDR'),
]


def printPdr(pdr):
    """Log the scored PDR, for the run log."""
    print('--- Posterior dominant rhythm (SCORE) ---')
    for key, label in PROPERTY_ORDER:
        prop = pdr.get(key)
        if not prop or not prop.get('term'):
            continue
        flag = ' [provisional]' if prop.get('provisional') else ''
        print('  %-26s %s%s' % (label + ':', prop['term'], flag))
        if prop.get('basis'):
            print('  %-26s   %s' % ('', prop['basis']))
    for note in pdr.get('notes', []):
        print('  NOTE: %s' % note)
