# EEG-AI-Report-Generator

A hybrid AI system that performs automated EEG background analysis and generates clinical reports. This is the implementation of our IEEE JBHI paper (2025).

[![DOI](https://img.shields.io/badge/DOI-10.1109%2FJBHI.2024.3496996-blue)](https://doi.org/10.1109/JBHI.2024.3496996)

[![arXiv](https://img.shields.io/badge/arXiv-2411.09874-b31b1b.svg)](https://arxiv.org/abs/2411.09874)

## Paper Information

This code implements the methodology described in:

C. -S. Tung, S. -F. Liang, S. -F. Chang and C. -P. Young, "A Hybrid Artificial Intelligence System for Automated EEG Background Analysis and Report Generation," in IEEE Journal of Biomedical and Health Informatics, vol. 29, no. 4, pp. 2629-2641, April 2025, doi: 10.1109/JBHI.2024.3496996.
 
https://doi.org/10.1109/JBHI.2024.3496996

The paper and its contents are © 2025 IEEE. 
<!-- Personal use of this material is permitted. Permission from IEEE must be obtained for all other uses, in any current or future media, including reprinting/republishing this material for advertising or promotional purposes, creating new collective works, for resale or redistribution to servers or lists, or reuse of any copyrighted component of this work in other works. -->

## Code License

This code is released under the GNU General Public License v3.0 (GPL-3.0). You are free to use, modify, and distribute this code according to the terms of the GPL-3.0 license.

## Overview

This repository provides an implementation of automated EEG background analysis and report generation using a hybrid AI approach. The system combines deep learning for EEG analysis with large language models for report generation.

### Key Features

- Automated EEG background analysis
- AI-powered report generation using multiple LLM providers
- Support for standard EEG file formats (EDF, FIF)
- Support for SPIS dataset MAT files
- Multi-language report generation
- PDF report export

## Installation

### Prerequisites

We recommend using a Conda environment for installation.

### Dependencies

Install required packages:

```bash
pip install tensorflow google-generativeai anthropic openai mne python-dotenv \
    ipykernel matplotlib pyod pandas scikit-learn seaborn tqdm ipywidgets \
    PyWavelets beautifulsoup4 fpdf2 mne-qt-browser PyQt6 dit librosa \
    statsmodels pyinform pymatreader6

```
### Fonts for supported languages in PDF reports

For displaying different languages in the PDF report, you must have the `arialuni.ttf` font file in the root directory.

### API Configuration

1. Create a `config.env` file in the project root
2. Add your API keys:
```
GOOGLE_API_KEY=YOUR_GOOGLE_API_KEY # for Google Gemini
ANTHROPIC_API_KEY=YOUR_ANTHROPIC_API_KEY # for Anthropic Claude
OPENAI_KEY=YOUR_OPENAI_KEY # for OpenAI gpt models
```

## Usage

### Supported File Formats
- EDF: General EEG recordings
- FIF: General EEG recordings
- MAT: SPIS dataset files only
- EEG: Native Compumedics ProfusionEEG 4 studies, read in place with no EDF export (see below)

### Patient information and recording conditions

`recording.py` fills SCORE's first two report sections — *Patient information* and
*Recording conditions* — entirely from metadata the study already carries, and the
PDF now opens with them the way a SCORE report does. Nothing on that page is a
proposal: name, sex, date of birth, age at recording, date and time, acquisition
and analysis sample rates, sensor group, review filters, device, montage and study
format are all read, not inferred. Fields a technologist observes rather than the
signal shows — alertness and cooperation, time of last meal, skull defect — are
listed as outstanding rather than guessed.

It also holds the **duration accountant**, which reports three different numbers
that are easy to conflate:

| | Demo.eeg |
| --- | --- |
| Recorded in the study | 1:45:48 |
| Loaded for analysis | 0:01:49 |
| Analysed after artifact rejection | 56 s — 51% of what was loaded |

This matters beyond bookkeeping. Every SCORE incidence and prevalence band is a
rate, and the denominator must be the duration actually examined. A pipeline that
discards half its epochs and then divides by the recording length halves every
rate it reports.

### Diagnostic significance, summary and clinical comments

`prompt.scoreConclusionPrompt` plus `CreateReport.scoreConclusion` fill SCORE
sections 15 and 17, and the PDF gains a **Diagnostic Significance** page. Requires
`--ai`.

SCORE treats these two sections very differently, and so does this:

- **Diagnostic significance is a forced choice** from a fixed list, not prose. The
  model picks terms; `score_common.validateSignificance` then rejects anything
  outside SCORE's list before a reader sees it, and says why it was rejected.
- **Summary of findings and clinical comments are genuinely free text** in SCORE,
  which is what a language model should be drafting - from the structured findings
  and nothing else.

**It is a proposal, never a scored value.** SCORE reserves the diagnostic
significance for the electroencephalographer, taken last and in the clinical
context - which an automated analysis does not have. The page carries a banner
saying so and a sign-off block for the reader to score it themselves.

**Yields this analysis cannot support are refused.** Epilepsy, status epilepticus,
CSWS/ESES, PNES, other non-epileptic episode, coma and brain death are rejected
whatever the findings suggest, because there is no epileptiform detection, no
episode capture and no clinical context behind them. Only focal dysfunction,
diffuse dysfunction and abnormality of uncertain significance can be proposed. A
conclusion of "epilepsy" from a background analysis carries consequences the
analysis cannot justify.

The prompt also forbids stating any number, band or percentage absent from the
findings, requires "not assessable" where a property was Not possible to
determine, and requires provisional findings to be described as unconfirmed. That
rule exists because the earlier free-text narrative was observed inventing an
amplitude range of "10 to 50 uV", which is neither SCORE's banding nor in the data.

Once a conclusion parses, the original free-text **EEG AI Analysis** page is
suppressed: the two overlap almost entirely, and a report carrying two
independently generated conclusions can carry two different ones. The narrative
remains as the fallback when the conclusion cannot be parsed.

### Report figures

Figures are scaled to fit the page box in both dimensions, centred, via
`writePDF._placeImage`. fpdf2 derives the missing dimension from the aspect
ratio, so passing only a width lets a tall figure run off the bottom - the EEG
traces page was a square figure drawn 280 mm wide on a 210 mm-tall landscape
page, and the spectrogram overflowed by about 28 mm. Pass a width only if the
height is genuinely unconstrained.

### Batch reporting

`batch_report.py` generates a report for every recording in a folder, naming each
PDF after its recording:

```powershell
.\.venv\Scripts\python.exe batch_report.py sample_data --jobs 2
```

`sample_dataRT.edf` becomes `reports\sample_dataRT.pdf`. Options mirror the
single-run flags: `--ai`, `--llm`, `--segment`, `--max-seconds`, `--no-sleep`, and
`--out` for a different output folder.

Each recording runs as its own `study_runner.py` process, exactly as the study
browser does, so one failure cannot take the batch with it and every run leaves an
options file that reproduces it alone. Failures are collected into
`batch_failures.log` with their full output rather than scrolling past. `--jobs`
runs several at once - each loads its own TensorFlow and uses several cores, so
2-3 is usually the most that helps.

### Spike and seizure detections, scored against SCORE

`spikeseizure.py` maps the Compumedics SpikeAndSeizure detector's output onto
SCORE terms: spikes onto the **Interictal Findings** page as epileptiform
interictal activity (section 8, Table 5), and electrographic seizures onto a new
**Episodes** page (section 10, Table 9).

The detector is not part of this project. Detections reach the mapper from either:

- **`EventStruct` records** from the cleared detector, once `CEventDetection` is
  available as an extension — carrying `vnDetections` (channel indices) and
  `Spike.fValue` per channel, so both the location and its maximum are exact;
- **a study already processed by the detector inside ProfusionEEG**, whose spike
  events `cmpeeg` reads back. Their channel labels survive in the event text,
  which is the only reason that route works at all.

With neither present the report simply has no epileptiform findings, which is the
honest outcome — nothing else in this pipeline detects them.

Two properties of `EventStruct` bound what can be reported, and both are stated on
the page:

**Morphology is not inferred.** SCORE separates `Spike` from `Sharp-wave` and
`Spike-and-slow-wave` by duration and shape. `nStart`/`nEnd` are *segment*
boundaries — `EventDetection.cpp` derives `nStart` from `m_nStartSamplePage` plus a
multiple of the half-segment length — so the detection duration says nothing about
the graphoelement. The subtype is left for the reader.

**A location maximum is only claimed when something discriminates.** Spike
amplitudes decide it where the detector supplies them, otherwise how often each
electrode was implicated — and where every electrode ties, no maximum is named at
all rather than picking one arbitrarily.

Incidence is banded over the duration the **detector** examined, which is the whole
loaded recording, not the epoch-screened duration the background analysis keeps.
Those differ by about half on the demo study, and using the smaller one inflates
every band.

Seizures are scored as electrographic only. Semiology, ILAE seizure type, the
evolution of the ictal pattern and the clinical–EEG relationship all need the video
and the clinical record, so the Episodes page lists them as outstanding — an
episode detected electrographically is not by itself an epileptic seizure.

### Interictal findings, scored against SCORE

`interictal.py` converts the focal slowing, diffuse slowing and band ratios the
pipeline has always computed into SCORE's *Interictal findings* folder
(section 8, Table 5, abnormal interictal rhythmic activity), and the PDF gains an
**Interictal Findings** page.

| Existing analysis | SCORE term |
| --- | --- |
| Diffuse slowing / slow-wave ratio | `Delta activity` or `Theta activity`, diffuse |
| Focal slowing / left-right asymmetry | `Delta activity` or `Theta activity`, lateralised |
| Excess beta / beta ratio | `Beta activity`, diffuse |
| Bad-electrode list | `Other artifact (electrode artifact)`, in the artifacts folder |

The band ratios themselves are **not** findings - they are the measurement a
finding rests on, so they are carried as its basis rather than reported as though
a percentage were a diagnosis. They remain on the findings page unchanged.

**Everything is computed per epoch and reported with a prevalence band.** The
original analysis averaged the whole record into one number, which cannot
distinguish intermittent slowing (usually functional) from continuous slowing
(usually structural) - the distinction a reader acts on. On `Demo.eeg` the diffuse
slowing scores `Continuous (>90%)`, the left-sided delta excess `Abundant (50-89%)`.

**Focal findings must actually be lateralised.** Each side is scored as its own
entry, as SCORE requires for a graphoelement seen independently in two locations,
and a side is only reported if it is sustained (>=20% of epochs) and clearly
dominates the other (1.5x). Without that test an asymmetry that flips between
hemispheres epoch to epoch yields electrodes on both sides in one finding, which
renders as "diffuse" - a restatement of the diffuse finding rather than a focal
one. On the PhysioNet EDF, where the excess alternates at 53% versus 53%, nothing
is reported and the reason is printed.

**Mode of appearance** (SCORE Table 6: random, periodic, variable) is scored by
comparing the intervals between occurrences against the intervals expected if the
same number were scattered at random over the same epochs - a permutation test
against each recording's own null. More regular than chance scores `Periodic`,
less regular scores `Variable`, and anything between scores `Random`; a finding
covering over 90% of epochs has no recurrence to characterise and scores
continuous instead. The median interval is reported alongside, which SCORE records
for periodic graphoelements.

A fixed threshold cannot do this job. Simulation shows the interval coefficient of
variation expected by chance runs from about 0.44 at 50% occurrence density to
0.85 at 5%, so any constant would call dense random activity periodic and sparse
regular activity random. The permutation test removes the constant, and 400
placements at a fixed seed keep a report reproducible.

Occurrences are grouped **on the clock, not by epoch index**. `extractAlphaEpochs`
sorts epochs by their alpha anterior-posterior ratio and drops artifact epochs
first, so epoch index is neither time order nor evenly spaced - two epochs adjacent
by index can be minutes apart. The original onsets survive in the events array and
every interval is measured from them.

Epileptiform activity is not detected at all and remains entirely the reader's -
these are rhythmic-activity abnormalities only.

Thresholds are the pipeline's own existing criteria (0.5 asymmetry, the 60% slow
and 30% beta benchmarks already printed on the findings page), so the clinical
behaviour is unchanged - only the vocabulary it is reported in. They remain
uncalibrated against expert scoring.

### Sleep staging and sleep graphoelements

`sleepstage.py` fills SCORE's *Sleep and drowsiness* folder (section 7) — which
stages were reached, time to the first non-wake epoch, per-stage timings, and sleep
spindles — and the PDF gains a **Sleep and Drowsiness** page.

Two backends, answering different questions:

| Backend | Role |
| --- | --- |
| **U-Sleep** | Staging. Fully convolutional network (Perslev et al.), using the published NSRR checkpoints that ship with [SLEEPYLAND](https://github.com/biomedical-signal-processing/sleepyland) |
| **YASA** | Graphoelements — spindles and slow waves — plus a fallback stager |

**Verified:** the U-Sleep integration scores **86.5% agreement with an expert
hypnogram** across 1364 epochs of an 11-hour reference PSG, at or above U-Sleep's
published level. Per-stage recall: N2 96.6%, REM 92.0%, W 83.2%, N1 50.5%. YASA's
spindle detector was validated by injection — 0 false positives on a recording with
no sigma peak, ~85% recall of 30 injected 13 Hz spindles, recovering 13.0 Hz.

Staging runs at the same point as artifact classification, before the pipeline
resamples and drops channels, because U-Sleep wants a central derivation against the
contralateral mastoid (**C4-A2** / **C3-A1**) at the native sample rate — and A1/A2
are about to be dropped. Where no mastoid exists it falls back to a bare central
electrode and says so, since that is off-distribution for the model.

Set `stageSleep=False` to skip it, or `sleepBackend='yasa'`. In the study browser:
**Stage sleep and detect spindles**, with a **Sleep stager** dropdown.

#### Caveats that matter

Both backends were built for overnight polysomnography. A routine EEG is 20–30
minutes of a mostly awake patient with no EOG and no chin EMG, so this is applied
out of distribution — fine for answering SCORE's question (was sleep reached, which
stages), but individual epochs, and REM especially, deserve caution. Recordings
under 5 minutes are reported with an explicit warning rather than at face value,
because U-Sleep evaluates them inside a 35-epoch window padded with zeros.

K-complexes are reported **provisionally**: they come from YASA's slow-wave detector
restricted to staged N2/N3, which is a proxy rather than a K-complex detector. Vertex
waves, saw-tooth waves, POSTS and hypnagogic hypersynchrony are not detected and are
listed as outstanding for the reader.

#### Getting the checkpoints

`sleepstage.py` looks for a U-Sleep `.h5` in, in order: `$USLEEP_MODEL_DIR`,
`models/usleep/`, then `$SLEEPYLAND_DIR/usleepyland/model/`. The architecture is
vendored at [vendor/usleep_model.py](vendor/usleep_model.py) — kept as a faithful
copy of uSLEEPYLAND's `utime/models/usleep.py` because the checkpoints are
weights-only, so the architecture must match exactly.

**Licensing, unresolved:** SLEEPYLAND and uSLEEPYLAND are MIT (© 2024 Luigi
Fiorillo), and the U-Sleep architecture is Perslev et al. But the checkpoints are
trained on NSRR data, whose Data Use Agreement has not been reviewed for
redistribution in a commercial product. `models/usleep/` is therefore gitignored —
resolve that before shipping anything that bundles these weights. YASA carries no
such question: BSD-3, on PyPI, with its own weights.

### Artifact types, scored against SCORE

`artifacts.py` names the artifact types present using SCORE's vocabulary
(Table 15), and the PDF gains an **EEG Artifacts** page giving each one a type, a
location, and how much of the recording it covers. `score_common.py` holds the
shared SCORE machinery both this and future modules need: the mapping from
electrodes to laterality × region with a location maximum, and the incidence and
prevalence bands from SCORE's Table 6.

Detected: 50/60 Hz mains, electrode pops, flat or disconnected electrodes, salt
bridges, eye blinks, horizontal eye movements, ECG and pulse artifact, EMG,
chewing, sweat, movement, and respiration (only where a respiration channel
confirms it).

Not detected, and left for the reader: nystagmus, sucking, glossokinetic, rocking
or patting, dialysis, artificial ventilation and induction — these need clinical
context or are not separable from the signal alone. **Significance is never
proposed.** SCORE scores an artifact's effect on the recording separately — not
interpretable, reduced diagnostic value, or does not interfere — and that is a
clinical judgement.

Classification runs on the recording **as loaded**, inside `getRawData` before the
pipeline filters, re-references, resamples and drops channels. Several of these
artifacts are invisible afterwards: sweat lives below 0.5 Hz, mains sits above the
resampled Nyquist, and ECG detection needs the ECG channel. Set
`classifyArtifacts=False` on `eegProcess` to skip it; it costs well under a second.

Detectors are deterministic and physically motivated rather than learned, so a
finding can be explained and points at a time and a set of electrodes — which an
ICA component label cannot. Amplitude-based tests are relative to the recording's
own baseline, because absolute microvolt thresholds depend on the reference and
the acquisition gain.

### Posterior dominant rhythm, scored against SCORE

`pdr.py` scores the posterior dominant rhythm on all nine properties SCORE
defines for it (Beniczky et al., *Clin Neurophysiol* 2017;128:2334–2346, Table 4),
and the PDF gains a **Posterior Dominant Rhythm** page listing each one with the
measurement behind it and a confidence:

| Property | How it is derived |
| --- | --- |
| Significance | Frequency against an **age-dependent** normal floor, plus symmetry and reactivity |
| Frequency | The model ensemble, cross-checked against the posterior spectral peak |
| Frequency asymmetry | Difference of the per-hemisphere estimates; symmetrical within 0.5 Hz |
| Amplitude | Median peak-to-peak in a band centred on the measured rhythm; SCORE bands at 20 and 70 µV |
| Amplitude asymmetry | Relative difference of left and right posterior amplitude |
| Reactivity to eye opening | Posterior band-power drop on eye opening, per side — needs eye-state annotations |
| Organization | **Provisional**: rhythm continuity and spectral concentration |
| Caveat | Eyes never closed, sleep deprivation, or drowsiness where separable |
| Absence of PDR | Only when no posterior rhythm is found, with the reason |

Two behaviours are deliberate. A property the recording cannot answer is scored
`Not possible to determine` — SCORE's own active choice — rather than guessed:
without a date of birth there is no significance, and without marked eye opening
there is no reactivity.

Reactivity can be unlocked on unmarked recordings with **Infer eye state from the
signal** in the study browser (`--auto-eye-state` on the command line, `autoEyeState`
in an options file). It is off by default because it is not trustworthy yet: on a
continuously eyes-closed test recording it split the record into two states and
reported reduced left-sided reactivity that was not there, since posterior alpha
waxes and wanes severalfold under continuous eye closure and frontal slow activity
is not specific enough to blinks to rule that out. A false reduced reactivity drives
the significance of the whole PDR to abnormal, so treat any reactivity it produces as
unconfirmed. Marking eye opening and closure at acquisition is the reliable route. And properties resting on uncalibrated thresholds are
marked provisional in the report, because the numeric thresholds in `pdr.py` are
conventional values, not values validated against expert scoring. They are
gathered in one block at the top of that file for exactly that reason.

**Age** drives the significance of the PDR, whose normal lower limit rises through
childhood — a fixed adult threshold reports every young child as abnormally slow.
Age is resolved from, in order: an explicit `patientAge`; an explicit
`patientDob` with the recording date; the study's own `EEG4PatientInfo.xml`. The
study browser passes the date of birth from `_CMPStudyList.mdb`, which holds it as
a real date — the study's own copy is numeric with no day/month marker, so it is
read month-first and flagged in the report for confirmation.

### Native ProfusionEEG studies

A ProfusionEEG study is a `*.eeg` **folder** (containing `*.sdy`, `EEGData/`, and so
on), not a single file. Pass the folder itself:

```bash
python report.py "C:\Studies\Demo.eeg" --pdf --out ./reports
```

Signal access goes through Compumedics' own `cmpeeg` Python extension, which wraps
the same `CMEEGStudyV4` COM component ProfusionEEG itself uses, so the study format
stays the single source of truth. Studies are opened read-only. `profusion.py` holds
the reader; `readStudyMetadata()` there reports a study's montage and sample rate
straight from its `.sdy` XML, which needs no SDK and is useful for checking a study
before a full run.

Two options apply only to this format:

- `--segment {longest,concat}`: a study may contain gaps where data packets were
  lost, and a read must never cross one. `longest` (the default) analyses the
  single biggest gap-free block; `concat` joins every recorded block end-to-end,
  which recovers more signal from a fragmented study at the cost of a
  discontinuity at each join. Each join is annotated `BAD_segment_join` so epoch
  rejection drops any epoch straddling it.
- `--max-seconds <n>`: cap how much signal is loaded, for long overnight studies.

ProfusionEEG events (spikes, photic, bookmarks, and so on) are carried across as MNE
annotations.

### Report review front end

`Start-StudyBrowser.ps1` and `batch_report.py` run the whole analysis unattended
and write a document. The review front end does the other thing: it runs the
analysis once, shows every finding with where it came from, and produces the
document only after a reader has accepted, overridden or excluded what is in it.

```powershell
.\Start-ReportUI.ps1
.\Start-ReportUI.ps1 -Study 'C:\Studies\Patient.eeg'
```

The study browser opens it too, through **Review in report UI...**, which hands
over the selected study.

It is a local web page served by `report_server.py` on the loopback address.
Nothing leaves the machine and the page loads no script from any network, so it
works offline. Ported from the Claude Design prototype in
`Dark theme and first pass screens/`, which rendered through a design-compiler
runtime that pulls React, ReactDOM and Babel from unpkg at load - right for a
design preview, wrong for a clinical tool that must draw a screen with the
network down. The palette is that design's, verbatim, in both themes.

#### Provenance

The point of the front end, and the reason it is worth having at all: every
value shows where it came from, and the mark is declared per field from what the
analysis actually did rather than guessed from the wording of a basis string.

| Mark | Meaning |
| --- | --- |
| **Measured** | A deterministic measurement of the signal. The same recording gives the same number. |
| **Model - unverified** | The output of a trained model. Reproducible, but wrong in ways the number does not show. |
| **Human-scored** | Entered or overridden by the electroencephalographer. |
| **Not scored** | Not scored, or not possible to determine. SCORE separates this from a negative finding, and so does this. |

Each is a different shape as well as a different colour, so the distinction
survives greyscale and colour-vision deficiency.

The PDR frequency pair is marked *model* because it comes from the
CNN/GoogleNet/ResNet ensemble, however confident it reads; the other seven
properties are measured. Sleep staging and spike/seizure detections are model
output. Diagnostic significance and the conclusion are human-scored and nothing
in the analysis writes them.

An override changes the mark to *human*, because it is now a human's value. The
measurement is kept beside it and the document names what was changed:

```
Frequency  9.5 Hz  high  9.2
  overridden by the reader; measured 9.2 Hz (model ensemble, left 9.2 / right 9.2 Hz)
...
Overridden by the reader
  frequency: reported as 9.5 Hz; measured 9.2 Hz
```

Without that the report would state 9.5 Hz on the PDR page and 9.2 Hz on the
measurement page with nothing to explain the difference.

#### Refusing to overreach

The diagnostic-yield picker offers SCORE's whole list and disables what this
analysis cannot argue, with the reason beside it:

```
Epilepsy                                    Unavailable   needs epileptiform findings, and none were detected
Status epilepticus                          Unavailable   needs ictal pattern detection, which is not implemented
Focal dysfunction of the central nervous..  Select
Diffuse dysfunction of the central nerv..   Select
Coma                                        Unavailable   needs the clinical state, which the signal alone does not give
```

Hiding them would teach a reader nothing. Supportability is recomputed from the
findings actually present - once the spike and seizure detector supplies
epileptiform findings, `Epilepsy` becomes available, because the reason for
withholding it no longer holds.

Empty sections say which kind of empty they are. *Not analysed* and *analysed,
nothing found* are different clinical answers and the screen never blurs them.

#### Two artefacts

Generation writes the report document and, beside it,
`<study>.score.json` - the same report as structured data, carrying every
value's provenance and the reader's overrides.

#### What it does not do yet

- The document is the existing PDF. The brief asks for a **.docx** from a Word
  template; that is not built.
- Drafts are not saved. A session lives in the server's memory: a reload keeps
  it (the session is in the URL) but restarting the server loses it.
- **Add finding (human-scored)** on Interictal, and the per-episode semiology
  and ILAE fields, are shown as the reader's to supply but are not editable
  here - the Episodes page lists them and leaves them blank.
- UI strings are not externalised, so the language selector the brief describes
  is absent rather than present-and-disabled.
- Jump-to-time back into the Profusion waveform view needs the host
  application and does nothing standalone.

#### Study browser (GUI)

A folder of ProfusionEEG studies carries a `_CMPStudyList.mdb` index at its root.
`study_browser.py` reads it, lists the studies, and generates a report for the one
you pick:

```powershell
.\Start-StudyBrowser.ps1 "C:\Studies"
```

`Start-StudyBrowser.ps1` uses the project's own virtual environment and resolves
paths from its own location, so it works from any prompt and can be pinned to a
shortcut. The folder argument is optional. Equivalent without the script:

```powershell
.\.venv\Scripts\python.exe study_browser.py "C:\Studies"
```

The folder argument is optional — the browser remembers the last one used, and has a
Browse button. The study table shows recording date, patient name, date of birth,
sex, duration, sample rate and whether the montage carries all 19 required
electrodes, so an unusable study is visible before anything is run. Every report
option is settable in the window: output folder, PDF, LLM report with language and
model, data-segment handling, load cap, analysis start/end, artifact repair, the
epoch-drop threshold, the bad-electrode ratio, and channel-name mapping.

Reports are generated by spawning `study_runner.py` as a subprocess, so the window
stays responsive, the log streams live, and Cancel actually stops the work. Each run
writes its options next to the report as `<study>_options.json`, which re-runs the
same analysis on its own:

```bash
python study_runner.py reports/Demo_options.json
```

Reading `_CMPStudyList.mdb` needs the **64-bit** Microsoft Access ODBC driver
(*Microsoft Access Database Engine*) and `pyodbc`. Without the driver the browser
falls back to listing `*.eeg` folders from disk and says so — you can still select
and run a study, just without the patient details the database holds.

#### Requirements

The `cmpeeg` extension is **not** installed by `pip` — it is built from
`ProfusionEEGSDK/PythonSDK/cmpeeg`, and `profusion.py` finds it automatically in that
project's `x64\Release` or `x64\Debug` output. Set `CMPEEG_PYD_DIR` to override the
location. Because it is a compiled extension talking to an in-process COM server, it
needs:

- **64-bit Python 3.12** — the same version the `.pyd` was built against.
- The **x64** `CMEEGStudyV4.dll` and `RawDataAccess.dll` from `ProfusionEEGSDK/x64/`
  registered with `regsvr32` from an elevated prompt. A ProfusionEEG application
  install registers only the 32-bit build of these, which an x64 Python cannot load
  in-process; the x64 registration lives in a separate registry view and does not
  disturb it. Note that registration records the **absolute path** of the DLL, so
  moving this checkout means re-running `regsvr32` from the new location.

See `ProfusionEEGSDK/PythonSDK/README.md` for the full build and registration
procedure. That document assumes a stand-alone Python at
`C:\Program Files\Python312\`; to build against this project's `.venv` instead,
`.py312root/` in the project root is a junction tree laying out the headers, import
library and pybind11 includes where `cmpeeg.vcxproj` expects them:

```powershell
$env:PYTHON312_64_ROOT = "<project>\.py312root"
& "<vs>\MSBuild\Current\Bin\amd64\MSBuild.exe" `
    ProfusionEEGSDK\PythonSDK\cmpeeg\cmpeeg\cmpeeg.sln `
    /p:Configuration=Release /p:Platform=x64 /t:Rebuild
```


### Required EEG Channels

The system requires the following 10-20 system electrodes (or equivalent mapped channels):
- Fp1, Fp2
- F7, F8, F3, F4, Fz
- C3, C4, Cz
- P3, P4, Pz
- T3, T4, T5, T6
- O1, O2

## You can get following datasets from the following links and use them to test the code.

### SPIS Dataset (MAT format)
Open-source resting-state EEG data:
- [SPIS Dataset Repository](https://github.com/mastaneht/SPIS-Resting-State-Dataset/tree/master/Pre-SART%20EEG)

### Temple University Hospital (TUH) EEG Dataset (EDF format)
Large clinical EEG database:
- [TUH EEG Dataset](https://isip.piconepress.com/projects/tuh_eeg/)

### Command Parameters

```bash
python report.py <eeg_file> [options]
```

#### Required Parameters
- `eeg_file`: Path to the input EEG data file (EDF, FIF, or MAT format), or to a
  native ProfusionEEG study folder (`*.eeg`)

#### Optional Parameters
- `--pdf`: Generate output in PDF format
- `--out <directory>`: Specify output directory for generated reports (default: current directory)
- `--ai`: Enable automated report generation using Large Language Models (LLMs)
  - Uses configured LLM APIs (Google PaLM, Anthropic Claude, OpenAI) for report generation
  - Requires valid API keys in config.env
- `--lang <language>`: Specify report language
  - Default: "english"
  - Supports any language available in the configured LLM models
  - Common options: English, Chinese (Simplified/Traditional), Japanese, Korean, Spanish, French, German, etc.
  - Language support depends on the capabilities of the configured LLM models
- `--llm <model>`: Specify LLM model for report generation
  - Default: "gemini-1.5-pro" 
  - Suggestions: "gemini-1.5-pro", "claude-3-5-sonnet-20240620", "gpt-4o"
- `--segment {longest,concat}`: ProfusionEEG studies only — which data segments to
  analyse (default: `longest`). See *Native ProfusionEEG studies* above.
- `--max-seconds <n>`: ProfusionEEG studies only — cap how much signal is loaded.
- `--auto-eye-state`: infer eyes-open/eyes-closed periods from the signal where the
  recording carries no eye-state annotations, so PDR reactivity can be scored. Off
  by default — see *Posterior dominant rhythm* above for why.

### Example Commands

```bash
# Basic usage with SPIS dataset (MAT format)
python report.py ./SPIS_dataset/S04_restingPre_EC.mat \
    --pdf \            # Generate PDF report
    --out ./pdf \      # Save to ./pdf directory
    --ai \             # Enable LLM report generation
    --lang "english"   # Generate report in English
    --llm "gemini-1.5-pro" # Use Google Gemini LLM model

# Generate report in Traditional Chinese
python report.py ./recordings/patient001.edf \
    --pdf \
    --out ./reports \
    --ai \
    --lang "traditional chinese"
    --llm "gpt-4o"

# Generate report in Japanese
python report.py ./recordings/patient002.edf \
    --pdf \
    --out ./reports \
    --ai \
    --lang "japanese"
    --llm "claude-3-5-sonnet-20240620"
```

### Note on Language Support

The `--lang` parameter accepts languages supported by the configured LLM models. Language availability and quality may vary depending on the specific LLM model being used. Please refer to the documentation of your configured LLM providers (Google Gemini, Anthropic Claude, OpenAI) for detailed language support information.
The '--llm' parameter specifies the LLM model to be used for report generation. The default model is "gemini-1.5-pro". Latest models can be found on the respective LLM provider websites.


## Code Attribution

The `eegFeatureExtract.py` module is adapted from:
> S. Saba-Sadiya, et al. "Unsupervised EEG artifact detection and correction," Frontiers in Digital Health, vol. 2, 2021. 
> [Original Repository](https://github.com/sari-saba-sadiya/EEGExtract)

## Citation

If you use this code in your research, please cite:

```bibtex
@ARTICLE{10752384,
  author={Tung, Chin-Sung and Liang, Sheng-Fu and Chang, Shu-Feng and Young, Chung-Ping},
  journal={IEEE Journal of Biomedical and Health Informatics}, 
  title={A Hybrid Artificial Intelligence System for Automated EEG Background Analysis and Report Generation}, 
  year={2025},
  volume={29},
  number={4},
  pages={2629-2641},
  keywords={Deep learning;Accuracy;Hospitals;Large language models;Predictive models;Brain modeling;Electroencephalography;Hybrid power systems;Signal analysis;Root mean square;Artificial intelligence;deep learning;electroencephalography (EEG);large language models;report generation},
  doi={10.1109/JBHI.2024.3496996}}
```
