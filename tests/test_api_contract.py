import unittest
from pathlib import Path

from story_tutor.web_server import LibraryReadCache


SERVER = (Path(__file__).parents[1] / "src/story_tutor/web_server.py").read_text(encoding="utf-8")


class HierarchyApiContractTests(unittest.TestCase):
    def test_library_cache_reuses_data_and_can_be_invalidated(self):
        cache = LibraryReadCache()
        calls: list[int] = []
        self.assertEqual(cache.get("catalog", lambda: calls.append(1) or ["first"]), ["first"])
        self.assertEqual(cache.get("catalog", lambda: calls.append(2) or ["second"]), ["first"])
        cache.invalidate()
        self.assertEqual(cache.get("catalog", lambda: calls.append(3) or ["third"]), ["third"])
        self.assertEqual(calls, [1, 3])

    def test_hierarchy_search_filters_and_manual_entry_routes_exist(self):
        for marker in ('/api/library/hierarchy', '/api/library/snapshot', 'query.get("search"', 'query.get("subject"',
                       'query.get("document_id"', '/api/topics/manual'):
            self.assertIn(marker, SERVER)

    def test_library_reads_are_cached_and_invalidated_after_writes(self):
        self.assertIn("class LibraryReadCache", SERVER)
        self.assertIn("def invalidate_library_cache", SERVER)
        self.assertGreaterEqual(SERVER.count("application.invalidate_library_cache()"), 6)

    def test_review_and_reprocess_routes_exist(self):
        self.assertIn("def do_PATCH", SERVER)
        self.assertIn('/reprocess', SERVER)
        self.assertIn("application.database.update_topic", SERVER)

    def test_manual_entry_is_independent_of_model_client(self):
        manual_start = SERVER.index('if path == "/api/topics/manual"')
        lesson_start = SERVER.index('if path == "/api/lesson"')
        self.assertLess(manual_start, lesson_start)
        self.assertNotIn("create_model_client", SERVER[manual_start:lesson_start])

    def test_specific_question_and_memory_deletion_are_exposed(self):
        self.assertIn('question=" ".join(str(payload.get("question", "")).split())', SERVER)
        self.assertIn('["api", "memories"]', SERVER)
        self.assertIn("delete_memory", SERVER)


if __name__ == "__main__": unittest.main()
