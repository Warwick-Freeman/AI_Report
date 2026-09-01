############################################
#  This module is used to create a PDF file with EEG analysis results
#  The PDF file contains figures of EEG epochs, PSDs, topomaps, spectrogram, 
#   and left/right power ratio
#  The EEG analysis results are also included in the PDF file
#  The PDF file is saved in the destination folder
#  The EEG jpg files are deleted after the PDF file is created
#  If ai_report_text is not None, the AI report by LLMs is included in the PDF file
############################################
import matplotlib.pyplot as plt
from scipy import signal
import numpy as np
import os
import mne
import pdr as pdrScore

mne.viz.set_browser_backend('matplotlib')

class writePDF:    
    def __init__(self, filename, rawData, epochs, psds, results, dest_folder, sr, chNames, ai_report_text=None, deleteJpg=False):
        self.fileName=filename
        
        # print ('eegFullNmae: ', self.eegFullNmae)
        if dest_folder[-1] not in ['\\', '/']:
            if '/' in dest_folder:
                dest_folder+='/'
            else:
                dest_folder += '\\'

        # Create the output folder, and say so plainly if it cannot be created.
        #
        # This used to print the error and carry on, which meant the next thing
        # to happen was a figure failing to save and the caller seeing a
        # FileNotFoundError about a .jpg - with nothing to connect it to the
        # output folder that was the actual problem. A nested path is fine:
        # makedirs is recursive.
        if not os.path.exists(dest_folder):
            try:
                os.makedirs(dest_folder)
            except OSError as e:
                raise OSError(
                    'Cannot create the output folder %r: %s'
                    % (os.path.abspath(dest_folder), e)) from e
        if not os.path.isdir(dest_folder):
            raise OSError('The output folder %r is not a folder'
                          % os.path.abspath(dest_folder))
        self.dest_folder=dest_folder  
        self.results=results

        self.drawEpochs(epochs)
        self.drawPsds(psds)
        self.drawLeftRightDiff(results['LR_alpha_ratio'], results['LR_theta_ratio'], results['LR_delta_ratio'], results['alphaDiffChannels'])
        self.drawFreqPower(psds)
        self.plotTopMaps(epochs)
        self.plotSpectrogram(rawData, sr, chNames)
        self.ai_report_text=ai_report_text
        self.deleteJpg=deleteJpg
        
        self.outFile=None
        self.savePDF(results)  
        # delete eeg jpg
        if deleteJpg:
            for jpg in ['eeg0.jpg','eeg1.jpg', 'eeg2.jpg', 'eeg3.jpg', 'eeg4.jpg', 'eeg5.jpg']:
                jpgFile= self.dest_folder+jpg
                if os.path.exists(jpgFile):
                    try: 
                        os.remove(jpgFile)
                    except Exception as e:
                        print ('Error: ', e)
                        continue


    def savePDF(self, results):     
        print ('savePDF')
        removeEpochsRatio=results['removeEpochsRatio']
        AP_difference=results['AP_difference']
        right_AP_difference=results['right_AP_difference']
        left_AP_difference=results['left_AP_difference']
        left_backgroud_frequency=results['left_backgroud_frequency']
        right_backgroud_frequency=results['right_backgroud_frequency']
        right_slow_ratio=results['right_slow_ratio']
        left_slow_ratio=results['left_slow_ratio']
        total_slow_ratio=results['total_slow_ratio']
        left_beta_ratio=results['left_beta_ratio']
        right_beta_ratio=results['right_beta_ratio']
        total_beta_ratio=results['total_beta_ratio']
        bad_channels=results['bad_channels']
        amplitudes=results['amplitudes']

        # create PDF with figList and removeEpochsRatio, slowRatio
        # create a pdf file
        # import FPDF class
        from fpdf import FPDF
        # 頁面大小
        pdf = FPDF(orientation="P", unit="mm", format="A4")
        # set margins
        pdf.set_margins(left=8, top=10, right=8)
        
        line_height = 7.5
        fontName='Arial Unicode MS'
        rootPath=os.path.dirname(os.path.abspath(__file__))
        print ('rootPath: ', rootPath)
        pdf.add_font(fontName, '', rootPath+'\\arialuni.ttf', uni=True)
    
        
        pdf.set_font(fontName, size=18)

        # First, the way a SCORE report opens: who was recorded and under what
        # conditions, before any finding.
        # Sections the reader excluded in the review front end. The results are
        # kept - they still go to the structured SCORE data - but the section is
        # left out of the document, which is what excluding it means.
        excluded = set(results.get('_excluded') or ())

        def wanted(sectionId, value):
            return None if sectionId in excluded else value

        self.writeRecordingPage(pdf, fontName, line_height,
                                wanted('recording', results.get('recording')))

        pdf.add_page(orientation = 'P')
        # set page horizontal
        # eeg5.jpg
        pdf.cell(196, line_height, text='Power Spectrum Topomap', ln=1, align='C')
        # pdf.set_font(fontName, size=12)
        # pdf.cell(196, line_height-3, text=self.fileName, ln=1, align='C' )
        # Three figures stacked: give each what is left after the ones above it,
        # so the last one shrinks rather than running off the page.
        for figure in ('eeg0.jpg', 'eeg1.jpg', 'eeg2.jpg'):
            self._placeImage(pdf, self.dest_folder + figure)

        
        # The structured findings are the substance of the report, so they are
        # always rendered. The LLM narrative, when requested, is added at the end
        # as a summary of them. It used to replace this table and the three figure
        # pages below, so enabling --ai silently produced a much shorter report.
        # 第一頁
        pdf.set_font(fontName, size=18)
        pdf.add_page()
        # 標題
        pdf.cell(200, 16, text='Computer EEG anlysis - '+self.fileName, ln=1, align='C',border=0)

        # 文字大小
        pdf.set_font(fontName, size=13)
        pdf.cell(200, 8, text='(Informal Report)', ln=1, align='C',border=0)

        pdf.cell(30, line_height, text='', ln=0, align='L')
        pdf.cell(70, line_height, text=' Drop epochs ratio', ln=0, align='L', border=1)
        #epochs比例
        color= (0, 0, 0)
        if removeEpochsRatio>=75:
            color=(255, 0, 0)
        pdf.set_text_color(*color)
        pdf.cell(46, line_height, text=' '+str(removeEpochsRatio)+'%', ln=0, align='L', border=1)
        pdf.set_text_color(0, 0, 0)
        pdf.cell(24, line_height, text=' ', ln=1, align='L', border=1)

        # 振幅
        pdf.cell(30, line_height, text='', ln=0, align='L')
        pdf.cell(70, line_height, text=' Amplitudes(μV)', ln=0, align='L', border=1)
        # text='α: '+str(round(amplitudes[0], 1))+' β: '+str(round(amplitudes[1], 1))+' θ: '+str(round(amplitudes[2], 1))+' δ: '+str(round(amplitudes[3], 1))
        pdf.cell(17, line_height, text='α: '+str(round(amplitudes['alpha'], 1)), ln=0, align='L', border=1)
        pdf.cell(17, line_height, text='β: '+str(round(amplitudes['beta'], 1)), ln=0, align='L', border=1)
        pdf.cell(17, line_height, text='θ: '+str(round(amplitudes['theta'], 1)), ln=0, align='L', border=1)
        pdf.cell(19, line_height, text='δ: '+str(round(amplitudes['delta'], 1)), ln=1, align='L', border=1)


        
        # 慢波比例
        pdf.cell(30, line_height, text='', ln=0, align='L')
        pdf.cell(70, line_height, text=' Slow wave ratio', ln=0, align='L', border=1)
        pdf.cell(23, line_height, text=' Right', ln=0, align='L', border=1)
        pdf.cell(23, line_height, text=' Left', ln=0, align='L', border=1)
        pdf.cell(24, line_height, text=' Total', ln=1, align='L', border=1)

        #  左右、總慢波比例
        pdf.cell(30, line_height, text='', ln=0, align='L')
        pdf.cell(70, line_height, text=' <60', ln=0, align='R', border=1)
        color= (0, 0, 0)
        if right_slow_ratio>=60:
            color=(255, 0, 0)
        pdf.set_text_color(*color)
        pdf.cell(23, line_height, text=' '+str(right_slow_ratio)+'%', ln=0, align='L', border=1)
        color= (0, 0, 0)
        if left_slow_ratio>=60:
            color=(255, 0, 0)
        pdf.set_text_color(*color)
        pdf.cell(23, line_height, text=' '+str(left_slow_ratio)+'%', ln=0, align='L', border=1)
        color= (0, 0, 0)
        if total_slow_ratio>=60:
            color=(255, 0, 0)
        pdf.set_text_color(*color)
        pdf.cell(24, line_height, text=' '+str(total_slow_ratio)+'%', ln=1, align='L', border=1)
        pdf.set_text_color(0, 0, 0)

        # 快波比例
        pdf.cell(30, line_height, text='', ln=0, align='L')
        pdf.cell(70, line_height, text=' Beta wave ratio', ln=0, align='L', border=1)
        pdf.cell(23, line_height, text=' Right', ln=0, align='L', border=1)
        pdf.cell(23, line_height, text=' Left', ln=0, align='L', border=1)
        pdf.cell(24, line_height, text=' Total', ln=1, align='L', border=1)

        #  左右、
        pdf.cell(30, line_height, text='', ln=0, align='L')
        pdf.cell(70, line_height, text=' <30', ln=0, align='R', border=1)
        color= (0, 0, 0)
        if right_beta_ratio>=30:
            color=(255, 0, 0)
        pdf.set_text_color(*color)

        pdf.cell(23, line_height, text=' '+str(right_beta_ratio)+'%', ln=0, align='L', border=1)
        color= (0, 0, 0)
        if left_beta_ratio>=30:
            color=(255, 0, 0)
        pdf.set_text_color(*color)
        pdf.cell(23, line_height, text=' '+str(left_beta_ratio)+'%', ln=0, align='L', border=1)
        color= (0, 0, 0)
        if total_beta_ratio>=30:
            color=(255, 0, 0)
        pdf.set_text_color(*color)
        pdf.cell(24, line_height, text=' '+str(total_beta_ratio)+'%', ln=1, align='L', border=1)
        pdf.set_text_color(0, 0, 0)

        # 前後gradient
        pdf.cell(30, line_height, text='', ln=0, align='L')
        pdf.cell(70, line_height, text=' AP gradient', ln=0, align='L', border=1)
        pdf.cell(23, line_height, text=' Right', ln=0, align='L', border=1)
        pdf.cell(23, line_height, text=' Left', ln=0, align='L', border=1)
        pdf.cell(24, line_height, text=' Total', ln=1, align='L', border=1)

        pdf.cell(30, line_height, text='', ln=0, align='L')
        pdf.cell(70, line_height, text=' <40', ln=0, align='R', border=1)
        color= (0, 0, 0)
        if right_AP_difference>=40:
            color=(255, 0, 0)
        pdf.set_text_color(*color)
        pdf.cell(23, line_height, text=' '+str(right_AP_difference)+'%', ln=0, align='L', border=1)
        pdf.set_text_color(0, 0, 0)
        color= (0, 0, 0)
        if left_AP_difference>=40:
            color=(255, 0, 0)
        pdf.set_text_color(*color)
        pdf.cell(23, line_height, text=' '+str(left_AP_difference)+'%', ln=0, align='L', border=1)
        color= (0, 0, 0)
        if AP_difference>=40:
            color=(255, 0, 0)
        pdf.set_text_color(*color)
        pdf.cell(24, line_height, text=' '+str(AP_difference)+'%', ln=1, align='L', border=1)
        pdf.set_text_color(0, 0, 0)

        # O1, O2 主頻率
        pdf.cell(30, line_height, text='', ln=0, align='L')
        pdf.cell(70, line_height, text=' Background peak', ln=0, align='L', border=1)
        color= (0, 0, 0)
        if left_backgroud_frequency<8:
            color=(255, 0, 0)
        pdf.set_text_color(*color)
        pdf.cell(23, line_height, text=' '+str(right_backgroud_frequency), ln=0, align='L', border=1)
        color= (0, 0, 0)
        if right_backgroud_frequency<8:
            color=(255, 0, 0)
        pdf.cell(23, line_height, text=' '+str(left_backgroud_frequency), ln=0, align='L', border=1)
        pdf.set_text_color((0, 0, 0))
        pdf.cell(24, line_height, text=' >=8', ln=1, align='L', border=1)

        # O1, O2 主頻率差異
        fDiff=left_backgroud_frequency-right_backgroud_frequency
        pdf.cell(30, line_height, text='', ln=0, align='L')
        pdf.cell(70, line_height, text=' Background difference', ln=0, align='L', border=1)
        color= (0, 0, 0)
        if abs(fDiff)>0.5:
            color=(255, 0, 0)
        pdf.set_text_color(*color)
        pdf.cell(46, line_height, text=' '+str(round(abs(fDiff), 2)), ln=0, align='L', border=1)
        pdf.set_text_color(0, 0, 0)
        pdf.cell(24, line_height, text='<=0.5', ln=1, align='L', border=1)

        # 左右channel差異，列出異常channel
        # for ab in abnormals:
        #     st=','.join(abnormals[ab]) 
        #     # pdf.cell(200, line_height, text=ab+': '+st, ln=1, align='C')
        #     pdf.cell(30, line_height, text='', ln=0, align='L')
        #     pdf.cell(70, line_height, text=' '+ab, ln=0, align='L', border=1)
        #     pdf.set_text_color(255, 0, 0)
        #     pdf.cell(70, line_height, text=' '+st, ln=1, align='L', border=1)
        #     pdf.set_text_color(0, 0, 0)

        
        # bad channels
        pdf.cell(30, line_height, text='', ln=0, align='L')
        pdf.cell(70, line_height, text=' Bad electrodes', ln=0, align='L', border=1)
        pdf.set_text_color(255, 0, 0)
        pdf.cell(70, line_height, text=' '+','.join(bad_channels), ln=1, align='L', border=1)   
        pdf.set_text_color(0, 0, 0)


        # 新增頁面
        pdf.add_page(orientation = 'L')
        # set page horizontal    
        # eeg5.jpg
        pdf.cell(0, line_height, text='EEG, 4s/epochs', ln=1, align='C')
        # A square figure at full landscape width would be 280 mm tall on a
        # 210 mm page, so it has to be fitted to the height as well.
        self._placeImage(pdf, self.dest_folder + 'eeg5.jpg', top=20)

        # 第二頁
        pdf.add_page()
        pdf.set_font(fontName, size=18)
        # 標題
        pdf.cell(0, 20, text='Topography and Power Spectrum', ln=1, align='C')
        self._placeImage(pdf, self.dest_folder + 'eeg3.jpg', top=25)

        # 第三頁
        pdf.add_page()
        pdf.set_font(fontName, size=18)
        # 標題
        pdf.cell(0, 20, text='Spectrogram', ln=1, align='C')
        self._placeImage(pdf, self.dest_folder + 'eeg4.jpg', top=25)
        self.writePdrPage(pdf, fontName, line_height, wanted('pdr', results.get('pdr')))
        self.writeInterictalPage(pdf, fontName, line_height, wanted('interictal', results.get('interictal')))
        self.writeEpisodesPage(pdf, fontName, line_height, wanted('episodes', (results.get('spikeseizure') or {}).get('episodes')))
        self.writeSleepPage(pdf, fontName, line_height, wanted('sleep', results.get('sleep')))
        self.writeArtifactPage(pdf, fontName, line_height, wanted('artifacts', results.get('artifacts')))
        self.writeConclusionPage(pdf, fontName, line_height, wanted('conclusion', results.get('conclusion')))
        self.writeAiPage(pdf, fontName, line_height, wanted('conclusion', results.get('conclusion')))

        # splitext, not split('.'): a study called
        # 'Surname, Given 2024.01.15.eeg' truncated at the first dot, and any
        # caller that reconstructed the name the other way looked for a file
        # that was never written.
        outFile=os.path.join(self.dest_folder,
                             os.path.splitext(self.fileName)[0]+'.pdf')
        pdf.output(outFile)
        # Recorded so callers use the path that was actually written instead of
        # rebuilding it and having to agree about how names are truncated.
        self.outFile=os.path.abspath(outFile)
        print ('Successfully generate pdf file: ', outFile)
        return self.outFile
        # open pdf file
        # os.system('start '+ outFile)
        
    
    def writePdrPage(self, pdf, fontName, line_height, pdrResult):
        """A page for the posterior dominant rhythm, scored against SCORE.

        One row per SCORE property, carrying the scored term, the measurement it
        came from, and how much to trust it. A property the recording cannot
        answer says so, which SCORE treats as a real choice rather than a blank.
        """
        if not pdrResult:
            return

        pdf.add_page(orientation='P')
        pdf.set_font(fontName, size=18)
        pdf.cell(196, line_height, text='Posterior Dominant Rhythm', ln=1, align='C')
        pdf.set_font(fontName, size=10)
        pdf.cell(196, line_height - 2,
                 text='Scored against SCORE (Beniczky et al., Clin Neurophysiol 2017), Table 4',
                 ln=1, align='C')
        pdf.ln(2)

        widths = (46, 62, 22, 66)
        rowHeight = line_height - 1
        pdf.set_font(fontName, size=9)
        pdf.set_fill_color(232, 234, 240)
        self._row(pdf, list(zip(('Property', 'Scored term', 'Confidence', 'Measured'),
                                widths)), rowHeight, fill=True)

        for key, label in pdrScore.PROPERTY_ORDER:
            prop = pdrResult.get(key)
            if not prop:
                continue
            term = prop['term'] or '(not applicable)'
            if prop.get('provisional'):
                term += ' *'
            # Abnormal findings and unscorable properties are the two things a
            # reader must not skim past, so they are the only coloured rows.
            if term.startswith('Abnormal') or 'Reduced' in term:
                pdf.set_text_color(170, 0, 0)
            elif prop['term'] == pdrScore.NOT_DETERMINED:
                pdf.set_text_color(120, 120, 120)
            else:
                pdf.set_text_color(0, 0, 0)

            measured = self._formatPdrValue(prop.get('value'))
            self._row(pdf, ((label, widths[0]), (term, widths[1]),
                            (prop.get('confidence', ''), widths[2]),
                            (measured, widths[3])), rowHeight)
            pdf.set_text_color(0, 0, 0)

            # The measurement in full when the cell had to truncate it, then the
            # basis - both wrapped, indented under the property name.
            detail = prop.get('basis') or ''
            if measured and pdf.get_string_width(measured) > widths[3] - 2.5:
                detail = ('%s. %s' % (measured, detail)) if detail else measured
            self._subLine(pdf, fontName, detail, widths[0], line_height - 3.5)
            pdf.set_font(fontName, size=9)

        pdf.set_text_color(0, 0, 0)
        pdf.ln(3)

        measures = pdrResult.get('measures') or {}
        if measures:
            pdf.set_font(fontName, size=11)
            pdf.cell(196, line_height - 1, text='Underlying measurements', ln=1, align='L')
            pdf.set_font(fontName, size=9)
            for text in self._pdrMeasureLines(measures, pdrResult.get('age_source')):
                pdf.cell(196, line_height - 2.5, text=text, ln=1, align='L')

        notes = list(pdrResult.get('notes') or [])
        if any(p and p.get('provisional') for p in pdrResult.values() if isinstance(p, dict)):
            notes.append('* Provisional: derived from uncalibrated thresholds. '
                         'Confirm visually before accepting.')
        if notes:
            pdf.ln(2)
            pdf.set_font(fontName, size=11)
            pdf.cell(196, line_height - 1, text='Notes', ln=1, align='L')
            pdf.set_font(fontName, size=9)
            for note in notes:
                pdf.multi_cell(196, line_height - 2.5, text='- ' + note, align='L')
                pdf.set_x(pdf.l_margin)

        # Anything the reader changed, named. The measurement table earlier in
        # the report is unchanged - it reports what was measured - so without
        # this a reader would find two different numbers for one property and
        # nothing to explain the difference.
        overridden = [(key, entry) for key, entry in (pdrResult or {}).items()
                      if isinstance(entry, dict) and entry.get('overridden')]
        if overridden:
            pdf.ln(2)
            pdf.set_font(fontName, size=11)
            self._row(pdf, [('Overridden by the reader', 196)], line_height - 1)
            pdf.set_font(fontName, size=9)
            for key, entry in overridden:
                self._subLine(pdf, fontName,
                              '%s: reported as %s; measured %s'
                              % (key.replace('_', ' '), entry.get('term'),
                                 entry.get('measured_term')),
                              4, line_height - 3.5)
            pdf.set_font(fontName, size=9)

    def writeConclusionPage(self, pdf, fontName, line_height, conclusion):
        """SCORE sections 15 and 17: diagnostic significance, summary, comments.

        The significance is rendered as a proposal awaiting confirmation, and
        never as a scored value. SCORE makes it the mandatory last step for the
        electroencephalographer, taken in the clinical context - which is
        precisely what an automated analysis does not have.
        """
        if not conclusion:
            return

        pdf.add_page(orientation='P')
        pdf.set_font(fontName, size=18)
        pdf.cell(196, line_height, text='Diagnostic Significance', ln=1, align='C')
        pdf.set_font(fontName, size=10)
        pdf.cell(196, line_height - 2,
                 text='SCORE sections 15 and 17 - proposed from the structured '
                      'findings, for confirmation', ln=1, align='C')
        pdf.ln(3)

        # A banner, because the single most important thing about this page is
        # that nothing on it has been signed.
        pdf.set_fill_color(246, 237, 220)
        pdf.set_draw_color(140, 90, 15)
        pdf.set_text_color(120, 75, 10)
        pdf.set_font(fontName, size=10)
        pdf.set_x(pdf.l_margin)
        pdf.multi_cell(196, line_height - 2, border=1, fill=True, align='L',
                       text='  NOT A SCORED CONCLUSION. Diagnostic significance is '
                            'the electroencephalographer\'s, taken last and in the '
                            'clinical context. The proposal below is drawn only from '
                            'the structured findings in this report - there is no '
                            'clinical history, referral question or imaging behind '
                            'it. Confirm, amend or replace it before signing.')
        pdf.set_x(pdf.l_margin)
        pdf.set_text_color(0, 0, 0)
        pdf.set_draw_color(0, 0, 0)
        pdf.ln(3)

        if conclusion.get('status') == 'unparsed':
            pdf.set_font(fontName, size=11)
            pdf.cell(196, line_height, text='Proposal could not be read', ln=1, align='L')
            pdf.set_font(fontName, size=9)
            for note in conclusion.get('notes') or []:
                pdf.multi_cell(196, line_height - 2.5, text='- ' + note, align='L')
                pdf.set_x(pdf.l_margin)
            raw = (conclusion.get('raw') or '').strip()
            if raw:
                pdf.ln(1)
                pdf.multi_cell(196, line_height - 3, text=raw[:3000], align='L')
                pdf.set_x(pdf.l_margin)
            return

        widths = (52, 124, 20)
        rowHeight = line_height - 1
        pdf.set_font(fontName, size=9)
        pdf.set_fill_color(232, 234, 240)
        self._row(pdf, list(zip(('Property', 'Proposed term', 'Confidence'), widths)),
                  rowHeight, fill=True)

        category = conclusion.get('category') or '(none proposed - reader to score)'
        if category.startswith('Abnormal'):
            pdf.set_text_color(170, 0, 0)
        self._row(pdf, (('Significance', widths[0]), (category, widths[1]),
                        (conclusion.get('confidence') or '', widths[2])), rowHeight)
        pdf.set_text_color(0, 0, 0)

        yields = conclusion.get('yields') or []
        if yields:
            for y in yields:
                self._row(pdf, (('Diagnostic yield', widths[0]), (y, widths[1]),
                                ('', widths[2])), rowHeight)
                if pdf.get_string_width(y) > widths[1] - 2.5:
                    self._subLine(pdf, fontName, y, widths[0], line_height - 3.5)
                    pdf.set_font(fontName, size=9)
        elif category.startswith('Abnormal'):
            self._row(pdf, (('Diagnostic yield', widths[0]),
                            ('(none supportable - reader to score)', widths[1]),
                            ('', widths[2])), rowHeight)

        basis = conclusion.get('basis') or []
        if basis:
            pdf.ln(2)
            pdf.set_font(fontName, size=11)
            pdf.cell(196, line_height - 1, text='Based on', ln=1, align='L')
            pdf.set_font(fontName, size=9)
            for item in basis:
                pdf.multi_cell(196, line_height - 2.5, text='- ' + str(item), align='L')
                pdf.set_x(pdf.l_margin)

        for title, key in (('Summary of findings', 'summary_of_findings'),
                           ('Clinical comments', 'clinical_comments')):
            body = (conclusion.get(key) or '').strip()
            if not body:
                continue
            pdf.ln(2)
            pdf.set_font(fontName, size=11)
            pdf.cell(196, line_height - 1, text=title, ln=1, align='L')
            pdf.set_font(fontName, size=10)
            pdf.multi_cell(196, line_height - 2, text=body, align='L')
            pdf.set_x(pdf.l_margin)

        notes = conclusion.get('notes') or []
        if notes:
            pdf.ln(2)
            pdf.set_font(fontName, size=11)
            pdf.cell(196, line_height - 1, text='Notes', ln=1, align='L')
            pdf.set_font(fontName, size=9)
            for note in notes:
                pdf.multi_cell(196, line_height - 2.5, text='- ' + note, align='L')
                pdf.set_x(pdf.l_margin)

        # Somewhere for the reader to actually take it over.
        pdf.ln(4)
        pdf.set_font(fontName, size=11)
        pdf.cell(196, line_height - 1, text='For completion by the reader', ln=1,
                 align='L')
        pdf.set_font(fontName, size=10)
        for label in ('Diagnostic significance as scored',
                      'Clinical correlation', 'Electroencephalographer', 'Date'):
            pdf.set_x(pdf.l_margin)
            pdf.cell(60, line_height, text='   ' + label, border=0, align='L')
            pdf.cell(136, line_height, text='', border='B', align='L')
            pdf.ln(line_height)
        pdf.set_font(fontName, size=8)
        pdf.set_text_color(105, 105, 105)
        pdf.set_x(pdf.l_margin)
        pdf.multi_cell(196, line_height - 3.5, align='L',
                       text='Drafted by %s. Sections 2 and 3 are free text under '
                            'SCORE and were written from the structured findings '
                            'only; the significance terms above are SCORE database '
                            'codes and are reproduced verbatim.'
                            % (conclusion.get('model') or 'a language model'))
        pdf.set_x(pdf.l_margin)
        pdf.set_text_color(0, 0, 0)

    def writeAiPage(self, pdf, fontName, line_height, conclusion=None):
        """The free-text LLM narrative from the original pipeline.

        Suppressed once a SCORE conclusion has been produced. The two overlap
        almost entirely, and a report carrying two independently generated
        conclusions can carry two different ones. The SCORE page is the
        constrained version - its terms come from a fixed list and it is
        forbidden from stating numbers absent from the findings, which this
        narrative is not: it has been observed inventing an amplitude range.
        Kept as the fallback for when the conclusion could not be parsed.
        """
        if not self.ai_report_text:
            return
        if conclusion and conclusion.get('status') == 'proposed':
            print('AI narrative page suppressed - the SCORE conclusion page '
                  'supersedes it')
            return
        pdf.add_page()
        pdf.set_font(fontName, size=18)
        pdf.cell(196, line_height, text='EEG AI Analysis', ln=1, align='C')
        # Underline the title at the current cursor rather than a fixed y - the
        # old fixed y=20 sat below the title but above the body, so the rule was
        # drawn straight through the first line of text.
        pdf.set_draw_color(0, 0, 0)
        pdf.set_line_width(0.4)
        ruleY = pdf.get_y() + 1
        pdf.line(pdf.l_margin, ruleY, pdf.w - pdf.r_margin, ruleY)
        pdf.set_y(ruleY + 3)
        pdf.set_font(fontName, size=12)
        pdf.set_x(pdf.l_margin)
        pdf.multi_cell(196, line_height - 1.5, text=self.ai_report_text, align='L')
        pdf.set_x(pdf.l_margin)
    def writeRecordingPage(self, pdf, fontName, line_height, described):
        """SCORE's patient and recording-conditions sections.

        Pure metadata, so nothing here is a proposal. The fields a technologist
        observes rather than the signal shows are listed as outstanding rather
        than guessed.
        """
        if not described:
            return

        pdf.add_page(orientation='P')
        pdf.set_font(fontName, size=18)
        pdf.cell(196, line_height, text='EEG Report - ' + self.fileName, ln=1, align='C')
        pdf.set_font(fontName, size=10)
        pdf.cell(196, line_height - 2,
                 text='Sections follow SCORE (Beniczky et al., Clin Neurophysiol 2017)',
                 ln=1, align='C')
        pdf.ln(3)

        def section(title, rows):
            pdf.set_font(fontName, size=13)
            pdf.set_x(pdf.l_margin)
            pdf.cell(196, line_height, text=title, ln=1, align='L')
            pdf.set_font(fontName, size=10)
            for label, value in rows:
                pdf.set_x(pdf.l_margin)
                pdf.cell(58, line_height - 1.5, text='   ' + label, border=0, align='L')
                # multi_cell leaves x at the right-hand edge, so the next label
                # would otherwise start at the page margin.
                pdf.multi_cell(138, line_height - 1.5, text=str(value), border=0,
                               align='L')
                pdf.set_x(pdf.l_margin)
            pdf.ln(2)

        section('Patient information', list(described['patient'].items()))
        section('Recording conditions', list(described['conditions'].items()))

        if described.get('duration_lines'):
            pdf.set_font(fontName, size=13)
            pdf.cell(196, line_height, text='Duration examined', ln=1, align='L')
            pdf.set_font(fontName, size=10)
            for line in described['duration_lines']:
                pdf.multi_cell(196, line_height - 1.5, text='   ' + line, align='L')
                pdf.set_x(pdf.l_margin)
            pdf.set_font(fontName, size=8)
            pdf.set_text_color(105, 105, 105)
            pdf.multi_cell(196, line_height - 3.5, align='L',
                           text='   Rates elsewhere in this report - how often an event '
                                'occurs, what fraction of the recording a pattern covers - '
                                'are taken over the analysed duration, not the recorded '
                                'length.')
            pdf.set_x(pdf.l_margin)
            pdf.set_text_color(0, 0, 0)
            pdf.ln(2)

        outstanding = described.get('technologist_fields') or []
        if outstanding:
            pdf.set_font(fontName, size=13)
            pdf.cell(196, line_height, text='For completion by the reader', ln=1, align='L')
            pdf.set_font(fontName, size=10)
            for field in outstanding:
                pdf.cell(196, line_height - 1.5, text='   - ' + field, ln=1, align='L')
            pdf.set_font(fontName, size=8)
            pdf.set_text_color(105, 105, 105)
            pdf.multi_cell(196, line_height - 3.5, align='L',
                           text='   Observed at the bedside rather than derivable from the '
                                'signal, so they are left blank rather than assumed. '
                                'Referral details, modulators and procedures, and the '
                                'diagnostic significance are likewise the reader\'s.')
            pdf.set_x(pdf.l_margin)
            pdf.set_text_color(0, 0, 0)

        notes = described.get('notes') or []
        if notes:
            pdf.ln(2)
            pdf.set_font(fontName, size=13)
            pdf.cell(196, line_height, text='Notes', ln=1, align='L')
            pdf.set_font(fontName, size=9)
            for note in notes:
                pdf.multi_cell(196, line_height - 2.5, text='- ' + note, align='L')
                pdf.set_x(pdf.l_margin)

    def writeInterictalPage(self, pdf, fontName, line_height, interictalResult):
        """SCORE's Interictal findings folder - abnormal rhythmic activity.

        The focal and diffuse slowing the pipeline has always computed, now with
        a location and a prevalence band instead of a record-wide average, since
        intermittent and continuous slowing mean different things.
        """
        if not interictalResult:
            return

        pdf.add_page(orientation='P')
        pdf.set_font(fontName, size=18)
        pdf.cell(196, line_height, text='Interictal Findings', ln=1, align='C')
        pdf.set_font(fontName, size=10)
        pdf.cell(196, line_height - 2,
                 text='Scored against SCORE (Beniczky et al., Clin Neurophysiol 2017), '
                      'Table 5 - abnormal interictal rhythmic activity', ln=1, align='C')
        pdf.ln(3)

        findings = interictalResult.get('findings') or []
        if not findings:
            pdf.set_font(fontName, size=11)
            pdf.cell(196, line_height,
                     text='No abnormal interictal rhythmic activity reported.',
                     ln=1, align='L')
        else:
            widths = (34, 52, 44, 46, 20)
            rowHeight = line_height - 1
            pdf.set_font(fontName, size=9)
            pdf.set_fill_color(232, 234, 240)
            self._row(pdf, list(zip(('Activity', 'Location', 'Prevalence',
                                     'Mode of appearance', 'Conf.'), widths)),
                      rowHeight, fill=True)
            for f in findings:
                location = f['location']['text']
                mode = f.get('mode_of_appearance') or ''
                # Rhythmic activity is banded by prevalence, discrete
                # discharges by incidence; show whichever the finding carries.
                timing = f.get('prevalence') or f.get('incidence') or ''
                if f.get('count'):
                    timing = ('%s (%d)' % (timing, f['count'])) if timing else str(f['count'])
                self._row(pdf, ((f['name'], widths[0]), (location, widths[1]),
                                (timing, widths[2]),
                                (mode, widths[3]),
                                (f.get('confidence', ''), widths[4])), rowHeight)
                # Location and the timing evidence in full underneath, since both
                # are longer than any sensible column.
                parts = []
                if pdf.get_string_width(location) > widths[1] - 2.5:
                    parts.append(location)
                if f.get('discharge_pattern'):
                    parts.append('Discharge pattern: %s' % f['discharge_pattern'])
                if f.get('timing_basis'):
                    parts.append(f['timing_basis'])
                if f.get('basis'):
                    parts.append(f['basis'])
                self._subLine(pdf, fontName, '. '.join(parts), widths[0],
                              line_height - 3.5)
                pdf.set_font(fontName, size=9)

        measures = interictalResult.get('measures') or {}
        if measures:
            pdf.ln(3)
            pdf.set_font(fontName, size=11)
            pdf.cell(196, line_height - 1, text='Underlying measurements', ln=1,
                     align='L')
            pdf.set_font(fontName, size=9)
            labels = [
                ('epochs', 'Epochs analysed', '%s'),
                ('analysed_seconds', 'Seconds analysed', '%s s'),
                ('diffuse_slow_percent', 'Mean slow (1.5-8 Hz) fraction', '%s%%'),
                ('beta_percent', 'Mean beta (13-30 Hz) fraction', '%s%%'),
            ]
            for key, label, fmt in labels:
                if measures.get(key) is not None:
                    pdf.cell(196, line_height - 2.5,
                             text='   %s: %s' % (label, fmt % measures[key]),
                             ln=1, align='L')

        pdf.ln(2)
        pdf.set_font(fontName, size=9)
        pdf.set_text_color(105, 105, 105)
        pdf.multi_cell(196, line_height - 3.5, align='L',
                       text='Mode of appearance compares the intervals between '
                            'occurrences with the intervals expected if the same number '
                            'were scattered at random over the same epochs: more regular '
                            'than chance is scored periodic, less regular is scored '
                            'variable, and anything between is random. Occurrences are '
                            'grouped on the clock rather than by epoch index, because '
                            'discarded artifact epochs leave gaps. Epileptiform activity '
                            'is not detected at all and remains entirely for the reader; '
                            'the findings above are rhythmic-activity abnormalities only.')
        pdf.set_x(pdf.l_margin)
        pdf.set_text_color(0, 0, 0)

        notes = interictalResult.get('notes') or []
        if notes:
            pdf.ln(1)
            pdf.set_font(fontName, size=11)
            pdf.cell(196, line_height - 1, text='Notes', ln=1, align='L')
            pdf.set_font(fontName, size=9)
            for note in notes:
                pdf.multi_cell(196, line_height - 2.5, text='- ' + note, align='L')
                pdf.set_x(pdf.l_margin)

    def writeEpisodesPage(self, pdf, fontName, line_height, episodes):
        """SCORE's Episodes folder - electrographic seizures only.

        SCORE's episode template is built around the electro-clinical
        correlation: semiology, three phases, evolution of the ictal pattern.
        A detector supplies none of that, so what appears here is the
        electrographic half and the rest is marked as the reader's.
        """
        if not episodes:
            return

        pdf.add_page(orientation='P')
        pdf.set_font(fontName, size=18)
        pdf.cell(196, line_height, text='Episodes', ln=1, align='C')
        pdf.set_font(fontName, size=10)
        pdf.cell(196, line_height - 2,
                 text='Scored against SCORE (Beniczky et al., Clin Neurophysiol 2017), '
                      'section 10 - electrographic findings only', ln=1, align='C')
        pdf.ln(3)

        widths = (56, 52, 24, 44, 20)
        rowHeight = line_height - 1
        pdf.set_font(fontName, size=9)
        pdf.set_fill_color(232, 234, 240)
        self._row(pdf, list(zip(('Episode', 'Location', 'Onset', 'Duration',
                                 'Conf.'), widths)), rowHeight, fill=True)
        for e in episodes:
            onset = e.get('onset_seconds')
            duration = e.get('duration_seconds')
            self._row(pdf, ((e['name'], widths[0]),
                            (e['location']['text'], widths[1]),
                            ('' if onset is None else '%.0f s' % onset, widths[2]),
                            (e.get('duration_band') or (
                                '' if duration is None else '%.0f s' % duration),
                             widths[3]),
                            (e.get('confidence', ''), widths[4])), rowHeight)
            detail = []
            if duration is not None:
                detail.append('duration %.0f s' % duration)
            if e['location']['text'] and pdf.get_string_width(
                    e['location']['text']) > widths[1] - 2.5:
                detail.append(e['location']['text'])
            if e.get('basis'):
                detail.append(e['basis'])
            self._subLine(pdf, fontName, '. '.join(detail), widths[0],
                          line_height - 3.5)
            pdf.set_font(fontName, size=9)

        pdf.ln(3)
        pdf.set_font(fontName, size=11)
        pdf.cell(196, line_height - 1, text='For completion by the reader', ln=1,
                 align='L')
        pdf.set_font(fontName, size=10)
        for field in ('Seizure type (ILAE classification)',
                      'Semiology and its somatotopic modifiers',
                      'Ictal EEG pattern and its evolution',
                      'Clinical-EEG temporal relationship',
                      'Consciousness and awareness',
                      'Postictal findings'):
            pdf.set_x(pdf.l_margin)
            pdf.cell(196, line_height - 1.5, text='   - ' + field, ln=1, align='L')
        pdf.set_font(fontName, size=8)
        pdf.set_text_color(105, 105, 105)
        pdf.set_x(pdf.l_margin)
        pdf.multi_cell(196, line_height - 3.5, align='L',
                       text='   These need the video and the clinical record, so they '
                            'are left blank rather than assumed. An episode detected '
                            'electrographically is not by itself an epileptic seizure.')
        pdf.set_x(pdf.l_margin)
        pdf.set_text_color(0, 0, 0)

    def writeSleepPage(self, pdf, fontName, line_height, sleep):
        """SCORE's Sleep and drowsiness folder."""
        if not sleep:
            return

        pdf.add_page(orientation='P')
        pdf.set_font(fontName, size=18)
        pdf.cell(196, line_height, text='Sleep and Drowsiness', ln=1, align='C')
        pdf.set_font(fontName, size=10)
        pdf.cell(196, line_height - 2,
                 text='Scored against SCORE (Beniczky et al., Clin Neurophysiol 2017), '
                      'section 7 - staged by %s' % (sleep.get('backend') or '?'),
                 ln=1, align='C')
        pdf.ln(3)

        pdf.set_font(fontName, size=11)
        pdf.set_x(pdf.l_margin)
        pdf.cell(58, line_height - 1.5, text='   Finding', align='L')
        pdf.multi_cell(138, line_height - 1.5, text=str(sleep.get('term') or ''), align='L')
        pdf.set_x(pdf.l_margin)
        if sleep.get('stages_achieved'):
            pdf.cell(58, line_height - 1.5, text='   Stages achieved', align='L')
            pdf.multi_cell(138, line_height - 1.5,
                           text=', '.join(sleep['stages_achieved']), align='L')
            pdf.set_x(pdf.l_margin)
        if sleep.get('derivation'):
            pdf.cell(58, line_height - 1.5, text='   Staged from', align='L')
            pdf.multi_cell(138, line_height - 1.5, text=str(sleep['derivation']), align='L')
            pdf.set_x(pdf.l_margin)
        pdf.ln(2)

        stats = sleep.get('statistics') or {}
        if 'sleep_onset_minutes' in stats:
            pdf.set_font(fontName, size=10)
            pdf.cell(196, line_height - 1.5,
                     text='   Time to first non-wake epoch: %.1f min'
                          % stats['sleep_onset_minutes'], ln=1, align='L')

        # Hypnogram summary: minutes and share per stage.
        widths = (34, 40, 40, 82)
        rowHeight = line_height - 1
        pdf.set_font(fontName, size=9)
        pdf.set_fill_color(232, 234, 240)
        self._row(pdf, list(zip(('Stage', 'Epochs', 'Minutes', 'Share of recording'),
                                widths)), rowHeight, fill=True)
        import sleepstage
        for stage in sleepstage.USLEEP_STAGES:
            s = stats.get(stage)
            if not s or not s.get('epochs'):
                continue
            self._row(pdf, ((stage, widths[0]), (str(s['epochs']), widths[1]),
                            ('%.1f' % s['minutes'], widths[2]),
                            ('%.1f%%' % s['percent'], widths[3])), rowHeight)
        pdf.ln(3)

        grapho = sleep.get('graphoelements') or []
        pdf.set_font(fontName, size=11)
        pdf.cell(196, line_height - 1, text='Sleep graphoelements', ln=1, align='L')
        if not grapho:
            pdf.set_font(fontName, size=10)
            pdf.cell(196, line_height - 1.5,
                     text='   None detected.', ln=1, align='L')
        else:
            widths = (52, 60, 64, 20)
            pdf.set_font(fontName, size=9)
            pdf.set_fill_color(232, 234, 240)
            self._row(pdf, list(zip(('Graphoelement', 'Location', 'Incidence',
                                     'Confidence'), widths)), rowHeight, fill=True)
            for f in grapho:
                name = f['name'] + (' *' if f.get('provisional') else '')
                incidence = f.get('incidence') or ''
                if f.get('count'):
                    incidence = '%s (%d)' % (incidence, f['count'])
                self._row(pdf, ((name, widths[0]), (f['location']['text'], widths[1]),
                                (incidence, widths[2]),
                                (f.get('confidence', ''), widths[3])), rowHeight)
                self._subLine(pdf, fontName, f.get('basis'), widths[0], line_height - 3.5)
                pdf.set_font(fontName, size=9)

        if sleep.get('undetected'):
            pdf.ln(2)
            pdf.set_font(fontName, size=9)
            pdf.set_text_color(105, 105, 105)
            pdf.multi_cell(196, line_height - 3.5, align='L',
                           text='Not detected, and left for the reader: %s. Sleep '
                                'architecture (normal or abnormal), and the significance '
                                'of any absent or asymmetric graphoelement, are scored '
                                'separately by SCORE and are clinical judgements.'
                                % ', '.join(sleep['undetected']))
            pdf.set_x(pdf.l_margin)
            pdf.set_text_color(0, 0, 0)

        notes = sleep.get('notes') or []
        if notes:
            pdf.ln(1)
            pdf.set_font(fontName, size=11)
            pdf.cell(196, line_height - 1, text='Notes', ln=1, align='L')
            pdf.set_font(fontName, size=9)
            for note in notes:
                pdf.multi_cell(196, line_height - 2.5, text='- ' + note, align='L')
                pdf.set_x(pdf.l_margin)

    def writeArtifactPage(self, pdf, fontName, line_height, artifactResult):
        """A page for the artifact types found, in SCORE's vocabulary.

        Type, location and how much of the recording each covers. Significance -
        whether an artifact leaves the recording uninterpretable, of reduced
        value, or unaffected - is scored separately by SCORE and is the reader's
        call, so it is not proposed here.
        """
        if not artifactResult:
            return

        pdf.add_page(orientation='P')
        pdf.set_font(fontName, size=18)
        pdf.cell(196, line_height, text='EEG Artifacts', ln=1, align='C')
        pdf.set_font(fontName, size=10)
        pdf.cell(196, line_height - 2,
                 text='Scored against SCORE (Beniczky et al., Clin Neurophysiol 2017), '
                      'Table 15 - %.0f s analysed' % artifactResult.get('analysed_seconds', 0),
                 ln=1, align='C')
        pdf.ln(2)

        findings = artifactResult.get('findings') or []
        if not findings:
            pdf.set_font(fontName, size=11)
            pdf.cell(196, line_height, text='No artifact types detected.', ln=1, align='L')
        else:
            widths = (58, 74, 44, 20)
            rowHeight = line_height - 1
            pdf.set_font(fontName, size=9)
            pdf.set_fill_color(232, 234, 240)
            self._row(pdf, list(zip(('Artifact type', 'Location',
                                     'Prevalence / incidence', 'Confidence'),
                                    widths)), rowHeight, fill=True)

            for f in findings:
                timing = f.get('prevalence') or f.get('incidence') or ''
                if f.get('count'):
                    timing = ('%s (%d)' % (timing, f['count'])) if timing else str(f['count'])
                location = f['location']['text']
                self._row(pdf, ((f['name'], widths[0]), (location, widths[1]),
                                (timing, widths[2]),
                                (f.get('confidence', ''), widths[3])), rowHeight)

                # A location naming several regions is longer than any sensible
                # column, so repeat it in full below when it had to be cut.
                detail = f.get('basis') or ''
                if pdf.get_string_width(location) > widths[1] - 2.5:
                    detail = ('%s. %s' % (location, detail)) if detail else location
                self._subLine(pdf, fontName, detail, widths[0], line_height - 3.5)
                pdf.set_font(fontName, size=9)

        pdf.ln(3)
        pdf.set_font(fontName, size=9)
        pdf.set_text_color(105, 105, 105)
        pdf.multi_cell(196, line_height - 3.5, align='L',
                       text='Significance is not proposed. SCORE scores an artifact\'s '
                            'effect on the recording separately - not interpretable, '
                            'reduced diagnostic value, or does not interfere - and that '
                            'is a clinical judgement. Types needing clinical context '
                            '(nystagmus, sucking, glossokinetic, rocking or patting, '
                            'dialysis, artificial ventilation, induction) are not '
                            'detected and remain for the reader to add.')
        pdf.set_x(pdf.l_margin)
        pdf.set_text_color(0, 0, 0)

        notes = artifactResult.get('notes') or []
        if notes:
            pdf.ln(1)
            pdf.set_font(fontName, size=11)
            pdf.cell(196, line_height - 1, text='Notes', ln=1, align='L')
            pdf.set_font(fontName, size=9)
            for note in notes:
                pdf.multi_cell(196, line_height - 2.5, text='- ' + note, align='L')
                pdf.set_x(pdf.l_margin)

    # ---------------------------------------------------------- table helpers
    # fpdf2's multi_cell leaves the cursor at the right-hand edge of the cell it
    # just drew, so anything written afterwards starts at the page margin unless
    # x is put back. Every table below goes through these two helpers so that
    # cannot be got wrong one row at a time.

    def _placeImage(self, pdf, jpgFile, maxWidth=None, maxHeight=None, top=None,
                    gap=2.0, bottomMargin=8.0):
        """Draw a figure scaled to fit the space available, aspect preserved.

        fpdf2's image() honours whichever of width or height it is given and
        derives the other from the aspect ratio, so passing only a width lets a
        tall figure run straight off the bottom of the page. That is what
        happened to the EEG traces: a square 2400x2400 figure drawn 280 mm wide
        became 280 mm tall on a landscape page with 190 mm of usable height.

        Returns the height consumed, so a page stacking several figures can pass
        the remaining space to the next one.
        """
        if not os.path.exists(jpgFile):
            print('Figure missing, skipped: %s' % jpgFile)
            return 0.0
        try:
            from PIL import Image
            with Image.open(jpgFile) as img:
                pixelWidth, pixelHeight = img.size
            aspect = pixelHeight / float(pixelWidth)
        except Exception as e:
            print('Could not measure %s (%s); drawing at width only' % (jpgFile, e))
            pdf.image(jpgFile, x=pdf.l_margin, w=maxWidth or 190)
            return 0.0

        usableWidth = pdf.w - pdf.l_margin - pdf.r_margin
        if top is None:
            top = pdf.get_y()
        maxWidth = usableWidth if maxWidth is None else min(maxWidth, usableWidth)
        available = pdf.h - bottomMargin - top
        maxHeight = available if maxHeight is None else min(maxHeight, available)
        if maxWidth <= 0 or maxHeight <= 0:
            return 0.0

        width = maxWidth
        height = width * aspect
        if height > maxHeight:
            height = maxHeight
            width = height / aspect
        # Centre whatever is left over horizontally.
        x = pdf.l_margin + (usableWidth - width) / 2.0
        pdf.image(jpgFile, x=x, y=top, w=width, h=height)
        pdf.set_y(top + height + gap)
        return height

    @staticmethod
    def _fit(pdf, text, width, padding=2.5):
        """Truncate text to fit a fixed-width cell, since cell() does not wrap."""
        text = '' if text is None else str(text)
        if pdf.get_string_width(text) <= width - padding:
            return text
        while text and pdf.get_string_width(text + '...') > width - padding:
            text = text[:-1]
        return text + '...'

    def _row(self, pdf, cells, line_height, fill=False, border=1):
        """One table row of (text, width) pairs, ending back at the left margin."""
        pdf.set_x(pdf.l_margin)
        for text, width in cells:
            pdf.cell(width, line_height, text=' ' + self._fit(pdf, text, width),
                     border=border, align='L', fill=fill)
        pdf.ln(line_height)

    def _subLine(self, pdf, fontName, text, indent, line_height, size=8):
        """A wrapped continuation line under a table row."""
        if not text:
            return
        pdf.set_font(fontName, size=size)
        pdf.set_text_color(105, 105, 105)
        pdf.set_x(pdf.l_margin + indent)
        pdf.multi_cell(196 - indent, line_height, text=str(text), border=0, align='L')
        pdf.set_x(pdf.l_margin)
        pdf.set_text_color(0, 0, 0)

    @staticmethod
    def _formatPdrValue(value):
        """Render a property's measurement compactly for the table cell."""
        if value is None:
            return ''
        if isinstance(value, dict):
            return ', '.join('%s %s' % (k, 'n/a' if v is None else v)
                             for k, v in value.items())
        if isinstance(value, float):
            return '%g' % round(value, 3)
        return str(value)

    @staticmethod
    def _pdrMeasureLines(measures, ageSource):
        """The numbers behind the scored terms, as report lines."""
        band = measures.get('pdr_band_hz')
        lines = []
        if measures.get('age_years') is not None:
            lines.append('   Age at recording: %.1f years (normal PDR floor %.1f Hz)%s'
                         % (measures['age_years'], measures.get('age_floor_hz') or 0,
                            ' - from %s' % ageSource if ageSource else ''))
        else:
            lines.append('   Age at recording: unavailable%s'
                         % (' - %s' % ageSource if ageSource else ''))
        if band:
            lines.append('   Measurement band: %g-%g Hz (centred on the measured rhythm)'
                         % (band[0], band[1]))
        lines.append('   Frequency: left %s Hz, right %s Hz; posterior spectral peak %s Hz'
                     % (measures.get('frequency_left_hz'), measures.get('frequency_right_hz'),
                        measures.get('posterior_peak_hz')))
        lines.append('   Amplitude: left %s uV, right %s uV (peak-to-peak, median epoch)'
                     % (measures.get('amplitude_left_uv'), measures.get('amplitude_right_uv')))
        lines.append('   Epochs: %s total, %s eyes-closed, %s eyes-open'
                     % (measures.get('epochs_total'), measures.get('epochs_eyes_closed'),
                        measures.get('epochs_eyes_open')))
        lines.append('   Eye state: %s' % measures.get('eye_state_basis', 'not determined'))
        lines.append('   Rhythm continuity: %s; peak-to-broadband: %s; theta/alpha: %s'
                     % (measures.get('rhythm_continuity'), measures.get('peak_prominence'),
                        measures.get('theta_alpha_ratio')))
        return lines

    def drawPsds(self, psds):   
        picks=['T5', 'T6', 'O1', 'O2', 'P3', 'P4']
        powers, freqs=psds.copy().get_data(picks=picks,  return_freqs=True, fmin=1, fmax=25)
        powers=powers*1e12
        # print(freqs)
        # print ('p.shape: ', powers.shape, 'f.shape: ', freqs.shape) #p.shape:  (6, 18) f.shape:  (18,)
        powers=10*np.log10(powers)
        
        plt.figure(figsize=(12, 3))
        plt.xlabel('Frequency [Hz]')
        plt.ylabel('Power [dB/Hz]')
        plt.title('Posterior Dominant Frequency')
        legends=[]
            
        for i in range(powers.shape[0]):
            ch_name=picks[i]
            psd=powers[i, :]
            max=np.max(psd)
            # peaks, _ = find_peaks(psd, height=0.3*max, prominence=0.3)
            # plt.plot(freqs[peaks], psd[peaks], "x" if i%2==0 else "o")
            # legends.append(ch_name+' peaks')
            # for peak in peaks:
                
            #     plt.text(freqs[peak], psd[peak], picks[i], fontsize=12)

            # print ('ch_name: ', ch_name)
            if ch_name == 'P3':
                color='blue'
            elif ch_name == 'P4':
                color='green'
            elif i%2==0:
                color='black'
            else:
                color='red'

            lineW=0.6

            if ch_name in ['O1', 'O2']:
                plt.plot(freqs, powers[i], label=ch_name, color=color, linewidth=lineW, alpha=1)
            elif ch_name in ['P3', 'P4']:
                plt.plot(freqs,  powers[i], label=ch_name, alpha=0.7, color=color, linewidth=lineW)
            else:
                plt.plot(freqs,  powers[i], label=ch_name, linestyle='--', alpha=0.5, color=color, linewidth=lineW)
            legends.append(ch_name)
        # draw x grid
        plt.grid(axis='x', linestyle='--', alpha=0.5)
        plt.xticks(np.arange(3, 25,1))
        plt.title('Posterior power sepectrum densiy', fontsize=18)
            
        # plt.show()
        plt.legend(legends)
        jpgFile=self.dest_folder+'eeg2.jpg'
        plt.savefig(jpgFile, dpi=300)
        plt.close()
    

    def drawEpochs(self, epochs):
        # 畫出epochs的圖
            epochs_sub=epochs.copy()
            # color list [black, black, darkred,
            ch_num=len(epochs_sub.ch_names)
            # colorList=['black' for i in range(ch_num) if i%2==0 else 'darkred']
            # colorList=['black', 'black', 'darkred', 'darkred'.....
            colorList=['black' if i%2==0 else 'darkred' for i in range(ch_num)]
            epoch_num=len (epochs_sub)
            colorList=[colorList]*epoch_num
                        
            fig=epochs_sub.plot(scalings={'eeg': 60e-6, 'misc':50e-6, 'seeg':50e-6}, block=False, n_epochs=6, show=False,
                        overview_mode='hidden', show_scrollbars=False, epoch_colors=colorList)
            
            # fig.grab().save('eeg5.jpg')
            jpgFile=self.dest_folder+'eeg5.jpg'
            fig.savefig(jpgFile, dpi=300)
            plt.close()


    def drawLeftRightDiff(self, diffAlpha, diffTheta, diffDelta, chNames):
        fig, ax = plt.subplots(figsize=(12,3))

        # range -1-1
        ax.set_ylim([-1, 1])

        # plot bar in separate positions
        
        aplha=0.9
        ax.bar(np.arange(len(diffDelta)), diffDelta, width=0.2, label='1-4Hz', alpha=aplha, color='salmon')
        ax.bar(np.arange(len(diffTheta)) + 0.2, diffTheta, width=0.2, label='4-8Hz', alpha=aplha, color='peachpuff')
        ax.bar(np.arange(len(diffAlpha)) + 0.4, diffAlpha, width=0.2, label='8-12Hz', alpha=aplha, color='mediumseagreen')


        ax.set_xticks(np.arange(len(diffDelta)) + 0.2)
        ax.set_xticklabels(chNames)

        # plot y=0 green, y=0.5 red y=-0.5 red
        ax.axhline(y=0, color='green', linestyle='--')
        ax.axhline(y=0.5, color='red', linestyle='--')
        ax.axhline(y=-0.5, color='red', linestyle='--')

        ax.legend()
        plt.title('Left/Right power ratio, left is positive', fontsize=18)

        # Append the figure to the list
        jpgFile=self.dest_folder+'eeg1.jpg'
        plt.savefig(jpgFile, dpi=300)
        plt.close()

    def drawFreqPower(self, psds):
        # Create a 20x25 figure
        fig = plt.figure(figsize=(20, 25))
        gs = fig.add_gridspec(4, 4)    

        # psds.plot_topomap(
        #     bands = [(1,4,'Delta'), (4,8,'Theta'), (8,13,'Alpha'), (13,30,'Beta')], show=True, 
        #     normalize=True , axes=[fig.add_subplot(gs[0, i]) for i in range(4) ], cmap='coolwarm',)
        # psds:  <Power Spectrum (from Epochs, multitaper method) | 277 epochs × 21 channels × 15 freqs, 1.0-8.0 Hz>

        
        # psds=raw_epochs.compute_psd(fmin=1, fmax=30, verbose=False, method='welch', n_fft=64, n_overlap=16, n_per_seg=64)
        def plot_psds(L1, L2, axes):
            dataL1=psds.copy().pick(L1).get_data()*1e12
            dataL2=psds.copy().pick(L2).get_data()*1e12
            freqs=psds.freqs

            axes.plot(freqs, 10*np.log10(dataL1.mean(axis=0)), color='maroon', alpha=0.7)
            axes.plot(freqs, 10*np.log10(dataL2.mean(axis=0)), color='midnightblue', alpha=0.7)
            # plot vertical grid
            axes.grid(axis='x', linestyle='--', alpha=0.5)
            

            # psds.copy().pick(chs).plot( show=True, axes=axes, color='maroon', spatial_colors=False,)
            # psds.copy().pick(L2).plot( show=True,  axes=axes, color='midnightblue', spatial_colors=False, )
            axes.set_title('Power Spectrum (PSD){}'.format(' - '.join(L1+L2)))
            axes.set_xticks(range(0, 30, 1))  # Set x-axis ticks at 1 Hz intervals
            # legend concat L1 and L2, L1 
            axes.legend(['{}'.format(ch_name) for ch_name in L1+L2], labelcolor=['maroon' if ch_name in L1 else 'midnightblue' for ch_name in L1+L2])


        #plot in axes row 1 , 
        plot_psds(['O1'], ['O2'], fig.add_subplot(gs[0, 0:2]))
        plot_psds(['T5'], ['T6'], fig.add_subplot(gs[0, 2:4]))
        plot_psds(['T3'], ['T4'], fig.add_subplot(gs[1,0:2]))
        plot_psds(['P3'], ['P4'], fig.add_subplot(gs[1,2:4]))
        plot_psds(['C3'], ['C4'], fig.add_subplot(gs[2,0:2]))
        plot_psds(['F7'], ['F8'], fig.add_subplot(gs[2,2:4]))
        plot_psds(['F3'], ['F4'], fig.add_subplot(gs[3,0:2]))
        plot_psds(['Fp1'], ['Fp2'], fig.add_subplot(gs[3,2:4]))
        jpgFile=self.dest_folder+'eeg3.jpg'
        plt.savefig(jpgFile, dpi=72)
        plt.close()

    
    def plotSpectrogram(self, data, sr, picks_chs):
        f, t, Sxx = signal.spectrogram(data, fs=sr, nperseg=sr*2, noverlap=sr, nfft=sr*4)
        freq_range_mask = (f >= 1) & (f <= 30)
        f = f[freq_range_mask]
        Sxx = Sxx[:, freq_range_mask, :]

        # subplot 1 row 2 column, figsize=(20, 5)    
        plt.figure(figsize=(20, 30))
        rows=len(picks_chs)//2+1  
        
        for idx in range(len(picks_chs)):
            plt.subplot(rows, 2, idx+1)       

            plt.pcolormesh(t, f, 10 * np.log10(Sxx[idx]), cmap='coolwarm', vmin=-25, vmax=25)
            ch_name=picks_chs[idx]
            plt.ylabel(ch_name+'-Hz')
            plt.xlabel('Time [sec]')
            # plt pink line at y=8
            plt.axhline(y=8, color='darkred', linestyle='--')
            plt.colorbar(label='Power [dB/Hz]')
        jpgFile=self.dest_folder+'eeg4.jpg'
        plt.savefig(jpgFile, dpi=72)
        plt.close()

    def plotTopMaps(self, epochs):
        
        # Define your power spectrum data and channel names
        # Replace this with your actual power spectrum array and channel names

        # plot 4 columns
        fig, ax = plt.subplots(3,4, figsize=(12,9))
        # grid line
        fig.subplots_adjust( hspace=0.5)
        fv = 0.2
        L = 1*fv
        y = np.linspace(-L/2, L/2, 200)
        for i in range(4):
            for j in range(3):
                x=plot_egg_contour( ax[j,i], y, L, 0.9*fv, 0.005*fv, 0.77*fv, show=False)
                
        # y= np.concatenate((y, y))
        # x= np.concatenate((-x, x))
            


        axes=[ax[0,0], ax[0,1], ax[0,2], ax[0,3]]

        power_spectrum=epochs.copy().compute_psd(method='welch', fmin=1, fmax=30, n_jobs=4)
        # outlines outlines‘head’ | dict | None
        # The outlines to be drawn. If ‘head’, the default head scheme will be drawn. If dict, each key refers to a tuple of x and y positions, the values in ‘mask_pos’ will serve as image mask. Alternatively, a matplotlib patch object can be passed for advanced masking options, either directly or as a function that returns patches (required for multi-axis plots). If None, nothing will be drawn. Defaults to ‘head’.
        # custom outline
        outlines_dict = dict(
                        head=([],[]),
                        mask_pos=(x, y),
                        clip_radius=[0.09,0.1]

                    )
        power_spectrum.plot_topomap( normalize=True, bands = [(1,4,'Delta'), (4,8,'Theta'), (8,13,'Alpha'), (13,30,'Beta')], border=0,
                axes=axes,  contours=2, cmap=('turbo',True), outlines=outlines_dict, vlim=(0,1), sensors=False, colorbar=False)

        axes=[ax[1,0], ax[1,1], ax[1,2], ax[1,3]]
        power_spectrum.plot_topomap( normalize=False, bands = [(1,4,'Delta'), (4,8,'Theta'), (8,13,'Alpha'), (13,30,'Beta')], 
                dB=True, axes=axes,  contours=1, cmap='turbo', outlines=outlines_dict, sensors=False, vlim='joint', colorbar=True)


        axes=[ax[2,0], ax[2,1], ax[2,2], ax[2,3]]
        power_spectrum.plot_topomap( normalize=False, bands = [(1,4,'Delta'), (4,8,'Theta'), (8,13,'Alpha'), (13,30,'Beta')],  
            dB=True, axes=axes,  contours=1, cmap='turbo', outlines=outlines_dict, sensors=False, colorbar=False)
        rowTitle=[r'Normalized PSD (μV${^2}$/Hz)', 'Absolute SPD(dB)', 'Band absolute SPD(dB)']
        for i in range(3):

            for j in range(4):
                # draw border
                if j==0:
                    ax[i,j].text(-max(x), 1.4*max(y), rowTitle[i], color='black', fontsize=16)
                ax[i,j].axis('off')
                ax[i,j].plot(x, y, 'k', alpha=0.9, linewidth=0.5)
                ax[i,j].plot(-x, y, 'k', alpha=0.9, linewidth=0.5)
                # write text "Left" in the left lower corner
                ax[i,j].text(-max(x), min(y), 'Left O', color='black')  

        # ax[0,0].text(3*max(x), 1.8*max(y),'Power spectrum density', fontsize=20, color='black')
        jpgFile=self.dest_folder+'eeg0.jpg'
        fig.savefig(jpgFile, dpi=300)
        plt.close()
        


