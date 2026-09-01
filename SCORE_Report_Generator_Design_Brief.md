# Design brief — SCORE Report Generator (Profusion EEG)

Prepared for Claude Design. Proof of concept, September 2026.
Notes marked **Undecided** are places the requirements are genuinely unsettled — they are flagged rather than guessed. Do not resolve them silently; draw the safest option and mark it.

---

## 1. PRODUCT

A report-authoring panel that docks inside Profusion EEG and produces a SCORE-compatible clinical EEG report. Profusion EEG is Compumedics' application for recording, reviewing and reporting clinical EEG — routine studies and long-term monitoring — and it already holds the waveform data, the technologist's annotations, and the output of automatic detectors such as spike-and-seizure. This panel reads that study through the ProfusionEEG SDK, runs or collects the analyses a SCORE report needs, lets the author include or exclude sections and individual events, gathers by hand the findings no algorithm can supply, and emits two artefacts: a Word document the author may edit further, and a structured SCORE data file. It serves clinical neurophysiology technologists and neurologists in hospital EEG departments and sleep/neurology labs — Australia and the United States first — working at a review workstation, usually in a dim reading room, alongside the waveform view. The report standard is *Standardized computer-based organized reporting of EEG: SCORE — Second version* (Beniczky et al., Clin Neurophysiol 2017;128:2334–2346).

This proof of concept is shown to distributors and users. The one question it must answer: **is the auto-generated content good enough that a neurologist would sign it, and is the process of getting there worth using?**

## 2. THE JOB

**Turn a reviewed EEG study into a signed-off-able SCORE report without leaving Profusion.**

One person, one sitting (resumable): open the study's report, confirm what the software measured, fill in what only a human can score, exclude what does not belong, and produce a Word document they would put their name to. They are done when the document exists and nothing they disagreed with is in it.

The design succeeds or fails on one thing: at every point the author must be able to see, without clicking, **where each statement came from** — measured from the signal, proposed by a model, or scored by a human. Treat provenance as a first-class visual system, not a disclaimer banner. A report that looks uniformly authoritative will demo well and mislead, which is the opposite of what this proof of concept is for.

## 3. SCREENS

Routes are hash routes inside the WebView2 panel. The panel is a single-page app; the section rail persists across all `#/section/*` routes.

| # | Screen | Route | Its one job | Key elements |
|---|---|---|---|---|
| 1 | **Report Home** | `#/report` | Start a new report or resume the saved draft for the open study | Study identity strip (patient, DOB, recording date, duration, montage); draft status and last-saved time; SCORE section list with per-section completeness and include/exclude toggles; count of outstanding items; primary action **Generate**; secondary **Run analyses** |
| 2 | **Analyses** | `#/analysis` | Show which analyses have results and run the ones that don't | Per-analysis row: name, source (acquisition-time vs report-time), last run, result state; **Run** / **Re-run** per row and **Run all**; progress with elapsed time and cancel; per-row failure with reason and retry |
| 3 | **Patient & Recording Conditions** | `#/section/recording` | Confirm the facts the study already knows, and supply the ones it doesn't | Pre-filled editable fields (name, sex, DOB, age at recording, date/time, sample rates, sensor group, filters, device, montage); the duration accountant — recorded / loaded / analysed after artifact rejection; empty-but-required fields (alertness and cooperation, time of last meal, skull defect) marked as human-entry |
| 4 | **Posterior Dominant Rhythm** | `#/section/pdr` | Review the nine scored PDR properties and accept or override each | One row per SCORE Table 4 property: scored value, the measurement behind it, confidence, provenance mark; `Not possible to determine` shown as a deliberate value, not a blank; provisional properties visibly flagged; override control per row |
| 5 | **Interictal Findings** | `#/section/interictal` | Choose which rhythmic-activity findings go in the report | Finding cards with SCORE term, location (laterality × region, location maximum), prevalence/incidence band and the basis measurement, mode of appearance; include/exclude per finding; **Add finding** for human-scored entries; link to Events |
| 6 | **Episodes** | `#/section/episodes` | Select detected electrographic events and score what the signal cannot say | Detected episode list with time, duration band, location; include/exclude; per-episode outstanding fields (semiology, ILAE type, ictal evolution, clinical–EEG relationship) as human-entry; jump-to-time link back into Profusion |
| 7 | **Sleep & Drowsiness** | `#/section/sleep` | Report which stages were reached and which graphoelements were seen | Stage summary and time to first non-wake epoch; spindles; K-complexes marked provisional; not-detected items (vertex waves, POSTS, hypnagogic hypersynchrony) listed as outstanding |
| 8 | **Artifacts** | `#/section/artifacts` | Name the artifact types present and let a human judge their significance | Artifact rows with type, location, coverage; significance left empty as an explicit human judgement (not interpretable / reduced diagnostic value / does not interfere) |
| 9 | **Events** | `#/events` | Pick individual study events to carry into the report | Event table from the study (type, time, channels, duration) with filter and multi-select; selection count; jump-to-time link back into the Profusion waveform view |
| 10 | **Diagnostic Significance & Conclusion** | `#/section/conclusion` | Score the conclusion — the one thing the software must not decide | Forced-choice category (normal / abnormal / no definite abnormality); diagnostic-yield picker restricted to SCORE's list; yields the analysis cannot support shown **disabled with the reason**, never hidden; AI-drafted summary and clinical comments in an editable field, visibly marked as unverified draft with edited/unedited state; human sign-off block |
| 11 | **Outstanding Items** | `#/outstanding` | One list of everything unanswered across all sections | Grouped by section, each row linking to the field that needs it; distinguishes *required for a complete SCORE report* from *optional*; count mirrors the badge on Report Home |
| 12 | **Generate** | `#/generate` | Produce the Word document and the structured data | Included-sections summary; Word template picker; output location (inside the study folder); document preview; **Generate**; success state naming both files with an open-containing-folder action |
| 13 | **Settings** | `#/settings` | Manage templates and analysis defaults | Word template list with add/replace; default output location; analysis defaults; language selector present but English-only, shown disabled |

