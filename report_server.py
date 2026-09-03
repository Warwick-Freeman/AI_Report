############################################
# Local server for the report review front end.
#
# Serves webui/ and a small JSON API over the existing analysis. Nothing leaves
# the machine: it binds to the loopback address only, and the front end loads no
# script from any network.
#
# The analysis runs once, in a worker thread, and the CreateReport instance
# stays in memory afterwards. That is the whole reason this is a server rather
# than the subprocess the study browser uses: the reader reviews the findings
# and then generates the document from the same analysis, instead of paying for
# it twice. A session is abandoned rather than killed - the thread is left to
# finish into a result nobody reads.
#
#   python report_server.py                    serve and open a browser
#   python report_server.py --study <path>     and start on that study
#   python report_server.py --no-browser --port 8731
############################################
import os

# Before anything can import pyplot. The analysis and the document both draw
# figures, and they draw them on a worker thread; an interactive backend
# segfaults the process when it is driven from off the main thread. Agg has no
# event loop and no window, which is what a server wants.
os.environ.setdefault('MPLBACKEND', 'Agg')

import argparse
import io
import json
import mimetypes
import threading
import traceback
import uuid
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import report_api

# Bumped whenever the front end starts relying on something new from the API.
#
# The page's static files are read from disk on every request, so editing them
# takes effect on the next reload while the Python process keeps running the code
# it started with. A new front end then talks to an old API and misreads what it
# gets back - a missing field looks like an empty one. The page compares this
# against what it expects and says to restart rather than guessing.
API_VERSION = 3

HERE = os.path.dirname(os.path.abspath(__file__))
WEBUI = os.path.join(HERE, 'webui')

# Sessions live for the life of the process. Reports are small; the analysis
# behind them is not, which is why they are kept.
SESSIONS = {}
LOCK = threading.Lock()


class Tee(io.TextIOBase):
    """Captures the analysis log while leaving it on the console."""

    def __init__(self, session, stream):
        self.session = session
        self.stream = stream

    def write(self, text):
        if text:
            with LOCK:
                self.session['log'].append(text)
                # A long analysis prints a lot; the front end only shows a tail.
                if len(self.session['log']) > 4000:
                    del self.session['log'][:2000]
        try:
            return self.stream.write(text)
        except Exception:
            return len(text)

    def flush(self):
        try:
            self.stream.flush()
        except Exception:
            pass


def ensureOutputFolder(path, study=None):
    """Create the output folder now, and report why if it cannot be.

    Checked before the analysis starts, not at the end of it. The folder is only
    needed when the document is written, so leaving it unchecked meant a reader
    waited out a few minutes of analysis and then learnt that the folder they
    typed could not be made. A relative path is resolved here too, so the
    message names somewhere real.

    Returns (absolutePath, error).
    """
    import profusion
    raw = profusion.resolveOutputFolder(path, study) if study else (path or '.')
    absolute = os.path.abspath(raw)
    if os.path.isdir(absolute):
        return absolute, None
    if os.path.exists(absolute):
        return absolute, ('%s already exists and is not a folder.' % absolute)
    try:
        os.makedirs(absolute)
    except OSError as e:
        return absolute, ('Cannot create the output folder %s: %s' % (absolute, e))
    return absolute, None


def resolveLlm(options):
    """Settle which model will draft the narrative, or say why none can.

    Returns (model, error, note). Only consulted when the narrative is asked
    for; with it switched off the analysis and the document need no provider at
    all. The note says which provider ended up answering, and belongs in the
    session log rather than only on the console - a reader should know the
    narrative came from a different model than the default named.

    A model the caller named is honoured when its key is present. Otherwise the
    first provider that does have a key is used, because the front end offers no
    picker and silently keeping a default whose key is missing is what made the
    option fail every time.
    """
    import study_runner

    if not options.get('aiReport'):
        return options.get('llm_model'), None, None

    available = study_runner.availableProviders()
    if not available:
        wanted = ', '.join(envVar for _, envVar, _ in study_runner.PROVIDERS)
        return None, ('The narrative needs a language-model key, and config.env '
                      'has none. Set one of %s, or clear "Draft the narrative '
                      'with a language model" - everything else in the report is '
                      'produced without a provider.' % wanted), None

    requested = options.get('llm_model')
    wantedProvider = study_runner.providerFor(requested)
    for name, _envVar, model in available:
        if name == wantedProvider:
            return requested, None, ('Narrative drafted with %s (%s).'
                                     % (requested, name))

    name, _envVar, model = available[0]
    return model, None, (
        'No key for %s, so the narrative will be drafted with %s (%s).'
        % (requested or 'the requested model', model, name))


