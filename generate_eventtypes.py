"""Generate eventtypes.py: EnumEventType -> ProfusionEEG's own display strings.

The enum and the gs_EventStringIDs table come from ProFusionEEG's EEGEvent.cpp;
the display strings come from ProFusionEEG.rc. This writes the resulting table
out as a Python module so the project does not have to carry either file.
"""
import io
import re

RC = 'c:/Users/wef.CMPHQ/Claude/AI_EEEG_REPORT/ProFusionEEG.rc'
OUT = 'c:/Users/wef.CMPHQ/Claude/AI_EEEG_REPORT/eventtypes.py'

# EnumEventType, verbatim: identifier -> numeric value.
ENUM = [
    ('eetInvalid', -1), ('eetUnknown', 0), ('eetAnnotation', 1), ('eetBookmark', 2),
    ('eetMontageChange', 3), ('eetPhotic', 4), ('eetTemplateMatch', 5),
    ('eetVideo', 6), ('eetCalibration', 7), ('eetHyperventilation', 8),
    ('eetData', 9), ('eetNoData', 10), ('eetExcessPreviewData', 11),
    ('eetMarkedRegionEEG', 12), ('eetForDeletionEEG', 13), ('eetZTest', 14),
    ('eetLostPackets', 15), ('eetEventButton', 16), ('eetGain', 17),
    ('eetGZTestEnd', 18), ('eetUserOperation', 19),
    ('eetNetViewStartRecording', 20), ('eetNetViewStopRecording', 21),
    ('eetRevealAnyType', 22), ('eetRevealSpike', 23), ('eetRevealSpikeBurst', 24),
    ('eetRevealRhythmBurst', 25), ('eetRevealVPlotType', 26),
    ('eetElectrodeAssignmentChange', 27), ('eetMontageSequenceChange', 28),
    ('eetHighPassFilterChange', 29), ('eetNotchFilterChange', 30),
    ('eetLowPassFilterChange', 31), ('eetVerticalScaleChange', 32),
    ('eetTimeBaseChange', 33), ('eetNoiseReductionChange', 34),
    ('eetPhoticFrequencyChange', 35), ('eetAmpDataError', 36),
    ('eetAmpZDataError', 37), ('eetAmpAmbulatoryError', 38),
    ('eetImpedanceDataBlock', 39), ('eetTaggedRegion', 40),
    ('eetTaggedBrainMap', 41), ('eetTaggedBrainCartoon', 42),
    ('eetTaggedBrainSpectrum', 43), ('eetTaggedBrainCoherence', 44),
    ('eetPhoticFlash', 45), ('eetPostHyperventilation', 46),
    ('eetSelectionMarker', 47), ('eetOximeterDesat', 48), ('eetCachedData', 49),
    ('eetCorticalStimulation', 50), ('eetViewed', 51), ('eetEditingSession', 52),
    ('eetAlertsCleared', 53), ('eetIdentEventEvent', 54),
    ('eetVideoProfileChanged', 55), ('eetUserLoggedOn', 56),
    ('eetUserLoggedOff', 57), ('eetBatteryFlat', 58), ('eetRecordedSession', 59),
    ('eetTrigger', 60), ('eetResponse', 61), ('eetNotForDeletion', 62),
    ('eetGenericTimer', 63), ('eetJackboxConnect', 64),
    ('eetJackboxDisconnect', 65), ('eetHeartRateAlarm', 66),
    ('eetCorticalStimCurrentConfirmed', 67), ('eetHFO', 68),
    ('eetMarkedRegionVideo', 69), ('eetForDeletionVideo', 70), ('eetVideo2', 71),
    ('eetClickerTest', 72), ('eetNotMarkedRegionEEG', 73), ('eetEEGSpike', 74),
    ('eetEEGSeizure', 75), ('eetNetworkEvent', 76), ('eetVideo3', 77),
    ('eetVideo4', 78), ('eetHDSpaceLowWarning', 79),
    ('eetHDSpaceLowVideoStopped', 80), ('eetSDCardSpaceLowWarning', 81),
    ('eetSDCardRecordingStopped', 82), ('eetOktiPowerSource', 83),
    ('eetSDCardRecordingStarted', 84), ('eetNoEEGData', 85),
]