**Undecided — screen scope.** "I want the entire SCORE" and "at this stage I just want proof of concept" were not reconciled. This brief covers the eight sections the existing pipeline can populate plus the human-entry items around them. The full SCORE hierarchical terminology — the complete branching tree for every graphoelement subtype — is **not** designed here. If the demo must show the full tree, that is a further screen family and a separate brief.

**Undecided — the neurologist's path.** The stated review flow is that a technologist generates the document and the neurologist reviews the *Word file*. That means the neurologist may never open this app, and screen 10 may have no user. Screens are drawn for a single author who may be either role. If an in-app review-and-approve path is wanted, it does not yet exist as a requirement.

## 4. STATES

Draw these. Everything else may be implied.

- **Report Home** — first-run (no draft: "no report yet for this study"); resumed draft; **stale draft** (study changed since the draft was saved — annotations added or an analysis re-run); error (study cannot be read through the SDK).
- **Analyses** — empty (nothing run yet); running (per-row progress, elapsed, cancel); mixed (some acquisition-time results present, some report-time analyses not yet run); error (one analysis failed, others succeeded — a failure must not blank the screen).
- **Patient & Recording Conditions** — loaded-and-prefilled; partially empty (fields the study does not carry); error (metadata unreadable). No true empty state: the study always supplies something.
- **PDR / Interictal / Episodes / Sleep / Artifacts** — **not yet analysed** (distinct from "analysed, nothing found"); **analysed, no findings** — this is a valid clinical result and must read as one, not as failure; populated; section disabled by the author; analysis failed.
- **Events** — empty (study has no events); populated with nothing selected; populated with a selection; filtered to zero results.
- **Conclusion** — empty (nothing scored); AI draft present and unedited; AI draft edited by a human; unsupportable yields disabled with reasons visible.
- **Outstanding Items** — none outstanding (a genuine success state, design it as one); many outstanding.
- **Generate** — blocked (required sections incomplete — say which); ready; generating; success; failed (template invalid, or output location not writable).

**Undecided — analysis duration.** No wall-clock figures were given for a routine 20-minute EEG versus a 72-hour LTM study. The progress state must therefore work at both ends: a determinate bar where progress is known, elapsed time and cancel where it is not, and no modal that traps the user for an unknown period. Assume the panel stays usable while analyses run.

**Undecided — stale-draft behaviour.** That the state exists is certain; what it should do — warn, offer refresh, refresh silently — is not decided. Draw the warning, and a **Refresh from study** action. Do not draw silent refresh.

## 5. VOICE AND BRAND

**Must feel:** precise, quiet, accountable.

**Must never feel:** persuasive, decorative, clever.

Specifically: no marketing tone, no encouragement, no celebration on completion. Empty states state a fact and the next action; they do not reassure. Uncertainty is stated plainly — "Not possible to determine" is a result, not an apology. Where the software refuses to propose something, the refusal and its reason are shown to the reader, not hidden.

## 6. VISUAL DIRECTION

