############################################
# Shared SCORE vocabulary: location and time-related features.
#
# Every finding in SCORE - a spike, a run of rhythmic delta, an artifact - is
# characterised on the same axes (name/morphology, location, time-related
# features, modulators). Location and the time bands are therefore built once,
# here, rather than once per detector.
#
# Reference: Beniczky et al., Standardized computer-based organized reporting of
# EEG: SCORE - Second version, Clin Neurophysiol 2017;128:2334-2346, and its
# Table 6 for the incidence and prevalence bands.
############################################

LATERALITY = ('Left', 'Right', 'Midline', 'Bilateral', 'Diffuse')
REGIONS = ('Frontal', 'Central', 'Temporal', 'Parietal', 'Occipital')

# The 10-20 electrodes grouped onto SCORE's five regions. F7/F8 are frontal
# rather than temporal in this scheme, matching SCORE's region list; the
# posterior temporal pair T5/T6 are temporal.
ELECTRODE_REGION = {
    'Fp1': 'Frontal', 'Fp2': 'Frontal', 'F7': 'Frontal', 'F3': 'Frontal',
    'Fz': 'Frontal', 'F4': 'Frontal', 'F8': 'Frontal',
    'T3': 'Temporal', 'T4': 'Temporal', 'T5': 'Temporal', 'T6': 'Temporal',
    'C3': 'Central', 'Cz': 'Central', 'C4': 'Central',
    'P3': 'Parietal', 'Pz': 'Parietal', 'P4': 'Parietal',
    'O1': 'Occipital', 'O2': 'Occipital',
}

# Odd numbers are left, even are right, 'z' is midline - the 10-20 convention.
def electrodeSide(name):
    """'Left', 'Right', 'Midline' or None for a 10-20 electrode name."""
    if not name:
        return None
    if name.endswith('z') or name.endswith('Z'):
        return 'Midline'
    digits = ''.join(c for c in name if c.isdigit())
    if not digits:
        return None
    return 'Left' if int(digits) % 2 else 'Right'


# Bilateral involvement covering at least this many of the five regions on both
# sides is reported as diffuse. SCORE reserves "diffuse" for activity occurring
# *asynchronously* over large areas of both sides; asynchrony is not assessed
# here, so this is a spatial-extent approximation and is flagged as such by
# callers that care.
DIFFUSE_MIN_REGIONS = 4


def locationFromChannels(channels, amplitudes=None):
    """Describe a set of involved channels in SCORE's location vocabulary.

    channels   : involved electrode names.
    amplitudes : optional {channel: magnitude}, used to name the location
                 maximum - the electrode where the finding is largest, which
                 SCORE records alongside the region.

    Returns a dict with 'laterality', 'regions', 'maximum', 'channels' and a
    'text' rendering for the report.
    """
    channels = [c for c in (channels or []) if c in ELECTRODE_REGION]
    if not channels:
        return {'laterality': None, 'regions': [], 'maximum': None,
                'channels': [], 'text': 'not localised'}

    sides = {electrodeSide(c) for c in channels}
    sides.discard(None)
    regions = []
    for c in channels:
        region = ELECTRODE_REGION[c]
        if region not in regions:
            regions.append(region)
    regions.sort(key=REGIONS.index)

    hasLeft, hasRight = 'Left' in sides, 'Right' in sides
    if hasLeft and hasRight:
        laterality = ('Diffuse' if len(regions) >= DIFFUSE_MIN_REGIONS
                      else 'Bilateral')
    elif hasLeft:
        laterality = 'Left'
    elif hasRight:
        laterality = 'Right'
    else:
        laterality = 'Midline'

    maximum = None
    if amplitudes:
        candidates = {c: amplitudes[c] for c in channels if c in amplitudes}
        if candidates:
            maximum = max(candidates, key=candidates.get)

    text = '%s %s' % (laterality, '/'.join(regions).lower()) if regions else laterality
    if maximum:
        text += ', maximum %s' % maximum
    return {'laterality': laterality, 'regions': regions, 'maximum': maximum,
            'channels': sorted(channels), 'text': text}