def runAnalysis(sessionId, study, options):
    """Analyse one study, then leave the instance available for generation."""
    import contextlib
    import sys

    session = SESSIONS[sessionId]
    tee = Tee(session, sys.__stdout__)
    try:
        with contextlib.redirect_stdout(tee), contextlib.redirect_stderr(tee):
            from auto_report import CreateReport
            import study_runner

            filePath, fileName = os.path.split(study.rstrip('/\\'))
            if not filePath:
                filePath = '.'

            apiKey, keyError = study_runner.resolveApiKey(options.get('llm_model'))
            if options.get('aiReport') and not apiKey:
                raise RuntimeError('AI report requested but %s' % keyError)

            report = CreateReport(
                fileName, filePath,
                LLM_API_KEY=apiKey or '',
                llm_model=options.get('llm_model') or 'gemini-1.5-flash',
                # Passed through: CreateReport resolves an empty destination
                # to the study's own folder, and the handler has already put a
                # resolved absolute path here. Defaulting to './reports' would
                # override that.
                dest_pdfPath=options.get('dest_pdfPath') or '',
                autogenerate=False,
                outputPdf=False,
                aiReport=bool(options.get('aiReport')),
                reportLang=options.get('reportLang') or 'english',
                useRepair=options.get('useRepair', True),
                unit_uV=options.get('unit_uV', True),
                dropEpochSD=options.get('dropEpochSD', 2.2),
                removeEpochsRationThreshold=options.get(
                    'removeEpochsRationThreshold', 0.3),
                renameChannels=options.get('renameChannels', True),
                tmin=options.get('tmin'), tmax=options.get('tmax'),
                profusionSegment=options.get('profusionSegment') or 'longest',
                profusionMaxSeconds=options.get('profusionMaxSeconds'),
                patientDob=study_runner.parseDob(options.get('patientDob')),
                patientAge=options.get('patientAge'),
                autoEyeState=bool(options.get('autoEyeState')),
                stageSleep=bool(options.get('stageSleep', True)),
                sleepBackend=options.get('sleepBackend') or 'usleep',
                spikeTypeIds=options.get('spikeTypeIds'))

            raw, results = report.process()
            report.raw = raw

            # Draw the figures now, while the epochs are still in memory, and
            # save the results beside them. That is what lets a later session
            # rebuild the document without analysing the recording again - and
            # the figures would be written at generate time anyway.
            saved = None
            try:
                report.drawFigures()
                saved = report_api.saveAnalysis(
                    results, report.dest_pdfPath, report.fileName,
                    study=study, options=options)
                print('Analysis saved: %s' % saved)
            except Exception as e:
                print('Could not save the analysis for re-use: %s: %s'
                      % (type(e).__name__, e))

            with LOCK:
                session['instance'] = report
                session['report'] = report_api.buildReport(results, study, options)
                session['saved'] = saved
                session['status'] = 'ready'
    except Exception as e:
        with LOCK:
            session['status'] = 'failed'
            session['error'] = '%s: %s' % (type(e).__name__, e)
            session['traceback'] = traceback.format_exc()
        try:
            tee.write('\nANALYSIS FAILED\n%s\n' % traceback.format_exc())
        except Exception:
            pass


# matplotlib keeps global state, so two documents drawn at once would draw into
# each other. One at a time.
DRAW = threading.Lock()


