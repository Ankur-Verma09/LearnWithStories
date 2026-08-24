import unittest

from story_tutor.hierarchy import NEEDS_REVIEW, chapter_for_page, normalized_name, parse_toc, subtopic_from_page


class HierarchyExtractionTests(unittest.TestCase):
    def test_toc_builds_distinct_chapters(self):
        chapters = parse_toc(["SECTION – I : ARITHMETICAL ABILITY\n1. Number System 3 – 23\n2. H.C.F. and L.C.M. 24 – 34"])
        self.assertEqual([x.title for x in chapters], ["Number System", "H.C.F. and L.C.M"])
        self.assertEqual(chapter_for_page(chapters, 30).title, "H.C.F. and L.C.M")

    def test_running_book_header_is_not_a_subtopic(self):
        chapter = parse_toc(["SECTION – I : ARITHMETICAL ABILITY\n1. Number System 3 – 23"])[0]
        self.assertEqual(subtopic_from_page("12 QUANTITATIVE APTITUDE\nSolved Examples\nbody", chapter), "")

    def test_unmapped_pages_are_explicitly_reviewable(self):
        self.assertIsNone(chapter_for_page([], 1))
        self.assertEqual(NEEDS_REVIEW, "Needs review")

    def test_names_dedupe_case_and_extra_spaces(self):
        self.assertEqual(normalized_name("  Profit   and Loss "), normalized_name("profit and loss"))


if __name__ == "__main__": unittest.main()
