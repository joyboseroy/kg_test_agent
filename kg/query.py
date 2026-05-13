"""
kg/query.py

Cypher query helpers over FalkorDB.
Provides a clean query interface used by delta.py and the MCP server.

Usage:
    from kg.query import KGQuery
    q = KGQuery()
    features = q.all_features()
    gaps = q.coverage_gaps()
"""

import sys
import os
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
    QUERY_SUMMARY,
)


class KGQuery:
    """
    Clean query interface over FalkorDB.
    All Cypher queries live in schema.py — this class executes them.
    """

    def __init__(
        self,
        host: str = "localhost",
        port: int = 6379,
        graph_name: str = "kg_test",
    ):
        self.db = FalkorDB(host=host, port=port)
        self.graph = self.db.select_graph(graph_name)

    def summary(self) -> list[dict]:
        """Count of each node type in the graph."""
        result = self.graph.query(QUERY_SUMMARY)
        return [{"node_type": r[0], "count": r[1]} for r in result.result_set]

    def all_features(self) -> list[dict]:
        """All features with test counts."""
        result = self.graph.query(QUERY_FEATURE_COVERAGE)
        return [
            {
                "feature": r[0],
                "description": r[1],
                "status": r[2],
                "test_count": r[3],
            }
            for r in result.result_set
        ]

    def coverage_gaps(self) -> list[dict]:
        """Features with no test cases."""
        result = self.graph.query(QUERY_COVERAGE_GAPS)
        return [
            {
                "feature": r[0],
                "description": r[1],
                "kpi_type": r[2],
                "status": r[3],
            }
            for r in result.result_set
        ]

    def feature_functions(self, feature_name: str) -> list[dict]:
        """Functions implementing a given feature."""
        result = self.graph.query(
            QUERY_FEATURE_FUNCTIONS,
            {"feature_name": feature_name}
        )
        return [
            {
                "function_name": r[0],
                "signature": r[1],
                "docstring": r[2],
                "params": r[3],
                "returns": r[4],
            }
            for r in result.result_set
        ]

    def raw(self, cypher: str, params: dict = None) -> list:
        """Execute a raw Cypher query."""
        result = self.graph.query(cypher, params or {})
        return result.result_set


if __name__ == "__main__":
    q = KGQuery()

    print("KG Summary:")
    for row in q.summary():
        print(f"  {row['node_type']}: {row['count']}")

    print("\nAll features:")
    for f in q.all_features():
        covered = "COVERED" if f["test_count"] > 0 else "GAP"
        print(f"  [{covered}] {f['feature']} ({f['test_count']} tests) [{f['status']}]")

    print("\nCoverage gaps:")
    for g in q.coverage_gaps():
        print(f"  {g['feature']} - {g['description']}")
