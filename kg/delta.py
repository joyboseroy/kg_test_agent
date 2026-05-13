"""
kg/delta.py

Delta engine — detects meaningful changes between KG states.

Implements the delta detection described in the paper Section 4.3:
  Stage 1: Compare current KG state vs previous snapshot
  Stage 2: Relevance filtering
  Stage 3: Impact propagation — find features with no tests (coverage gaps)

In this simplified implementation:
  - Delta = features present in KG but with no associated TestCase nodes
  - This directly maps to "coverage gaps" in the paper

Usage:
    python kg/delta.py
    python kg/delta.py --host localhost --port 6379 --graph kg_test
"""

import sys
import os
import json
import argparse
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

try:
    from falkordb import FalkorDB
except ImportError:
    print("ERROR: falkordb not installed. Run: pip install falkordb")
    sys.exit(1)

from kg.schema import (
    QUERY_COVERAGE_GAPS,
    QUERY_FEATURE_COVERAGE,
    QUERY_FEATURE_FUNCTIONS,
)


class DeltaEngine:
    """
    Detects coverage gaps and structural deltas in the knowledge graph.

    Paper reference: Section 3.2, Section 4.3
    """

    def __init__(
        self,
        host: str = "localhost",
        port: int = 6379,
        graph_name: str = "kg_test",
    ):
        self.db = FalkorDB(host=host, port=port)
        self.graph = self.db.select_graph(graph_name)

    def get_coverage_gaps(self) -> list[dict]:
        """
        Find features with no associated test cases.

        This is Stage 1 + Stage 2 of the delta engine:
        identify features that are not covered by any test.

        Returns:
            List of dicts: {feature, description, kpi_type, status}
        """
        result = self.graph.query(QUERY_COVERAGE_GAPS)
        gaps = []
        for row in result.result_set:
            gaps.append({
                "feature": row[0],
                "description": row[1],
                "kpi_type": row[2],
                "status": row[3],
            })
        return gaps

    def get_feature_coverage(self) -> list[dict]:
        """
        Get all features with their test counts.

        Returns:
            List of dicts: {feature, description, status, test_count}
        """
        result = self.graph.query(QUERY_FEATURE_COVERAGE)
        coverage = []
        for row in result.result_set:
            coverage.append({
                "feature": row[0],
                "description": row[1],
                "status": row[2],
                "test_count": row[3],
            })
        return coverage

    def get_feature_functions(self, feature_name: str) -> list[dict]:
        """
        Get function details for a given feature.

        Used by the agent to understand what to test.

        Args:
            feature_name: The feature name in the KG

        Returns:
            List of dicts with function details
        """
        result = self.graph.query(
            QUERY_FEATURE_FUNCTIONS,
            {"feature_name": feature_name}
        )
        functions = []
        for row in result.result_set:
            functions.append({
                "function_name": row[0],
                "signature": row[1],
                "docstring": row[2],
                "params": row[3],
                "returns": row[4],
            })
        return functions

    def build_delta_report(self) -> dict:
        """
        Build a structured delta report for the agent.

        This is the output of Stage 3 (impact propagation):
        a ranked list of (feature, impact, recommended_action) tuples.

        Paper reference: Section 4.3 Stage 3

        Returns:
            Dict with:
                - timestamp: when the report was generated
                - total_features: total features in KG
                - covered_features: features with at least one test
                - gaps: list of coverage gap dicts with function context
                - summary: human-readable summary
        """
        coverage = self.get_feature_coverage()
        gaps = self.get_coverage_gaps()

        total = len(coverage)
        covered = sum(1 for f in coverage if f["test_count"] > 0)

        # Enrich gaps with function context (for the agent)
        enriched_gaps = []
        for gap in gaps:
            functions = self.get_feature_functions(gap["feature"])
            enriched_gaps.append({
                **gap,
                "functions": functions,
                "recommended_action": "generate_tests",
                "priority": "high" if gap["status"] == "new" else "medium",
            })

        # Sort by priority — new features first
        enriched_gaps.sort(
            key=lambda x: 0 if x["priority"] == "high" else 1
        )

        report = {
            "timestamp": datetime.now().isoformat(),
            "total_features": total,
            "covered_features": covered,
            "uncovered_features": total - covered,
            "coverage_percent": round(covered / total * 100, 1) if total > 0 else 0,
            "gaps": enriched_gaps,
            "summary": (
                f"{total - covered} of {total} features have no test coverage. "
                f"Coverage: {round(covered / total * 100, 1) if total > 0 else 0}%. "
                f"{sum(1 for g in enriched_gaps if g['priority'] == 'high')} high-priority gaps "
                f"(new features)."
            ),
        }

        return report


def main():
    parser = argparse.ArgumentParser(
        description="Run delta engine and print coverage report"
    )
    parser.add_argument("--host", default="localhost")
    parser.add_argument("--port", type=int, default=6379)
    parser.add_argument("--graph", default="kg_test")
    parser.add_argument(
        "--output",
        default=None,
        help="Save report to JSON file"
    )
    args = parser.parse_args()

    engine = DeltaEngine(
        host=args.host,
        port=args.port,
        graph_name=args.graph,
    )

    print("Running delta engine...")
    report = engine.build_delta_report()

    print(f"\n{report['summary']}")
    print(f"\nFeature coverage:")
    for f in engine.get_feature_coverage():
        status = "COVERED" if f["test_count"] > 0 else "GAP"
        print(f"  [{status}] {f['feature']} ({f['test_count']} tests) [{f['status']}]")

    if report["gaps"]:
        print(f"\nCoverage gaps ({len(report['gaps'])}):")
        for gap in report["gaps"]:
            print(f"  [{gap['priority'].upper()}] {gap['feature']}")
            print(f"    Description: {gap['description']}")
            for fn in gap["functions"]:
                print(f"    Function: {fn['signature']}")

    if args.output:
        with open(args.output, "w") as f:
            json.dump(report, f, indent=2)
        print(f"\nReport saved to {args.output}")

    return report


if __name__ == "__main__":
    main()
