import unittest
import bhakti_lexical_support as support

class SurfaceCaseTests(unittest.TestCase):
    def test_sentence_initial_case_does_not_break_same_word_alignment(self):
        row={'literal_english':'Adamantine limbs!', 'segments':[{'text':'Adamantine ','word_indices':[3]},{'text':'limbs!','word_indices':[4]}]}
        self.assertTrue(support.expression_matches_segments(row,'adamantine',[3]))
        self.assertFalse(support.expression_matches_segments(row,'adamantine',[4]))
        self.assertFalse(support.expression_matches_segments(row,'adamant',[3]))
        self.assertFalse(support.expression_matches_segments(row,'adamantine limbs',[3]))

if __name__=='__main__':unittest.main()