**Propose a palette and type system.** No Compumedics style guide, screenshot or component set was supplied. Constraints it must satisfy:

- It sits inside Profusion EEG as a docked panel. It must read as part of the host application, not as an embedded website. Restrained neutrals; no brand colour used decoratively.
- Support **dark and light**, with dark as the design default — EEG reading rooms are dim and the adjacent waveform view is high-contrast. Do not let the panel become the brightest object on the screen.
- **Provenance is the one place colour and form do real work.** Three states must be distinguishable at a glance and from each other: *measured from the signal*, *model-proposed (unverified)*, *human-scored*. Plus a fourth modifier, *provisional* — a measured value resting on an uncalibrated threshold. Encode these with shape, label and position as well as colour, so they survive greyscale printing and colour-vision deficiency. Never colour alone.
- Dense tabular data at small sizes: a type stack with real tabular figures, and a numeric style that keeps µV, Hz, percentages and time bands scannable in a column.
- The section rail must survive a narrow dock — icon-plus-label at wide widths, degrading to something legible at 420 px without becoming a mystery-icon strip.

## 7. NON-NEGOTIABLES

- **Currency:** none. This product handles no money, no pricing and no transactions. Draw no currency anywhere.
- **Locale and language:** English only for the proof of concept, en-AU and en-US. All UI strings must be externalised so language support can be added later — no text baked into images or icons, and layouts that tolerate roughly 30% string growth.
- **Dates and time:** unambiguous formats only. Day-month-year with an alphabetic month (`01 Sep 2026`), or ISO 8601. 24-hour clock. Never `01/09/2026`, which reads as two different dates in the two launch markets.
- **Units:** SI. µV, Hz, seconds. SCORE's own banded vocabulary (incidence, prevalence, duration, amplitude) is used verbatim wherever SCORE defines a band — do not paraphrase the band labels.
- **Accessibility:** WCAG 2.1 AA contrast in both themes; full keyboard operability with a visible focus ring; no information carried by colour alone; hit targets usable with a trackpad in a dim room. Screen-reader semantics on all data tables.
- **Minimum viewport:** usable at **420 px wide**, comfortable at 640, full layout above 900, and correct when the panel is maximised to full window. Height: assume 700 px minimum, and expect a tall narrow dock.
- **Legal text:** a persistent, non-dismissible label marking this build as a proof of concept not for diagnostic use, and a per-item marking of model-generated content as an unverified proposal. **Undecided:** the exact wording, and the regulatory framing (AU/US only, or EU MDR as well), were not settled. Draw the label with placeholder wording and leave room for it to be twice as long.

## 8. OUT OF SCOPE

Do not draw:

- Any waveform viewer or EEG signal rendering. The panel links back into Profusion's own viewer; it never displays traces.
- Annotation editing. Events are selected, never created or modified here.
- User accounts, roles, or permissions.
- Electronic signature, 21 CFR Part 11 audit trails, or report version history.
- PACS, HL7, DICOM or EMR export.
- Any printing pipeline beyond producing the .docx.
- Re-import of an edited Word document. Generation is strictly one-way.
- LLM provider configuration, API keys, or model selection UI.
- Multi-study, cohort, or worklist views. The panel is scoped to the one study open in Profusion.
- A Word template *designer*. The app consumes a template; it does not build one.

## 9. DELIVERABLE

**Artboards.** One per screen at **1024 px wide** (the comfortable full layout), plus a **420 px** narrow-dock variant of Report Home, the section rail, and one section screen, to prove the layout degrades honestly.

Screens 4–8 share one section layout. Draw **PDR (4)**, **Interictal (5)** and **Conclusion (10)** in full — they carry the demo's argument about provenance and about refusing to overreach. Draw **Sleep (7)** and **Artifacts (8)** as the shared pattern only. Draw every state named in §4 as its own artboard or as a clearly labelled variant; the states are the point of this brief, not an afterthought.

**Design tokens.** A single token block naming every value used, with nothing left implicit:

- **Colour** — background layers (at least: canvas, surface, raised); text (primary, secondary, disabled); border (subtle, strong); focus ring; the three provenance states plus *provisional*; status (success, warning, error, info); the SCORE band scale if bands are given any visual weight. Both themes, same token names.
- **Typeface** — family stack for UI and for tabular numerals; the full size scale with line heights; weights actually used.
- **Radius** — every step used.
- **Shadow / elevation** — every step used, and note which are suppressed in dark theme.
- **Spacing** — the base unit and the scale.

Tokens must be theme-swappable by value, not by name: one set of names, two sets of values.
