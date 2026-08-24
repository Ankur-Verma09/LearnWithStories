import unittest
from pathlib import Path


ROOT = Path(__file__).parents[1]


class ExamUiContractTests(unittest.TestCase):
    def test_configuration_and_results_controls_exist(self):
        html = (ROOT / "web/index.html").read_text(encoding="utf-8")
        for marker in ('id="examType"', 'id="examOverallSubjects"', 'id="examDifficulty"',
                       'id="examTotalTimer"', 'id="examQuestionTimer"', 'id="examAnalysis"', 'id="examHistory"'):
            self.assertIn(marker, html)

    def test_timer_auto_advance_and_history_reopen_are_present(self):
        js = (ROOT / "web/exam.js").read_text(encoding="utf-8")
        self.assertIn("submitCurrentAnswer(null,true)", js)
        self.assertIn("data-exam-id", js)
        self.assertIn("Start exam", js)

    def test_exam_layout_is_responsive_and_uses_no_animation(self):
        css = (ROOT / "web/exam.css").read_text(encoding="utf-8")
        self.assertIn("@media(max-width:760px)", css)
        self.assertNotIn("@keyframes", css)


if __name__ == "__main__": unittest.main()
