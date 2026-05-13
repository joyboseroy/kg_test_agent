"""
agent/agent.py

Generative test agent.

Workflow (paper Section 4.4):
  1. Query MCP server for delta report (coverage gaps)
  2. For each gap: get feature context from KG via MCP
  3. Build prompt with KG subgraph + function signatures
  4. Call TinyLlama via Ollama to generate test code
  5. Write generated tests to file
  6. Persist test case metadata back to KG via MCP

Usage:
    # Start MCP server first:
    python mcp_server/server.py &

    # Then run agent:
    python agent/agent.py
    python agent/agent.py --output tests/test_generated_kpi.py
"""

import sys
import os
import json
import argparse
import subprocess
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

try:
    import ollama
except ImportError:
    print("ERROR: ollama not installed. Run: pip install ollama")
    sys.exit(1)

# Direct KG access (fallback when MCP server not running)
from kg.delta import DeltaEngine
from kg.schema import CREATE_TESTCASE, CREATE_TESTED_BY, CREATE_COVERS

try:
    from falkordb import FalkorDB
    FALKORDB_AVAILABLE = True
except ImportError:
    FALKORDB_AVAILABLE = False

# ── Configuration ──────────────────────────────────────────────────────────────

FALKORDB_HOST = os.getenv("FALKORDB_HOST", "localhost")
FALKORDB_PORT = int(os.getenv("FALKORDB_PORT", "6379"))
GRAPH_NAME = os.getenv("GRAPH_NAME", "kg_test")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "tinyllama")
OUTPUT_FILE = "tests/test_generated_kpi.py"


# ── Prompt builder ─────────────────────────────────────────────────────────────

def build_test_prompt(gap: dict) -> str:
    """
    Build a prompt for TinyLlama to generate pytest test cases.

    Uses the KG subgraph (feature info + function signatures) as context.
    Paper reference: Section 4.4 — Context assembly + Prompt engineering
    """
    feature = gap["feature"]
    description = gap["description"]
    kpi_type = gap["kpi_type"]
    functions = gap.get("functions", [])

    fn_context = ""
    for fn in functions:
        fn_context += f"""
Function: {fn['function_name']}
Signature: {fn['signature']}
Description: {fn['docstring']}
Parameters: {fn['params']}
Returns: {fn['returns']}
"""

    prompt = f"""You are a Python test engineer. Write pytest test cases.

FEATURE TO TEST: {feature}
DESCRIPTION: {description}
KPI TYPE: {kpi_type}

{fn_context}

Write 3 pytest test functions for this feature:
1. Test normal/happy path with valid inputs
2. Test edge case or boundary value
3. Test invalid input raises ValueError

Rules:
- Use pytest style (def test_...)
- Import from kpi_app.kpi import the function
- Each test must have an assert statement
- Keep tests simple and clear
- No explanations, just code

```python"""

    return prompt


# ── LLM call ──────────────────────────────────────────────────────────────────

def generate_tests_with_tinyllama(prompt: str, model: str = OLLAMA_MODEL) -> str:
    """
    Call TinyLlama via Ollama to generate test code.

    Args:
        prompt: The prompt with KG context
        model: Ollama model name

    Returns:
        Generated Python test code as string
    """
    try:
        response = ollama.generate(
            model=model,
            prompt=prompt,
            options={
                "temperature": 0.2,    # low temp for code generation
                "num_predict": 512,    # enough for 3 test functions
                "stop": ["```"],       # stop at end of code block
            }
        )
        return response["response"].strip()
    except Exception as e:
        print(f"  Ollama error: {e}")
        print(f"  Is Ollama running? Try: ollama serve")
        print(f"  Is TinyLlama pulled? Try: ollama pull tinyllama")
        return ""


# ── Test code cleanup ─────────────────────────────────────────────────────────

def extract_test_functions(raw_code: str, feature_name: str) -> tuple[list[str], str]:
    """
    Extract test function names and clean up generated code.

    Returns:
        (list of test function names, cleaned code string)
    """
    lines = raw_code.split("\n")
    test_names = []
    clean_lines = []

    for line in lines:
        # Skip markdown artifacts
        if line.strip().startswith("```"):
            continue
        clean_lines.append(line)
        # Extract test function names
        stripped = line.strip()
        if stripped.startswith("def test_"):
            name = stripped.split("(")[0].replace("def ", "").strip()
            test_names.append(name)

    # If no test functions found, generate fallback names
    if not test_names:
        fn_safe = feature_name.replace("-", "_")
        test_names = [
            f"test_{fn_safe}_normal",
            f"test_{fn_safe}_edge_case",
            f"test_{fn_safe}_invalid_input",
        ]

    return test_names, "\n".join(clean_lines)


# ── KG write-back ─────────────────────────────────────────────────────────────

def write_tests_to_kg(
    test_names: list[str],
    feature_name: str,
    function_name: str,
    test_file: str,
    host: str = FALKORDB_HOST,
    port: int = FALKORDB_PORT,
    graph_name: str = GRAPH_NAME,
) -> None:
    """
    Persist generated test cases back to FalkorDB KG.
    Paper reference: Section 4.6 — Test Execution and Feedback Loop
    """
    if not FALKORDB_AVAILABLE:
        print("  FalkorDB not available — skipping KG write-back")
        return

    db = FalkorDB(host=host, port=port)
    graph = db.select_graph(graph_name)
    now = datetime.now().isoformat()

    for test_name in test_names:
        try:
            graph.query(CREATE_TESTCASE, {
                "name": test_name,
                "file": os.path.basename(test_file),
                "feature": feature_name,
                "status": "generated",
                "generated_by": "agent",
                "created_at": now,
            })
            graph.query(CREATE_TESTED_BY, {
                "feature_name": feature_name,
                "test_name": test_name,
            })
            graph.query(CREATE_COVERS, {
                "test_name": test_name,
                "func_name": function_name,
            })
            print(f"  KG: persisted {test_name}")
        except Exception as e:
            print(f"  KG write error for {test_name}: {e}")


