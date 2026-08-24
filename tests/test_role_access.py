import tempfile
import unittest
from pathlib import Path

from story_tutor.auth import hash_password, verify_password
from story_tutor.db import Database
from story_tutor.exams import ExamRequest


ROOT = Path(__file__).parents[1]


class AuthenticationAndOwnershipTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.database = Database(Path(self.temp.name) / "role-access.db")
        self.database.initialize()

    def tearDown(self):
        self.temp.cleanup()

    def test_password_hash_and_multi_role_bootstrap(self):
        encoded = hash_password("SecurePass123")
        self.assertTrue(verify_password("SecurePass123", encoded))
        self.assertFalse(verify_password("wrong", encoded))
        admin = self.database.create_user(
            "admin@example.com", "Administrator", encoded, ["ADMIN", "STUDENT"], bootstrap=True,
        )
        self.assertEqual(admin["roles"], ["ADMIN", "STUDENT"])
        self.assertFalse(self.database.bootstrap_required())

    def test_student_can_change_own_manual_context_but_not_model_context(self):
        admin = self.database.create_user(
            "admin@example.com", "Administrator", hash_password("SecurePass123"),
            ["ADMIN", "STUDENT"], bootstrap=True,
        )
        student = self.database.create_user(
            "student@example.com", "Student", hash_password("StudentPass123"), ["STUDENT"],
        )
        manual = self.database.add_memory("goal", "Practice daily", owner_user_id=student["id"], created_by="USER")
        model = self.database.add_memory("model_preference", "Use diagrams", owner_user_id=student["id"], created_by="MODEL")
        self.assertTrue(self.database.update_memory(manual, "Practice twice daily", student["id"]))
        with self.assertRaises(PermissionError):
            self.database.delete_memory(model, student["id"], False)
        self.assertTrue(self.database.delete_memory(model, admin["id"], True))

    def test_student_inventory_is_owner_scoped(self):
        self.database.create_user(
            "admin@example.com", "Administrator", hash_password("SecurePass123"),
            ["ADMIN"], bootstrap=True,
        )
        first = self.database.create_user(
            "one@example.com", "One", hash_password("StudentPass123"), ["STUDENT"],
        )
        second = self.database.create_user(
            "two@example.com", "Two", hash_password("StudentPass456"), ["STUDENT"],
        )
        self.database.add_memory("goal", "First goal", owner_user_id=first["id"])
        self.database.add_memory("goal", "Second goal", owner_user_id=second["id"])
        visible = self.database.memory_inventory(owner_user_id=first["id"], is_admin=False)
        self.assertEqual([item["content"] for item in visible], ["First goal"])


class ExamPatternTests(unittest.TestCase):
    catalog = [
        {"subject": "English Language"}, {"subject": "Quantitative Aptitude"},
        {"subject": "Reasoning Ability"},
    ]

    def test_ibps_preset_controls_time_questions_and_negative_marking(self):
        request = ExamRequest.from_payload({
            "exam_name": "IBPS practice", "exam_pattern": "IBPS_PO_PRELIMS",
            "exam_type": "OVERALL", "subjects": [item["subject"] for item in self.catalog],
            "difficulty": "MIXED", "question_count": 5, "total_time_minutes": 5,
        }, self.catalog)
        self.assertEqual(request.question_count, 100)
        self.assertEqual(request.total_time_minutes, 60)
        self.assertEqual(request.negative_mark_per_wrong, 0.25)

    def test_ssc_preset_uses_half_mark_penalty(self):
        request = ExamRequest.from_payload({
            "exam_name": "SSC practice", "exam_pattern": "SSC_CGL_TIER1",
            "exam_type": "SUBJECT", "subjects": ["Quantitative Aptitude"],
            "difficulty": "MIXED", "question_count": 10, "total_time_minutes": 10,
        }, self.catalog)
        self.assertEqual(request.negative_mark_per_wrong, 0.5)


class RoleUiAndApiContractTests(unittest.TestCase):
    def test_admin_gates_auth_ui_charts_and_watermark_are_present(self):
        server = (ROOT / "src/story_tutor/web_server.py").read_text(encoding="utf-8")
        html = (ROOT / "web/index.html").read_text(encoding="utf-8")
        js = (ROOT / "web/app.js").read_text(encoding="utf-8")
        worker = (ROOT / "cloudflare/worker.js").read_text(encoding="utf-8")
        self.assertIn("require_admin", server)
        self.assertIn("/api/auth/bootstrap", server)
        self.assertIn("LOCAL_SETUP_REQUIRED", server)
        self.assertIn("data-admin-only", html)
        self.assertIn("ANKUR VERMA", html)
        self.assertIn('id="progressChart"', html)
        self.assertIn('id="studyChart"', html)
        self.assertIn("The service is offline", html)
        self.assertNotIn("The model PC is offline", html)
        self.assertIn("X-LWS-CSRF", js)
        self.assertNotIn('responseHeaders.delete("set-cookie")', worker)


if __name__ == "__main__":
    unittest.main()
