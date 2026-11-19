"""入库决策的单元测试：新增、未变、内容变更、重复内容、强制重写。"""

from __future__ import annotations

import unittest

from src.cli.ingest import decide_action

DIGEST_A = "a" * 64
DIGEST_B = "b" * 64


class TestDecideAction(unittest.TestCase):
    def test_new_document(self):
        self.assertEqual(decide_action("d1", DIGEST_A, {}, {}), ("insert", "new"))

    def test_unchanged_document_skipped(self):
        self.assertEqual(decide_action("d1", DIGEST_A, {"d1": DIGEST_A}, {}), ("skip", "unchanged"))

    def test_content_changed_inserts_again(self):
        self.assertEqual(decide_action("d1", DIGEST_B, {"d1": DIGEST_A}, {}), ("insert", "content_changed"))

    def test_duplicate_content_skipped(self):
        # seen 的键是内容哈希、值是 doc_id
        action, reason = decide_action("d2", DIGEST_A, {}, {DIGEST_A: "d1"})
        self.assertEqual(action, "skip")
        self.assertTrue(reason.startswith("duplicate_content"))

    def test_same_doc_same_digest_not_treated_as_duplicate(self):
        action, reason = decide_action("d1", DIGEST_A, {"d1": DIGEST_A}, {DIGEST_A: "d1"})
        self.assertEqual((action, reason), ("skip", "unchanged"))

    def test_force_rewrites_everything(self):
        self.assertEqual(decide_action("d1", DIGEST_A, {"d1": DIGEST_A}, {}, force=True), ("insert", "content_changed"))


if __name__ == "__main__":
    unittest.main()
