############################################
# Generate a report for every recording in a folder.
#
#   python batch_report.py sample_data
#   python batch_report.py sample_data --out reports/sample_data --jobs 2
#
# Each recording is run through study_runner.py as its own process, exactly as
# the study browser does, so one failure cannot take the rest of the batch with
# it and every run leaves an options file that reproduces it on its own.
#
# Reports are named after the recording: sample_data/01RT.edf becomes
# reports/sample_data/01RT.pdf.
############################################
import argparse
import concurrent.futures
import glob
import json
import os
import subprocess
import sys
import time

import study_runner

# Recording formats the pipeline reads. ProfusionEEG studies are folders rather
# than files and are picked up separately.
FILE_PATTERNS = ('*.edf', '*.EDF', '*.fif', '*.mat')
STUDY_PATTERN = '*.eeg'

# Intermediate figures every run writes into the output folder before embedding
# them. Harmless, but there is no reason to leave six of them behind.
INTERMEDIATE_FIGURES = ('eeg0.jpg', 'eeg1.jpg', 'eeg2.jpg', 'eeg3.jpg',
                        'eeg4.jpg', 'eeg5.jpg')


def findRecordings(folder):
    """Every recording in a folder, files and ProfusionEEG studies alike."""
    found = []
    for pattern in FILE_PATTERNS:
        found += glob.glob(os.path.join(folder, pattern))
    for study in glob.glob(os.path.join(folder, STUDY_PATTERN)):
        if os.path.isdir(study):
            found.append(study)
    # Case-insensitive globs can match the same file twice on Windows.
    unique = {os.path.normcase(os.path.abspath(f)): f for f in found}
    return sorted(unique.values(), key=lambda f: os.path.basename(f).lower())


def buildOptions(recording, outputFolder, overrides):
    """The options file for one recording, on top of study_runner's defaults."""
    options = dict(study_runner.DEFAULTS)
    options.update(overrides)
    options['study'] = recording
    options['dest_pdfPath'] = outputFolder
    return options


def runOne(recording, outputFolder, overrides, python=None):
    """Run one recording. Returns a result dict; never raises."""
    name = os.path.basename(recording.rstrip('/\\'))
    stem = name.split('.')[0]
    optionsPath = os.path.join(outputFolder, stem + '_options.json')
    options = buildOptions(recording, outputFolder, overrides)

    started = time.time()
    try:
        with open(optionsPath, 'w', encoding='utf-8') as f:
            json.dump(options, f, indent=2)
    except OSError as e:
        return {'name': name, 'ok': False, 'seconds': 0.0,
                'message': 'could not write the options file: %s' % e}

    command = [python or sys.executable, '-u', 'study_runner.py', optionsPath]
    try:
        finished = subprocess.run(
            command, cwd=os.path.dirname(os.path.abspath(__file__)),
            capture_output=True, text=True, encoding='utf-8', errors='replace')
    except Exception as e:
        return {'name': name, 'ok': False, 'seconds': time.time() - started,
                'message': 'could not start study_runner.py: %s' % e}

    elapsed = time.time() - started
    output = (finished.stdout or '') + (finished.stderr or '')
    pdf = None
    for line in output.splitlines():
        if line.startswith('REPORT_PDF: '):
            pdf = line[len('REPORT_PDF: '):].strip()

    if finished.returncode == 0 and pdf:
        return {'name': name, 'ok': True, 'seconds': elapsed, 'pdf': pdf,
                'message': 'ok', 'log': output}

    # Surface the most useful line rather than the whole log.
    message = 'exit code %d' % finished.returncode
    for line in reversed(output.splitlines()):
        stripped = line.strip()
        if stripped.startswith(('ERROR', 'RuntimeError', 'ValueError',
                                'FileNotFoundError', 'ImportError')):
            message = stripped
            break
    return {'name': name, 'ok': False, 'seconds': elapsed, 'message': message,
            'log': output}


def cleanIntermediates(outputFolder):
    """Remove the leftover figures from the last run in the folder."""
    removed = 0
    for figure in INTERMEDIATE_FIGURES:
        path = os.path.join(outputFolder, figure)
        if os.path.exists(path):
            try:
                os.remove(path)
                removed += 1
            except OSError:
                pass
    return removed


