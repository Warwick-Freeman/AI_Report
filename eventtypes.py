############################################
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
      -1: ('eetInvalid', None),
       0: ('eetUnknown', 'Unkown'),
       1: ('eetAnnotation', 'Annotation'),
       2: ('eetBookmark', 'Bookmark'),
       3: ('eetMontageChange', 'Montage Change'),
       4: ('eetPhotic', 'Photic'),
       5: ('eetTemplateMatch', 'Template Match'),
       6: ('eetVideo', 'Video'),
       7: ('eetCalibration', 'Calibration'),
       8: ('eetHyperventilation', 'Hyperventilation'),
       9: ('eetData', 'EEG Data'),
      10: ('eetNoData', 'No EEG Data'),
      11: ('eetExcessPreviewData', 'Safeguard Preview Data'),
      12: ('eetMarkedRegionEEG', 'Keep EEG'),
      13: ('eetForDeletionEEG', 'For deletion EEG'),
      14: ('eetZTest', 'Impedance Test'),
      15: ('eetLostPackets', 'Lost Packets'),
      16: ('eetEventButton', 'Event Button'),
      17: ('eetGain', 'Gain'),
      18: ('eetGZTestEnd', 'G Impedance Test End'),
      19: ('eetUserOperation', 'User Operation'),
      20: ('eetNetViewStartRecording', 'Recording started'),
      21: ('eetNetViewStopRecording', 'Recording stopped'),
      22: ('eetRevealAnyType', 'Persyst: Seizure'),
      23: ('eetRevealSpike', 'Persyst: Spike'),
      24: ('eetRevealSpikeBurst', 'Persyst: Spike burst'),
      25: ('eetRevealRhythmBurst', 'Persyst: Rhythmic burst'),
      26: ('eetRevealVPlotType', 'Persyst: V Plot'),
      27: ('eetElectrodeAssignmentChange', 'Electrode Assignment Change'),
      28: ('eetMontageSequenceChange', 'Montage Sequence Change'),
      29: ('eetHighPassFilterChange', 'High Pass Change'),
      30: ('eetNotchFilterChange', 'Notch Change'),
      31: ('eetLowPassFilterChange', 'Low Pass Change'),
      32: ('eetVerticalScaleChange', 'Sensitivity Change'),
      33: ('eetTimeBaseChange', 'Time Base Change'),
      34: ('eetNoiseReductionChange', 'Noise Reduction Change'),
      35: ('eetPhoticFrequencyChange', 'Photic Frequency change'),
      36: ('eetAmpDataError', 'Amplifier Data Error'),
      37: ('eetAmpZDataError', 'Amplifier Impedance Data Error'),
      38: ('eetAmpAmbulatoryError', 'Amplifier Ambulatory Error'),
      39: ('eetImpedanceDataBlock', 'Impedance data block'),
      40: ('eetTaggedRegion', 'Reporting Tag'),
      41: ('eetTaggedBrainMap', 'Brain Map tag'),
      42: ('eetTaggedBrainCartoon', 'Brain Map Cartoon tag'),
      43: ('eetTaggedBrainSpectrum', 'Spectrum Brain Map tag'),
      44: ('eetTaggedBrainCoherence', 'Coherence Brain Map tag'),
      45: ('eetPhoticFlash', 'Photic Flash'),
      46: ('eetPostHyperventilation', 'Post Hyperventilation'),
      47: ('eetSelectionMarker', 'Selection Marker'),
      48: ('eetOximeterDesat', 'Oximeter Desaturation'),
      49: ('eetCachedData', 'Cached Data'),
      50: ('eetCorticalStimulation', 'Cortical Stimulation'),
      51: ('eetViewed', 'Viewed'),
      52: ('eetEditingSession', 'Current Editing Session'),
      53: ('eetAlertsCleared', 'Alerts Cleared'),
      54: ('eetIdentEventEvent', 'IdentEvent'),
      55: ('eetVideoProfileChanged', 'Video Profile Changed'),
      56: ('eetUserLoggedOn', 'User logged on'),
      57: ('eetUserLoggedOff', 'User logged off'),
      58: ('eetBatteryFlat', 'Battery Flat'),
      59: ('eetRecordedSession', 'Recorded Session'),
      60: ('eetTrigger', 'Trigger'),
      61: ('eetResponse', 'Response'),
      62: ('eetNotForDeletion', 'Save Data'),
      63: ('eetGenericTimer', 'Timer'),
      64: ('eetJackboxConnect', 'Jackbox connect'),
      65: ('eetJackboxDisconnect', 'Jackbox disconnect'),
      66: ('eetHeartRateAlarm', 'Heart Rate Alarm'),
      67: ('eetCorticalStimCurrentConfirmed', 'Cortical Stimulation Current Confirmed'),
      68: ('eetHFO', 'HFO'),
      69: ('eetMarkedRegionVideo', 'Keep video'),
      70: ('eetForDeletionVideo', 'For deletion video'),
      71: ('eetVideo2', 'Video 2'),
      72: ('eetClickerTest', 'Clicker Test'),
      73: ('eetNotMarkedRegionEEG', 'Not kept EEG'),
      74: ('eetEEGSpike', 'Spike'),
      75: ('eetEEGSeizure', 'Seizure'),
      76: ('eetNetworkEvent', 'Network Event'),
      77: ('eetVideo3', 'Video 3'),
      78: ('eetVideo4', 'Video 4'),
      79: ('eetHDSpaceLowWarning', 'Hard Disk Space Low Warning'),
      80: ('eetHDSpaceLowVideoStopped', 'Hard disk getting full.  Recording of video stopped'),
      81: ('eetSDCardSpaceLowWarning', 'SD Card Space Low Warning'),
      82: ('eetSDCardRecordingStopped', 'SD Card Recording Stopped'),
      83: ('eetOktiPowerSource', 'Okti Power Source'),
      84: ('eetSDCardRecordingStarted', 'SD Card Recording Started'),
      85: ('eetNoEEGData', 'Check the amplifier is securely connected'),
}

