############################################
# This file contains the prompt messages
# for the EEG report generation task.
############################################

def reportPrompt(finalResults, reportLang='English', promptLength='long'):
    if promptLength=='long':
       
        message="""You are a neurologist with access to a comprehensive neurological database from Medline and textbooks. 
            JSON Findings:
            {}
            Meanings of JSON findings:
            'backgroundFrequency': the background frequency of the EEG in the left and right hemispheres. Differences <=0.5 Hz are considered symmetric.
            'bg_active': the overall presence of background activity.
            'bg_amp_sym', 'bg_freq': symmetry of alpha amplitude and background frequency.            
            'abnormalFindings': all abnormal findings in the EEG examination.

            Task: Generate a detailed and structured EEG report based on the provided EEG findings.
            === EEG Findings ===
            Present the EEG findings in a list format in concise and professional language.
            === Conclusion ===
            - If the results are normal: "The EEG examination reveals normal findings."
            - If the results are abnormal: "Abnormal EEG findings are observed."
            - A brief description of the abnormal observations should be included.
            === Clinical Correlation ===
            - For normal EEG results: "No evidence of cortical dysfunction or epileptiform activity is observed."
            === Advanced Strategies ===
            - - For abnormal EEG results, very briefly suggest further investigations or follow-up tests.

            Examples for Abnormal Clinical Correlations:
            - Diffuse background slowing may indicate associations with degenerative diseases, metabolic encephalopathy, and bilateral cortical lesions.
            - Slow waves in a specific region or hemisphere might suggest a structural lesion in the corresponding brain region.
            - Detection of spikes or sharp waves raises concerns about an increasing risk of epilepsy.
            - Excess beta activity is linked to factors like anxiety or the effects of certain drugs, such as benzodiazepines.

        Examples for Advanced Strategies:
            - For structural lesions: Recommend neuroimaging studies, such as MRI or CT, to identify abnormalities.
            - In cases of epilepsy: Suggest long-term video EEG monitoring for detecting epileptiform activity.
            - In the presence of artifacts: Advise a repeat EEG examination to confirm findings.
            - Emphasize that correlation with clinical symptoms and other laboratory tests is essential for establishing a diagnosis.

            Important Notes:
                - Must Enclose the title of each section in ===

            Report: 
            Your detailed and structured EEG report in {}.
        """.format(finalResults, reportLang)
    elif  promptLength=='medium':
        message="""
            You are a neurologist with access to a comprehensive neurological database from Medline and textbooks. 
            JSON Findings:
            {}
            Meanings of JSON findings:
            'backgroundFrequency': the background frequency of the EEG in the left and right hemispheres. Differences <=0.5 Hz are considered symmetric.
            'bg_active': the overall presence of background activity.
            'bg_amp_sym', 'bg_freq': symmetry of alpha amplitude and background frequency.            
            'abnormalFindings': all abnormal findings in the EEG examination.

            Task: Generate a detailed and structured EEG report based on the provided EEG findings.
            === EEG Findings ===
            Present the EEG findings in a list format in concise and professional language.
            === Conclusion ===
            - A brief description of the normal or abnormal observations.
            === Clinical Correlation ===
            === Advanced Strategies ===
            - - For abnormal EEG results, very briefly suggest further investigations or follow-up tests.
            Report: 
            Your detailed and structured EEG report in {}.
        """.format(finalResults, reportLang)
    elif promptLength=='short':
        message="""
            You are a neurologist. 
            Task: Generate a EEG report based on the provided EEG findings.
            EEG Findings, Conclusion, Clinical Correlation, and Advanced Strategies should be included.
            JSON Findings:
            {}
            Meanings of JSON findings:
            'bg_active': presence of background activity.
            'bg_amp_sym', 'bg_freq': symmetry of background alpha amplitude and  frequency.            
            'abnormalFindings': all abnormal findings in the EEG examination.
            Your EEG report in {}:
        """.format(finalResults, reportLang)

    return message

