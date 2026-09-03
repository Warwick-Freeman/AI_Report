############################################
# The report as an editable Word document.
#
# The PDF is a fixed record; this is the same report in a form the
# electroencephalographer can change. SCORE's own report is a document a human
# signs, and a reader who cannot correct a wording, add a sentence about the
# clinical context or delete a finding they disagree with will either sign
# something they do not quite mean or retype the whole thing.
#
# Everything comes from the same results dict the PDF is built from, so the two
# cannot drift apart in substance. Real Word styles are used - Heading 1,
# Heading 2, Table Grid - rather than hand-set fonts, so the document restyles
# cleanly and takes a house template.
#
# The figures are the ones the analysis drew, embedded from the same files the
# PDF uses.
############################################
import os

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Inches, Pt, RGBColor

from createPDF import figureNames
from recording import _hms

# Grey, for the basis lines that sit under a value. The same distinction the
# PDF makes between a finding and the measurement behind it.
BASIS_GREY = RGBColor(0x69, 0x69, 0x69)

# The usable width of a portrait page at these margins. Every column set below
# adds up to this or less; Word will otherwise widen the table past the margin.
PAGE_WIDTH_IN = 7.1

# What each figure actually shows.
#
# Keyed by the index createPDF writes, not by position in a list. The figures
# are not drawn in the order they are numbered - eeg0 comes from plotTopMaps
# and eeg5 from drawEpochs - and a positional tuple quietly put every caption
# against the wrong picture. Each of these was read off the figure itself:
#
#   0  plotTopMaps        delta/theta/alpha/beta maps, three normalisations
#   1  drawLeftRightDiff  'Left/Right power ratio, left is positive'
#   2  drawPsds           'Posterior power spectrum density'
#   3  drawFreqPower      per-pair spectra: O1-O2, T5-T6, ... Fp1-Fp2
#   4  plotSpectrogram    the spectrogram
#   5  drawEpochs         the traces, 4 s to a page
FIGURE_CAPTIONS = {
    0: 'Band-power topographic maps (delta, theta, alpha, beta)',
    1: 'Left/right power ratio by electrode pair',
    2: 'Posterior power spectral density',
    3: 'Power spectrum by electrode pair, left against right',
    4: 'Spectrogram',
    5: 'EEG traces, 4 s epochs',
}


def writeDOCX(fileName, results, dest_folder, ai_report_text=None,
              template=None):
    """Write the report as a .docx. Returns the path written.

    A template is opened and appended to when given, so a department's own
    styles, header and footer carry into the report.
    """
    document = Document(template) if template else Document()
    if not template:
        _setUpStyles(document)

    excluded = set(results.get('_excluded') or ())

    def wanted(sectionId):
        return sectionId not in excluded

    stem = os.path.splitext(os.path.basename(fileName))[0]
    document.add_heading('EEG Report - %s' % fileName, level=0)
    _scoreNote(document)

    if wanted('recording'):
        _recording(document, results.get('recording'))
    if wanted('pdr'):
        _pdr(document, results.get('pdr'))
    if wanted('interictal'):
        _interictal(document, results.get('interictal'))
    if wanted('episodes'):
        _episodes(document, (results.get('spikeseizure') or {}).get('episodes'),
                  (results.get('spikeseizure') or {}).get('notes'))
    if wanted('events'):
        _studyEvents(document, results.get('selected_events'))
    if wanted('sleep'):
        _sleep(document, results.get('sleep'))
    if wanted('artifacts'):
        _artifacts(document, results.get('artifacts'))
    if wanted('conclusion'):
        _conclusion(document, results.get('conclusion'))
    if ai_report_text:
        _narrative(document, ai_report_text)

    _measurements(document, results)
    _figures(document, dest_folder, fileName)

    outFile = os.path.join(dest_folder, stem + '.docx')
    try:
        document.save(outFile)
    except PermissionError as e:
        # Word holds an exclusive lock on an open document, and regenerating a
        # report you are reading is an obvious thing to do. Say which file and
        # why rather than surfacing a bare errno.
        raise PermissionError(
            'Cannot write %s - it is open in another application, most likely '
            'Word. Close it and generate again.' % os.path.abspath(outFile)) from e
    outFile = os.path.abspath(outFile)
    print('Successfully generate docx file: ', outFile)
    return outFile


