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

#### Study browser (GUI)

A folder of ProfusionEEG studies carries a `_CMPStudyList.mdb` index at its root.
`study_browser.py` reads it, lists the studies, and generates a report for the one
you pick:

```bash
python study_browser.py "C:\Studies"
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