# ── Main agent loop ────────────────────────────────────────────────────────────

def run_agent(
    output_file: str = OUTPUT_FILE,
    model: str = OLLAMA_MODEL,
    host: str = FALKORDB_HOST,
    port: int = FALKORDB_PORT,
    graph_name: str = GRAPH_NAME,
    dry_run: bool = False,
) -> None:
    """
    Main agent loop.

    1. Get delta report from KG
    2. For each coverage gap:
       a. Build prompt from KG context
       b. Generate tests with TinyLlama
       c. Write tests to file
       d. Persist test metadata to KG
    """
    print(f"KG Test Generation Agent")
    print(f"Model: {model}")
    print(f"FalkorDB: {host}:{port}, graph: {graph_name}")
    print(f"Output: {output_file}")
    print("=" * 50)

    # Step 1: Get delta report
    print("\nStep 1: Querying knowledge graph for coverage gaps...")
    engine = DeltaEngine(host=host, port=port, graph_name=graph_name)
    report = engine.build_delta_report()

    print(f"\n{report['summary']}")

    if not report["gaps"]:
        print("\nNo coverage gaps found. All features are tested.")
        return

    # Step 2: Generate tests for each gap
    os.makedirs(os.path.dirname(output_file), exist_ok=True)

    all_test_code = [
        '"""',
        f'Generated test cases for kpi_app/kpi.py',
        f'Generated by: KG Test Agent with {model}',
        f'Timestamp: {datetime.now().isoformat()}',
        f'Source: Knowledge Graph delta report',
        '"""',
        '',
        'import pytest',
        'import sys',
        'import os',
        'sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))',
        'from kpi_app.kpi import (',
        '    calculate_cell_availability,',
        '    check_rsrp_signal,',
        '    check_call_drop_rate,',
        '    check_handover_success_rate,',
        '    validate_latency_sla,',
        '    calculate_throughput,',
        ')',
        '',
        '',
    ]

    generated_count = 0

    for i, gap in enumerate(report["gaps"], 1):
        feature = gap["feature"]
        functions = gap.get("functions", [])
        fn_name = functions[0]["function_name"] if functions else feature

        print(f"\nStep 2.{i}: Generating tests for [{gap['priority'].upper()}] {feature}")
        print(f"  Function: {fn_name}")
        print(f"  Description: {gap['description']}")

        # Build prompt
        prompt = build_test_prompt(gap)

        if dry_run:
            print("  [DRY RUN] Skipping LLM call")
            raw_code = f"""
def test_{feature}_normal():
    # Generated placeholder
    pass

def test_{feature}_edge_case():
    # Generated placeholder
    pass

def test_{feature}_invalid():
    # Generated placeholder
    pass
"""
        else:
            print(f"  Calling {model}...")
            raw_code = generate_tests_with_tinyllama(prompt, model)

        if not raw_code:
            print(f"  No code generated for {feature} — skipping")
            continue

        # Extract and clean
        test_names, clean_code = extract_test_functions(raw_code, feature)

        # Add section header
        all_test_code.append(f"# {'=' * 60}")
        all_test_code.append(f"# Feature: {feature}")
        all_test_code.append(f"# KPI type: {gap['kpi_type']}")
        all_test_code.append(f"# Priority: {gap['priority']}")
        all_test_code.append(f"# {'=' * 60}")
        all_test_code.append("")
        all_test_code.append(clean_code)
        all_test_code.append("")

        print(f"  Generated {len(test_names)} test functions: {test_names}")

        # Step 3: Write to KG
        if not dry_run:
            write_tests_to_kg(
                test_names=test_names,
                feature_name=feature,
                function_name=fn_name,
                test_file=output_file,
                host=host,
                port=port,
                graph_name=graph_name,
            )

        generated_count += len(test_names)

    # Write all tests to file
    with open(output_file, "w") as f:
        f.write("\n".join(all_test_code))

    print(f"\n{'=' * 50}")
    print(f"Agent complete.")
    print(f"Generated {generated_count} test functions across {len(report['gaps'])} features.")
    print(f"Written to: {output_file}")

    # Print updated coverage
    print("\nUpdated KG coverage:")
    updated_coverage = engine.get_feature_coverage()
    for f in updated_coverage:
        status = "COVERED" if f["test_count"] > 0 else "GAP"
        print(f"  [{status}] {f['feature']} ({f['test_count']} tests)")


def main():
    parser = argparse.ArgumentParser(
        description="KG-guided generative test agent"
    )
    parser.add_argument(
        "--output",
        default=OUTPUT_FILE,
        help="Output test file path"
    )
    parser.add_argument(
        "--model",
        default=OLLAMA_MODEL,
        help="Ollama model name (default: tinyllama)"
    )
    parser.add_argument("--host", default=FALKORDB_HOST)
    parser.add_argument("--port", type=int, default=FALKORDB_PORT)
    parser.add_argument("--graph", default=GRAPH_NAME)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Skip LLM calls, generate placeholder tests"
    )
    args = parser.parse_args()

    run_agent(
        output_file=args.output,
        model=args.model,
        host=args.host,
        port=args.port,
        graph_name=args.graph,
        dry_run=args.dry_run,
    )


if __name__ == "__main__":
    main()