# ------------------------------------------------------------------ scaffolding

def _setUpStyles(document):
    """Body text a clinician can read, and margins a table fits in."""
    style = document.styles['Normal']
    style.font.name = 'Calibri'
    style.font.size = Pt(10)
    for section in document.sections:
        section.left_margin = Inches(0.7)
        section.right_margin = Inches(0.7)


def _scoreNote(document):
    paragraph = document.add_paragraph()
    run = paragraph.add_run(
        'Scored against SCORE - Standardized Computer-based Organized Reporting '
        'of EEG, second version (Beniczky et al., Clin Neurophysiol '
        '2017;128:2334-2346). Values marked as not scored were not determinable '
        'from the recording; they are not negative findings.')
    run.font.size = Pt(8)
    run.font.color.rgb = BASIS_GREY


def _basis(document, text, indent=Inches(0.25)):
    """The measurement under a value, in the smaller grey the PDF uses."""
    if not text:
        return
    paragraph = document.add_paragraph()
    paragraph.paragraph_format.left_indent = indent
    paragraph.paragraph_format.space_after = Pt(2)
    run = paragraph.add_run(text)
    run.font.size = Pt(8)
    run.font.color.rgb = BASIS_GREY


def _repeatHeader(row):
    """Mark a row as a header so Word repeats it on every page.

    A table that runs over a page break otherwise continues with unlabelled
    columns, which for a findings table means a reader cannot tell prevalence
    from confidence.
    """
    properties = row._tr.get_or_add_trPr()
    header = OxmlElement('w:tblHeader')
    header.set(qn('w:val'), 'true')
    properties.append(header)


def _table(document, headers, widths=None):
    table = document.add_table(rows=1, cols=len(headers))
    table.style = 'Table Grid'
    # Word recalculates column widths when autofit is left on, so the widths set
    # per cell below were being discarded and the columns came out squashed.
    table.autofit = False
    header = table.rows[0].cells
    for index, text in enumerate(headers):
        header[index].text = ''
        run = header[index].paragraphs[0].add_run(text)
        run.bold = True
        run.font.size = Pt(8)
        if widths:
            header[index].width = Inches(widths[index])
    _repeatHeader(table.rows[0])
    return table


def _row(table, values, widths=None, basis=None):
    cells = table.add_row().cells
    for index, value in enumerate(values):
        cells[index].text = ''
        run = cells[index].paragraphs[0].add_run(
            '' if value is None else str(value))
        run.font.size = Pt(9)
        if widths:
            cells[index].width = Inches(widths[index])
    if basis:
        paragraph = cells[0].add_paragraph()
        run = paragraph.add_run(basis)
        run.font.size = Pt(7.5)
        run.font.color.rgb = BASIS_GREY
    return cells


def _notes(document, notes, heading='Notes'):
    notes = [n for n in (notes or []) if n]
    if not notes:
        return
    document.add_heading(heading, level=2)
    for note in notes:
        document.add_paragraph(note, style='List Bullet')


def _readerFields(document, fields):
    """What SCORE wants from the reader, left blank for them to complete."""
    document.add_heading('For completion by the reader', level=2)
    for field in fields:
        paragraph = document.add_paragraph(style='List Bullet')
        paragraph.add_run('%s: ' % field).bold = True
        paragraph.add_run('_' * 40)


# --------------------------------------------------------------- the sections

def _recording(document, recording):
    if not recording:
        return
    document.add_heading('Patient and Recording Conditions', level=1)

    for group, title in (('patient', 'Patient'), ('conditions', 'Recording')):
        entries = (recording.get(group) or {})
        if not entries:
            continue
        document.add_heading(title, level=2)
        table = _table(document, ('Item', 'Value'), (2.0, 5.0))
        for label, value in entries.items():
            _row(table, (label, value), (2.0, 5.0))

    lines = recording.get('duration_lines') or []
    if lines:
        document.add_heading('Duration examined', level=2)
        for line in lines:
            document.add_paragraph(line, style='List Bullet')

    _activation(document, recording.get('activation'))

    fields = recording.get('technologist_fields') or []
    if fields:
        _readerFields(document, fields)

    _notes(document, recording.get('notes'))