# gs_EventStringIDs, verbatim: identifier -> resource identifier.
STRING_IDS = {
    'eetUnknown': 'IDS_EEG_EVENT_TYPE_UNKNOWN',
    'eetAnnotation': 'IDS_EEG_EVENT_TYPE_ANNOTATION',
    'eetBookmark': 'IDS_EEG_EVENT_TYPE_BOOKMARK',
    'eetMontageChange': 'IDS_EEG_EVENT_TYPE_MONTAGE_CHANGE',
    'eetPhotic': 'IDS_EEG_EVENT_TYPE_PHOTIC',
    'eetTemplateMatch': 'IDS_EEG_EVENT_TYPE_TEMPLATE_MATCH',
    'eetVideo': 'IDS_EEG_EVENT_TYPE_VIDEO',
    'eetCalibration': 'IDS_EEG_EVENT_TYPE_CALIBRATION',
    'eetHyperventilation': 'IDS_EEG_EVENT_TYPE_HYPERVENTILATION',
    'eetData': 'IDS_EEG_EVENT_DATA',
    'eetNoData': 'IDS_EEG_EVENT_NODATA',
    'eetExcessPreviewData': 'IDS_EEG_EVENT_EXCESS_PREVIEW_DATA',
    'eetMarkedRegionEEG': 'IDS_EEG_EVENT_TYPE_MARKED_REGION_EEG',
    'eetForDeletionEEG': 'IDS_EEG_EVENT_TYPE_FOR_DELETION_EEG',
    'eetZTest': 'IDS_EEG_EVENT_TYPE_Z_TEST',
    'eetLostPackets': 'IDS_EEG_EVENT_TYPE_LOST_PACKETS',
    'eetEventButton': 'IDS_EEG_EVENT_TYPE_EVENT_BUTTON',
    'eetGain': 'IDS_EEG_EVENT_TYPE_GAIN',
    'eetGZTestEnd': 'IDS_EEG_EVENT_TYPE_GZ_TEST_END',
    'eetUserOperation': 'IDS_EEG_EVENT_TYPE_USER_OPERATION',
    'eetNetViewStartRecording': 'IDS_EEG_EVENT_TYPE_START_RECORDING',
    'eetNetViewStopRecording': 'IDS_EEG_EVENT_TYPE_STOP_RECORDING',
    'eetRevealAnyType': 'IDS_EEG_EVENT_TYPE_REVEAL_ANY_TYPE',
    'eetRevealSpike': 'IDS_EEG_EVENT_TYPE_REVEAL_SPIKE',
    'eetRevealSpikeBurst': 'IDS_EEG_EVENT_TYPE_REVEAL_SPIKE_BURST',
    'eetRevealRhythmBurst': 'IDS_EEG_EVENT_TYPE_REVEAL_RHYTHM_BURST',
    'eetRevealVPlotType': 'IDS_EEG_EVENT_TYPE_REVEAL_VPLOT_TYPE',
    'eetElectrodeAssignmentChange': 'IDS_EEG_EVENT_TYPE_ELECTRODE_ASSIGNMENT_CHANGE',
    'eetMontageSequenceChange': 'IDS_EEG_EVENT_TYPE_MONTAGE_SEQUENCE_CHANGE',
    'eetHighPassFilterChange': 'IDS_EEG_EVENT_TYPE_HIGH_PASS_FILTER_CHANGE',
    'eetNotchFilterChange': 'IDS_EEG_EVENT_TYPE_NOTCH_FILTER_CHANGE',
    'eetLowPassFilterChange': 'IDS_EEG_EVENT_TYPE_LOW_PASS_FILTER_CHANGE',
    'eetVerticalScaleChange': 'IDS_EEG_EVENT_TYPE_SENSITIVITY_CHANGE',
    'eetTimeBaseChange': 'IDS_EEG_EVENT_TYPE_TIME_BASE_CHANGE',
    'eetNoiseReductionChange': 'IDS_EEG_EVENT_TYPE_NOISE_REDUCTION_CHANGE',
    'eetPhoticFrequencyChange': 'IDS_EEG_EVENT_TYPE_PHOTIC_FREQUENCY_CHANGE',
    'eetAmpDataError': 'IDS_EEG_EVENT_TYPE_AMP_DATA_ERROR',
    'eetAmpZDataError': 'IDS_EEG_EVENT_TYPE_AMP_ZDATA_ERROR',
    'eetAmpAmbulatoryError': 'IDS_EEG_EVENT_TYPE_AMP_AMBULATORY_ERROR',
    'eetImpedanceDataBlock': 'IDS_EEG_EVENT_TYPE_IMPEDANCE_DATA_BLOCK',
    'eetTaggedRegion': 'IDS_EEG_EVENT_TYPE_TAGGED_REGION',
    'eetTaggedBrainMap': 'IDS_EEG_EVENT_TYPE_TAGGED_BRAIN_MAP',
    'eetTaggedBrainCartoon': 'IDS_EEG_EVENT_TYPE_TAGGED_BRAIN_CARTOON',
    'eetTaggedBrainSpectrum': 'IDS_EEG_EVENT_TYPE_TAGGED_BRAIN_SPECTRUM',
    'eetTaggedBrainCoherence': 'IDS_EEG_EVENT_TYPE_TAGGED_BRAIN_COHERENCE',
    'eetPhoticFlash': 'IDS_EEG_EVENT_TYPE_PHOTIC_FLASH',
    'eetPostHyperventilation': 'IDS_EEG_EVENT_TYPE_POST_HYPERVENTILATION',
    'eetSelectionMarker': 'IDS_EEG_EVENT_TYPE_SELECTION_MARKER',
    'eetOximeterDesat': 'IDS_EEG_EVENT_TYPE_OXIMETER_DESAT',
    'eetCachedData': 'IDS_EEG_EVENT_TYPE_CACHED_DATA',
    'eetCorticalStimulation': 'IDS_EEG_EVENT_TYPE_CORTICAL_STIMULATION',
    'eetViewed': 'IDS_EEG_EVENT_TYPE_VIEWED',
    'eetEditingSession': 'IDS_EEG_EVENT_TYPE_EDITING_SESSION',
    'eetAlertsCleared': 'IDS_EEG_EVENT_TYPE_ALERTS_CLEARED',
    'eetIdentEventEvent': 'IDS_EEG_EVENT_TYPE_IDENT_EVENT_EVENT',
    'eetVideoProfileChanged': 'IDS_EEG_EVENT_TYPE_VIDEO_PROFILE_CHANGED',
    'eetUserLoggedOn': 'IDS_EEG_EVENT_TYPE_USER_LOGGED_ON',
    'eetUserLoggedOff': 'IDS_EEG_EVENT_TYPE_USER_LOGGED_OFF',
    'eetBatteryFlat': 'IDS_EEG_EVENT_TYPE_BATTERY_FLAT',
    'eetRecordedSession': 'IDS_EEG_EVENT_TYPE_RECORDED_SESSION',
    'eetTrigger': 'IDS_EEG_EVENT_TYPE_TRIGGER',
    'eetResponse': 'IDS_EEG_EVENT_TYPE_RESPONSE',
    'eetNotForDeletion': 'IDS_EEG_EVENT_TYPE_NOT_FOR_DELETION',
    'eetGenericTimer': 'IDS_EEG_EVENT_TYPE_GENERIC_TIMER',
    'eetJackboxConnect': 'IDS_EEG_EVENT_TYPE_JACKBOX_CONNECT',
    'eetJackboxDisconnect': 'IDS_EEG_EVENT_TYPE_JACKBOX_DISCONNECT',
    'eetHeartRateAlarm': 'IDS_EEG_EVENT_TYPE_HEART_RATE_ALARM',
    'eetCorticalStimCurrentConfirmed': 'IDS_EEG_EVENT_TYPE_CORTICAL_STIM_CURRENT_CONFIRMED',
    'eetHFO': 'IDS_EEG_EVENT_TYPE_HIGH_FREQUENCY_OSCILLATION',
    'eetMarkedRegionVideo': 'IDS_EEG_EVENT_TYPE_MARKED_REGION_VIDEO',
    'eetForDeletionVideo': 'IDS_EEG_EVENT_TYPE_FOR_DELETION_VIDEO',
    'eetVideo2': 'IDS_EEG_EVENT_TYPE_VIDEO_2',
    'eetClickerTest': 'IDS_EEG_EVENT_TYPE_CLICKER_TEST',
    'eetNotMarkedRegionEEG': 'IDS_EEG_EVENT_TYPE_NOT_MARKED_REGION_EEG',
    'eetEEGSpike': 'IDS_EEG_EVENT_TYPE_SPIKE',
    'eetEEGSeizure': 'IDS_EEG_EVENT_TYPE_SEIZURE',
    'eetNetworkEvent': 'IDS_EEG_EVENT_TYPE_NETWORK_EVENT',
    'eetVideo3': 'IDS_EEG_EVENT_TYPE_VIDEO_3',
    'eetVideo4': 'IDS_EEG_EVENT_TYPE_VIDEO_4',
    'eetHDSpaceLowWarning': 'IDS_EEG_EVENT_TYPE_HD_SPACE_LOW_WARNING',
    'eetHDSpaceLowVideoStopped': 'IDS_EEG_EVENT_TYPE_HD_SPACE_LOW_VIDEO_STOPPED',
    'eetSDCardSpaceLowWarning': 'IDS_EEG_EVENT_TYPE_SD_CARD_SPACE_LOW_WARNING',
    'eetSDCardRecordingStopped': 'IDS_EEG_EVENT_TYPE_SD_CARD_RECORDING_STOPPED',
    'eetOktiPowerSource': 'IDS_EEG_EVENT_TYPE_OKTI_POWER_SOURCE',
    'eetSDCardRecordingStarted': 'IDS_EEG_EVENT_TYPE_SD_CARD_RECORDING_STARTED',
    'eetNoEEGData': 'IDS_EEG_EVENT_TYPE_NO_EEG_DATA',
}

