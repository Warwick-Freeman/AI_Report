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

import eventtypes

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


def _columnMap(cursor, table):
    """{lowercase name: actual name} for a table's columns.

    The event schema is not fixed across ProfusionEEG versions: Demo.eeg's
    EEGEventString carries ShortText and FullText, while the 01RT..06MS studies
    have FullText only. Access reports an unknown column as a missing query
    parameter ("Too few parameters. Expected 1") rather than as a bad column
    name, so a hardcoded SELECT fails obscurely on any schema but the one it was
    written against. Every query below is built from what the study actually has.
    """
    return {c.column_name.lower(): c.column_name for c in cursor.columns(table=table)}


def _pick(columns, *candidates):
    """The first candidate column present, or None."""
    for name in candidates:
        actual = columns.get(name.lower())
        if actual:
            return actual
    return None


def _select(cursor, table, columns, names):
    """Run a SELECT over the named columns, skipping any the table lacks.

    Returns (rows, index) where index maps each requested name to its position
    in a row, or None where the column does not exist.
    """
    present = [(n, columns[n.lower()]) for n in names if n.lower() in columns]
    if not present:
        return [], {n: None for n in names}
    cursor.execute('SELECT %s FROM %s'
                   % (', '.join('[%s]' % actual for _, actual in present), table))
    index = {n: None for n in names}
    for position, (name, _) in enumerate(present):
        index[name] = position
    return cursor.fetchall(), index


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

        # The type's name comes from ProfusionEEG's own event-type table
        # (eventtypes.py), which is the only thing that actually names a type.
        #
        # EEGEventString does not: across every study examined all its rows carry
        # EventTypeID 1, because that table is the pick-list of annotation texts
        # an operator chooses from - 'Eyes Open', 'Coughing' - and type 1 is
        # eetAnnotation. Reading it as a type name gave every type-1 event in
        # Demo.eeg the label 'Drowsy', the first row of that list. It is still
        # read, but only as what it is: the set of predefined annotation texts.
        annotationTexts = []
        if 'EEGEventString' in tables:
            columns = _columnMap(cursor, 'EEGEventString')
            rows, at = _select(cursor, 'EEGEventString', columns,
                               ('EventTypeID', 'ShortText', 'FullText'))
            for row in rows:
                short = row[at['ShortText']] if at['ShortText'] is not None else None
                full = row[at['FullText']] if at['FullText'] is not None else None
                text = (short or full or '').strip()
                if text:
                    annotationTexts.append(text)

        categories = {}
        if 'EEGEventCategory' in tables:
            columns = _columnMap(cursor, 'EEGEventCategory')
            rows, at = _select(cursor, 'EEGEventCategory', columns,
                               ('EventCategoryID', 'Name'))
            if at['EventCategoryID'] is not None and at['Name'] is not None:
                categories = {r[at['EventCategoryID']]: (r[at['Name']] or '').strip()
                              for r in rows}

        # The per-event trace association - the structural location source.
        traces, montages = {}, {}
        if 'EEGEventGraphs' in tables:
            columns = _columnMap(cursor, 'EEGEventGraphs')
            rows, at = _select(cursor, 'EEGEventGraphs', columns,
                               ('EventID', 'TraceName', 'MontageName'))
            for row in rows:
                if at['EventID'] is None:
                    break
                eventId = row[at['EventID']]
                traceName = row[at['TraceName']] if at['TraceName'] is not None else None
                montageName = row[at['MontageName']] if at['MontageName'] is not None else None
                if traceName:
                    traces.setdefault(eventId, []).append(traceName.strip())
                if montageName:
                    montages[eventId] = montageName.strip()

        columns = _columnMap(cursor, 'EEGEvent')
        wanted = ('EventID', 'EventTypeID', 'StartSecondHi', 'StartSecondLo',
                  'DurationHi', 'DurationLo', 'EventString', 'EventCategoryID',
                  'IsEndEvent')
        missing = [n for n in ('EventID', 'EventTypeID', 'StartSecondHi',
                               'StartSecondLo') if n.lower() not in columns]
        if missing:
            if verbose:
                print('EEGEvent in %s lacks %s - cannot read events from this '
                      'schema.' % (os.path.basename(path), ', '.join(missing)))
            return []
        rows, at = _select(cursor, 'EEGEvent', columns, wanted)

        def value(row, name):
            position = at[name]
            return None if position is None else row[position]

        events = []
        for row in rows:
            eventId = value(row, 'EventID')
            events.append({
                'id': eventId,
                'type_id': value(row, 'EventTypeID'),
                'type_label': eventtypes.labelFor(value(row, 'EventTypeID')),
                'type_name': eventtypes.identifierFor(value(row, 'EventTypeID')),
                'is_detection': eventtypes.isDetection(value(row, 'EventTypeID')),
                'is_annotation': eventtypes.isAnnotation(value(row, 'EventTypeID')),
                'provocation': eventtypes.provocationFor(value(row, 'EventTypeID')),
                'category': categories.get(value(row, 'EventCategoryID'), ''),
                'start_ns': decodeTime(value(row, 'StartSecondHi'),
                                       value(row, 'StartSecondLo')),
                'duration_ns': decodeTime(value(row, 'DurationHi'),
                                          value(row, 'DurationLo')),
                'text': (value(row, 'EventString') or '').strip(),
                'is_end_event': bool(value(row, 'IsEndEvent')),
                'traces': traces.get(eventId, []),
                'montage': montages.get(eventId),
            })
        events.sort(key=lambda e: (e['start_ns'] is None, e['start_ns']))
    finally:
        conn.close()

    if verbose:
        printEvents(events, os.path.basename(path))
    return events


def describeTypes(studyPath):
    """What event types a study holds - the way to find a detector's type ids.

    Run this on a study the detector has processed and its spike and seizure
    types will stand out as ones this project does not otherwise see.
    """
    events = readEvents(studyPath, verbose=False)
    for (typeId, label), count in sorted(summariseTypes(events).items(),
                                         key=lambda kv: -kv[1]):
        samples = [e['text'] for e in events
                   if e['type_id'] == typeId and e['text']][:3]
        print('  %5dx  %-28s (type %-5s) %s'
              % (count, label or 'unnamed', typeId,
                 '; '.join(repr(s) for s in samples)))
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
        print('    %5dx  %-30s (type %s)'
              % (count, label or 'unnamed', typeId))
    if not withTraces:
        print('  NOTE: no event carries a trace name, so location for these '
              'events must come from the event text.')
