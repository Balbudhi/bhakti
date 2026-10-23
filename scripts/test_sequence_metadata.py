"""Credits follow evidenced performances, including expanded repeat blocks."""
import copy
import unittest
from pathlib import Path
import bhakti_library_source_pass as source


def event(ref, repeats=1):
    return {'ref':ref,'section':'verse','repeats':repeats}


def fixture():
    reader={'SONG_META':{'title':'Keep title',
        'sectionNotices':[{'sequenceIndex':1,'title':'Second work','poet':'Known poet','note':'Keep this prose.'}],
        'adaptedSequenceIndices':[1]},
        'SONG_SEQUENCE':[event('intro'),event('A',2),event('B')],
        'SONG_LINES':{key:{} for key in ('intro','A','B')}}
    return reader


def plan(lineage):
    return {'adopted_delta':{'occurrence_lineage':[
        {'old_index':old,'new_index':new} for old,new in lineage]}}


class SequenceMetadata(unittest.TestCase):
    def remap(self,reader,change,new):
        before=copy.deepcopy((reader,change,new))
        result=source.remap_sequence_metadata(reader,change,new)
        self.assertEqual((reader,change,new),before)
        return result

    def test_deleted_prefix_and_partial_repeat_preserve_credit_and_adaptation(self):
        reader=fixture()
        result=self.remap(reader,plan([(0,None),(1,None),(2,0),(3,1)]),[event('A'),event('B')])
        expected=copy.deepcopy(reader['SONG_META'])
        expected['sectionNotices'][0]['sequenceIndex']=0
        expected['adaptedSequenceIndices']=[0]
        self.assertEqual(result,expected)

    def test_removed_section_start_moves_only_within_its_retained_span(self):
        reader=fixture();reader['SONG_META']['sectionNotices'][0]['sequenceIndex']=0
        result=self.remap(reader,plan([(0,None),(1,0),(2,1),(3,2)]),[event('A',2),event('B')])
        self.assertEqual(result['sectionNotices'],reader['SONG_META']['sectionNotices'])
        self.assertEqual(result['adaptedSequenceIndices'],[0])

    def test_fully_removed_section_does_not_reassign_its_credit(self):
        reader=fixture();reader['SONG_META']['sectionNotices']=[
            {'sequenceIndex':0,'title':'Intro work','poet':'First poet','note':''},
            *reader['SONG_META']['sectionNotices']]
        with self.assertRaisesRegex(ValueError,'(?i)(empty|removed|span)'):
            self.remap(reader,plan([(0,None),(1,0),(2,1),(3,2)]),[event('A',2),event('B')])

    def test_insertion_inside_one_evidenced_section_preserves_its_scope(self):
        reader=fixture();reader['SONG_META'].pop('adaptedSequenceIndices')
        result=self.remap(reader,plan([(0,0),(1,1),(2,2),(None,3),(3,4)]),
            [event('intro'),event('A',2),event('new'),event('B')])
        self.assertEqual(result,reader['SONG_META'])

    def test_new_material_at_attribution_boundary_or_tail_holds(self):
        reader=fixture();reader['SONG_META'].pop('adaptedSequenceIndices')
        reader['SONG_META']['sectionNotices'].append(
            {'sequenceIndex':2,'title':'Third work','poet':'Other poet','note':''})
        for change,new in (
            ([(0,0),(1,1),(2,2),(None,3),(3,4)],[event('intro'),event('A',2),event('new'),event('B')]),
            ([(0,0),(1,1),(2,2),(3,3),(None,4)],[event('intro'),event('A',2),event('B'),event('new')]),
        ):
            with self.subTest(change=change),self.assertRaisesRegex(ValueError,'(?i)(attribution|section|span)'):
                self.remap(reader,plan(change),new)

    def test_merge_cannot_hide_different_credits_or_adaptation_states(self):
        reader=fixture();reader['SONG_SEQUENCE']=[event('A'),event('A'),event('B')]
        change=plan([(0,0),(1,1),(2,2)])
        for field in ('sectionNotices','adaptedSequenceIndices'):
            value=copy.deepcopy(reader)
            value['SONG_META']={field:reader['SONG_META'][field]}
            with self.subTest(field=field),self.assertRaisesRegex(ValueError,'(?i)(merged|block|adaptation|section)'):
                self.remap(value,change,[event('A',2),event('B')])

    def test_identity_without_delta_preserves_exact_metadata_but_changed_order_holds(self):
        reader=fixture()
        self.assertEqual(self.remap(reader,{},reader['SONG_SEQUENCE']),reader['SONG_META'])
        with self.assertRaisesRegex(ValueError,'(?i)(lineage|order)'):
            self.remap(reader,{},[event('A',2),event('B')])

    def test_incomplete_lineage_cannot_relocate_credits(self):
        with self.assertRaisesRegex(ValueError,'(?i)(lineage|complete)'):
            self.remap(fixture(),plan([(0,None),(1,0),(3,1)]),[event('A'),event('B')])

    def test_existing_composite_aartis_keep_all_metadata_on_identity_mapping(self):
        import audit_bhakti_contract as contract
        root=Path(__file__).resolve().parents[1]
        for slug in ('shree-sai-aarti','shejarti'):
            with self.subTest(slug=slug):
                reader=contract.load_data(root/'songs'/slug/'data.js')
                self.assertTrue(reader['SONG_META'].get('sectionNotices'))
                self.assertEqual(self.remap(reader,{},reader['SONG_SEQUENCE']),reader['SONG_META'])
