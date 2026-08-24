import unittest
from pathlib import Path


ROOT = Path(__file__).parents[1]


class AdaptiveUiAndApiContractTests(unittest.TestCase):
    def test_age_and_knowledge_are_distinct_inputs(self):
        html = (ROOT / "web/index.html").read_text(encoding="utf-8")
        js = (ROOT / "web/app.js").read_text(encoding="utf-8")
        self.assertIn("Learner age", html)
        self.assertIn('id="knowledgeLevel"', html)
        self.assertIn("knowledge_level:$('#knowledgeLevel').value", js)
        self.assertIn("age,level:age", js)

    def test_story_style_difficulty_and_rich_output_are_exposed(self):
        html = (ROOT / "web/index.html").read_text(encoding="utf-8")
        js = (ROOT / "web/app.js").read_text(encoding="utf-8")
        for marker in ('id="storyStyle"', 'id="lessonDifficulty"', 'id="conceptSummary"',
                       'id="keyPoints"', 'id="realWorldExample"', 'id="funFact"'):
            self.assertIn(marker, html)
        self.assertIn("l.concept_summary", js)

    def test_api_is_backward_compatible_with_level_alias(self):
        server = (ROOT / "src/story_tutor/web_server.py").read_text(encoding="utf-8")
        self.assertIn('payload.get("age", payload.get("level"', server)
        self.assertIn('"adaptive_learning_profiles"', server)

    def test_browser_service_failures_have_safe_fallbacks(self):
        recognition = (ROOT / "web/voice/speech-recognition-service.js").read_text(encoding="utf-8")
        controller = (ROOT / "web/voice/voice-controller.js").read_text(encoding="utf-8")
        server = (ROOT / "src/story_tutor/web_server.py").read_text(encoding="utf-8")
        self.assertIn("Type your question", recognition)
        self.assertIn('code === "network" ? "unavailable" : "error"', controller)
        self.assertIn('/.well-known/appspecific/com.chrome.devtools.json', server)
        self.assertIn("HTTPStatus.NO_CONTENT", server)


if __name__ == "__main__":
    unittest.main()