def _activation(document, activation):
    procedures = (activation or {}).get('procedures') or []
    if not procedures:
        return
    document.add_heading('Activation procedures', level=2)
    widths = (1.7, 1.6, 2.3, 1.4)
    table = _table(document, ('Procedure', 'State', 'Timing', 'Response'), widths)
    for procedure in procedures:
        onset = procedure.get('onset_seconds')
        _row(table,
             (procedure.get('name'), procedure.get('state'),
              '' if onset is None else 'from %s' % _hms(onset),
              procedure.get('response') or 'Not scored'),
             widths, basis=procedure.get('detail'))
    for note in activation.get('notes') or []:
        _basis(document, note, indent=Inches(0))


def _pdr(document, pdr):
    if not pdr:
        return
    document.add_heading('Posterior Dominant Rhythm', level=1)
    widths = (1.6, 2.2, 0.9, 2.3)
    table = _table(document, ('Property', 'Scored value', 'Confidence',
                              'Measurement behind it'), widths)

    labels = (('frequency', 'Frequency'), ('frequency_asymmetry', 'Frequency asymmetry'),
              ('amplitude', 'Amplitude'), ('amplitude_asymmetry', 'Amplitude asymmetry'),
              ('reactivity', 'Reactivity'), ('organization', 'Organisation'),
              ('caveat', 'Caveat'), ('absence', 'Absence of the PDR'),
              ('significance', 'Significance'))
    overridden = []
    for key, label in labels:
        entry = pdr.get(key)
        if not isinstance(entry, dict):
            continue
        term = entry.get('term')
        if entry.get('provisional'):
            term = '%s (provisional)' % term
        _row(table, (label, term, entry.get('confidence', ''),
                     entry.get('basis', '')), widths)
        if entry.get('overridden'):
            overridden.append((label, entry))

    if overridden:
        document.add_heading('Overridden by the reader', level=2)
        for label, entry in overridden:
            document.add_paragraph(
                '%s: reported as %s; measured %s'
                % (label, entry.get('term'), entry.get('measured_term')),
                style='List Bullet')

    _notes(document, pdr.get('notes'))


def _findingTable(document, findings, timingHeader):
    widths = (1.5, 2.0, 1.4, 1.3, 0.8)
    table = _table(document, ('Graphoelement', 'Location', timingHeader,
                              'Mode of appearance', 'Confidence'), widths)
    for finding in findings:
        location = (finding.get('location') or {})
        timing = finding.get('prevalence') or finding.get('incidence') or ''
        if finding.get('count'):
            timing = ('%s (%d)' % (timing, finding['count'])) if timing \
                else str(finding['count'])
        mode = ', '.join(x for x in (finding.get('mode_of_appearance'),
                                     finding.get('discharge_pattern')) if x)
        basis = '. '.join(x for x in (finding.get('basis'),
                                      finding.get('timing_basis')) if x)
        _row(table,
             (finding.get('name'), location.get('text') or '', timing, mode,
              finding.get('confidence', '')), widths, basis=basis)


def _interictal(document, interictal):
    findings = (interictal or {}).get('findings') or []
    if not interictal:
        return
    document.add_heading('Interictal Findings', level=1)
    if findings:
        _findingTable(document, findings, 'Prevalence / incidence')
    else:
        document.add_paragraph(
            'Analysed. No abnormal interictal rhythmic activity or epileptiform '
            'discharges of this class were detected. This is a clinical result, '
            'not a failure to analyse.')
    _notes(document, interictal.get('notes'),
           heading='What the analysis decided not to report')


def _episodes(document, episodes, notes):
    if not episodes:
        return
    document.add_heading('Episodes', level=1)
    widths = (1.9, 1.9, 1.0, 1.5, 0.8)
    table = _table(document, ('Episode', 'Location', 'Onset', 'Duration',
                              'Confidence'), widths)
    readerFields = None
    for episode in episodes:
        location = (episode.get('location') or {})
        onset = episode.get('onset_seconds')
        duration = episode.get('duration_seconds')
        _row(table,
             (episode.get('name'), location.get('text') or '',
              '' if onset is None else _hms(onset),
              episode.get('duration_band')
              or ('' if duration is None else '%.0f s' % duration),
              episode.get('confidence', '')),
             widths, basis=episode.get('basis'))
        readerFields = episode.get('reader_fields') or readerFields

    _readerFields(document, readerFields or [
        'Seizure type (ILAE classification)',
        'Semiology and its somatotopic modifiers',
        'Ictal EEG pattern and its evolution',
        'Clinical-EEG temporal relationship',
        'Consciousness and awareness',
        'Postictal findings'])
    _notes(document, notes)


