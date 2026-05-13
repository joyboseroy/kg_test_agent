"""
kg/ingest.py

Ingests kpi_app/kpi.py into FalkorDB knowledge graph.

Parses the Python source using AST to extract:
- File nodes
- Function nodes (with signatures, docstrings, params)
- Feature nodes (derived from function names and docstrings)
- CONTAINS and IMPLEMENTS edges

Usage:
    python kg/ingest.py --mode initial    # ingest first 3 features
    python kg/ingest.py --mode extended   # ingest all 6 features

Requires FalkorDB running:
    docker run -p 6379:6379 falkordb/falkordb
"""

import ast
import argparse
import inspect
import sys
import os
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

try:
    from falkordb import FalkorDB
except ImportError:
    print("ERROR: falkordb not installed. Run: pip install falkordb")
    sys.exit(1)

from kg.schema import (
    CREATE_FILE, CREATE_FUNCTION, CREATE_FEATURE,
    CREATE_CONTAINS, CREATE_IMPLEMENTS,
    QUERY_SUMMARY,
)

# ── Feature metadata ───────────────────────────────────────────────────────────
# Maps function names to feature metadata
# This is the "ontological alignment" described in the paper Section 3.1

FEATURE_MAP = {
    "calculate_cell_availability": {
        "feature_name": "cell_availability",
        "description": "Calculate cell availability as a percentage of uptime",
        "kpi_type": "availability",
        "sla_threshold": "99.9%",
        "status": "initial",
    },
    "check_rsrp_signal": {
        "feature_name": "rsrp_signal_quality",
        "description": "Check RSRP signal strength is within acceptable bounds",
        "kpi_type": "signal_quality",
        "sla_threshold": "-110 dBm",
        "status": "initial",
    },
    "check_call_drop_rate": {
        "feature_name": "call_drop_rate",
        "description": "Check call drop rate does not exceed SLA threshold",
        "kpi_type": "reliability",
        "sla_threshold": "2.0%",
        "status": "initial",
    },
    "check_handover_success_rate": {
        "feature_name": "handover_success_rate",
        "description": "Check handover success rate meets SLA requirement",
        "kpi_type": "mobility",
        "sla_threshold": "95.0%",
        "status": "new",
    },
    "validate_latency_sla": {
        "feature_name": "latency_sla",
        "description": "Validate network latency meets SLA requirements",
        "kpi_type": "latency",
        "sla_threshold": "100ms",
        "status": "new",
    },
    "calculate_throughput": {
        "feature_name": "network_throughput",
        "description": "Calculate network throughput in Mbps",
        "kpi_type": "throughput",
        "sla_threshold": "N/A",
        "status": "new",
    },
}

# Initial features (3) vs extended (all 6)
INITIAL_FUNCTIONS = {
    "calculate_cell_availability",
    "check_rsrp_signal",
    "check_call_drop_rate",
}

EXTENDED_FUNCTIONS = set(FEATURE_MAP.keys())


def parse_kpi_file(filepath: str) -> list[dict]:
    """
    Parse kpi.py using AST and extract function metadata.

    Returns list of dicts with function details.
    """
    with open(filepath, "r") as f:
        source = f.read()

    tree = ast.parse(source)
    functions = []

    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef):
            continue

        # Extract docstring
        docstring = ""
        if (node.body and isinstance(node.body[0], ast.Expr)
                and isinstance(node.body[0].value, ast.Constant)):
            docstring = node.body[0].value.s.strip().split("\n")[0]

        # Extract parameters
        params = [arg.arg for arg in node.args.args]

        # Extract return annotation
        returns = ""
        if node.returns:
            returns = ast.unparse(node.returns)

        # Build signature string
        param_str = ", ".join(params)
        signature = f"def {node.name}({param_str})"

        functions.append({
            "name": node.name,
            "signature": signature,
            "docstring": docstring[:200],
            "params": ", ".join(params),
            "returns": returns,
            "line_number": node.lineno,
        })

    return functions


def ingest_to_falkordb(
    functions: list[dict],
    allowed_functions: set,
    host: str = "localhost",
    port: int = 6379,
    graph_name: str = "kg_test",
) -> None:
    """
    Ingest parsed functions into FalkorDB.

    Args:
        functions: List of function dicts from parse_kpi_file
        allowed_functions: Which functions to ingest (initial or extended)
        host: FalkorDB host
        port: FalkorDB port
        graph_name: Name of the graph in FalkorDB
    """
    db = FalkorDB(host=host, port=port)
    graph = db.select_graph(graph_name)
    now = datetime.now().isoformat()

    # Create File node
    graph.query(CREATE_FILE, {
        "name": "kpi.py",
        "path": "kpi_app/kpi.py",
        "language": "python",
        "ingested_at": now,
    })
    print("Created File node: kpi.py")

    # Create Function and Feature nodes
    ingested = 0
    for fn in functions:
        if fn["name"] not in allowed_functions:
            continue
        if fn["name"] not in FEATURE_MAP:
            continue

        meta = FEATURE_MAP[fn["name"]]

        # Create Function node
        graph.query(CREATE_FUNCTION, {
            "name": fn["name"],
            "file": "kpi.py",
            "signature": fn["signature"],
            "docstring": fn["docstring"],
            "params": fn["params"],
            "returns": fn["returns"],
            "line_number": fn["line_number"],
            "ingested_at": now,
        })

        # Create Feature node
        graph.query(CREATE_FEATURE, {
            "name": meta["feature_name"],
            "description": meta["description"],
            "kpi_type": meta["kpi_type"],
            "sla_threshold": meta["sla_threshold"],
            "status": meta["status"],
            "ingested_at": now,
        })

        # Create edges
        graph.query(CREATE_CONTAINS, {
            "file_name": "kpi.py",
            "func_name": fn["name"],
        })

        graph.query(CREATE_IMPLEMENTS, {
            "func_name": fn["name"],
            "feature_name": meta["feature_name"],
        })

        print(f"  Ingested: {fn['name']} -> Feature: {meta['feature_name']} [{meta['status']}]")
        ingested += 1

    print(f"\nIngested {ingested} functions and features.")

    # Print summary
    result = graph.query(QUERY_SUMMARY)
    print("\nKnowledge Graph summary:")
    for row in result.result_set:
        print(f"  {row[0]}: {row[1]} nodes")


def main():
    parser = argparse.ArgumentParser(
        description="Ingest kpi.py into FalkorDB knowledge graph"
    )
    parser.add_argument(
        "--mode",
        choices=["initial", "extended"],
        default="initial",
        help="initial: 3 features, extended: all 6 features"
    )
    parser.add_argument("--host", default="localhost")
    parser.add_argument("--port", type=int, default=6379)
    parser.add_argument("--graph", default="kg_test")
    parser.add_argument(
        "--kpi-file",
        default="kpi_app/kpi.py",
        help="Path to kpi.py"
    )
    args = parser.parse_args()

    print(f"Ingesting kpi.py in {args.mode} mode...")
    print(f"FalkorDB: {args.host}:{args.port}, graph: {args.graph}\n")

    allowed = INITIAL_FUNCTIONS if args.mode == "initial" else EXTENDED_FUNCTIONS

    functions = parse_kpi_file(args.kpi_file)
    print(f"Parsed {len(functions)} functions from {args.kpi_file}")

    ingest_to_falkordb(
        functions=functions,
        allowed_functions=allowed,
        host=args.host,
        port=args.port,
        graph_name=args.graph,
    )


if __name__ == "__main__":
    main()