def generateDocument(sessionId):
    """Write the document from the analysis in memory, as the reader left it."""
    import contextlib
    import sys

    session = SESSIONS[sessionId]
    instance = session.get('instance')
    restored = session.get('restored')
    if instance is None and not restored:
        raise RuntimeError('nothing analysed in this session')

    folder, folderError = ensureOutputFolder(
        instance.dest_pdfPath if instance else restored['dest'])
    if folderError:
        with LOCK:
            session['status'] = 'ready'
            session['error'] = folderError
        return
    if instance:
        instance.dest_pdfPath = folder
    else:
        restored['dest'] = folder

    applied = report_api.applyOverrides(session['report'], session.get('overrides'))
    session['report'] = applied
    applyToResults(instance.results if instance else restored['results'], applied)

    tee = Tee(session, sys.__stdout__)
    try:
        with DRAW, contextlib.redirect_stdout(tee), contextlib.redirect_stderr(tee):
            if instance:
                instance.outputPdf = True
                # The path comes back from the writer. Rebuilding it here meant
                # agreeing with createPDF about how a filename is truncated, and
                # a study name containing a dot broke that agreement: the
                # document was written and this reported that it was not.
                pdf = instance.writeDocument()
            else:
                # No signal in memory - the figures on disk are the analysis.
                import createPDF
                written = createPDF.writePDFFromSaved(
                    restored['file_name'], restored['results'], folder)
                pdf = written.outFile
        pdf = pdf if (pdf and os.path.isfile(pdf)) else None
        fileName = instance.fileName if instance else restored['file_name']
        stem = os.path.splitext(os.path.basename(pdf))[0] if pdf \
            else os.path.splitext(fileName)[0]

        # The structured SCORE data file, written beside the document. The
        # document is for a person; this is the same report as data, carrying
        # the provenance of every value and the reader's overrides - which the
        # document states but cannot be queried for.
        data = None
        try:
            data = os.path.abspath(os.path.join(folder, stem + '.score.json'))
            report_api.save(applied, data)
        except OSError as e:
            tee.write('Could not write the SCORE data file: %s\n' % e)
            data = None

        with LOCK:
            session['pdf'] = pdf
            session['data'] = data
            session['status'] = 'ready'
            if not pdf:
                # Say where it looked. 'No document was written' on its own gave
                # a reader nothing to act on and hid a path disagreement between
                # the writer and this.
                session['error'] = (
                    'No document was written. The writer reported %r and the '
                    'output folder is %r - check that folder is writable.'
                    % (getattr(instance, 'documentPath', None) if instance else None,
                       folder))
    except Exception as e:
        with LOCK:
            session['status'] = 'ready'
            session['error'] = 'document generation failed: %s: %s' % (
                type(e).__name__, e)
        tee.write('\nDOCUMENT GENERATION FAILED\n%s\n' % traceback.format_exc())


def applyToResults(results, report):
    """Fold the reader's decisions back into the results the PDF is built from.

    Without this the review would be decorative: the reader would accept and
    override values that the document then ignored.
    """
    if not results:
        return
    excluded = set()
    for section in report.get('sections') or []:
        if not section.get('included', True):
            excluded.add(section['id'])
            continue
        if section['id'] == 'recording' and results.get('recording'):
            # The reader's activation responses live in the section's rows;
            # without this they would show on screen and not in the document.
            answers = {}
            for row in section.get('rows') or []:
                if row['id'].startswith('activation_') and row.get('override'):
                    answers[row['label']] = row['override']
            activation = (results['recording'] or {}).get('activation') or {}
            for procedure in activation.get('procedures') or []:
                answer = answers.get('%s response' % procedure['name'])
                if answer:
                    procedure['response'] = answer

        if section['id'] == 'pdr' and results.get('pdr'):
            for row in section.get('rows') or []:
                key = row['id'][4:] if row['id'].startswith('pdr_') else None
                if key and row.get('override') and key in results['pdr']:
                    entry = results['pdr'][key]
                    # The measurement is kept, not replaced. A reader's scored
                    # value and the number measured off the signal are different
                    # things, and a document that shows only the override leaves
                    # no way to see what was changed - or to explain why the
                    # measurement table earlier in the report says something
                    # else. Both are stated, and which is which.
                    original = entry.get('term')
                    originalBasis = entry.get('basis') or ''
                    entry['term'] = row['override']
                    entry['basis'] = ('overridden by the reader; measured %s%s'
                                      % (original,
                                         ' (%s)' % originalBasis if originalBasis else ''))
                    entry['measured_term'] = original
                    entry['overridden'] = True
                    entry['provisional'] = False
        if section['id'] in ('interictal', 'artifacts'):
            block = results.get(section['id'])
            keep = {f['name'] for f in section.get('findings') or []
                    if f.get('included', True)}
            if block and block.get('findings'):
                block['findings'] = [f for f in block['findings']
                                     if f.get('name') in keep]
        if section['id'] == 'episodes' and results.get('spikeseizure'):
            keep = {f['name'] for f in section.get('findings') or []
                    if f.get('included', True)}
            episodes = results['spikeseizure'].get('episodes') or []
            results['spikeseizure']['episodes'] = [
                e for e in episodes if e.get('name') in keep]
        if section['id'] == 'events':
            # The Events screen offers to carry events into the report, and
            # until now nothing did: the selection was recorded and then
            # ignored. Whatever the reader ticked goes to the document.
            results['selected_events'] = [
                {'type': e.get('type'), 'seconds': e.get('seconds'),
                 'duration_seconds': e.get('duration_seconds'),
                 'text': e.get('text'), 'channels': e.get('channels') or [],
                 'provocation': e.get('provocation'),
                 'is_detection': bool(e.get('is_detection'))}
                for e in section.get('events') or [] if e.get('included')]

        if section['id'] == 'conclusion':
            values = {row['id']: row.get('override') or row.get('value')
                      for row in section.get('rows') or []}
            conclusion = results.get('conclusion') or {}
            if values.get('significance'):
                conclusion['significance'] = values['significance']
            if values.get('yield'):
                conclusion['yield'] = values['yield']
            results['conclusion'] = conclusion
    # createPDF skips these pages.
    results['_excluded'] = sorted(excluded)