def _studyEvents(document, events):
    if not events:
        return
    document.add_heading('Study Events', level=1)
    _basis(document, 'Selected by the reader as context, from the study\'s own '
                     'event record. None of these is a finding.', Inches(0))
    widths = (1.7, 0.9, 0.7, 2.1, 1.6)
    table = _table(document, ('Event', 'Time', 'Duration', 'Text', 'Channels'),
                   widths)
    for event in events:
        seconds = event.get('seconds')
        duration = event.get('duration_seconds') or 0
        note = []
        if event.get('provocation'):
            note.append('SCORE provocation: %s' % event['provocation'])
        if event.get('is_detection'):
            note.append('detector output')
        _row(table,
             (event.get('type'), '' if seconds is None else _hms(seconds),
              '%.0f s' % duration if duration else '',
              event.get('text') or '',
              ', '.join(event.get('channels') or [])),
             widths, basis='. '.join(note) or None)


def _sleep(document, sleep):
    if not sleep:
        return
    document.add_heading('Sleep and Drowsiness', level=1)
    backend = sleep.get('backend') or 'model'
    _basis(document, 'Staged by %s. This is AI analysis and has not been '
                     'verified.' % backend, Inches(0))

    rows = [(label, sleep.get(key)) for label, key in
            (('Stages reached', 'stages_text'), ('Sleep reached', 'sleep_reached'),
             ('Drowsiness', 'drowsiness'))
            if sleep.get(key) is not None]
    if rows:
        table = _table(document, ('Item', 'Value'), (2.0, 5.0))
        for label, value in rows:
            _row(table, (label, value), (2.0, 5.0))

    findings = sleep.get('findings') or []
    if findings:
        document.add_heading('Sleep graphoelements', level=2)
        _findingTable(document, findings, 'Prevalence / incidence')
    _notes(document, sleep.get('notes'))


def _artifacts(document, artifacts):
    findings = (artifacts or {}).get('findings') or []
    if not artifacts:
        return
    document.add_heading('EEG Artifacts', level=1)
    if findings:
        widths = (1.8, 2.2, 1.6, 0.9)
        table = _table(document, ('Artifact type', 'Location',
                                  'Prevalence / incidence', 'Confidence'), widths)
        for finding in findings:
            location = (finding.get('location') or {})
            timing = finding.get('prevalence') or finding.get('incidence') or ''
            _row(table,
                 (finding.get('name'), location.get('text') or '', timing,
                  finding.get('confidence', '')), widths,
                 basis=finding.get('basis'))
        _readerFields(document, [
            'Significance (not interpretable / reduced diagnostic value / '
            'does not interfere with interpretation)'])
    else:
        document.add_paragraph('Analysed. No artifact types were detected.')
    _notes(document, artifacts.get('notes'))


def _conclusion(document, conclusion):
    document.add_heading('Diagnostic Significance and Conclusion', level=1)
    _basis(document, 'SCORE reserves the diagnostic significance and the '
                     'conclusion for the electroencephalographer. Nothing in '
                     'the analysis writes them.', Inches(0))

    if conclusion:
        table = _table(document, ('Item', 'Value'), (2.0, 5.0))
        for label, key in (('Diagnostic significance', 'significance'),
                           ('Diagnostic yield', 'yield')):
            _row(table, (label, conclusion.get(key) or 'Not scored'), (2.0, 5.0))
        for label, key in (('Based on', 'basis'), ('Notes', 'notes')):
            for line in (conclusion.get(key) or []):
                _basis(document, line)
        summary = conclusion.get('summary') or conclusion.get('text')
        if summary:
            document.add_heading('Summary and clinical comments', level=2)
            document.add_paragraph(summary)

    _readerFields(document, ['Diagnostic significance (normal recording / '
                             'abnormal recording / no definite abnormality)',
                             'Diagnostic yield (from SCORE\'s list)',
                             'Summary and clinical comments',
                             'Reported by', 'Date'])


