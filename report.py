##################################################
# This file is used to test the autimatic EEG report generation system.
# The origin dataset is not available due to ethical reasons.
# You can test the system with the open-source dataset.
# SPIS_dataset: download the dataset from the following link:
# https://github.com/mastaneht/SPIS-Resting-State-Dataset/tree/master/Pre-SART%20EEG
# Here is an example of how to run the system:
# python report.py ./SPIS_dataset/S04_restingPre_EC.mat --pdf  --out ./pdf --ai --lang "english"
# 
# For using the LLMs to generate the report, you need to set the GOOGLE_API_KEY in the config.env file.
##################################################

from auto_report import CreateReport
import argparse
import os
from dotenv import load_dotenv
def main():
    parser = argparse.ArgumentParser(description='create report automatically')
    # filename
    parser.add_argument('edf_file', type=str,
                        help='EEG input: an .edf/.fif/.mat file, or a native '
                             'ProfusionEEG study folder (*.eeg)')
    parser.add_argument('--pdf', action='store_true', help='output pdf')
    parser.add_argument('--ai', action='store_true', help='output ai')
    parser.add_argument('--lang', type=str, help='report language')
    parser.add_argument('--out', type=str, help='output folder')
    # llm model
    parser.add_argument('--llm', type=str, help='llm model')
    # TUH eeg
    parser.add_argument('--tuh', type=bool, help='tuh eeg')
    # native ProfusionEEG studies only
    parser.add_argument('--segment', type=str, default='longest',
                        choices=['longest', 'concat'],
                        help='ProfusionEEG study only: read the longest gap-free '
                             'data segment (default), or concatenate all of them')
    parser.add_argument('--max-seconds', dest='max_seconds', type=float,
                        help='ProfusionEEG study only: cap how much signal to load')
    parser.add_argument('--auto-eye-state', dest='auto_eye_state', action='store_true',
                        help='infer eyes-open/eyes-closed from the signal where the '
                             'recording has no eye-state annotations, so PDR '
                             'reactivity can be scored. Unconfirmed: it can report '
                             'a reduced reactivity that is not there')

    args = parser.parse_args()
    # os.path.split handles both separators, and a ProfusionEEG study folder
    # given with a trailing separator
    edf_path, edf_filename = os.path.split(args.edf_file.rstrip('/\\'))
    if not edf_path:
        edf_path = '.'

    outputPdf = args.pdf
    aiReport = args.ai
    reportLang = args.lang
    output_folder = args.out
    llm_model = args.llm
    tuh_eeg = args.tuh
    if output_folder is None:
        output_folder = './'

    try :
    # create report
        envFile=os.path.join(os.getcwd(),'config.env')
        load_dotenv(envFile)
        Google_API_KEY= os.environ.get('GOOGLE_API_KEY')
        OPENAI_API_KEY=os.environ.get('OPENAI_KEY')
        ANTHROPIC_API_KEY=os.environ.get('ANTHROPIC_API_KEY')

        # check model is gpt, claude or gemini
        if llm_model is None:
            llm_model = 'gemini-1.5-flash'
            print('No LLM model specified, using default model: gemini-1.5-flash')
        if llm_model is not None:
            if 'gpt' in llm_model.lower():
                LLM_API_KEY = OPENAI_API_KEY
            elif 'claude' in llm_model.lower():
                LLM_API_KEY = ANTHROPIC_API_KEY
            elif 'gemini' in llm_model.lower():
                LLM_API_KEY = Google_API_KEY
            else:
                LLM_API_KEY = None
        
        if LLM_API_KEY is None:
            print('Please set the LLM_API_KEY in the config.env file')
            return

        CreateReport(edf_filename,edf_path, outputPdf=outputPdf, LLM_API_KEY=LLM_API_KEY,
                    llm_model=llm_model, unit_uV= not tuh_eeg,
            aiReport=aiReport, reportLang=reportLang,dest_pdfPath=output_folder,
            profusionSegment=args.segment, profusionMaxSeconds=args.max_seconds,
            autoEyeState=args.auto_eye_state)
    except Exception as e:
        print(e)
    

if __name__ == '__main__':
    main()
