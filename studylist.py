############################################
# Reader for a ProfusionEEG study-list database.
#
# A folder holding ProfusionEEG studies carries a "_CMPStudyList.mdb" Access
# database at its root, whose single Study table indexes the "*.eeg" study
# folders beneath it along with patient and recording details.
#
# Reading it needs the 64-bit Microsoft Access ODBC driver. Where that is
# absent the study folders are enumerated from disk instead, so the list still
# works - just without the patient details the database carries.
############################################
import os
import glob

STUDY_LIST_FILENAME = '_CMPStudyList.mdb'

ACCESS_DRIVER = 'Microsoft Access Driver (*.mdb, *.accdb)'

# The 10-20 electrodes the analysis pipeline needs; eeg.py imports this so the
# requirement is stated once. T7/T8/P7/P8 in a 10-10 montage are mapped onto
# T3/T4/T5/T6 by eegProcess.getRawData before this check applies.
REQUIRED_CHANNELS = ['Fp1', 'Fp2', 'F7', 'F8', 'F3', 'F4', 'T5', 'T6', 'P3', 'P4',
                     'O1', 'O2', 'C3', 'C4', 'Cz', 'Fz', 'Pz', 'T3', 'T4']

# Applied to a study's own montage before checking it against the list above.
CHANNEL_ALIASES = {'T7': 'T3', 'T8': 'T4', 'P7': 'T5', 'P8': 'T6', 'POz': 'Pz'}

# Columns read from the Study table. Selecting them explicitly keeps the reader
# working against a study list that carries extra columns.
_STUDY_COLUMNS = ['StudyID', 'StudyDate', 'Surname', 'GivenName', 'DateOfBirth',
                  'Gender', 'Age', 'StudyPath', 'StudyLength', 'HasVideo',
                  'Physician', 'Status']


def findStudyList(root):
    """Path to the study-list database in root, or None."""
    candidate = os.path.join(root, STUDY_LIST_FILENAME)
    return candidate if os.path.isfile(candidate) else None


def _connect(mdbPath):
    import pyodbc
    # Access rejects a relative DBQ, and read-only keeps a study list that
    # ProfusionEEG has open from being locked.
    return pyodbc.connect('DRIVER={%s};DBQ=%s;ReadOnly=1;'
                          % (ACCESS_DRIVER, os.path.abspath(mdbPath)))


def _readMdb(mdbPath, root):
    """Study rows from the Access database."""
    conn = _connect(mdbPath)
    try:
        cursor = conn.cursor()
        cursor.execute('SELECT %s FROM Study' % ', '.join(_STUDY_COLUMNS))
        names = [d[0] for d in cursor.description]
        studies = []
        for row in cursor.fetchall():
            record = dict(zip(names, row))
            relPath = (record.get('StudyPath') or '').strip()
            if not relPath:
                continue
            record['path'] = os.path.normpath(os.path.join(root, relPath))
            studies.append(record)
        return studies
    finally:
        conn.close()


def _scanFolders(root):
    """Study rows built from the *.eeg folders on disk.

    The fallback when the Access driver is unavailable: enough to pick and run
    a study, without the patient details only the database holds.
    """
    studies = []
    for path in sorted(glob.glob(os.path.join(root, '*.eeg'))):
        if not os.path.isdir(path):
            continue
        studies.append({'StudyID': None, 'StudyPath': os.path.basename(path),
                        'path': os.path.normpath(path)})
    return studies


def readStudyList(root):
    """Return (studies, source, note) for a folder of ProfusionEEG studies.

    source is 'mdb' when the study list was read, 'filesystem' when it was not;
    note explains any fallback so a UI can say why patient details are missing.
    """
    mdb = findStudyList(root)
    if mdb:
        try:
            return _readMdb(mdb, root), 'mdb', None
        except Exception as e:
            # Missing 64-bit Access driver is by far the likeliest cause, and
            # is worth reporting rather than silently listing folders.
            note = ('Could not read %s (%s). Listing *.eeg folders instead - '
                    'patient details are unavailable. Reading the study list '
                    'needs the 64-bit "%s" ODBC driver (Microsoft Access '
                    'Database Engine).' % (STUDY_LIST_FILENAME, e, ACCESS_DRIVER))
            return _scanFolders(root), 'filesystem', note

    return (_scanFolders(root), 'filesystem',
            'No %s in this folder - listing *.eeg folders instead.'
            % STUDY_LIST_FILENAME)


def describeStudy(record):
    """Add montage details to a study record, read from its .sdy XML.

    Cheap (no SDK, no COM, no signal read), so a UI can annotate a whole list
    up front. Adds 'sfreq', 'ch_names', 'missing_channels' and 'exists'; a
    study whose .sdy cannot be read gets 'missing_channels' of None, meaning
    "unknown" rather than "none missing".
    """
    import profusion

    record['exists'] = os.path.isdir(record['path'])
    record['sfreq'] = None
    record['ch_names'] = None
    record['missing_channels'] = None
    if not record['exists']:
        return record

    meta = profusion.readStudyMetadata(record['path'])
    if not meta:
        return record

    record['sfreq'] = meta['sfreq']
    record['ch_names'] = meta['ch_names']
    if meta['study_length'] and not record.get('StudyLength'):
        record['StudyLength'] = int(meta['study_length'])

    present = {CHANNEL_ALIASES.get(name, name) for name in (meta['ch_names'] or [])}
    record['missing_channels'] = [ch for ch in REQUIRED_CHANNELS if ch not in present]
    return record


def loadStudies(root):
    """readStudyList + describeStudy for every study, sorted by date then path."""
    studies, source, note = readStudyList(root)
    studies = [describeStudy(s) for s in studies]
    studies.sort(key=lambda s: (s.get('StudyDate') is None,
                                s.get('StudyDate'), s.get('StudyPath') or ''))
    return studies, source, note
