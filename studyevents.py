############################################
# Read a ProfusionEEG study's event database directly.
#
# This is the route that matters for the spike and seizure detector. The
# detector can be run during acquisition inside ProfusionEEG, so by the time a
# recording is finished its detections are already in the study - which means
# reading them needs no wrapper around the detector, no matching of bitness or
# C++ ABI, and no recompilation of cleared code. The detector ran in its own
# configuration with its own parameters and its own data pipeline; this only
# reads the result, as any review tool does.
#
# Events live in EEGStudyDB.mdb (EVENTS.MDB in a study is a legacy empty shell):
#
#   EEGEvent          EventID, EventTypeID, StartSecondHi/Lo, DurationHi/Lo,
#                     EventString, EventCategoryID, IsEndEvent, OtherEventID
#   EEGEventString    per-type and per-category label text
#   EEGEventCategory  category names
#   EEGEventGraphs    EventID -> TraceName, MontageName
#
# EEGEventGraphs is the reason for reading the database directly rather than
# going through cmpeeg: cmpeeg's Event exposes type, times, id and text but no
# channel association, whereas this table holds it structurally. Where the
# detector populates it, location comes from data rather than from parsing an
# annotation string.
#
# Times are 64-bit nanosecond counts split across two 32-bit columns. Access
# stores the low half signed, so it has to be masked before recombining -
# verified against cmpeeg's start_ns on every event of DemoStudies/Demo.eeg.
############################################
import glob
import os

ACCESS_DRIVER = 'Microsoft Access Driver (*.mdb, *.accdb)'
EVENT_DB_NAMES = ('EEGStudyDB.mdb', 'EVENTS.MDB')


def findEventDatabase(studyPath):
    """Path to the study's event database, or None.

    Prefers EEGStudyDB.mdb; a study's EVENTS.MDB is normally an empty legacy
    file holding only Access system tables.
    """
    studyPath = (studyPath or '').rstrip('\\/')
    if studyPath.lower().endswith('.mdb'):
        return studyPath if os.path.isfile(studyPath) else None
    for name in EVENT_DB_NAMES:
        candidate = os.path.join(studyPath, name)
        if os.path.isfile(candidate):
            return candidate
    matches = glob.glob(os.path.join(studyPath, '*.mdb'))
    return matches[0] if matches else None


def _connect(path):
    import pyodbc
    # Read-only so a study open in ProfusionEEG is never locked or altered.
    return pyodbc.connect('DRIVER={%s};DBQ=%s;ReadOnly=1;'
                          % (ACCESS_DRIVER, os.path.abspath(path)))


def decodeTime(high, low):
    """Recombine a split 64-bit nanosecond count.

    Two separate sign traps here, both found by checking every event of
    DemoStudies/Demo.eeg against cmpeeg's own start_ns:

    Access hands back each half as a signed 32-bit integer, so both must be
    masked before recombining - otherwise every event whose low word has the top
    bit set decodes to the wrong time.

    The recombined 64-bit value is itself signed. An event can sit slightly
    before the study's zero point - Demo.eeg has one at -2 ms - and read as
    unsigned that becomes 2**64 - 2000000 instead of a small negative number.
    """
    if high is None or low is None:
        return None
    value = ((int(high) & 0xFFFFFFFF) << 32) | (int(low) & 0xFFFFFFFF)
    if value >= 1 << 63:
        value -= 1 << 64
    return value


def _tableNames(cursor):
    return {t.table_name for t in cursor.tables(tableType='TABLE')}


def readEvents(studyPath, verbose=True):
    """Every event in a study, with its traces where the study records them.

    Returns a list of dicts: id, type_id, type_label, category, start_ns,
    duration_ns, text, traces (list of channel/trace names), montage.
    Returns [] and explains itself if the database cannot be read.
    """
    path = findEventDatabase(studyPath)
    if not path:
        if verbose:
            print('No event database found in %s' % studyPath)
        return []

    try:
        conn = _connect(path)
    except Exception as e:
        if verbose:
            print('Could not open %s (%s).\nReading the event database needs the '
                  '64-bit "%s" ODBC driver.' % (path, e, ACCESS_DRIVER))
        return []

    try:
        cursor = conn.cursor()
        tables = _tableNames(cursor)
        if 'EEGEvent' not in tables:
            if verbose:
                print('%s holds no EEGEvent table - this is the legacy empty '
                      'events file, not the study database.' % os.path.basename(path))
            return []

        # Per-type and per-category labels, so an event carries a name and not
        # just a numeric type.
        labels = {}
        if 'EEGEventString' in tables:
            cursor.execute('SELECT EventTypeID, ShortText, FullText FROM EEGEventString')
            for typeId, shortText, fullText in cursor.fetchall():
                if typeId is not None and typeId not in labels:
                    labels[typeId] = (shortText or fullText or '').strip()
        categories = {}
        if 'EEGEventCategory' in tables:
            cursor.execute('SELECT EventCategoryID, Name FROM EEGEventCategory')
            categories = {cid: (name or '').strip() for cid, name in cursor.fetchall()}

        # The per-event trace association - the structural location source.
        traces, montages = {}, {}
        if 'EEGEventGraphs' in tables:
            cursor.execute('SELECT EventID, TraceName, MontageName FROM EEGEventGraphs')
            for eventId, traceName, montageName in cursor.fetchall():
                if traceName:
                    traces.setdefault(eventId, []).append(traceName.strip())
                if montageName:
                    montages[eventId] = montageName.strip()

        cursor.execute('''SELECT EventID, EventTypeID, StartSecondHi, StartSecondLo,
                                 DurationHi, DurationLo, EventString, EventCategoryID,
                                 IsEndEvent
                          FROM EEGEvent''')
        events = []
        for row in cursor.fetchall():
            eventId = row[0]
            events.append({
                'id': eventId,
                'type_id': row[1],
                'type_label': labels.get(row[1], ''),
                'category': categories.get(row[7], ''),
                'start_ns': decodeTime(row[2], row[3]),
                'duration_ns': decodeTime(row[4], row[5]),
                'text': (row[6] or '').strip(),
                'is_end_event': bool(row[8]),
                'traces': traces.get(eventId, []),
                'montage': montages.get(eventId),
            })
        events.sort(key=lambda e: (e['start_ns'] is None, e['start_ns']))
    finally:
        conn.close()

    if verbose:
        printEvents(events, os.path.basename(path))
    return events


def summariseTypes(events):
    """{(type_id, label): count}, for seeing what a study actually contains."""
    counts = {}
    for event in events:
        key = (event['type_id'], event['type_label'])
        counts[key] = counts.get(key, 0) + 1
    return counts


def printEvents(events, source=''):
    """Log what the event database holds."""
    print('--- Study events%s ---' % (' from %s' % source if source else ''))
    if not events:
        print('  none')
        return
    withTraces = sum(1 for e in events if e['traces'])
    print('  %d event(s), %d carrying trace names' % (len(events), withTraces))
    for (typeId, label), count in sorted(summariseTypes(events).items(),
                                         key=lambda kv: -kv[1]):
        print('    %5dx  type %-8s %s' % (count, typeId, label or '(unlabelled)'))
    if not withTraces:
        print('  NOTE: no event carries a trace name, so location for these '
              'events must come from the event text.')
