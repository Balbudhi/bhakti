"""Exact real held choice; no claim that structural tests decide the language."""
import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
import bhakti_pipeline as pipeline
from bhakti_editorial_adjudication import recover_editorial_candidate


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()).hexdigest()

def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()
def write(path, value):
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n')

HELD_GLOSS = {'id': 'source-new-line-023',
 'word_glosses': [{'roman': 'Aisī', 'gloss': 'such', 'concept_key': '', 'preserve_in_english': False},
                  {'roman': 'bānī', 'gloss': 'speech', 'concept_key': '', 'preserve_in_english': False},
                  {'roman': 'boliye',
                   'gloss': 'one should speak',
                   'concept_key': '',
                   'preserve_in_english': False}],
 'semantic_frame': {'agent': 'the spiritual seeker / person addressed (impersonal second-person or inclusive '
                             "'one')",
                    'action_or_state': 'should speak (boliye)',
                    'patient_or_complement': 'such speech (aisī bānī)',
                    'modifiers': "demonstrative/qualitative adjective aisī ('such')",
                    'negation_or_modality': 'prescriptive optative / polite imperative',
                    'literal_image_and_agency': 'An ethical admonition directing the speaker to utter words '
                                                'possessing spiritual and calming virtue',
                    'idiom_or_phrase': "aisī bānī bolnā ('to speak wholesome, gentle speech')",
                    'cross_line_relation': 'Forms the main governing clause of the classic Kabir couplet, '
                                           'elaborated by lines 024-026'},
 'grammar_note': 'Boliye is an impersonal/polite imperative form of bolnā taking the feminine direct object '
                 'phrase aisī bānī.',
 'uncertainty': '',
 'sense_decisions': [{'word_index': 0,
                      'roman': 'Aisī',
                      'evidence_status': 'contextual_inference',
                      'chosen': [],
                      'rejected': [],
                      'contextual_reason': 'Feminine singular demonstrative adjective modifying bānī, '
                                           "meaning 'of such a quality' or 'such'.",
                      'grammatical_role': 'demonstrative adjective (feminine singular)'},
                     {'word_index': 1,
                      'roman': 'bānī',
                      'evidence_status': 'dictionary_supported',
                      'chosen': [{'entry_id': 'platts1884.p128.hw6dc593d1524a1b3b.h3',
                                  'sense_id': 'platts1884.p128.hw6dc593d1524a1b3b.h3:entry'}],
                      'rejected': [{'entry_id': 'platts1884.p128.hw6dc593d1524a1b3b.h1',
                                    'sense_id': 'platts1884.p128.hw6dc593d1524a1b3b.h1:entry',
                                    'reason': 'Candidate h1 denotes natural temper, mental constitution, or '
                                              'potter earth, which does not fit utterance or speech.'},
                                   {'entry_id': 'platts1884.p128.hw6dc593d1524a1b3b.h2',
                                    'sense_id': 'platts1884.p128.hw6dc593d1524a1b3b.h2:entry',
                                    'reason': 'Candidate h2 denotes weaving thread or weaving cost, '
                                              'inapplicable to verbal expression.'}],
                      'contextual_reason': 'Derived from Sanskrit vāṇī, denoting speech, utterance, or '
                                           'spoken words in ethical and devotional discourse.',
                      'grammatical_role': 'direct object noun (feminine singular)'},
                     {'word_index': 2,
                      'roman': 'boliye',
                      'evidence_status': 'contextual_inference',
                      'chosen': [],
                      'rejected': [],
                      'contextual_reason': 'Polite/precative imperative form of bolnā used as a general '
                                           "moral precept meaning 'one should speak'.",
                      'grammatical_role': 'transitive finite verb (polite imperative / precative optative)'}]}
