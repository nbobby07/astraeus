import importlib.util
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location(
    "commit_subject", Path(__file__).resolve().parents[1] / "scripts/check-commit.py"
)
commit_subject = importlib.util.module_from_spec(spec)
spec.loader.exec_module(commit_subject)


class CommitSubjectTests(unittest.TestCase):
    def test_conventional_subject_and_limits(self):
        for subject in ["fix(hardware): resolve partition parents", "feat(boot)!: change UKI paths", "docs: " + "x" * 66]:
            with self.subTest(subject=subject):
                self.assertTrue(commit_subject.valid_subject(subject))
        for subject in ["", "fix: ", "fix: trailing ", "Fix boot", "unknown: change", "docs: " + "x" * 67, "fix: one\nfix: two"]:
            with self.subTest(subject=subject):
                self.assertFalse(commit_subject.valid_subject(subject))
