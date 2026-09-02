##############################################
#   The main file for the EEG report generation task.
#   This file contains the main class CreateReport, which is used to 
#   generate the EEG report based on the EEG data provided.
#   The class CreateReport has the following methods:
#   - __init__(): Initializes the CreateReport class.
#   - process(): Processes the EEG data and generates the raw data and results.
#   - getMeanAmplitudes(): Calculates the mean amplitudes of the EEG data.
#   - getFeatures(): Extracts features from the EEG data.
#   - checkFollowOrder(): Checks if the patient is able to follow commands.
#   - slow_score(): Calculates the slow wave scores for the EEG data.
#   - evaluate_alpha_amp(): Evaluates the alpha amplitude of the EEG data.
#   - symmetric_frequency_of_background(): Calculates the symmetric frequency 
#       of the background EEG data.
#   - focal_slow_conclusion(): Generates the conclusion for focal slow waves.
#   - eeg_quality_conclusion(): Generates the conclusion for EEG quality.
#   - background_conclusion(): Generates the conclusion for the background EEG data.
#   - genFinalResults(): Generates the final results of the EEG report.
#   - AI_generate(): Generates AI text based on the EEG data.
#   - AI_Text_generate(): Generates AI text for the EEG report.
#   The CreateReport class takes the following parameters:
#   - fileName: The name of the EEG file.
#   - filePath: The path to the EEG file.
#   - GOOGLE_API_KEY: The Google API key for AI text generation.
#   - dest_pdfPath: The destination path for the PDF report.
#   - autogenerate: A boolean value indicating whether to automatically generate the report.
#   - outputPdf: A boolean value indicating whether to output the report as a PDF.
#   - aiReport: A boolean value indicating whether to generate an AI report.
#   - reportLang: The language of the report.
#   - model_folder: The folder containing the AI models.
#   - model_names: The names of the AI models.
#   - useRepair: A boolean value indicating whether to use repair.
#   - removeEpochsRationThreshold: The threshold for removing epochs.
#   - dropEpochSD: The standard deviation for dropping epochs.
#   The CreateReport class returns the
#   raw data and results of the EEG data.
#   The CreateReport class also generates the EEG report
#   and AI text based on the EEG data.
##############################################

import numpy as np
import os
from scipy.integrate import simpson
from eeg import eegProcess
from models import predict
import google.generativeai as genai
import markdown
from bs4 import BeautifulSoup
import time
from createPDF import writePDF
import pdr as pdrScore
import profusion
import recording
import interictal
import spikeseizure
import score_common as sc
import json
import re
import prompt as pmt

from openai import OpenAI
import anthropic


os.environ['TF_CPP_MIN_LOG_LEVEL'] = '2'
os.environ['TF_ENABLE_ONEDNN_OPTS'] = '0'

# EDF+ headers carry a date-of-birth field, but exporters routinely blank it with
# a sentinel rather than leaving it empty. 1899-12-30 is the OLE/Delphi zero date
# and is what the sample recordings here all carry. Taking such a value at face
# value yields an age of about 125 years, which lands on the adult plateau of the
# PDR age table and therefore looks right - while being silently wrong on any
# child recorded by the same exporter. So the sentinels are rejected by name, and
# anything outside a plausible human age is rejected as well.
EDF_PLACEHOLDER_BIRTHDAYS = {(1899, 12, 30), (1900, 1, 1), (1970, 1, 1),
                             (1, 1, 1), (1904, 1, 1)}
PLAUSIBLE_AGE_YEARS = (0.0, 120.0)


def ageFromRecordingHeader(raw):
    """Age at recording from the file's own header, or (None, reason).

    Works for any format MNE fills subject_info for, which in practice means
    EDF+. Returns (ageYears, description).
    """
    if raw is None:
        return None, None
    info = (raw.info.get('subject_info') or {})
    birthday = info.get('birthday')
    measured = raw.info.get('meas_date')
    if birthday is None:
        return None, None
    if measured is None:
        return None, 'the recording header has a date of birth but no recording date'

    # MNE returns a date, or a (year, month, day) tuple on older versions.
    if isinstance(birthday, (tuple, list)) and len(birthday) == 3:
        parts = tuple(int(v) for v in birthday)
    else:
        parts = (birthday.year, birthday.month, birthday.day)

    if parts in EDF_PLACEHOLDER_BIRTHDAYS:
        return None, ('the recording header carries %04d-%02d-%02d as the date of '
                      'birth, which is a placeholder written by the exporter '
                      'rather than a real date' % parts)

    from datetime import datetime
    try:
        born = datetime(*parts)
    except ValueError:
        return None, 'the date of birth in the recording header is not a valid date'
    recorded = datetime(measured.year, measured.month, measured.day)
    age = (recorded - born).days / 365.2425
    if not PLAUSIBLE_AGE_YEARS[0] <= age <= PLAUSIBLE_AGE_YEARS[1]:
        return None, ('the recording header implies an age of %.0f years, which is '
                      'not plausible, so it was not used' % age)
    return age, 'the recording header'


def printConclusion(conclusion):
    """Log the proposed conclusion."""
    print('--- Diagnostic significance (SCORE) - PROPOSED, needs confirmation ---')
    print('  %-22s %s' % ('Category:', conclusion.get('category') or '(none proposed)'))
    for y in conclusion.get('yields') or []:
        print('  %-22s %s' % ('Yield:', y))
    for b in conclusion.get('basis') or []:
        print('  %-22s %s' % ('Basis:', b))
    print('  %-22s %s' % ('Confidence:', conclusion.get('confidence')))
    for note in conclusion.get('notes') or []:
        print('  NOTE: %s' % note)