def validatePrompt(text):
    prompt="""
    Task: Read the EEG report and answer the following questions, answering 1 for yes and 0 for no.
    Questions:
    a.Does the report mention "diffuse background slowing" or "Increased background slow waves ratio diffusely"?
    b.Dose the report mention background asymmetry such as "lower amplitude" or "lower frequency" in right or left hemisphere, or "focal/regional slowing(delta/theta)"?
    Important Note: 
    1.if the left and right background frequency differ by within 1 Hz, it is considered as normal.
    2. Excessive beta activity is not classified as abnormal diffuse background slowing nor focal slow wave.
    The EEG report:
    {}
    Your answer should be in array format ([int, int]), and do not include any other information.
    Your answer array:
    """.format(text)
    
    return prompt

############################################
# SCORE conclusion: diagnostic significance, summary of findings and clinical
# comments (SCORE sections 15 and 17).
#
# Two things make this different from reportPrompt above, and both come from
# SCORE rather than from taste:
#
#   Diagnostic significance is a FORCED CHOICE from a fixed list, not prose. The
#   model picks terms; it does not invent them, and score_common.validateSignificance
#   rejects anything outside the list before a reader ever sees it.
#
#   It is also the step SCORE reserves for the electroencephalographer, taken
#   last and in the clinical context. So what is produced here is a proposal for
#   confirmation, never a scored value, and the report says so.
#
# The summary of findings and clinical comments are genuinely free text in
# SCORE, which is exactly what a language model should be drafting - from the
# structured findings and nothing else.
############################################

def scoreConclusionPrompt(finalResults, categories, supportable, unsupportable,
                          reportLang='English'):
    """Prompt for a SCORE-shaped conclusion, returned as JSON.

    finalResults  : the structured findings, as a dict
    categories    : SCORE's three significance categories
    supportable   : the diagnostic yields this analysis can justify
    unsupportable : {term: why it cannot be proposed here}
    """
    forbidden = '\n'.join('              - "%s" - %s' % (term, reason)
                           for term, reason in sorted(unsupportable.items()))

    return """You are a clinical neurophysiologist completing an EEG report using SCORE
(Standardized Computer-based Organized Reporting of EEG, Beniczky et al.,
Clinical Neurophysiology 2017).

These are the structured findings extracted from the recording. They are the
ONLY evidence you have. There is no clinical history, no referral question, and
no imaging.

STRUCTURED FINDINGS (JSON):
{findings}

Produce three things.

1. DIAGNOSTIC SIGNIFICANCE (SCORE section 15)
   Choose exactly one category from this list, copied verbatim:
{categoryList}

   If, and only if, you chose "Abnormal recording", also choose one or more
   diagnostic yields from this list, copied verbatim:
{yieldList}

   You MUST NOT propose any of the following, whatever the findings suggest,
   because the analysis you are given cannot support them:
{forbidden}

   For every term you choose, cite the specific findings it rests on. Do not
   cite a finding that is not in the JSON above.

2. SUMMARY OF FINDINGS (SCORE section 17)
   A short paragraph, in professional clinical language, describing what was
   found. Restate only what is in the JSON.

3. CLINICAL COMMENTS (SCORE section 17)
   A short paragraph on what the findings may mean and what, if anything, would
   help next. Where the findings are non-specific, say so. Do not speculate
   about a diagnosis.

RULES
- Never state a number, frequency, amplitude, duration or percentage that does
  not appear in the JSON. Do not convert or re-band values that are already
  banded.
- Where a property is "Not possible to determine", say it was not assessable.
  Do not guess it.
- Where a finding is marked provisional, describe it as unconfirmed.
- Write sections 2 and 3 in {language}. Keep the SCORE terms in section 1 in
  English exactly as listed, since they are database codes.

Reply with JSON only, no commentary, in exactly this shape:

{{
  "category": "<one category, verbatim>",
  "yields": ["<zero or more yields, verbatim>"],
  "basis": ["<finding supporting the choice>", "..."],
  "confidence": "<high|medium|low>",
  "summary_of_findings": "<paragraph>",
  "clinical_comments": "<paragraph>"
}}
""".format(findings=finalResults,
           categoryList='\n'.join('              - "%s"' % c for c in categories),
           yieldList='\n'.join('              - "%s"' % y for y in supportable),
           forbidden=forbidden,
           language=reportLang)