# set font chinese
plt.rc('font')#, family='Arial Unicode MS')
def yegg(x, L, B, w, D):
    """
    The "universal" formula for an egg, from Narushin et al., "Egg and math:
    introducing a universal formula for egg shape", *Ann. N.Y. Acad. Sci.*,
    **1505**, 169 (2021).
    x should vary between -L/2 and L/2 where L is the length of the egg; B
    is the maximum breadth of the egg; w is the distance between two vertical
    lines corresponding to the maximum breadth and y-axis (with the origin
    taken to be at the centre of the egg); D is the egg diameter at the point
    a distance L/4 from the pointed end.

    """

    fac1 = np.sqrt(5.5*L**2 + 11*L*w + 4*w**2)
    fac2 = np.sqrt(L**2 + 2*w*L + 4*w**2)
    fac3 = np.sqrt(3)*B*L
    fac4 = L**2 + 8*w*x + 4*w**2
    return (B/2) * np.sqrt((L**2 -4*x**2) / fac4) * (
        1 - (fac1 * (fac3 - 2*D*fac2) / (fac3 * (fac1 - 2*fac2)))
     * (1 - np.sqrt(L*fac4 / (2*(L - 2*w)*x**2
                    + (L**2 + 8*L*w - 4*w**2)*x + 2*L*w**2 + L**2*w + L**3))))

def plot_egg_contour(axes, y, L, B, w, D, show=True):

    x = yegg(y, L, B, w, D)
    if show:
        axes.plot(x, y, 'k')
        axes.plot(-x, y, 'k')
        axes.axis('equal')
    return x
    # plt.axis('off')