# SCORE Table 6. Prevalence is for trains and bursts - the percentage of the
# recording the pattern covers.
PREVALENCE_BANDS = (
    (0.01, 'Rare (<1%)'),
    (0.10, 'Occasional (1-9%)'),
    (0.50, 'Frequent (10-49%)'),
    (0.90, 'Abundant (50-89%)'),
    (float('inf'), 'Continuous (>90%)'),
)

# Incidence is for single discharges - how often one occurs. Expressed here as
# events per second so the comparison is unit-safe.
INCIDENCE_BANDS = (
    (1.0 / 3600, 'Rare (less than 1/h)'),
    (1.0 / 300, 'Uncommon (1/5 min to 1/h)'),
    (1.0 / 60, 'Occasional (1/min to 1/5 min)'),
    (1.0 / 10, 'Frequent (1/10 s to 1/min)'),
    (float('inf'), 'Abundant (>1/10 s)'),
)


# --------------------------------------------------- diagnostic significance
# SCORE section 15 and Table 17. This is a forced-choice list: the report's
# conclusion is picked from these terms, never written freehand.

SIGNIFICANCE_CATEGORIES = ('Normal recording', 'Abnormal recording',
                           'No definite abnormality')

# Diagnostic yield, for an abnormal recording (Table 17).
SIGNIFICANCE_YIELDS = (
    'Epilepsy',
    'Status epilepticus',
    'Continuous spikes and waves during slow sleep (CSWS) or electrical status '
    'epilepticus in sleep (ESES)',
    'Psychogenic non-epileptic seizures (PNES)',
    'Other non-epileptic clinical episode',
    'Focal dysfunction of the central nervous system',
    'Diffuse dysfunction of the central nervous system',
    'Coma',
    'Brain death',
    'EEG abnormality of uncertain clinical significance',
)

# What this pipeline can actually support. It analyses background, artifacts and
# sleep; it has no epileptiform detection, no episode capture and no clinical
# context, so the yields that rest on those cannot be proposed from it however
# suggestive the background looks. Anything outside this set is rejected rather
# than passed to the reader, because a conclusion of "epilepsy" carries
# consequences that a background analysis cannot justify.
SUPPORTABLE_YIELDS = (
    'Focal dysfunction of the central nervous system',
    'Diffuse dysfunction of the central nervous system',
    'EEG abnormality of uncertain clinical significance',
)

UNSUPPORTABLE_REASON = {
    'Epilepsy': 'needs epileptiform findings, which this analysis does not detect',
    'Status epilepticus': 'needs ictal pattern detection, which is not implemented',
    'Continuous spikes and waves during slow sleep (CSWS) or electrical status '
    'epilepticus in sleep (ESES)': 'needs spike-wave quantification in sleep',
    'Psychogenic non-epileptic seizures (PNES)': 'needs recorded episodes and clinical correlation',
    'Other non-epileptic clinical episode': 'needs recorded episodes',
    'Coma': 'needs the clinical state, which the signal alone does not give',
    'Brain death': 'needs a dedicated protocol and clinical criteria',
}


def validateSignificance(category, yields):
    """Check a proposed conclusion against SCORE's vocabulary.

    Returns (category, accepted, rejected) where rejected lists (term, reason)
    for anything outside SCORE's list or beyond what this analysis supports.
    Silently dropping them would be worse than saying why.
    """
    if category not in SIGNIFICANCE_CATEGORIES:
        category = None

    accepted, rejected = [], []
    for term in (yields or []):
        term = (term or '').strip()
        if not term:
            continue
        if term in SUPPORTABLE_YIELDS:
            accepted.append(term)
        elif term in SIGNIFICANCE_YIELDS:
            rejected.append((term, UNSUPPORTABLE_REASON.get(
                term, 'not supportable from background analysis alone')))
        else:
            rejected.append((term, 'not a SCORE diagnostic-significance term'))
    return category, accepted, rejected


