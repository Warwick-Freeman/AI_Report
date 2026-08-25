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