class Handler(BaseHTTPRequestHandler):
    server_version = 'SCOREReportUI'

    def log_message(self, fmt, *args):
        pass  # the analysis log is the interesting one

    # ------------------------------------------------------------- plumbing
    def _send(self, code, body, contentType='application/json'):
        if isinstance(body, (dict, list)):
            body = json.dumps(body, default=str).encode('utf-8')
        elif isinstance(body, str):
            body = body.encode('utf-8')
        self.send_response(code)
        self.send_header('Content-Type', contentType)
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store')
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionAbortedError):
            pass

    def _body(self):
        length = int(self.headers.get('Content-Length') or 0)
        if not length:
            return {}
        try:
            return json.loads(self.rfile.read(length).decode('utf-8'))
        except ValueError:
            return {}

    def _static(self, path):
        relative = path.lstrip('/') or 'index.html'
        full = os.path.normpath(os.path.join(WEBUI, relative))
        if not full.startswith(WEBUI) or not os.path.isfile(full):
            return self._send(404, {'error': 'not found'})
        kind = mimetypes.guess_type(full)[0] or 'application/octet-stream'
        with open(full, 'rb') as f:
            self._send(200, f.read(), kind)

    # ------------------------------------------------------------------ GET
    def do_GET(self):
        path = self.path.split('?')[0]
        query = {}
        if '?' in self.path:
            from urllib.parse import parse_qs, unquote
            query = {k: unquote(v[0]) for k, v in
                     parse_qs(self.path.split('?', 1)[1]).items()}

        if not path.startswith('/api/'):
            return self._static(path)

        if path == '/api/config':
            import study_runner
            available = study_runner.availableProviders()
            defaults = dict(study_runner.DEFAULTS)
            # Show the model that will actually be used, not the one in the
            # defaults table - with no key for the default provider they differ,
            # and the Settings screen showing the unusable one is misleading.
            if available:
                defaults['llm_model'] = available[0][2]
            return self._send(200, {
                'api': API_VERSION,
                # So a reader can identify the process answering them when it
                # turns out not to be the one they just started.
                'pid': os.getpid(),
                'defaults': defaults,
                'provenance': report_api.SECTIONS,
                'study': self.server.startStudy,
                # Provider names and the model each would use. No keys: the
                # front end never needs one and must never be sent one.
                'llm': {
                    'available': [{'provider': name, 'model': model}
                                  for name, _envVar, model in available],
                    'wanted': [envVar for _, envVar, _ in study_runner.PROVIDERS],
                },
            })

        if path == '/api/analysis':
            study = (query.get('study') or '').strip()
            if not study:
                return self._send(400, {'error': 'no study given'})
            # Resolved but not created: asking whether a study has been analysed
            # should not leave a folder behind.
            import profusion
            folder = os.path.abspath(
                profusion.resolveOutputFolder(query.get('dest'), study))
            described = (report_api.describeSavedAnalysis(folder, os.path.basename(
                study.rstrip('/\\'))) if os.path.isdir(folder) else None)
            return self._send(200, {'study': study, 'dest': folder,
                                    'analysis': described})

        if path == '/api/studies':
            return self._send(200, self._studies(query.get('root')))

        if path.startswith('/api/session/'):
            parts = path.split('/')
            sessionId = parts[3]
            session = SESSIONS.get(sessionId)
            if not session:
                return self._send(404, {'error': 'no such session'})
            tail = parts[4] if len(parts) > 4 else ''
            with LOCK:
                logText = ''.join(session['log'][-400:])
            if tail == 'log':
                return self._send(200, {'log': logText,
                                        'status': session['status']})
            payload = {
                'id': sessionId,
                'status': session['status'],
                'error': session.get('error'),
                'log': logText,
                'study': session['study'],
                'pdf': session.get('pdf'),
                'data': session.get('data'),
                'restored': bool(session.get('restored')),
                'saved': session.get('saved'),
                'can_generate': (session.get('restored') or {}).get('can_generate', True)
                                if session.get('restored') else True,
            }
            if session.get('report'):
                report = report_api.applyOverrides(session['report'],
                                                   session.get('overrides'))
                payload['report'] = report
                payload['outstanding'] = report_api.outstandingTotal(report)
            return self._send(200, payload)

        return self._send(404, {'error': 'unknown endpoint'})

    def _studies(self, root):
        """Studies under a folder, via the study list where there is one."""
        if not root or not os.path.isdir(root):
            return {'root': root, 'studies': [], 'error': 'folder not found'}
        try:
            import studylist
            found = studylist.loadStudies(root)
            return {'root': root, 'studies': [report_api._clean(s) for s in found]}
        except Exception as e:
            return {'root': root, 'studies': [], 'error': str(e)}

    # ----------------------------------------------------------------- POST
    def do_POST(self):
        path = self.path.split('?')[0]
        body = self._body()

        if path == '/api/analyse':
            study = (body.get('study') or '').strip()
            if not (os.path.isdir(study) or os.path.isfile(study)):
                return self._send(400, {'error': 'study not found: %s' % study})

            # Settle the output folder before spending minutes on the analysis.
            options = dict(body.get('options') or {})
            folder, folderError = ensureOutputFolder(
                options.get('dest_pdfPath'), study)
            if folderError:
                return self._send(400, {'error': folderError})
            options['dest_pdfPath'] = folder

            # And the provider, for the same reason: better refused now than
            # after the analysis has run.
            model, llmError, llmNote = resolveLlm(options)
            if llmError:
                return self._send(400, {'error': llmError})
            if model:
                options['llm_model'] = model

            sessionId = uuid.uuid4().hex[:12]
            SESSIONS[sessionId] = {'status': 'running', 'log': [], 'study': study,
                                   'report': None, 'overrides': {}, 'instance': None}
            if llmNote:
                SESSIONS[sessionId]['log'].append(llmNote + '\n')
                print(llmNote)
            thread = threading.Thread(target=runAnalysis,
                                      args=(sessionId, study, options),
                                      daemon=True)
            thread.start()
            return self._send(200, {'id': sessionId, 'status': 'running'})

        if path == '/api/restore':
            study = (body.get('study') or '').strip()
            folder, folderError = ensureOutputFolder(
                (body.get('options') or {}).get('dest_pdfPath'), study)
            if folderError:
                return self._send(400, {'error': folderError})
            fileName = os.path.basename(study.rstrip('/\\'))
            payload = report_api.loadAnalysis(folder, fileName)
            if not payload:
                return self._send(404, {
                    'error': 'No saved analysis for %s in %s.'
                             % (fileName, folder)})
            import createPDF
            missing = createPDF.missingFigures(folder, fileName)
            sessionId = uuid.uuid4().hex[:12]
            results = payload.get('results') or {}
            SESSIONS[sessionId] = {
                'status': 'ready', 'log': [], 'study': study, 'overrides': {},
                'instance': None,
                'restored': {'results': results, 'dest': folder,
                             'file_name': payload.get('file_name') or fileName,
                             'saved': payload.get('saved'),
                             'can_generate': not missing},
                'report': report_api.buildReport(results, study,
                                                 payload.get('options')),
                'saved': report_api.analysisPath(folder, fileName),
            }
            note = ('Loaded the analysis of %s saved %s. The recording was not '
                    'analysed again.' % (fileName, payload.get('saved')))
            if missing:
                note += (' The figures are missing from the output folder (%s), '
                         'so a document cannot be written until the analysis is '
                         're-run.' % ', '.join(missing))
            SESSIONS[sessionId]['log'].append(note + '\n')
            print(note)
            return self._send(200, {'id': sessionId, 'status': 'ready',
                                    'restored': True,
                                    'can_generate': not missing})

        if path.startswith('/api/session/'):
            parts = path.split('/')
            sessionId = parts[3]
            session = SESSIONS.get(sessionId)
            if not session:
                return self._send(404, {'error': 'no such session'})
            action = parts[4] if len(parts) > 4 else ''

            if action == 'overrides':
                with LOCK:
                    overrides = session.setdefault('overrides', {})
                    for sectionId, edits in (body or {}).items():
                        overrides.setdefault(sectionId, {}).update(edits)
                report = report_api.applyOverrides(session['report'],
                                                   session['overrides'])
                return self._send(200, {'ok': True,
                                        'outstanding': report_api.outstandingTotal(report)})

            if action == 'generate':
                if session['status'] != 'ready':
                    return self._send(409, {'error': 'analysis is %s' % session['status']})
                with LOCK:
                    session['status'] = 'generating'
                    session['error'] = None
                    session['pdf'] = None
                threading.Thread(target=generateDocument, args=(sessionId,),
                                 daemon=True).start()
                return self._send(202, {'status': 'generating'})

            if action == 'open':
                target = session.get('pdf')
                if not target or not os.path.isfile(target):
                    return self._send(404, {'error': 'no document yet'})
                try:
                    os.startfile(target)  # noqa: S606 - Windows shell open
                except AttributeError:
                    webbrowser.open('file:///%s' % target.replace('\\', '/'))
                return self._send(200, {'ok': True})

        return self._send(404, {'error': 'unknown endpoint'})


