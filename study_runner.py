############################################
# Runs one report from a JSON options file.
#
# The study browser (study_browser.py) spawns this as a subprocess rather than
# calling CreateReport in-process: the analysis loads TensorFlow and draws
# matplotlib figures, neither of which belongs on a Qt event loop, and a
# separate process can be cancelled outright and cannot take the UI down with
# it.
#
# Usable on its own too, which is the easiest way to re-run exactly what the UI
# ran - the browser writes the options file next to the report:
#
#   python study_runner.py options.json
############################################
import argparse
import json
import os
import sys
import traceback

# Every key the options file may carry, with the default applied when absent.
# Names match CreateReport's arguments, except 'study' which is split into the
# (fileName, filePath) pair it wants.
DEFAULTS = {
    'study': None,               # path to the .eeg study folder or EEG file
    'outputPdf': True,
    'aiReport': False,
    'reportLang': 'english',
    'llm_model': 'gemini-1.5-flash',
    'dest_pdfPath': './reports',
    'useRepair': True,
    'unit_uV': True,
    'dropEpochSD': 2.2,
    'removeEpochsRationThreshold': 0.3,
    'renameChannels': True,
    'tmin': None,
    'tmax': None,
    'profusionSegment': 'longest',
    'profusionMaxSeconds': None,
    # SCORE scores PDR significance against an age-dependent limit. ISO date
    # string, e.g. "1984-11-12"; patientAge (years) is the fallback.
    'patientDob': None,
    'patientAge': None,
    # Infer eye state from the signal where the recording has no eye-state
    # annotations. Enables PDR reactivity scoring, at the risk of a false
    # reduced-reactivity finding - see pdr.py.
    'autoEyeState': False,
    # Sleep staging and sleep graphoelements. 'usleep' or 'yasa'.
    'stageSleep': True,
    'sleepBackend': 'usleep',
}


# Each provider, the environment variable its key lives in, and a default model
# to use when a caller has not named one. Order is preference.
PROVIDERS = (
    ('openai', 'OPENAI_KEY', 'gpt-4o'),
    ('anthropic', 'ANTHROPIC_API_KEY', 'claude-sonnet-4-5'),
    ('google', 'GOOGLE_API_KEY', 'gemini-1.5-flash'),
)


def providerFor(llm_model):
    """Which provider a model name belongs to, or None."""
    model = (llm_model or '').lower()
    if 'gpt' in model or model.startswith('o1') or model.startswith('o3'):
        return 'openai'
    if 'claude' in model:
        return 'anthropic'
    if 'gemini' in model:
        return 'google'
    return None


def availableProviders():
    """Providers with a usable key in config.env, as (name, envVar, model).

    The review front end has no provider or model picker - the design brief put
    that out of scope - so something has to choose, and choosing a provider
    whose key is missing is how ticking the narrative option came to fail every
    time with a complaint about GOOGLE_API_KEY.
    """
    from dotenv import load_dotenv
    load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'config.env'))

    out = []
    for name, envVar, model in PROVIDERS:
        key = os.environ.get(envVar)
        if key and not key.startswith('REPLACE_WITH'):
            out.append((name, envVar, model))
    return out


def resolveApiKey(llm_model):
    """The API key matching the requested model, from config.env.

    Returns (key, error). CreateReport only contacts a provider when aiReport
    is set, so a missing key is not fatal on its own.
    """
    from dotenv import load_dotenv
    load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'config.env'))

    model = (llm_model or '').lower()
    if 'gpt' in model:
        name = 'OPENAI_KEY'
    elif 'claude' in model:
        name = 'ANTHROPIC_API_KEY'
    elif 'gemini' in model:
        name = 'GOOGLE_API_KEY'
    else:
        return None, 'Unrecognised LLM model %r - expected a gpt, claude or gemini model' % llm_model

    key = os.environ.get(name)
    if not key or key.startswith('REPLACE_WITH'):
        return None, 'No usable %s in config.env' % name
    return key, None


def parseDob(text):
    """An ISO date string as a datetime, or None. Raises on a malformed date."""
    if not text:
        return None
    from datetime import datetime
    return datetime.strptime(str(text).strip()[:10], '%Y-%m-%d')