class CreateReport:
    benchmark = {
        'DBS': 0, # DBS
        'FSlow': 0, # focal slow        
    }

    alphaEpochs=None
    def __init__(self, fileName, filePath, LLM_API_KEY='', dest_pdfPath='',  
                 autogenerate=True, outputPdf=False, aiReport=False, reportLang='English',
                 # '' or 'study' puts every output in the study's own folder.
                 llm_model='gemini-1.5-pro',
                 model_folder='./models/',
                 model_names=['CNN', 'GoogleNet','ResNet'], useRepair=True, unit_uV=True,
                 removeEpochsRationThreshold=0.3, dropEpochSD=2.2,
                 tmax=None, tmin=None, renameChannels=True,
                 profusionSegment='longest', profusionMaxSeconds=None,
                 patientDob=None, patientAge=None, autoEyeState=False,
                 stageSleep=True, sleepBackend='usleep', spikeDetections=None,
                 spikeTypeIds=None
                ):
        self.benchmark = {
            'DBS': 0, # DBS
            'FSlow': 0, # focal slow        
        }
        # if path not end with '\', or '/', add it
        if filePath[-1] not in ['\\', '/']:
            if '/' in filePath:
                filePath+='/'
            else:
                filePath += '\\'
        self.unit_uV=unit_uV
        self.eegFullName=filePath+fileName
        # Resolved here so every caller gets it: an empty destination, or
        # 'study', means the study's own folder. Doing it at this one point
        # covers the runner, the batch, the review front end and direct use.
        self.dest_pdfPath=profusion.resolveOutputFolder(dest_pdfPath,
                                                        self.eegFullName)
        self.model_folder=model_folder
        self.fileName=fileName
        self.filePath=filePath
        self.removeEpochsRationThreshold=removeEpochsRationThreshold
        self.model_names=model_names
        self.useRepair=useRepair
        self.results=None
        self.LLM_API_KEY=LLM_API_KEY
        self.llm_model=llm_model
        self.outputPdf=outputPdf
        self.dropEpochSD=dropEpochSD
        self.aiReport=aiReport
        self.reportLang=reportLang
        self.tmax=tmax
        self.tmin=tmin
        self.renameChannels=renameChannels
        self.profusionSegment=profusionSegment
        self.profusionMaxSeconds=profusionMaxSeconds
        # SCORE scores the significance of the PDR, whose normal lower limit is
        # age-dependent. patientDob wins over patientAge; both may be omitted,
        # in which case the age is read from the study and, failing that,
        # significance goes unscored rather than assuming an adult.
        self.patientDob=patientDob
        self.patientAge=patientAge
        # Infer eyes-open/eyes-closed periods from the signal where the
        # recording carries no eye-state annotations. Off by default: on a
        # continuously eyes-closed recording it has been seen to split the
        # record and report a reduced reactivity that is not there.
        self.autoEyeState=autoEyeState
        self.stageSleep=stageSleep
        self.sleepBackend=sleepBackend
        # Detections from the cleared spike/seizure detector, when a caller has
        # them. Nothing in this project produces them.
        self.spikeDetections=spikeDetections
        # {'spike': [ids], 'seizure': [ids]} - the detector's own EventTypeID
        # values, once known. Selecting events by type id is the reliable way to
        # tell a detection from a technologist's note; see spikeseizure.py.
        self.spikeTypeIds=spikeTypeIds

        # a native ProfusionEEG study is a folder, not a single file
        if os.path.isfile(self.eegFullName) or os.path.isdir(self.eegFullName):
            print ('File exists: ', self.eegFullName)
            if autogenerate:
                raw, _=self.process()
                self.raw=raw
                print ('Run AI_Text_generate() to generate the report')
                
            else:
                self.raw=None
                self.results=None
                print ("""Please call process() to create the raw data and results""")
        else:
            print('File not exists: ', self.eegFullName)
    
    
    def getMeanAmplitudes(self,epochs):
        bandNames=['alpha', 'beta', 'theta', 'delta']
        bandFreqs=[[8, 13], [13, 30], [4, 8], [1, 4]]
        # Measured over the whole epoch. This used to crop to 0.5 s first, which
        # is shorter than the band-pass filters then applied (a 1-4 Hz filter is
        # ~413 samples against 63 of signal), so the reported amplitudes were
        # filter ringing - alpha came out near 190 uV on normal recordings.
        results={}
        for i in range(4):
            band=bandNames[i]
            low, high=bandFreqs[i]
            band_epo=epochs.copy().filter(low, high, verbose=False)
            data=band_epo.get_data(units='uV')
            amp=np.max(data, axis=2)-np.min(data, axis=2)
            # TOP 2% quantile
            amp=np.quantile(amp.reshape(-1), 0.98)
            results[band]=round(amp, 2)
        return results


    ################### get features ###################
    def getFeatures(self, epochs):
        
        chn_order=['Fp1', 'Fp2', 'F7', 'F8', 'F3', 'F4', 
                   'C3', 'C4', 'T3', 'T4', 'T5', 'T6', 'P3', 'P4', 'O1', 'O2']
        # if epochs don't have the chanel in chn_order, it will raise error
        if not set(chn_order).issubset(set(epochs.ch_names)):
            print ('Error: channels not match', 'Must have channels: ', chn_order)
            return None, None
        epochs.reorder_channels(chn_order)      

        epoch_for_psd=epochs.copy()        
        sfr=epochs.info['sfreq']
        epochLength=epochs._data.shape[2]
        
        # calculate bandwidth and psds
        bandWidth=np.round(sfr/epochLength,2)
        psds=epoch_for_psd.compute_psd(method='multitaper', fmin=1.5, fmax=30, bandwidth=bandWidth, n_jobs=4, verbose=False)
        
        rightPreds, leftPreds=predict(self.model_folder, self.model_names).ensemble(psds.copy().average())
        print ('rightPreds: ', rightPreds, 'leftPreds: ', leftPreds)

        bandPsds=[[], [], []]
        bandRange=[(1.5, 4), (4, 8), (8, 13)]
        for i in range(3):
            band=bandRange[i]
            bandPsds[i]=psds.copy().average().get_data(fmin=band[0], fmax=band[1])*1e12# convert V^2/Hz to uV^2/Hz
        psdsDelta, psdsTheta, psdsAlpha=bandPsds


        ch_names=epochs.ch_names 
        
        def pltDiff(psds):
            # L_R_diff odd channel - even channel
            L_R_diff=[]
            L_R_Channels=[]
            for i in range(0, len(ch_names), 2):
                # get psd1: left channel, psd2: right channel
                psd1=psds[i, :]
                psd2=psds[i+1, :]
                # flatten psd1, psd2 and sum
                psd1=simpson(psd1.reshape(-1), dx=bandWidth)
                psd2=simpson(psd2.reshape(-1), dx=bandWidth)
                
                diff=round(2*(psd1-psd2)/(psd1+psd2)  ,3)
                L_R_diff.append(diff)
                L_R_Channels.append(ch_names[i]+'-'+ch_names[i+1])
            return L_R_diff, L_R_Channels        

        diff1, _ = pltDiff(psdsDelta)
        diff2, _ = pltDiff(psdsTheta)
        diff3, alphaDiffChannels = pltDiff(psdsAlpha)        

        right_chs=['Fp2', 'F4', 'C4', 'P4', 'O2', 'F8', 'T4', 'T6']
        left_chs=['Fp1', 'F3', 'C3', 'P3', 'O1', 'F7', 'T3', 'T5']

        def calcPowerSum(psds, fmin, fmax, pick_chs, bandWidth):
            psds=psds.copy().pick(pick_chs).average().get_data(fmin=fmin, fmax=fmax)*1e12
            psds= np.average( simpson(psds, dx=bandWidth))
            return psds

        # slow /all ratio
        bandRange=[(1.5, 8), (8, 13), (13, 30), (1.5, 30)]

        # slow, beta, all power sum, right/left/all
        pSums=[]
        for i in range(len(bandRange)):
            band=bandRange[i]
            for c in [right_chs, left_chs, ch_names]:
                pSum=calcPowerSum(psds, band[0], band[1], c, bandWidth)
                pSums.append(pSum)

        right_slow, left_slow, total_slow=pSums[0:3]
        right_alpha, left_alpha, total_alpha=pSums[3:6]
        right_beta, left_beta, total_beta=pSums[6:9]
        right_all, left_all, total_all=pSums[9:12]
        
        # slow ratio
        right_slow_ratio=round(100*right_slow/right_all, 2)
        left_slow_ratio=round(100*left_slow/left_all, 2)
        all_slow_ratio=round(100*total_slow/total_all, 2)

        # beta ratio
        right_beta_ratio=round(100*right_beta/right_all, 2)
        left_beta_ratio=round(100*left_beta/left_all, 2)
        all_beta_ratio=round(100*total_beta/total_all, 2)

        # beta/alpha ratio
        right_beta_alpha_ratio=round(100*right_beta/right_alpha, 2)
        left_beta_alpha_ratio=round(100*left_beta/left_alpha, 2)
        all_beta_alpha_ratio=round(100*total_beta/total_alpha, 2)
        
        # AP difference
        antChs=['Fp1', 'Fp2', 'F7', 'F8', 'F3',  'F4']
        right_antChs=['Fp2', 'F4', 'F8']
        left_antChs=['Fp1', 'F3', 'F7']
        posChs=['T5', 'T6', 'P3', 'P4', 'O1', 'O2']
        right_posChs=['T6', 'P4', 'O2']
        left_posChs=['T5', 'P3', 'O1']

        APPsds=[]

        for c in [antChs, posChs, right_antChs, right_posChs, left_antChs, left_posChs]:
            pSum=calcPowerSum(psds, 8, 13, c, bandWidth)
            APPsds.append(pSum)
        antPsds,posPsds=APPsds[0:2]
        right_antPsds,right_posPsds=APPsds[2:4]
        left_antPsds,left_posPsds=APPsds[4:6]

        AP_difference=100*antPsds/(antPsds+posPsds)
        AP_difference=round(AP_difference, 2)

        right_AP_difference=100*right_antPsds/(right_antPsds+right_posPsds)
        right_AP_difference=round(right_AP_difference, 2)

        left_AP_difference=100*left_antPsds/(left_antPsds+left_posPsds)
        left_AP_difference=round(left_AP_difference, 2)


        # log        
        results={
            'AP_difference': AP_difference,
            'right_AP_difference': right_AP_difference,
            'left_AP_difference': left_AP_difference,
            'left_backgroud_frequency': leftPreds,
            'right_backgroud_frequency': rightPreds,
            'right_slow_ratio': right_slow_ratio,
            'left_slow_ratio': left_slow_ratio,
            'total_slow_ratio': all_slow_ratio,
            'right_beta_ratio': right_beta_ratio,
            'left_beta_ratio': left_beta_ratio,
            'total_beta_ratio': all_beta_ratio,
            'right_beta_alpha_ratio': right_beta_alpha_ratio,
            'left_beta_alpha_ratio': left_beta_alpha_ratio,
            'total_beta_alpha_ratio': all_beta_alpha_ratio,
            'LR_delta_ratio': diff1,
            'LR_theta_ratio': diff2,
            'LR_alpha_ratio': diff3,
            'alphaDiffChannels': alphaDiffChannels,
            'DiffTwoFold': "1",
            "followOrder": ''
        }
        
        return  results, psds.average()


    def checkFollowOrder(self):
        # event filename=edf_file_name.split('.')[0]+'.txt'
        edf_file=self.eegFullName
        # print ('edf_file: ', edf_file)
        event_file=edf_file.replace('.edf', '.txt')
        # print ('event_file: ', event_file)
        followOrder="True"
        if os.path.isfile(event_file):
            
            with open(event_file, 'r') as f:
                lines=f.readlines()
                for line in lines:
                    if "Unable to Follow Commands" in line:
                        followOrder="False"
                        break
        return followOrder

    def resolveAgeYears(self, raw=None):
        """Age at recording, from the caller or from the study's own files.

        Returns (age, source). An explicit date of birth is preferred because
        the date in EEG4PatientInfo.xml is numeric with no day/month marker,
        which matters for infants even though it rarely does for adults.
        """
        if self.patientAge is not None:
            return float(self.patientAge), 'supplied age'

        recordingDate = None
        meta = profusion.readStudyMetadata(self.eegFullName)             if profusion.isProfusionStudy(self.eegFullName) else None
        if meta:
            recordingDate = meta.get('recording_date')

        if self.patientDob is not None:
            age = profusion.ageYearsAt(self.patientDob, recordingDate)
            if age is not None:
                return age, 'supplied date of birth'
            return None, 'date of birth supplied but no recording date found'

        info = profusion.readPatientInfo(self.eegFullName)             if profusion.isProfusionStudy(self.eegFullName) else None
        if info and info.get('dob'):
            age = profusion.ageYearsAt(info['dob'], recordingDate)
            if age is not None:
                source = 'study patient record'
                if info.get('dob_ambiguous'):
                    source += ' (date of birth %s read month-first - confirm)'                         % info['dob_raw']
                return age, source

        # Finally the recording's own header, which EDF+ carries.
        age, description = ageFromRecordingHeader(raw)
        if age is not None:
            return age, description
        if description:
            return None, description

        return None, 'no date of birth available'

    def describeRecording(self, raw, epochs, bad_ratio, eegWork):
        """SCORE's patient and recording-conditions sections, plus the duration
        accounting every rate in the report depends on."""
        age, ageSource = self.resolveAgeYears(raw)

        epochLength = getattr(eegWork, 'epoch_length', 4)
        retained = len(epochs)
        total = getattr(eegWork, 'epochsTotal', None) or retained

        loaded = getattr(eegWork, 'loadedSeconds', None)
        if loaded is None and raw is not None:
            loaded = raw.n_times / float(raw.info['sfreq'])
        meta = profusion.readStudyMetadata(self.eegFullName) \
            if profusion.isProfusionStudy(self.eegFullName) else None

        durations = recording.DurationAccount(
            recordedSeconds=(meta or {}).get('study_length'),
            loadedSeconds=loaded,
            analysedSeconds=retained * epochLength,
            epochLength=epochLength, epochsRetained=retained, epochsTotal=total)

        # When rejection would have left too few epochs to analyse, the pipeline
        # keeps them all. The drop ratio elsewhere in the report then describes
        # epochs identified as bad rather than epochs removed, which is a
        # material difference to anyone reading a rate.
        if getattr(eegWork, 'rejectionApplied', None) is False:
            durations.rejectionSkipped = (getattr(eegWork, 'epochsIdentifiedBad', 0),
                                          total)

        return recording.describeRecording(
            self.eegFullName, raw=raw,
            channels=getattr(eegWork, 'sourceChannels', None) or (raw.ch_names if raw is not None else None),
            ageYears=age, ageSource=ageSource, durations=durations,
            # the rate before the pipeline resampled, which is the rate the
            # recording was actually acquired at
            sourceSampleRate=getattr(eegWork, 'sourceSampleRate', None),
            analysisSampleRate=raw.info['sfreq'] if raw is not None else None,
            analysisFilter='1-60 Hz band pass, REST reference')

    def scoreDetections(self, raw, epochs, eegWork):
        """Score spike and seizure detections, if a detector supplied any.

        Detections reach this from one of two places, neither of which this
        project owns:

          the cleared SpikeAndSeizure detector, once CEventDetection is
          available as an extension - it hands back EventStruct records with
          per-channel detections;

          a study that has already been through the detector inside
          ProfusionEEG, whose detections sit in the study's event database.
          Events are selected by TYPE there, never by their text - the text is
          whatever the person at the keyboard typed.

        With neither present this returns an empty result and the report simply
        has no epileptiform findings - which is the honest outcome, since
        nothing in this pipeline detects them.
        """
        detections = list(self.spikeDetections or [])
        source = 'supplied directly' if detections else None

        # The study's own event database, which is where the detector leaves its
        # detections when it runs during acquisition. Preferred over everything
        # else: the detector ran inside ProfusionEEG in its own configuration,
        # and this only reads the result.
        if not detections and profusion.isProfusionStudy(self.eegFullName):
            fromStudy = spikeseizure.detectionsFromStudy(
                self.eegFullName, typeIds=self.spikeTypeIds, verbose=True)
            if fromStudy:
                detections = fromStudy
                source = "the study's event database"

        if not detections and raw is not None and raw.annotations is not None:
            # Events carried across from a ProfusionEEG study by profusion.py.
            fromStudy = spikeseizure.detectionsFromAnnotations(raw.annotations)
            if fromStudy:
                detections = fromStudy
                source = 'events stored in the study by the detector'

        if not detections:
            return None

        # The denominator is the duration the DETECTOR examined, which is the
        # whole loaded recording - not the epoch-screened duration the background
        # analysis kept. Those differ by about half on this data, and using the
        # smaller one inflates every incidence band the detections produce.
        examined = getattr(eegWork, 'loadedSeconds', None)
        if not examined and raw is not None:
            examined = raw.n_times / float(raw.info['sfreq'])
        print('Spike/seizure detections: %d (%s), over %.0f s examined'
              % (len(detections), source, examined or 0))
        result = spikeseizure.scoreSpikesAndSeizures(
            detections, analysedSeconds=examined,
            sampleRate=getattr(eegWork, 'sourceSampleRate', None))
        result['source'] = source
        result['examined_seconds'] = None if examined is None else round(examined, 1)
        return result

    def scorePdr(self, raw, epochs, results, bad_ratio):
        """Score the posterior dominant rhythm on all nine SCORE properties."""
        age, ageSource = self.resolveAgeYears(raw)
        if age is None:
            print('PDR: age unavailable (%s)' % ageSource)
        else:
            print('PDR: age %.1f years (%s)' % (age, ageSource))

        modulators = []
        if raw is not None and raw.annotations is not None:
            modulators = sorted({d for d in raw.annotations.description if d})

        scored = pdrScore.scorePdr(
            epochs,
            leftFrequency=results.get('left_backgroud_frequency'),
            rightFrequency=results.get('right_backgroud_frequency'),
            raw=raw, ageYears=age,
            artifactRatio=None if bad_ratio is None else bad_ratio / 100.0,
            modulators=modulators, autoEyeState=self.autoEyeState)
        scored['age_source'] = ageSource
        return scored

    def process(self):
        eegWork=eegProcess(self.fileName, self.filePath, useRepair=self.useRepair,
                           dropEpochSD=self.dropEpochSD, unit_uV=self.unit_uV,
                           tmax=self.tmax, tmin=self.tmin, renameChannels=self.renameChannels,
                           removeEpochsRationThreshold=self.removeEpochsRationThreshold,
                           profusionSegment=self.profusionSegment,
                           profusionMaxSeconds=self.profusionMaxSeconds,
                           stageSleep=self.stageSleep,
                           sleepBackend=self.sleepBackend)
        raw, events=eegWork.getRawData()
        sample_rate=int(raw.info['sfreq'])
        self.sample_rate=sample_rate
        epochs,bad_ratio, bad_channels=eegWork.extractAlphaEpochs()
        results, psds=self.getFeatures(epochs)
        self.alphaEpochs=epochs
        results['bad_channels']=bad_channels
        results['pdr']=self.scorePdr(raw, epochs, results, bad_ratio)
        # classified on the recording as loaded, inside eegProcess.getRawData
        results['artifacts']=eegWork.artifacts
        results['sleep']=eegWork.sleep
        results['recording']=self.describeRecording(raw, epochs, bad_ratio, eegWork)

        # The focal slowing, diffuse slowing and band ratios computed above are
        # interictal findings in SCORE's vocabulary; scored here so they land in
        # a folder instead of standing beside the report as percentages.
        results['interictal']=interictal.scoreInterictal(
            epochs, results, epochLength=getattr(eegWork, 'epoch_length', 4))

        # Spike and seizure detections, where a detector has supplied any. The
        # findings merge onto the interictal page; seizures get their own.
        results['spikeseizure']=self.scoreDetections(raw, epochs, eegWork)
        spikeFindings=(results['spikeseizure'] or {}).get('interictal') or []
        if spikeFindings and results.get('interictal'):
            results['interictal'].setdefault('findings', []).extend(spikeFindings)
            results['interictal'].setdefault('notes', []).extend(
                (results['spikeseizure'] or {}).get('notes') or [])

        # The bad-electrode list belongs in the artifact folder, with a location.
        badFinding=interictal.badElectrodeFinding(
            bad_channels, len(epochs) * getattr(eegWork, 'epoch_length', 4),
            threshold=self.removeEpochsRationThreshold)
        if badFinding and results.get('artifacts'):
            results['artifacts'].setdefault('findings', []).append(badFinding)
        elif badFinding:
            results['artifacts']={'findings': [badFinding], 'notes': [],
                                  'analysed_seconds': None}
        rawData=raw.copy().get_data(units='uV')
        amplitude=self.getMeanAmplitudes(epochs)
        results['removeEpochsRatio']=bad_ratio
        results['amplitudes']=amplitude
        self.results=results
        self.genFinalResults()

        # What writePDF needs, kept so the document can be written later from an
        # analysis that has already run. The review front end depends on this:
        # the reader accepts and overrides findings, and only then is the
        # document produced - re-running the analysis to write it would cost
        # minutes and could not honour the review anyway.
        #
        # This holds the epoch data for the life of the object, which for a long
        # recording is not free. The command-line path writes immediately below
        # and lets it go.
        self._documentInputs = {
            'rawData': rawData, 'epochs': epochs, 'psds': psds,
            'sample_rate': sample_rate, 'ch_names': raw.ch_names,
        }

        if self.outputPdf:
            self.writeDocument()

        return raw, results

    def drawFigures(self):
        """Draw the report's figures without assembling the document.

        Called after the analysis so the figures land beside the report while
        the epochs are still in memory. They are what makes a saved analysis
        re-usable: with the figures and the results on disk, a document can be
        rebuilt later without analysing the recording again.
        """
        if not getattr(self, '_documentInputs', None):
            raise RuntimeError('nothing analysed yet - call process() first')

        import createPDF
        from createPDF import writePDF as _writePDF
        inputs = self._documentInputs
        # A writePDF is constructed only for its drawing; the pages are not
        # assembled here. deleteJpg stays off - the figures are the point.
        drawer = _writePDF.__new__(_writePDF)
        drawer.fileName = self.fileName
        folder = self.dest_pdfPath
        if folder and folder[-1] not in ('\\', '/'):
            folder += '/' if '/' in folder else '\\'
        os.makedirs(folder, exist_ok=True)
        drawer.dest_folder = folder
        drawer.results = self.results
        drawer.figures = [folder + name
                          for name in createPDF.figureNames(self.fileName)]
        drawer.drawEpochs(inputs['epochs'])
        drawer.drawPsds(inputs['psds'])
        drawer.drawLeftRightDiff(self.results['LR_alpha_ratio'],
                                 self.results['LR_theta_ratio'],
                                 self.results['LR_delta_ratio'],
                                 self.results['alphaDiffChannels'])
        drawer.drawFreqPower(inputs['psds'])
        drawer.plotTopMaps(inputs['epochs'])
        drawer.plotSpectrogram(inputs['rawData'], inputs['sample_rate'],
                               inputs['ch_names'])
        return folder

    def writeDocument(self):
        """Write the report document from the analysis already in memory.

        Called by process() on the command-line path, and by the review front
        end once the reader has finished with the findings. Returns the path
        written.
        """
        if not getattr(self, '_documentInputs', None):
            raise RuntimeError('nothing analysed yet - call process() first')

        results = self.results
        ai_report_text = None
        if self.aiReport:
            ai_report_text = self.AI_Text_generate()
            try:
                results['conclusion'] = self.scoreConclusion()
            except Exception as e:
                print('Conclusion generation failed: %s' % e)

        inputs = self._documentInputs
        written = writePDF(self.fileName, inputs['rawData'], inputs['epochs'],
                           inputs['psds'], results, self.dest_pdfPath,
                           inputs['sample_rate'], inputs['ch_names'],
                           ai_report_text)
        # The path that was actually written, so no caller has to guess it.
        self.documentPath = written.outFile
        return self.documentPath
    


    optionBackground = [
        'Normal background frequency',
        'Diffuse background slowing',
    ]

    optionAmplitude = [
        'low (<10 mV)',
        'medium (10–50 mV)',
        'high (>50 mV)'
    ]

    frequencySym = [
        'symmetric',
        'lower in right',
        'lower in left',
        'borderline lower in right',
        'borderline lower in left'
    ]

    amplitudeSym = [
        'symmetric',
        'lower in right',
        'lower in left',
        'borderline lower in right',
        'borderline lower in left'
    ]


    def slow_score(self):
        left_right_delta_ratio = self.results['LR_delta_ratio']
        left_right_theta_ratio = self.results['LR_theta_ratio']
        left_right_alpha_ratio = self.results['LR_alpha_ratio']
        bad_channels = self.results['bad_channels']
        # channels ['Fp1', 'Fp2', 'F7', 'F8', 'F3', 'F4', 'C3', 'C4', 'T3', 'T4', 'T5', 'T6', 'P3', 'P4', 'O1', 'O2']
        right_channels = ['Fp2', 'F8', 'F4', 'C4', 'T4', 'T6', 'P4', 'O2']
        right_posterior_channels = ['T6', 'P4', 'O2']
        left_channels = ['Fp1', 'F7', 'F3', 'C3', 'T3', 'T5', 'P3', 'O1']
        left_posterior_channels = ['T5', 'P3', 'O1']
        abnormal_threshold = 0.5

        right_slow_channels = []
        left_slow_channels = []

        for i in range(len(left_right_delta_ratio)):
            theta_ratio = left_right_theta_ratio[i]
            delta_ratio = left_right_delta_ratio[i]
            alpha_ratio = left_right_alpha_ratio[i]
            
            leftCh=left_channels[i]
            rightCh=right_channels[i]
            if delta_ratio >= abnormal_threshold or theta_ratio >= abnormal_threshold:
                if leftCh not in left_slow_channels \
                    and not (leftCh in left_posterior_channels and max(delta_ratio, theta_ratio, alpha_ratio) == alpha_ratio) \
                    and leftCh not in bad_channels:
                    left_slow_channels.append(left_channels[i])
            elif delta_ratio <= -abnormal_threshold or theta_ratio <= -abnormal_threshold:
                if rightCh not in right_slow_channels \
                    and not (rightCh in right_posterior_channels and min(delta_ratio, theta_ratio, alpha_ratio) == alpha_ratio) \
                    and rightCh not in bad_channels:
                    right_slow_channels.append(right_channels[i])

        # print('left_slow_channels', left_slow_channels, 'right_slow_channels', right_slow_channels)


        left_adjacents = {
            'Fp1': ['F7', 'F3'],
            'F7': ['Fp1', 'F3', 'T3'],
            'F3': ['Fp1', 'F7', 'C3'],
            'C3': ['F3', 'T3', 'P3'],
            'T3': ['F3', 'C3', 'T5'],
            'T5': ['F7', 'T3', 'P3'],
            'P3': ['C3', 'T5', 'O1'],
            'O1': ['P3', 'T5']
        }

        right_adjacents = {
            'Fp2': ['F8', 'F4'],
            'F8': ['Fp2', 'F4', 'T4'],
            'F4': ['Fp2', 'F8', 'C4'],
            'C4': ['F4', 'T4', 'P4'],
            'T4': ['F4', 'C4', 'T6'],
            'T6': ['F8', 'T4', 'P4'],
            'P4': ['C4', 'T6', 'O2'],
            'O2': ['P4', 'T6']
        }

        slow_scores =[0,0]
        slow_channels = [[],[]]
        for i in range(2):
            s_chs= left_slow_channels if i == 0 else right_slow_channels
            for ch in s_chs:
                adj_of_ch = left_adjacents[ch] if i == 0 else right_adjacents[ch]
                # has_neighbour = False
                for adj_ch in adj_of_ch:
                    if adj_ch in s_chs:
                        # has_neighbour = True
                        slow_channels[i].append(ch)
                        all_chs = left_channels if i == 0 else right_channels
                        index=all_chs.index(ch) 

                        for r in [abs(left_right_delta_ratio[index]), abs(left_right_theta_ratio[index])]:
                            if r >= abnormal_threshold:
                                slow_scores[i] += round(r, 3)
                                break
                                
                        break

        return slow_scores, slow_channels


    def evaluate_alpha_amp(self):

        left_right_alpha_ratio = self.results['LR_alpha_ratio']
        bad_channels = self.results['bad_channels']
        val = left_right_alpha_ratio
        left_lower = []
        right_slow=self.right_slow_channels
        right_lower = [] 
        left_slow=self.left_slow_channels

        left_score = 0
        right_score = 0
        right_channels = ['Fp2', 'F8', 'F4', 'C4', 'T4', 'T6', 'P4', 'O2']
        left_channels = ['Fp1', 'F7', 'F3', 'C3', 'T3', 'T5', 'P3', 'O1']
        abnormal_threshold = 0.5
        bad_channels = bad_channels

        for i in range(1,len(val)): 

            ch_r = right_channels[i]
            ch_l = left_channels[i]
            if val[i] >= abnormal_threshold:
                if ch_l not in left_lower and ch_l not in bad_channels and ch_l not in left_slow:
                    right_lower.append(ch_r)
                    right_score += abs(val[i])
            elif val[i] <= -abnormal_threshold:
                if ch_r not in right_lower and ch_r not in bad_channels and ch_r not in right_slow:
                    left_lower.append(ch_l)
                    left_score += abs(val[i])

        self.results['left_lower_alpha_channels'] = left_lower
        self.results['right_lower_alpha_channels'] = right_lower
        self.results['right_lower_alpha_score'] = right_score
        self.results['left_lower_alpha_score'] = left_score

        value = ''
        lowAlphaChannels = []
        if right_score > left_score and right_score >1.6:
            #right abnormally 
            value = self.amplitudeSym[1]
            lowAlphaChannels = right_lower
            
        elif left_score > right_score and left_score >1.6:
            value = self.amplitudeSym[2]
            lowAlphaChannels = left_lower
        else:
            value = self.amplitudeSym[0]

        # print('amplitude_symmetry', value)
        bg_amplitude_symmetry = value
        
        return bg_amplitude_symmetry, lowAlphaChannels

    def symmetric_frequency_of_background(self):
        left_freq = self.results['left_backgroud_frequency']
        right_freq = self.results['right_backgroud_frequency']
        value = ''
        # >0.5 Hz difference
        # print('left_freq', left_freq, 'right_freq', right_freq)

        if left_freq - right_freq >= 1:
            value = self.frequencySym[1]
        elif right_freq - left_freq >=1:
            value = self.frequencySym[2]
        else:
            value = self.frequencySym[0]

        # print('symmetric_frequency_of_background', value)
        return value
    def focal_slow_conclusion(self):
        slow_scores, slow_channels=self.slow_score()
        self.left_slow_channels=slow_channels[0]
        self.right_slow_channels=slow_channels[1]
        self.results['left_slow_channels']=slow_channels[0]
        self.results['right_slow_channels']=slow_channels[1]
        self.results['right_slow_score']=slow_scores[1]
        self.results['left_slow_score']=slow_scores[0]
        # print ('slow_scores: ', slow_scores)
        # print ('slow_channels: ', slow_channels)
        str=''
        for i in range(2):
            if slow_scores[i] >= 2.4:
                self.benchmark['FSlow'] = 1
                str='Focal abnormality: higher slow wave power in  {} when compare left and right channels'.format(', '.join(slow_channels[i]))
                break
        
        return str

    def eeg_quality_conclusion(self):
        results=self.results
        str=''
        bad_ratio = results['removeEpochsRatio']
        
        if bad_ratio <= 50:
            str='Good'
        elif bad_ratio <= 75:
            str='Fair'
        elif results['removeEpochsRatio'] > 75:
            str='Poor'
        return str

    def background_conclusion(self, lowerAlphaChannels):
        results=self.results
        right_background_frequency = results['right_backgroud_frequency']
        left_background_frequency = results['left_backgroud_frequency']
        right_slow_ratio = results['right_slow_ratio']
        left_slow_ratio = results['left_slow_ratio']
        total_slow_ratio = results['total_slow_ratio']
        right_beta_ratio = results['right_beta_ratio']
        left_beta_ratio = results['left_beta_ratio']
        total_beta_ratio = results['total_beta_ratio']

        alpha_amplitude = results['amplitudes']['alpha']
        ap_gradient = results['AP_difference']
        max_freq = max(right_background_frequency, left_background_frequency)
        min_freq = min(right_background_frequency, left_background_frequency)
        
        # mild diffuse background slowing
        if  (max_freq <7.5) or (max_freq < 8 and total_slow_ratio >50 ):
            results['bg_active'] = self.optionBackground[1]
            self.benchmark['DBS'] = 1
            # self.benchmark['AI4'] = 0
        
        # elif  min(right_slow_ratio, left_slow_ratio) >=60 :             
            
        #     results['bg_active'] = self.optionBackground[1]
        #     self.benchmark['DBS'] = 1
            # self.benchmark['AI4'] = 0
        else:
            results['bg_active'] = self.optionBackground[0]
            self.benchmark['DBS'] = 0

        if alpha_amplitude < 10:
            results['bg_amp'] = self.optionAmplitude[0]
        elif alpha_amplitude <= 50:
            results['bg_amp'] = self.optionAmplitude[1]
        else:
            results['bg_amp'] = self.optionAmplitude[2]

        if results['bg_amp_sym'] != self.amplitudeSym[0] or  results['bg_freq'] != self.frequencySym[0]:
            self.benchmark['FSlow'] = 1        

        self.results=results
        str_abnormal_bg = ''
        if results['bg_active'] != self.optionBackground[0] :
            str_abnormal_bg = f'Abnormal, diffuse bacground slowing;'           
        
        if results['focal_abnormality']!= '' or results['bg_amp_sym']!=self.amplitudeSym[0] or results['bg_freq']!=self.frequencySym[0]:
            str_abnormal_bg+= 'Focal slow wave or asymmetric abnormality detected:'
            str_lower_alpha = ', '.join(lowerAlphaChannels)
            if results['focal_abnormality']!= '':
                str_abnormal_bg+=results['focal_abnormality']
            if results['bg_amp_sym']!=self.amplitudeSym[0]:
                str_abnormal_bg+=f';Lower alpha amplitude in {str_lower_alpha} channels'
            if results['bg_freq']!=self.frequencySym[0]:
                str_abnormal_bg+=f';Lower dominant frequency in {results["bg_freq"]} channels'    

        if str_abnormal_bg=='':
            str_abnormal_bg='Normal background activity'    

        return str_abnormal_bg

    def genFinalResults(self):
        results=self.results
            # example of results

        finalResults={'EEG_quality':'',
                    'bad_channels':'',
                    'backgroundFrequency':'',
                    'bg_active':'',
                    'bg_amp':'',
                    'bg_amp_sym':'',
                    'bg_freq':'',
                    'abnormalFindings':[''],
                }
        finalResults['bad_channels']=results['bad_channels']
        finalResults['backgroundFrequency'] = 'Right: ' + str(results['right_backgroud_frequency']) + ' Hz, Left: ' + str(results['left_backgroud_frequency']) + ' Hz'


        focal_slow=self.focal_slow_conclusion()
        # print ('focal_slow: ', focal_slow)
        # if not focal_slow=='':
        finalResults['abnormalFindings'].append(focal_slow)
        results['focal_abnormality']=focal_slow


            
        bg_amplitude_symmetry, lowerAlphaChannels=self.evaluate_alpha_amp()
        results['bg_amp_sym']=bg_amplitude_symmetry
        finalResults['bg_amp_sym']=bg_amplitude_symmetry
        # print ('alpha_amp: ', bg_amplitude_symmetry, lowerAlphaChannels)
        symmetric_background= self.symmetric_frequency_of_background()
        results['bg_freq']=symmetric_background
        finalResults['bg_freq']=symmetric_background
        # print ('backgroundFrequency: ', symmetric_background, lowerAlphaChannels)

        eeg_quality=self.eeg_quality_conclusion()
        # print ('eeg_quality: ', eeg_quality)
        finalResults['EEG_quality']=eeg_quality

        bg_conclusion=self.background_conclusion(lowerAlphaChannels)
        # print ('conclusion: ', bg_conclusion)
        if bg_conclusion != 'Normal background activity':
            finalResults['abnormalFindings'].append(bg_conclusion)
        
        finalResults['bg_active']=results['bg_active']
        finalResults['bg_amp']=results['bg_amp']

        # SCORE-scored PDR, flattened to term strings for the report prompt
        pdrResult=results.get('pdr')
        if pdrResult:
            finalResults['posteriorDominantRhythm']={
                label: pdrResult[key]['term']
                for key, label in pdrScore.PROPERTY_ORDER
                if pdrResult.get(key) and pdrResult[key]['term']}

        # The artifact and sleep folders too, so the conclusion is drawn from
        # everything that was scored rather than the background alone.
        artifactResult=results.get('artifacts')
        if artifactResult and artifactResult.get('findings'):
            finalResults['artifacts']=[
                {'type': f['name'], 'location': f['location']['text'],
                 'timing': f.get('prevalence') or f.get('incidence') or '',
                 'confidence': f.get('confidence')}
                for f in artifactResult['findings']]

        interictalResult=results.get('interictal')
        if interictalResult and interictalResult.get('findings'):
            finalResults['interictalFindings']=[
                {'name': f['name'], 'location': f['location']['text'],
                 'prevalence': f.get('prevalence') or ''}
                for f in interictalResult['findings']]

        sleepResult=results.get('sleep')
        if sleepResult and sleepResult.get('term'):
            finalResults['sleep']={
                'finding': sleepResult['term'],
                'stagesAchieved': sleepResult.get('stages_achieved') or [],
                'graphoelements': [
                    g['name'] + (' (unconfirmed)' if g.get('provisional') else '')
                    for g in (sleepResult.get('graphoelements') or [])]}
            if sleepResult.get('short_recording'):
                finalResults['sleep']['caveat']=(
                    'too few epochs to characterise sleep')
            
        self.finalResults=finalResults
        self.results=results
        return finalResults
    
    def scoreConclusion(self, reportLang=None):
        """Diagnostic significance, summary of findings and clinical comments.

        SCORE makes the diagnostic significance a forced choice from a fixed
        list and reserves it for the electroencephalographer, taken last and in
        the clinical context. So this produces a PROPOSAL from that list, marked
        for confirmation, never a scored value - and anything the model returns
        that is outside the list, or beyond what this analysis can support, is
        rejected here rather than shown to a reader.
        """
        if not self.finalResults:
            self.genFinalResults()
        reportLang = reportLang or self.reportLang or 'English'

        message = pmt.scoreConclusionPrompt(
            self.finalResults, sc.SIGNIFICANCE_CATEGORIES, sc.SUPPORTABLE_YIELDS,
            sc.UNSUPPORTABLE_REASON, reportLang)

        raw = self.AI_generate(message)
        parsed, parseNote = self._parseConclusion(raw)
        if parsed is None:
            return {'status': 'unparsed', 'raw': raw, 'notes': [parseNote],
                    'requires_confirmation': True}

        category, accepted, rejected = sc.validateSignificance(
            parsed.get('category'), parsed.get('yields'))

        notes = []
        if parsed.get('category') and category is None:
            notes.append('The model returned "%s", which is not one of SCORE\'s '
                         'three categories, so no category is proposed.'
                         % parsed.get('category'))
        for term, reason in rejected:
            notes.append('Rejected the proposed yield "%s": %s.' % (term, reason))
        if category == 'Abnormal recording' and not accepted:
            notes.append('Abnormal was proposed with no supportable diagnostic '
                         'yield, so the yield is left for the reader.')

        conclusion = {
            'status': 'proposed',
            'category': category,
            'yields': accepted,
            'basis': [b for b in (parsed.get('basis') or []) if b],
            'confidence': parsed.get('confidence'),
            'summary_of_findings': (parsed.get('summary_of_findings') or '').strip(),
            'clinical_comments': (parsed.get('clinical_comments') or '').strip(),
            'language': reportLang,
            'model': self.llm_model,
            'requires_confirmation': True,
            'notes': notes,
        }
        printConclusion(conclusion)
        return conclusion

    @staticmethod
    def _parseConclusion(raw):
        """Pull the JSON object out of the model's reply."""
        if not raw:
            return None, 'The model returned nothing.'
        text = raw.strip()
        # Models commonly wrap JSON in a fenced block or add a sentence first.
        start, end = text.find('{'), text.rfind('}')
        if start < 0 or end <= start:
            return None, 'No JSON object in the reply; the raw text is kept below.'
        try:
            return json.loads(text[start:end + 1]), None
        except ValueError as e:
            return None, 'The reply was not valid JSON (%s); the raw text is kept below.' % e

    def AI_generate(self, message, token=None):
        model_name=self.llm_model

        if 'gemini' in model_name.lower():
            genai.configure(api_key=self.LLM_API_KEY)
            limitWords=''
            if token:
                limitWords=' Output in {} words'.format(token)
            else:
                generation_config =None
                
            model = genai.GenerativeModel(model_name)
            i=1
            
            while i<4:
                print ('Attempt: {}, AI is generating the content...'.format(i))
                try:
                    response = model.generate_content([message,limitWords])
                    # print(response)
                    text=response.text
                    html=markdown.markdown(text)
                    soup = BeautifulSoup(html, features='html.parser')
                    return soup.get_text()
                    break
                except Exception as e:
                    i+=1
                    print(e)
                    time.sleep(20)
                    continue

            return ''
        elif 'claude' in model_name:
            client = anthropic.Anthropic(api_key=self.LLM_API_KEY)
            message = client.messages.create(
                model=model_name,
                max_tokens=1024,
                temperature=0.7,
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "text",
                                "text": message
                            }
                        ]
                    }
                ]
            )
            text=message.content[0].text
            # print ('text: ', text)
            # time.sleep(5)
            return text
        elif 'gpt' in model_name:    
        
            client = OpenAI(api_key=self.LLM_API_KEY)
            response = client.chat.completions.create(
            model= model_name, #"gpt-4-turbo",#"gpt-3.5-turbo", "gpt-4o"
            messages=[
                {
                "role": "user",
                "content": message
                }
            ],
            temperature=0.7,
            max_tokens=1024,
            top_p=1,
            frequency_penalty=0,
            presence_penalty=0
            )
            text=response.choices[0].message.content

            return text


    def AI_Text_generate(self, reportLang=None, prompt=0, token=None):
        if not self.finalResults:
            self.genFinalResults()
        finalResults=self.finalResults
        if not reportLang:
            reportLang=self.reportLang

        if prompt==0:
            message=pmt.reportPrompt(finalResults, reportLang, promptLength='long')
    
        elif prompt==1:
            message=pmt.reportPrompt(finalResults, reportLang, promptLength='medium')

        elif prompt==2:
            message=pmt.reportPrompt(finalResults, reportLang, promptLength='short')

        text=self.AI_generate(message, token)
        # remove blank lines
        text = os.linesep.join([s for s in text.splitlines() if s])
        # use regexp to insert  \n before === if line start with ===
        text = re.sub(r'(?m)^(===)', r'\n\1', text)
        return text