# Some studies store the type with 1000 added - see resolveTypeId().
DB_TYPE_OFFSET = 1000

# Spike detections.
#
# 74 is eetEEGSpike, the Spike and Seizure plug-in's own type. 23 and 24 are
# named for Persyst Reveal in ProfusionEEG's resources, but the Spike and
# Seizure plug-in writes its spikes there too: 05JC.eeg was processed by that
# plug-in - its four seizures are eetEEGSeizure (75) - and its 448 spike
# detections are type 24, with per-detection channel lists, while type 74 is
# empty. A spike-and-seizure detector that found four seizures and no
# interictal spikes at all is not credible.
#
# So the type says a spike was detected. It does not say which detector found
# it, and nothing here claims otherwise - the findings attribute them to 'the
# spike detector' and say so. The translation from the plug-in's internal type
# space (EVTY_SPIKE_DETECTION, 1.3 million and up) to these values happens in
# the ProfusionEEG host, which is not in this repository, so this rests on the
# study's contents rather than on the mapping code.
SPIKE_TYPES = (74, 23, 24)
SEIZURE_TYPES = (75,)

# Persyst's own seizure type, which no study seen here carries. Kept separate
# because 22 has never been observed alongside the plug-in's output, so there
# is no evidence it is shared the way 23 and 24 are.
REVEAL_SEIZURE_TYPES = (22,)
REVEAL_SPIKE_TYPES = ()
REVEAL_TYPES = (22, 25, 26)

# Where a type is shared between detectors, the vendor-specific resource string
# would assert something the type cannot support. These read as what they are.
SHARED_TYPE_LABELS = {
    23: 'Spike',
    24: 'Spike burst',
}

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
    if resolved in SHARED_TYPE_LABELS:
        return SHARED_TYPE_LABELS[resolved]
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
