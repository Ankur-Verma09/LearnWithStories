import unittest
from pathlib import Path


ROOT = Path(__file__).parents[1]


class ResponsiveLibraryContractTests(unittest.TestCase):
    def test_manual_entry_and_searchable_suggestions(self):
        html = (ROOT / "web/index.html").read_text(encoding="utf-8")
        self.assertIn('list="topicSuggestions"', html)
        self.assertNotIn('id="concept" list="topicSuggestions" maxlength="120" required disabled', html)

    def test_topic_is_optional_question_is_required_and_preferences_are_deletable(self):
        html = (ROOT / "web/index.html").read_text(encoding="utf-8")
        js = (ROOT / "web/app.js").read_text(encoding="utf-8")
        css = (ROOT / "web/question-preferences.css").read_text(encoding="utf-8")
        self.assertIn('id="concept" list="topicSuggestions" maxlength="120" placeholder=', html)
        self.assertIn('id="lessonQuestion" maxlength="500" rows="3" required', html)
        self.assertIn("data-delete-memory", js)
        self.assertIn("question=$('#lessonQuestion')", js)
        self.assertIn("@media(max-width:760px)", css)

    def test_hierarchy_filters_and_internal_scroll(self):
        html = (ROOT / "web/index.html").read_text(encoding="utf-8")
        css = (ROOT / "web/uploads.css").read_text(encoding="utf-8")
        js = (ROOT / "web/app.js").read_text(encoding="utf-8")
        for marker in ("librarySearch", "librarySubjectFilter", "libraryBookFilter"): self.assertIn(marker, html)
        self.assertIn("overflow:auto", css)
        self.assertIn("@media(max-width:760px)", css)
        self.assertIn("expandedNodes:new Set()", js)
        self.assertIn("No results", js)


if __name__ == "__main__": unittest.main()