def _narrative(document, text):
    document.add_heading('Narrative Draft', level=1)
    _basis(document, 'Drafted by a language model. This is AI analysis, has not '
                     'been verified, and is offered as a draft rather than as a '
                     'scored value - edit or delete it.', Inches(0))
    for block in str(text).split('\n'):
        if block.strip():
            document.add_paragraph(block.strip())


def _measurements(document, results):
    """The underlying numbers, for anyone who wants to check the findings."""
    document.add_heading('Underlying Measurements', level=1)
    widths = (2.6, 1.4, 1.4, 1.4)
    table = _table(document, ('Measurement', 'Left', 'Right', 'Total'), widths)

    def number(value, unit=''):
        if value is None:
            return ''
        try:
            return '%.2f%s' % (float(value), unit)
        except (TypeError, ValueError):
            return str(value)

    rows = (
        ('Background frequency (Hz)', 'left_backgroud_frequency',
         'right_backgroud_frequency', None),
        ('Slow-wave ratio', 'left_slow_ratio', 'right_slow_ratio',
         'total_slow_ratio'),
        ('Beta ratio', 'left_beta_ratio', 'right_beta_ratio', 'total_beta_ratio'),
        ('Anterior-posterior difference', 'left_AP_difference',
         'right_AP_difference', 'AP_difference'),
    )
    for label, left, right, total in rows:
        _row(table, (label, number(results.get(left)), number(results.get(right)),
                     number(results.get(total)) if total else ''), widths)

    bad = results.get('bad_channels')
    _basis(document, 'Electrodes marked bad: %s'
           % (', '.join(bad) if bad else 'none'), Inches(0))
    ratio = results.get('removeEpochsRatio')
    if ratio is not None:
        _basis(document, 'Epochs rejected as artifact: %s'
               % number(float(ratio) * 100, '%'), Inches(0))


def _usableBox(section):
    """The space a figure has on the page, in inches."""
    width = (section.page_width.inches
             - section.left_margin.inches - section.right_margin.inches)
    height = (section.page_height.inches
              - section.top_margin.inches - section.bottom_margin.inches)
    return width, height


def _figureWidth(path, maxWidth, maxHeight):
    """How wide to place a figure so it fits the page in both directions.

    Fitting width alone is what made the figures section unusable: the
    topographic maps are 1440x1800 and 1440x2160, so at 9.5 inches wide they
    wanted 11.9 and 14.2 inches of height on a page with 6.5 - Word moved each
    one to the page after its heading and left the heading stranded.
    """
    try:
        from PIL import Image
        with Image.open(path) as image:
            pixelWidth, pixelHeight = image.size
        aspect = float(pixelWidth) / float(pixelHeight or 1)
    except Exception:
        return maxWidth
    if aspect <= 0:
        return maxWidth
    # Whichever bound binds first.
    return min(maxWidth, maxHeight * aspect)


def _figures(document, dest_folder, fileName):
    """The analysis figures, each below its own caption.

    The page stays portrait. Four of the six figures are portrait or square -
    the topographic maps and the spectrogram - so a landscape section made them
    smaller, not larger, as well as breaking the document into two orientations
    for anyone editing it.
    """
    names = figureNames(fileName)
    # Paired with the index that names them: if one figure is missing, the rest
    # must keep their own captions rather than shifting up by one.
    present = [(index, os.path.join(dest_folder, name))
               for index, name in enumerate(names)]
    present = [(i, p) for i, p in present if os.path.isfile(p)]
    if not present:
        return

    document.add_page_break()
    document.add_heading('Figures', level=1)

    maxWidth, maxHeight = _usableBox(document.sections[-1])
    # Room for the caption above the figure.
    maxHeight -= 0.6

    for index, path in present:
        caption = FIGURE_CAPTIONS.get(index) or os.path.basename(path)
        heading = document.add_heading(caption, level=2)
        # Word must not put the caption on one page and the figure on the next.
        heading.paragraph_format.keep_with_next = True

        paragraph = document.add_paragraph()
        paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
        paragraph.paragraph_format.keep_together = True
        paragraph.add_run().add_picture(
            path, width=Inches(_figureWidth(path, maxWidth, maxHeight)))
