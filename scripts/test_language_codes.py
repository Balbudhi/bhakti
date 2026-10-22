"""Language metadata uses ISO language codes, never writing-system inference."""
import unittest
import bhakti_pipeline as pipeline

class LanguageCodeTests(unittest.TestCase):
    # Expected values checked against Library of Congress ISO 639-2/639-1 table.
    LANGUAGES = {'Hindi':'hi','Sanskrit':'sa','Punjabi':'pa','Kannada':'kn','Marathi':'mr',
                 'Awadhi':'awa','Braj':'bra','Rajasthani':'raj','Tamil':'ta','Telugu':'te',
                 'Odia':'or','Bengali':'bn','Malayalam':'ml','Persian':'fa','Urdu':'ur'}

    def test_each_published_catalogue_language_has_its_code(self):
        for name, code in self.LANGUAGES.items():
            with self.subTest(language=name):
                self.assertEqual(pipeline.language_code(name),code)

    def test_code_and_name_metadata_normalize_to_same_display_language(self):
        for name, code in self.LANGUAGES.items():
            for value in [name,name.lower(),code]:
                with self.subTest(value=value):
                    self.assertEqual(pipeline.normalized_language(value),name)
                    self.assertEqual(pipeline.language_code(pipeline.normalized_language(value)),code)

    def test_three_letter_aliases_remain_supported_including_new_languages(self):
        aliases={'hin':'Hindi','san':'Sanskrit','pan':'Punjabi','kan':'Kannada','mar':'Marathi',
                 'tam':'Tamil','tel':'Telugu','ori':'Odia','ben':'Bengali','mal':'Malayalam',
                 'fas':'Persian','per':'Persian','urd':'Urdu'}
        for value,name in aliases.items():
            with self.subTest(value=value):self.assertEqual(pipeline.normalized_language(value),name)

    def test_unknown_or_script_names_are_not_language_guesses(self):
        self.assertEqual(pipeline.normalized_language('  Unknown  '), 'Unknown')
        for value in ['', 'Unknown', 'Devanagari', 'Gurmukhi']:
            self.assertEqual(pipeline.language_code(value),'')
            self.assertEqual(pipeline.normalized_language(value),value)

if __name__=='__main__':unittest.main()
