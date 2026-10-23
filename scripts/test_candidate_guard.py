import copy
import unittest
from bhakti_semantic_repair import digest
from bhakti_candidate_guard import authorize_semantic_candidate


def row(id, passes=True, issues=None):
    return dict(id=id, passes=passes, human_review_recommended=False,
                agency_preserved=passes, imagery_preserved=True, all_meaning_accounted_for=True,
                unsupported_additions=[], material_choice='', reason='Source agency checked', issues=issues or [])


def envelope(reader, reviews, request):
    return dict(reader_digest=digest(reader), dependency_fingerprint='actual-source-and-policy',
                attempt_id=request, reviews=reviews)


class CandidateGuardTests(unittest.TestCase):
    def setUp(self):
        self.before={'SONG_META':{'title':'Example'}, 'SONG_SEQUENCE':[{'ref':'a'},{'ref':'b'}],
            'SONG_TIMINGS':[{'start':1},{'start':5}], 'SONG_LINES':{
            'a':{'source':'मन', 'roman':'mana', 'english':'{0:heart}', 'words':[{'roman':'mana','gloss':'mind'}]},
            'b':{'source':'नाम', 'roman':'nāma', 'english':'{0:Name}', 'words':[{'roman':'nāma','gloss':'Name'}]}}}
        self.after=copy.deepcopy(self.before); self.after['SONG_LINES']['a']['english']='{0:mind}'
        self.sources=[{'id':'a','source_text':'मन','roman':'mana'},{'id':'b','source_text':'नाम','roman':'nāma'}]
        self.glosses=[{'id':'a','word_glosses':[{'roman':'mana','gloss':'mind'}]}, {'id':'b','word_glosses':[{'roman':'nāma','gloss':'Name'}]}]
        self.issue=dict(kind='english_realization',target_line_ids=['a'],
            references=[dict(line_id='a',domain='word_glosses',word_indices=[0],source_quote='मन')],
            explanation='Draft differs from selected cognitive sense.', evidence='मन denotes the mind here.',
            hold_reason='',needed_evidence='')
        self.pre=envelope(self.before,[row('a',False,[self.issue]),row('b')],'review-before')
        self.post=envelope(self.after,[row('a')],'review-after')
    def call(self):
        return authorize_semantic_candidate(self.before,self.after,source_lines=self.sources,
            gloss_rows=self.glosses,pre_review=self.pre,post_review=self.post,
            dependency_fingerprint='actual-source-and-policy')
    def test_confirmed_one_line_only(self):
        receipt=self.call()
        self.assertEqual(receipt['confirmed_changes'],{'a':['english']})
        self.assertEqual(receipt['candidate_digest'],digest(self.after))
    def test_good_unchanged_requires_no_rewrite_or_post_call(self):
        self.after=copy.deepcopy(self.before); self.pre=envelope(self.before,[row('a'),row('b')],'clean'); self.post=None
        self.assertEqual(self.call()['confirmed_changes'],{})
    def test_style_only_and_missing_issue_cannot_authorize(self):
        for pre in ([row('a'),row('b')],[row('a',False),row('b')]):
            self.pre=envelope(self.before,pre,'before')
            with self.assertRaises(ValueError): self.call()
    def test_collateral_changes_are_rejected_even_with_passing_post(self):
        for field,value in [('source','चित्त'),('roman','citta'),('words',[{'roman':'mana','gloss':'soul'}])]:
            candidate=copy.deepcopy(self.after); candidate['SONG_LINES']['a'][field]=value
            with self.subTest(field=field):
                post=envelope(candidate,[row('a')],'review-after')
                with self.assertRaises(ValueError):
                    authorize_semantic_candidate(self.before,candidate,source_lines=self.sources,gloss_rows=self.glosses,
                      pre_review=self.pre,post_review=post,dependency_fingerprint='actual-source-and-policy')
        self.after['SONG_LINES']['b']['english']='{0:Holy Name}'
        self.post=envelope(self.after,[row('a'),row('b')],'after')
        with self.assertRaises(ValueError): self.call()
    def test_gloss_issue_allows_only_same_token_gloss(self):
        self.issue['kind']='gloss_sense'; self.after['SONG_LINES']['a']['words'][0]['gloss']='the thinking mind'
        self.post=envelope(self.after,[row('a')],'after')
        self.assertEqual(self.call()['confirmed_changes'],{'a':['english','words']})
        self.after['SONG_LINES']['a']['words'][0]['roman']='citta'; self.post=envelope(self.after,[row('a')],'after')
        with self.assertRaises(ValueError): self.call()
    def test_stale_and_nonindependent_reviews_rejected(self):
        for field,value in [('reader_digest','stale'),('dependency_fingerprint','other'),('attempt_id','review-before')]:
            original=copy.deepcopy(self.post); self.post[field]=value
            with self.subTest(field=field), self.assertRaises(ValueError): self.call()
            self.post=original
    def test_invalid_source_quote_and_indices_rejected(self):
        for field,value in [('source_quote','असत्य'),('word_indices',[True]),('word_indices',[9])]:
            old=copy.deepcopy(self.issue['references']); self.issue['references'][0][field]=value
            with self.subTest(field=field), self.assertRaises(ValueError): self.call()
            self.issue['references']=old
    def test_post_holds_losses_and_truthy_string_cannot_pass(self):
        for field,value in [('passes','true'),('imagery_preserved',False),('all_meaning_accounted_for',False),
                            ('human_review_recommended',True),('unsupported_additions',['holy']),('material_choice','new metaphor'),
                            ('issues',[self.issue])]:
            old=copy.deepcopy(self.post); self.post['reviews'][0][field]=value
            with self.subTest(field=field), self.assertRaises(ValueError): self.call()
            self.post=old
    def test_unresolved_evidence_is_never_rewrite_permission(self):
        self.issue.update(kind='unresolved_evidence',hold_reason='audited_source_ambiguity',needed_evidence='audio')
        with self.assertRaises(ValueError): self.call()
    def test_protected_wording_exact_in_both_readers(self):
        with self.assertRaises(ValueError):
            authorize_semantic_candidate(self.before,self.after,source_lines=self.sources,gloss_rows=self.glosses,
             pre_review=self.pre,post_review=self.post,dependency_fingerprint='actual-source-and-policy',
             protected_english={'a':'heart','b':'Name'})
    def test_missing_duplicate_or_unknown_review_row_rejected(self):
        for rows in ([row('a')],[row('a'),row('a')],[row('a'),row('b'),row('c')]):
            self.pre=envelope(self.before,rows,'before')
            with self.assertRaises(ValueError): self.call()

    def test_unchanged_shortcut_checks_every_pre_fidelity_field(self):
        self.after=copy.deepcopy(self.before); self.post=None
        with self.assertRaises(ValueError): self.call()
        for value in (False, 'true'):
            self.pre=envelope(self.before,[row('a'),row('b')],'clean')
            self.pre['reviews'][1]['agency_preserved']=value
            with self.assertRaises(ValueError): self.call()
    def test_protected_mapping_only_is_allowed_and_old_divergence_is_blocked(self):
        self.issue['kind']='english_mapping'
        self.before['SONG_LINES']['a']['english']='{0:he}{0:art}'
        self.after['SONG_LINES']['a']['english']='{0:heart}'
        self.pre=envelope(self.before,[row('a',False,[self.issue]),row('b')],'before')
        self.post=envelope(self.after,[row('a')],'after')
        args=dict(source_lines=self.sources,gloss_rows=self.glosses,pre_review=self.pre,post_review=self.post,
                  dependency_fingerprint='actual-source-and-policy',protected_english={'a':'heart','b':'Name'})
        self.assertEqual(authorize_semantic_candidate(self.before,self.after,**args)['confirmed_changes'],{'a':['english']})
        for baseline in ({'a':'heart'}, {'a':'heart','b':'Name','c':'Extra'}, {'a':'mind','b':'Name'}):
            args['protected_english']=baseline
            with self.assertRaises(ValueError): authorize_semantic_candidate(self.before,self.after,**args)
    def test_words_cannot_add_arbitrary_fields(self):
        self.issue['kind']='gloss_sense'
        self.after['SONG_LINES']['a']['words'][0]['invented']='new'
        self.post=envelope(self.after,[row('a')],'after')
        with self.assertRaises(ValueError): self.call()
    def test_source_and_gloss_evidence_bound_to_reader(self):
        for update in ('text','duplicate','token','gloss'):
            sources=copy.deepcopy(self.sources); glosses=copy.deepcopy(self.glosses)
            if update=='text': self.sources[0]['source_text']='असत्य'
            if update=='duplicate': self.sources.append(self.sources[0])
            if update=='token': self.glosses[0]['word_glosses'][0]['roman']='citta'
            if update=='gloss': self.glosses[0]['word_glosses'][0]['gloss']='body'
            with self.subTest(update=update), self.assertRaises(ValueError): self.call()
            self.sources=sources; self.glosses=glosses

    def test_roman_evidence_and_unreferenced_gloss_are_rejected(self):
        self.sources[0]['roman']='ātman'
        with self.assertRaises(ValueError): self.call()
        self.sources[0]['roman']='mana'
        for reader in (self.before,self.after):
            reader['SONG_LINES']['a']['words'].append({'roman':'bānī','gloss':'speech'})
        self.glosses[0]['word_glosses'].append({'roman':'bānī','gloss':'speech'})
        self.issue['kind']='gloss_sense'
        self.after['SONG_LINES']['a']['words'][1]['gloss']='divine revelation'
        self.pre=envelope(self.before,[row('a',False,[self.issue]),row('b')],'before')
        self.post=envelope(self.after,[row('a')],'after')
        with self.assertRaises(ValueError): self.call()

if __name__=='__main__': unittest.main()
