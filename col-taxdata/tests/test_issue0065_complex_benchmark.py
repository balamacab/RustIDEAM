from __future__ import annotations

from pathlib import Path
import shutil
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import case_benchmark as benchmark


class Issue65BenchmarkTests(unittest.TestCase):
    def setUp(self) -> None:
        self.spec = benchmark.load_json(benchmark.DEFAULT_SPEC)

    def assessment(self) -> dict:
        rubric = self.spec["semantic_rubric"]
        return {
            "version": rubric["rubric_version"],
            "items": {
                item_id: {"status": "pass", "evidence": [f"ref:{item_id}"]}
                for item_id in rubric["rules"]
            },
        }

    def record(self, backend_id: str, run_index: int) -> dict:
        case = self.spec["case"]
        contract = self.spec["application_contract"]
        return {
            "backend_id": backend_id,
            "run_index": run_index,
            "fingerprints": {
                "problem_text_sha256": case["problem_text_sha256"],
                "raw_request_sha256": case["http_request"]["sha256"],
                "canonical_case_input_sha256": case["canonical_case_input"]["sha256"],
                "case_id": case["canonical_case_input"]["expected_case_id"],
            },
            "application": {
                "contract_version": contract["contract_version"],
                "prompt_template_id": contract["prompt_template_id"],
                "prompt_template_version": contract["prompt_template_version"],
            },
            "generation": benchmark.expected_generation(self.spec),
            "baseline": {
                "main_sha": "1" * 40,
                "database_sha256": "2" * 64,
                "raw_evidence_manifest_sha256": "3" * 64,
                "runtime_image_or_build_id": f"runtime:{backend_id}",
            },
            "runtime_identity": {
                "served_model": f"served:{backend_id}",
                "model_artifact_identity": f"artifact:{backend_id}",
                "backend_build_identity": f"build:{backend_id}",
                "clean_state_policy_id": self.spec["clean_model_state"]["policy_id"],
                "clean_state_established": True,
            },
            "runtime": {
                "prompt_tokens": 3000,
                "completion_tokens": 4000,
                "max_output_tokens": 6144,
                "total_seconds": 200.0,
                "model_load_seconds": 20.0,
                "finish_reason": "stop",
                "malformed_or_incomplete_structured_output": False,
                "case_draft_contract_failure": False,
                "timeout": False,
                "backend_crash": False,
                "context_budget_rejection": False,
                "truncated": False,
            },
            "gates": {gate: True for gate in self.spec["mandatory_run_gates"]},
            "semantic_assessment": self.assessment(),
        }

    def suite(self) -> dict:
        runs = [
            self.record(item["backend_id"], item["run_index"])
            for item in benchmark.build_run_plan(self.spec)
        ]
        concordance = self.spec["e2b_concordance"]
        return {
            "runs": runs,
            "e2b_concordance": {
                "version": concordance["assessment_version"],
                "backend_pair": self.spec["cross_platform_same_model_pair"],
                "items": {
                    item: {"status": "pass", "evidence": [f"cmp:{item}"]}
                    for item in concordance["dimensions"]
                },
            },
        }

    def test_frozen_fingerprints_and_case_identity(self) -> None:
        result = benchmark.verify_package()
        self.assertTrue(result["valid"], result["errors"])
        self.assertEqual(
            result["problem_text_sha256"],
            "ee31a861095b69862f40c2050c1b5469f67506182fbebc64ddfe19f2099980e1",
        )
        self.assertEqual(
            result["canonical_case_input_sha256"],
            "9a88c7d1f818e22ef310ef52a4185d2795d3e51ddd374d22b25e713b522171d4",
        )
        self.assertEqual(
            result["request_sha256"],
            "b0b36bf6ab5c5d46572aee434933b4a87f830c953ef26ee17c78734c82a9b763",
        )
        self.assertEqual(result["expected_case_id"], "CASE-31fdda05d776558393b16095880202d7")

    def test_problem_byte_drift_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            copied = Path(tmp) / "col-taxdata"
            shutil.copytree(ROOT, copied)
            problem = copied / "config/benchmarks/issue65/complex-case.txt"
            problem.write_text(problem.read_text(encoding="utf-8").rstrip("\n"), encoding="utf-8")
            spec = copied / "config/benchmarks/issue65/benchmark.json"
            result = benchmark.verify_package(spec)
        self.assertFalse(result["valid"])
        self.assertIn("problem_text_sha256_mismatch", result["errors"])

    def test_plan_has_nine_isolated_writable_stores(self) -> None:
        plan = benchmark.build_run_plan(self.spec)
        self.assertEqual(len(plan), 9)
        self.assertEqual(len({r["run_id"] for r in plan}), 9)
        self.assertEqual(len({r["database"] for r in plan}), 9)
        self.assertEqual(len({r["case_store"] for r in plan}), 9)

    def test_valid_run_passes(self) -> None:
        backend = self.spec["model_matrix"][0]["id"]
        result = benchmark.score_run(self.record(backend, 1), self.spec)
        self.assertTrue(result["pass"], result["failures"])

    def test_output_ceiling_fails_even_with_stop(self) -> None:
        backend = self.spec["model_matrix"][0]["id"]
        record = self.record(backend, 1)
        record["runtime"]["completion_tokens"] = 6144
        record["runtime"]["finish_reason"] = "stop"
        result = benchmark.score_run(record, self.spec)
        self.assertIn("runtime:output_ceiling", result["failures"])

    def test_each_runtime_failure_flag_fails(self) -> None:
        backend = self.spec["model_matrix"][0]["id"]
        flags = (
            "malformed_or_incomplete_structured_output",
            "case_draft_contract_failure",
            "timeout",
            "backend_crash",
            "context_budget_rejection",
            "truncated",
        )
        for flag in flags:
            with self.subTest(flag=flag):
                record = self.record(backend, 1)
                record["runtime"][flag] = True
                result = benchmark.score_run(record, self.spec)
                self.assertIn(f"runtime:{flag}", result["failures"])

    def test_generation_gate_and_all_minimum_gates_are_strict(self) -> None:
        backend = self.spec["model_matrix"][0]["id"]
        drift = self.record(backend, 1)
        drift["generation"]["top_p"] = 0.95
        self.assertIn(
            "generation:does_not_match_frozen_policy",
            benchmark.score_run(drift, self.spec)["failures"],
        )
        for gate in self.spec["mandatory_run_gates"]:
            with self.subTest(gate=gate):
                record = self.record(backend, 1)
                record["gates"][gate] = False
                self.assertIn(
                    f"gate:{gate}",
                    benchmark.score_run(record, self.spec)["failures"],
                )

    def test_semantic_rubric_requires_pass_and_evidence(self) -> None:
        backend = self.spec["model_matrix"][0]["id"]
        item = next(iter(self.spec["semantic_rubric"]["rules"]))
        failed = self.record(backend, 1)
        failed["semantic_assessment"]["items"][item]["status"] = "fail"
        self.assertIn(
            f"semantic_assessment:{item}:not_pass",
            benchmark.score_run(failed, self.spec)["failures"],
        )
        empty = self.record(backend, 1)
        empty["semantic_assessment"]["items"][item]["evidence"] = []
        self.assertIn(
            f"semantic_assessment:{item}:evidence_required",
            benchmark.score_run(empty, self.spec)["failures"],
        )

    def test_suite_passes_without_cross_backend_byte_identity(self) -> None:
        suite = self.suite()
        suite["runs"][0]["runtime_identity"]["model_artifact_identity"] = "gguf:a"
        suite["runs"][3]["runtime_identity"]["model_artifact_identity"] = "fastflow:b"
        result = benchmark.score_suite(suite, self.spec)
        self.assertTrue(result["pass"], result["failures"])

    def test_suite_rejects_baseline_or_concordance_drift(self) -> None:
        baseline = self.suite()
        baseline["runs"][-1]["baseline"]["database_sha256"] = "9" * 64
        self.assertIn(
            "suite:frozen_baseline_mismatch",
            benchmark.score_suite(baseline, self.spec)["failures"],
        )
        concordance = self.suite()
        dimension = self.spec["e2b_concordance"]["dimensions"][0]
        concordance["e2b_concordance"]["items"][dimension]["status"] = "fail"
        self.assertIn(
            f"e2b_concordance:{dimension}:not_pass",
            benchmark.score_suite(concordance, self.spec)["failures"],
        )

    def test_http_contract_matches_merged_issue66_adapter(self) -> None:
        contract = self.spec["application_contract"]
        self.assertEqual(
            contract["http_transport"],
            {
                "adapter": "tools/case_http.py",
                "method": "POST",
                "endpoint": "/v1/cases",
                "required_success_fingerprints": [
                    "raw_request_sha256",
                    "case_input_sha256",
                ],
            },
        )
        self.assertEqual(
            contract["failure_codes"],
            {
                "provider_timeout": "CASE_PROVIDER_TIMEOUT",
                "output_ceiling": "CASE_OUTPUT_LIMIT",
                "context_budget_rejection": "CASE_CONTEXT_LIMIT",
                "malformed_or_contract_failure": "INVALID_CASE_DRAFT",
            },
        )

    def test_issue65_never_authorizes_benchmark_execution(self) -> None:
        self.assertFalse(self.spec["complex_benchmark_execution_authorized"])
        self.assertEqual(self.spec["purpose"], "preparation_only")


if __name__ == "__main__":
    unittest.main()