def main():
    parser = argparse.ArgumentParser(
        description='Generate a report for every recording in a folder')
    parser.add_argument('folder', help='folder holding the recordings')
    parser.add_argument('--out', help='output folder '
                                      '(default: reports/<folder name>)')
    parser.add_argument('--jobs', type=int, default=1,
                        help='recordings to run at once. Each one loads its own '
                             'TensorFlow and uses several cores, so 2-3 is '
                             'usually the most that helps (default 1)')
    parser.add_argument('--ai', action='store_true',
                        help='also generate the LLM sections (needs an API key)')
    parser.add_argument('--llm', default=study_runner.DEFAULTS['llm_model'],
                        help='LLM model for --ai')
    parser.add_argument('--segment', choices=['longest', 'concat'],
                        default='longest',
                        help='ProfusionEEG studies only: which data segments to read')
    parser.add_argument('--max-seconds', dest='maxSeconds', type=float,
                        help='cap how much signal each recording loads')
    parser.add_argument('--no-sleep', action='store_true',
                        help='skip sleep staging, which is the slowest stage')
    parser.add_argument('--keep-figures', action='store_true',
                        help='keep the intermediate eeg*.jpg files')
    args = parser.parse_args()

    if not os.path.isdir(args.folder):
        print('ERROR: not a folder: %s' % args.folder)
        return 2

    outputFolder = args.out or os.path.join(
        'reports', os.path.basename(os.path.abspath(args.folder.rstrip('/\\'))))
    os.makedirs(outputFolder, exist_ok=True)

    recordings = findRecordings(args.folder)
    if not recordings:
        print('ERROR: no recordings found in %s' % args.folder)
        return 2

    overrides = {'aiReport': args.ai, 'llm_model': args.llm,
                 'profusionSegment': args.segment,
                 'profusionMaxSeconds': args.maxSeconds,
                 'stageSleep': not args.no_sleep}

    print('%d recording(s) in %s' % (len(recordings), args.folder))
    print('Reports  -> %s' % os.path.abspath(outputFolder))
    print('Running %d at a time%s' % (args.jobs, ', with the LLM sections'
                                      if args.ai else ''))
    print('-' * 78, flush=True)

    started = time.time()
    results = []
    if args.jobs > 1:
        with concurrent.futures.ThreadPoolExecutor(max_workers=args.jobs) as pool:
            futures = {pool.submit(runOne, r, outputFolder, overrides): r
                       for r in recordings}
            for future in concurrent.futures.as_completed(futures):
                result = future.result()
                results.append(result)
                print('  %-16s %-8s %6.0f s  %s'
                      % (result['name'], 'ok' if result['ok'] else 'FAILED',
                         result['seconds'], result['message']), flush=True)
    else:
        for recording in recordings:
            print('  %-16s running...' % os.path.basename(recording), flush=True)
            result = runOne(recording, outputFolder, overrides)
            results.append(result)
            print('  %-16s %-8s %6.0f s  %s'
                  % (result['name'], 'ok' if result['ok'] else 'FAILED',
                     result['seconds'], result['message']), flush=True)

    if not args.keep_figures:
        cleanIntermediates(outputFolder)

    results.sort(key=lambda r: r['name'].lower())
    succeeded = [r for r in results if r['ok']]
    failed = [r for r in results if not r['ok']]

    print('-' * 78)
    print('%d of %d succeeded in %.0f s' % (len(succeeded), len(results),
                                            time.time() - started))
    for result in failed:
        print('  FAILED %-16s %s' % (result['name'], result['message']))
    if failed:
        # The full log of a failure is worth keeping rather than scrolling past.
        logPath = os.path.join(outputFolder, 'batch_failures.log')
        try:
            with open(logPath, 'w', encoding='utf-8') as f:
                for result in failed:
                    f.write('=' * 78 + '\n%s: %s\n' % (result['name'],
                                                       result['message']))
                    f.write((result.get('log') or '') + '\n')
            print('  full logs: %s' % logPath)
        except OSError:
            pass

    return 1 if failed else 0


if __name__ == '__main__':
    sys.exit(main())