def expectedPdfPath(options):
    """Where writePDF will put the report, mirroring its own naming."""
    studyName = os.path.basename(options['study'].rstrip('/\\'))
    # splitext, not split('.'): a study called 'Surname, Given 2024.01.15.eeg'
    # truncated at the first dot and the report was then looked for under a
    # name nothing had written.
    return os.path.join(options['dest_pdfPath'],
                        os.path.splitext(studyName)[0] + '.pdf')


def run(options):
    """Generate one report. Returns a process exit code."""
    study = options['study']
    if not study:
        print('ERROR: no study given')
        return 2
    study = study.rstrip('/\\')
    if not (os.path.isdir(study) or os.path.isfile(study)):
        print('ERROR: study not found: %s' % study)
        return 2

    apiKey, keyError = resolveApiKey(options['llm_model'])
    if options['aiReport'] and not apiKey:
        print('ERROR: --ai requested but %s' % keyError)
        return 2
    if keyError and not options['aiReport']:
        # Only worth a note: the analysis and the PDF do not need a provider.
        print('Note: %s (not needed - AI report is off)' % keyError)

    os.makedirs(options['dest_pdfPath'], exist_ok=True)

    # Imported here, not at module scope, so the argument and study checks above
    # fail fast instead of after TensorFlow has loaded.
    from auto_report import CreateReport

    filePath, fileName = os.path.split(study)
    if not filePath:
        filePath = '.'

    print('Study   : %s' % study)
    print('Output  : %s' % os.path.abspath(options['dest_pdfPath']))
    print('Options : %s' % json.dumps({k: v for k, v in options.items()
                                       if k != 'study'}, default=str))
    print('-' * 70, flush=True)

    report = CreateReport(fileName, filePath,
                 LLM_API_KEY=apiKey or '',
                 llm_model=options['llm_model'],
                 dest_pdfPath=options['dest_pdfPath'],
                 outputPdf=options['outputPdf'],
                 aiReport=options['aiReport'],
                 reportLang=options['reportLang'],
                 useRepair=options['useRepair'],
                 unit_uV=options['unit_uV'],
                 dropEpochSD=options['dropEpochSD'],
                 removeEpochsRationThreshold=options['removeEpochsRationThreshold'],
                 renameChannels=options['renameChannels'],
                 tmin=options['tmin'],
                 tmax=options['tmax'],
                 profusionSegment=options['profusionSegment'],
                 profusionMaxSeconds=options['profusionMaxSeconds'],
                 patientDob=parseDob(options['patientDob']),
                 patientAge=options['patientAge'],
                 autoEyeState=options['autoEyeState'],
                 stageSleep=options['stageSleep'],
                 sleepBackend=options['sleepBackend'])

    if options['outputPdf']:
        # The path the writer actually used, falling back to the expected one
        # only if the run did not report it.
        pdf = getattr(report, 'documentPath', None) or expectedPdfPath(options)
        if os.path.isfile(pdf):
            # The browser watches for this line to offer to open the report.
            print('-' * 70)
            print('REPORT_PDF: %s' % os.path.abspath(pdf), flush=True)
            return 0
        print('ERROR: expected a report at %s but it was not written' % pdf)
        return 1

    return 0


def loadOptions(path):
    """Options file merged over DEFAULTS, rejecting unknown keys."""
    with open(path, encoding='utf-8') as f:
        given = json.load(f)
    unknown = set(given) - set(DEFAULTS)
    if unknown:
        raise ValueError('Unknown option(s): %s' % ', '.join(sorted(unknown)))
    options = dict(DEFAULTS)
    options.update(given)
    return options


def main():
    parser = argparse.ArgumentParser(
        description='Generate one EEG report from a JSON options file')
    parser.add_argument('options', help='path to the JSON options file')
    args = parser.parse_args()

    try:
        options = loadOptions(args.options)
    except (OSError, ValueError, json.JSONDecodeError) as e:
        print('ERROR: could not read options file: %s' % e)
        return 2

    try:
        return run(options)
    except Exception:
        # CreateReport swallows its own exceptions, so anything arriving here is
        # worth a full traceback in the log pane.
        traceback.print_exc()
        return 1


if __name__ == '__main__':
    sys.exit(main())