HELD_TRANSLATION = {'id': 'source-new-line-023',
 'literal_english': 'One should speak such speech,',
 'segments': [{'text': 'One should speak ', 'word_indices': [2]},
              {'text': 'such ', 'word_indices': [0]},
              {'text': 'speech,', 'word_indices': [1]}],
 'fidelity': {'agency_and_image_preserved': True,
              'all_meaning_accounted_for': True,
              'unsupported_additions': [],
              'notes': "Impersonal subject 'one' and modal auxiliary 'should' express the precative optative "
                       'inflection of boliye.'},
 'material_alternatives': ['Speak such speech,', 'One should speak such words,', 'Speak such words,'],
 'human_review_recommended': True,
 'choice_note': "Rendered as 'One should speak such speech,' matching the precative optative modality and "
                'impersonal inclusive agency of boliye noted in the semantic frame, while preserving the '
                "cognate noun bānī. Direct imperative 'Speak such speech,' is provided as a material "
                'alternative.',
 'uncertainty': '',
 'independent_review': {'id': 'source-new-line-023',
                        'passes': True,
                        'human_review_recommended': True,
                        'agency_preserved': True,
                        'imagery_preserved': True,
                        'all_meaning_accounted_for': True,
                        'unsupported_additions': [],
                        'material_choice': "Impersonal gnomic optative ('One should speak') versus direct "
                                           "hortatory imperative ('Speak')",
                        'reason': 'Faithfully captures the prescriptive optative force of boliye and the '
                                  'cognate direct object bānī; flagged for human review due to the material '
                                  "choice between an impersonal prescriptive frame ('One should speak') and "
                                  "direct imperative address ('Speak').",
                        'issues': []}}

class EditorialAdjudicationTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);self.output=self.root/'resolved'
        self.candidate_path=self.root/'route/flash/candidate.json'
        self.state_path=self.root/'route/route-state.json';self.record_path=self.root/'decision.json'
        self.line={'id':'source-new-line-023','source_text':'ऐसी बानी बोलिए','roman':'Aisī bānī boliye','kind':'verse'}
        self.source={'targets':[self.line],'source':[self.line], 'order':[{'line_id':self.line['id'],'occurrence':1}], 'languages':['Hindi']}
        self.policy={'version':3,'fixture':'frozen policy; language judgment separately evidenced'}
        self.candidate={'glosses':{'packet':{'glosses':[copy.deepcopy(HELD_GLOSS)]}},
            'translations':{'packet':{'translations':[copy.deepcopy(HELD_TRANSLATION)]},
                            'review_responses':[{'original_human_review_recommended':True}]}}
        self.state={'version':1,'unit_id':'patta:new-source-semantics','input_fingerprint':digest(self.source),
          'dependency_fingerprint':digest(self.policy),'status':'unresolved','attempts':[
           {'attempt_id':'flash-review','model':'google/gemini-3.7-flash','status':'quality-failed'},
           {'attempt_id':'pro-failed','model':'google/gemini-3.1-pro-preview','status':'quality-failed'}]}
        write(self.candidate_path,self.candidate);write(self.state_path,self.state)
        self.record={'version':1,'decision_kind':'retain_existing_primary','reviewer':'explicit editorial reviewer',
          'rationale':'The polite prescriptive form permits the retained gnomic English; independent source review resolves this exact choice.',
          'source_references':[{'line_id':self.line['id'],'source_quote':'बोलिए'}],
          'unit_id':self.state['unit_id'],'input_fingerprint':self.state['input_fingerprint'],
          'dependency_fingerprint':self.state['dependency_fingerprint'],'candidate_path':str(self.candidate_path),
          'route_state_path':str(self.state_path),'attempt_id':'flash-review','source_digest':digest(self.source),
          'policy_digest':digest(self.policy),'line_id':self.line['id'],
          'selected_literal_english':HELD_TRANSLATION['literal_english'],
          'expected_flags':{'translation_human_review_recommended':True,'independent_human_review_recommended':True}}
        self.refresh_record()
        self.validation_calls=[]

    def effective(self):
        value=copy.deepcopy(self.candidate);row=value['translations']['packet']['translations'][0]
        row['human_review_recommended']=False;row['independent_review']['human_review_recommended']=False
        return value

    def refresh_record(self):
        self.record.update(candidate_file_sha256=sha(self.candidate_path),candidate_digest=digest(self.candidate),
          route_state_sha256=sha(self.state_path),original_row_digest=digest(self.candidate['translations']['packet']['translations'][0]),
          expected_result_digest=digest(self.effective()))
        write(self.record_path,self.record)

    def validate(self,value):
        self.validation_calls.append(copy.deepcopy(value))
        return pipeline.fresh_translation_contract_errors(self.source['targets'],
            value['glosses']['packet']['glosses'],value['translations']['packet']['translations'])

    def invoke(self,validator=None):
        return recover_editorial_candidate(self.record_path,unit_id=self.state['unit_id'],
            input_fingerprint=self.state['input_fingerprint'],dependency_fingerprint=self.state['dependency_fingerprint'],
            source_evidence=self.source,policy_payload=self.policy,validate_candidate=validator or self.validate,
            output_dir=self.output)

    def test_real_choice_changes_only_two_flags_and_preserves_failed_evidence(self):
        originals={p:p.read_bytes() for p in (self.candidate_path,self.state_path,self.record_path)}
        result=self.invoke()
        self.assertEqual(result['candidate'],self.effective())
        self.assertEqual(result['receipt']['decision_digest'],digest(self.record))
        self.assertEqual(result['receipt']['effective_changes'],[
            {'line_id':self.line['id'],'field':'human_review_recommended','before':True,'after':False},
            {'line_id':self.line['id'],'field':'independent_review.human_review_recommended','before':True,'after':False}])
        self.assertEqual(self.validation_calls,[self.effective()])
        self.assertEqual(originals,{p:p.read_bytes() for p in originals})
        self.assertTrue((self.output/'accepted-candidate.json').is_file())
        self.assertTrue((self.output/'receipt.json').is_file())

    def test_exact_resume_revalidates_without_changing_original_artifacts(self):
        first=self.invoke();second=self.invoke();self.assertEqual(first,second)
        self.assertEqual(len(self.validation_calls),2)

    def test_changed_source_order_or_policy_rejects_without_output(self):
        for subject in ('source','order','policy'):
            source,policy=copy.deepcopy(self.source),copy.deepcopy(self.policy)
            if subject=='source':self.source['source'][0]['source_text']='other source'
            elif subject=='order':self.source['order'].append({'line_id':self.line['id'],'occurrence':2})
            else:self.policy['version']=99
            with self.subTest(subject=subject),self.assertRaises(ValueError):self.invoke()
            self.source,self.policy=source,policy
        self.assertFalse(self.output.exists())

    def test_changed_candidate_bytes_or_route_state_rejects_without_output(self):
        for path in (self.candidate_path,self.state_path):
            before=path.read_bytes();path.write_bytes(before+b' ')
            with self.subTest(path=path.name),self.assertRaises(ValueError):self.invoke()
            path.write_bytes(before)
        self.assertFalse(self.output.exists())

    def test_exact_existing_english_row_and_flags_required(self):
        for field,value in [('selected_literal_english','Speak such speech,'),('line_id','other-row'),
                            ('original_row_digest','wrong'),('expected_result_digest','wrong'),
                            ('expected_flags',{'translation_human_review_recommended':'true','independent_human_review_recommended':True})]:
            old=copy.deepcopy(self.record);self.record[field]=value;write(self.record_path,self.record)
            with self.subTest(field=field),self.assertRaises(ValueError):self.invoke()
            self.record=old;write(self.record_path,self.record)
        self.assertFalse(self.output.exists())

    def test_failed_or_truthy_fidelity_cannot_be_adjudicated(self):
        for domain,key,value in [('fidelity','agency_and_image_preserved',False),('fidelity','all_meaning_accounted_for','true'),
                                ('independent_review','passes',False),('independent_review','issues',[{'kind':'unresolved_evidence'}])]:
            old=copy.deepcopy(self.candidate);self.candidate['translations']['packet']['translations'][0][domain][key]=value
            write(self.candidate_path,self.candidate);self.refresh_record()
            with self.subTest(field=key),self.assertRaises(ValueError):self.invoke()
            self.candidate=old;write(self.candidate_path,self.candidate);self.refresh_record()
        self.assertFalse(self.output.exists())

    def test_original_choice_flags_must_be_literal_true(self):
        for value in ('true', False, None):
            old=copy.deepcopy(self.candidate)
            self.candidate['translations']['packet']['translations'][0]['human_review_recommended']=value
            write(self.candidate_path,self.candidate);self.refresh_record()
            with self.subTest(value=value),self.assertRaises(ValueError):self.invoke()
            self.candidate=old;write(self.candidate_path,self.candidate);self.refresh_record()
        self.assertFalse(self.output.exists())

    def test_only_a_documented_material_choice_can_be_resolved(self):
        old=copy.deepcopy(self.candidate)
        self.candidate['translations']['packet']['translations'][0]['independent_review']['material_choice']=''
        write(self.candidate_path,self.candidate);self.refresh_record()
        with self.assertRaises(ValueError):self.invoke()
        self.assertFalse(self.output.exists())

    def test_uncertain_source_gloss_or_translation_cannot_be_cleared(self):
        for part in ('glosses','translations'):
            key='glosses' if part=='glosses' else 'translations'
            row=self.candidate[part]['packet'][key][0];old=row['uncertainty'];row['uncertainty']='source word unclear'
            write(self.candidate_path,self.candidate);self.refresh_record()
            with self.subTest(part=part),self.assertRaises(ValueError):self.invoke()
            row['uncertainty']=old;write(self.candidate_path,self.candidate);self.refresh_record()
        self.assertFalse(self.output.exists())

    def test_any_remaining_other_row_or_contract_error_blocks(self):
        with self.assertRaises(ValueError):self.invoke(lambda value:['source-new-line-024 still has an unresolved sense decision'])
        self.assertFalse(self.output.exists())

    def test_unknown_or_running_attempt_and_changed_unit_reject(self):
        for field,value in [('status','running'),('unit_id','other-unit')]:
            old=copy.deepcopy(self.state);self.state[field]=value;write(self.state_path,self.state);self.refresh_record()
            with self.subTest(field=field),self.assertRaises(ValueError):self.invoke()
            self.state=old;write(self.state_path,self.state);self.refresh_record()
        self.record['attempt_id']='not-present';write(self.record_path,self.record)
        with self.assertRaises(ValueError):self.invoke()
        self.assertFalse(self.output.exists())

    def test_invalid_source_reference_or_empty_rationale_rejects(self):
        for field,value in [('rationale',''),('reviewer',''),('source_references',[{'line_id':self.line['id'],'source_quote':'wrong quote'}])]:
            old=copy.deepcopy(self.record);self.record[field]=value;write(self.record_path,self.record)
            with self.subTest(field=field),self.assertRaises(ValueError):self.invoke()
            self.record=old;write(self.record_path,self.record)
        self.assertFalse(self.output.exists())

    def test_tampered_derived_artifact_cannot_resume_as_accepted(self):
        self.invoke();write(self.output/'accepted-candidate.json',{'tampered':True})
        with self.assertRaises(ValueError):self.invoke()

    def test_candidate_from_wrong_route_parent_cannot_be_adopted(self):
        wrong=self.root/'different-route/flash/candidate.json';write(wrong,self.candidate)
        self.record['candidate_path']=str(wrong);self.record['candidate_file_sha256']=sha(wrong)
        write(self.record_path,self.record)
        with self.assertRaises(ValueError):self.invoke()
        self.assertFalse(self.output.exists())

    def test_validator_mutation_is_not_authorized(self):
        def mutating(value):value['translations']['packet']['translations'][0]['literal_english']='other';return []
        with self.assertRaises(ValueError):self.invoke(mutating)
        self.assertFalse(self.output.exists())

if __name__=='__main__':unittest.main()