class ReportServer(ThreadingHTTPServer):
    """The server, with address reuse switched off deliberately.

    HTTPServer sets allow_reuse_address = 1, and on Windows SO_REUSEADDR does not
    mean what it means on Unix: it lets a second socket bind a port another
    process is already listening on, and which of them receives a given
    connection is undefined. So restarting this server while an old one was still
    running appeared to work - no error, a fresh console, a URL - while the
    browser went on talking to the old process. The symptom was the front end
    reporting a server older than itself, with nothing to explain why restarting
    had not helped.

    With reuse off, binding a port in use fails and says so.
    """
    allow_reuse_address = False


def portInUse(port):
    """Whether something is already listening on the loopback port."""
    import socket
    probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    probe.settimeout(0.3)
    try:
        return probe.connect_ex(('127.0.0.1', port)) == 0
    finally:
        probe.close()


def serve(port=8731, study=None, openBrowser=True):
    # Checked before binding as well, because the message is better than the
    # OSError and because a stray listener is the common case, not a rare one.
    if portInUse(port):
        print('Port %d is already in use, most likely by a report server that is '
              'still running.' % port)
        print('')
        print('That other server keeps answering the browser, so a page loaded '
              'now would still be served by its code.')
        print('Close its console window. To find it:')
        print('    netstat -ano | findstr :%d' % port)
        print('    taskkill /PID <the pid listed> /F')
        print('Or serve on another port:  python report_server.py --port %d'
              % (port + 1))
        return 2

    try:
        server = ReportServer(('127.0.0.1', port), Handler)
    except OSError as e:
        print('Could not listen on port %d: %s' % (port, e))
        print('Close whatever is using it, or pass --port with another number.')
        return 2

    server.startStudy = study
    url = 'http://127.0.0.1:%d/' % server.server_address[1]
    print('SCORE report review front end')
    print('  %s' % url)
    print('  serving %s' % WEBUI)
    print('  process %d' % os.getpid())
    if study:
        print('  study  %s' % study)
    print('  Ctrl+C to stop')
    if openBrowser:
        threading.Timer(0.4, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print('\nstopped')
    finally:
        server.server_close()
    return 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', type=int, default=8731)
    parser.add_argument('--study', help='study to open on start')
    parser.add_argument('--no-browser', action='store_true')
    args = parser.parse_args()
    return serve(args.port, args.study, not args.no_browser)


if __name__ == '__main__':
    raise SystemExit(main())