rc = io.open(RC, encoding='latin-1').read()
strings = dict(re.findall(r'\b(IDS_[A-Z0-9_]+)\s+"((?:[^"]|"")*)"', rc))
print('resource strings found in the .rc: %d' % len(strings))

rows, missing = [], []
for identifier, value in ENUM:
    resourceId = STRING_IDS.get(identifier)
    label = strings.get(resourceId) if resourceId else None
    if resourceId and label is None:
        missing.append((identifier, resourceId))
    rows.append((value, identifier, label))

if missing:
    print('no string in the .rc for:')
    for identifier, resourceId in missing:
        print('   %-32s %s' % (identifier, resourceId))

body = io.StringIO()
body.write('''############################################
# ProfusionEEG event types, and the words ProfusionEEG itself uses for them.
#
# An event in a study carries a numeric EventTypeID and nothing else that names
# it. Without this table the review front end could only show numbers, and
# spike and seizure detections could not be told apart from a technologist's
# annotation - which is exactly what went wrong when the event text was matched
# instead.
#
# Two things matter most here:
#
#   eetEEGSpike (74) and eetEEGSeizure (75) are the Spike and Seizure plug-in's
#   own types. They are what identifies a detection, and they are the default
#   the mapper selects on.
#
#   eetAnnotation (1) is a technologist's annotation. Every study examined has
#   its EEGEventString rows under this one type, because that table is the
#   pick-list of annotation texts, not a list of type names.
#
# The Persyst Reveal types (22-26) are a different detector and are not selected
# by default; a study carrying them is reported rather than silently mixed in.
#
# GENERATED - do not edit by hand. The enum and gs_EventStringIDs come from
# ProFusionEEG's EEGEvent.cpp; the display strings from ProFusionEEG.rc. Rebuild
# with generate_eventtypes.py, which needs ProFusionEEG.rc in the repository
# root - the .rc itself is gitignored as product source.
############################################

# id -> (identifier, display label). A label of None means ProfusionEEG defines
# no string for that type, so it is shown by its identifier instead.
EVENT_TYPES = {
''')
for value, identifier, label in rows:
    body.write('    %4d: (%r, %r),\n' % (value, identifier, label))