# SCORE Table 8's duration bands. Defined there for rhythmic and periodic
# patterns, but they are the vocabulary SCORE uses for the duration of a timed
# finding generally, so episodes are described with them too.
DURATION_BANDS = (
    (10.0, 'Very brief (<10 s)'),
    (60.0, 'Brief (10-59 s)'),
    (300.0, 'Intermediate (1-4.9 min)'),
    (3600.0, 'Long (5-59 min)'),
    (float('inf'), 'Very long (>1 h)'),
)


def durationBand(seconds):
    """SCORE duration band for a finding of this length."""
    if seconds is None or seconds < 0:
        return None
    for limit, label in DURATION_BANDS:
        if seconds < limit:
            return label
    return DURATION_BANDS[-1][1]


def prevalenceBand(coveredSeconds, analysedSeconds):
    """SCORE prevalence band for a pattern covering part of the recording.

    analysedSeconds must be the duration actually assessed, not the length of
    the recording: a pipeline that discards epochs and then divides by the full
    length understates every prevalence it reports.
    """
    if not analysedSeconds or analysedSeconds <= 0 or coveredSeconds is None:
        return None, None
    fraction = max(0.0, min(1.0, coveredSeconds / float(analysedSeconds)))
    for limit, label in PREVALENCE_BANDS:
        if fraction < limit:
            return label, fraction
    return PREVALENCE_BANDS[-1][1], fraction


def incidenceBand(count, analysedSeconds):
    """SCORE incidence band for a count of discrete events."""
    if not analysedSeconds or analysedSeconds <= 0 or count is None:
        return None, None
    if count == 0:
        return None, 0.0
    if count == 1:
        return 'Only once', 1.0 / analysedSeconds
    rate = count / float(analysedSeconds)
    for limit, label in INCIDENCE_BANDS:
        if rate < limit:
            return label, rate
    return INCIDENCE_BANDS[-1][1], rate

# Vocabularies for the entries SCORE leaves to the electroencephalographer.
#
# Where SCORE or the ILAE fixes the choices, the reader picks from them rather
# than typing: a free-text box invites 'abnormal', 'Abnormal.' and 'ABNORMAL'
# into the same field across three reports, and none of them can be counted
# afterwards. Where no standard list exists the field stays free text, because
# inventing one would be worse than leaving it open.

# SCORE Table 15. The measurement says how much of the recording an artifact
# covers; whether that ruined it is a judgement about what could still be read.
ARTIFACT_SIGNIFICANCE = (
    'Does not interfere with interpretation',
    'Reduced diagnostic value',
    'Not interpretable',
)

# ILAE 2017 operational classification of seizure types, expanded basic level.
# An electrographic detection is not one of these on its own - the classification
# needs the semiology and the clinical record, which is why it is the reader's.
ILAE_SEIZURE_TYPES = (
    'Focal aware',
    'Focal impaired awareness',
    'Focal motor onset',
    'Focal non-motor onset',
    'Focal to bilateral tonic-clonic',
    'Generalised motor - tonic-clonic',
    'Generalised motor - other',
    'Generalised non-motor - absence',
    'Unknown onset - motor, tonic-clonic',
    'Unknown onset - non-motor',
    'Unclassified',
)

# Whether the patient was aware and responsive during an episode.
CONSCIOUSNESS_STATES = (
    'Aware and responsive',
    'Aware, not responsive',
    'Impaired awareness',
    'Not possible to determine',
)

# How the clinical event and the EEG change relate in time.
CLINICAL_EEG_RELATIONSHIPS = (
    'EEG change precedes the clinical event',
    'Simultaneous',
    'Clinical event precedes the EEG change',
    'No clinical event observed',
    'Not possible to determine',
)

# Alertness, which SCORE records as part of the recording conditions.
ALERTNESS_STATES = (
    'Awake and cooperative',
    'Awake, poorly cooperative',
    'Drowsy',
    'Asleep',
    'Obtunded',
    'Comatose',
    'Not recorded',
)