body.write('''}

# Some studies store the type with 1000 added - see resolveTypeId().
DB_TYPE_OFFSET = 1000

# The Spike and Seizure plug-in.
SPIKE_TYPES = (74,)
SEIZURE_TYPES = (75,)

# Persyst Reveal, a separate detector. Recognised, labelled, not selected by
# default: attributing its output to the cleared detector would be wrong.
REVEAL_SPIKE_TYPES = (23, 24)
REVEAL_SEIZURE_TYPES = (22,)
REVEAL_TYPES = (22, 23, 24, 25, 26)

# High-frequency oscillations, another separate plug-in.
HFO_TYPES = (68,)

# A technologist's annotation, and the reason EEGEventString is all type 1.
ANNOTATION_TYPE = 1

# SCORE wants the provocations recorded. These are the types that carry them.
PROVOCATION_TYPES = {
    4: 'Photic stimulation',
    45: 'Photic stimulation',
    # A photic run is evidenced by its frequency changes: 05JC.eeg records nine
    # of them, at 4 to 40 Hz, and no individual flashes. recording.py counts
    # these as photic, so they are flagged as photic here too.
    35: 'Photic stimulation',
    8: 'Hyperventilation',
    46: 'Post hyperventilation',
    50: 'Cortical stimulation',
}


def resolveTypeId(typeId):
    """The enum value a stored EventTypeID refers to, and whether it was offset.

    Studies have been seen storing the type with 1000 added: 1029 alongside text
    '0.50' is eetHighPassFilterChange with a 0.5 Hz setting, 1031 with '70' is
    eetLowPassFilterChange, and 1051 with a user name is eetViewed. Small values
    appear unoffset in the same studies, so both forms are accepted rather than
    one rule being assumed.

    Returns (resolvedId, wasOffset).
    """
    if typeId is None:
        return None, False
    typeId = int(typeId)
    if typeId in EVENT_TYPES:
        return typeId, False
    candidate = typeId - DB_TYPE_OFFSET
    if candidate in EVENT_TYPES:
        return candidate, True
    return typeId, False


def identifierFor(typeId):
    """The enum identifier, e.g. 'eetEEGSpike', or None."""
    resolved, _ = resolveTypeId(typeId)
    entry = EVENT_TYPES.get(resolved)
    return entry[0] if entry else None


def labelFor(typeId):
    """What ProfusionEEG calls this event type.

    Falls back to the enum identifier where the application defines no string,
    and to the number itself where the type is not in the enum at all - never to
    a guess, and never to the event's own text.
    """
    resolved, offset = resolveTypeId(typeId)
    entry = EVENT_TYPES.get(resolved)
    if not entry:
        # Not in the enum at all. The number is all there is, so it is shown as
        # an unrecognised type rather than dressed up as a name.
        return 'Unrecognised type %s' % typeId
    identifier, label = entry
    return label or identifier


def isSpike(typeId, includeReveal=False):
    resolved, _ = resolveTypeId(typeId)
    if resolved in SPIKE_TYPES:
        return True
    return bool(includeReveal and resolved in REVEAL_SPIKE_TYPES)


def isSeizure(typeId, includeReveal=False):
    resolved, _ = resolveTypeId(typeId)
    if resolved in SEIZURE_TYPES:
        return True
    return bool(includeReveal and resolved in REVEAL_SEIZURE_TYPES)


def isDetection(typeId, includeReveal=False):
    return isSpike(typeId, includeReveal) or isSeizure(typeId, includeReveal)


def isAnnotation(typeId):
    resolved, _ = resolveTypeId(typeId)
    return resolved == ANNOTATION_TYPE


def provocationFor(typeId):
    """The provocation this event records, for SCORE section 2, or None."""
    resolved, _ = resolveTypeId(typeId)
    return PROVOCATION_TYPES.get(resolved)
''')

io.open(OUT, 'w', encoding='utf-8', newline='').write(body.getvalue())
labelled = sum(1 for _, _, label in rows if label)
print('wrote eventtypes.py: %d types, %d with a display string' % (len(rows), labelled))
for value, identifier, label in rows:
    if identifier in ('eetEEGSpike', 'eetEEGSeizure', 'eetAnnotation',
                      'eetRevealSpike', 'eetHFO', 'eetViewed'):
        print('   %4d %-22s %r' % (value, identifier, label))
