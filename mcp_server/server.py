"""
mcp_server/server.py

MCP server exposing knowledge graph tools to the generative agent.

Tools exposed:
    query_kg_coverage    — get feature coverage summary
    get_coverage_gaps    — get features with no tests + function context
    get_delta_report     — full delta report for agent consumption
    write_testcase_to_kg — persist a generated test case back to the KG
    get_feature_context  — get full context for a specific feature

Run with:
    python mcp_server/server.py

The agent connects to this server via MCP protocol.

Paper reference: Section 4.5 — MCP Server Integration
"""

import sys
import os
import json
import asyncio
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

try:
    import mcp.server.stdio
    from mcp.server import Server
    from mcp.types import Tool, TextContent
except ImportError:
    print("ERROR: mcp not installed. Run: pip install mcp")
    sys.exit(1)

try:
    from falkordb import FalkorDB
except ImportError:
    print("ERROR: falkordb not installed. Run: pip install falkordb")
    sys.exit(1)

from kg.delta import DeltaEngine
from kg.schema import CREATE_TESTCASE, CREATE_TESTED_BY, CREATE_COVERS

# ── Configuration ──────────────────────────────────────────────────────────────

FALKORDB_HOST = os.getenv("FALKORDB_HOST", "localhost")
FALKORDB_PORT = int(os.getenv("FALKORDB_PORT", "6379"))
GRAPH_NAME = os.getenv("GRAPH_NAME", "kg_test")

# ── MCP Server ─────────────────────────────────────────────────────────────────

app = Server("kg-test-agent")


def get_engine() -> DeltaEngine:
    """Get a fresh DeltaEngine instance."""
    return DeltaEngine(
        host=FALKORDB_HOST,
        port=FALKORDB_PORT,
        graph_name=GRAPH_NAME,
    )


def get_graph():
    """Get FalkorDB graph connection."""
    db = FalkorDB(host=FALKORDB_HOST, port=FALKORDB_PORT)
    return db.select_graph(GRAPH_NAME)


@app.list_tools()
async def list_tools() -> list[Tool]:
    """List all tools exposed by this MCP server."""
    return [
        Tool(
            name="query_kg_coverage",
            description=(
                "Get a summary of feature test coverage from the knowledge graph. "
                "Returns total features, covered count, and coverage percentage."
            ),
            inputSchema={
                "type": "object",
                "properties": {},
                "required": [],
            },
        ),
        Tool(
            name="get_coverage_gaps",
            description=(
                "Get all features that have no associated test cases. "
                "Returns feature names, descriptions, KPI types, and priority. "
                "Use this to decide which tests need to be generated."
            ),
            inputSchema={
                "type": "object",
                "properties": {},
                "required": [],
            },
        ),
        Tool(
            name="get_delta_report",
            description=(
                "Get the full delta report including coverage gaps and function "
                "context for each uncovered feature. This is the primary input "
                "for the test generation agent."
            ),
            inputSchema={
                "type": "object",
                "properties": {},
                "required": [],
            },
        ),
        Tool(
            name="get_feature_context",
            description=(
                "Get detailed context for a specific feature including its "
                "implementing functions, signatures, docstrings, and parameters. "
                "Use this before generating tests for a feature."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "feature_name": {
                        "type": "string",
                        "description": "The feature name in the knowledge graph",
                    }
                },
                "required": ["feature_name"],
            },
        ),
        Tool(
            name="write_testcase_to_kg",
            description=(
                "Persist a generated test case back to the knowledge graph. "
                "Creates TestCase node and links it to the feature and function."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "test_name": {
                        "type": "string",
                        "description": "Test function name e.g. test_cell_availability_normal",
                    },
                    "test_file": {
                        "type": "string",
                        "description": "Test file name e.g. test_generated_kpi.py",
                    },
                    "feature_name": {
                        "type": "string",
                        "description": "Feature being tested",
                    },
                    "function_name": {
                        "type": "string",
                        "description": "Function being covered",
                    },
                },
                "required": ["test_name", "test_file", "feature_name", "function_name"],
            },
        ),
    ]


@app.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    """Handle tool calls from the agent."""

    if name == "query_kg_coverage":
        engine = get_engine()
        coverage = engine.get_feature_coverage()
        total = len(coverage)
        covered = sum(1 for f in coverage if f["test_count"] > 0)
        pct = round(covered / total * 100, 1) if total > 0 else 0

        result = {
            "total_features": total,
            "covered_features": covered,
            "uncovered_features": total - covered,
            "coverage_percent": pct,
            "features": coverage,
        }
        return [TextContent(type="text", text=json.dumps(result, indent=2))]

    elif name == "get_coverage_gaps":
        engine = get_engine()
        gaps = engine.get_coverage_gaps()
        return [TextContent(type="text", text=json.dumps(gaps, indent=2))]

    elif name == "get_delta_report":
        engine = get_engine()
        report = engine.build_delta_report()
        return [TextContent(type="text", text=json.dumps(report, indent=2))]

    elif name == "get_feature_context":
        feature_name = arguments.get("feature_name", "")
        if not feature_name:
            return [TextContent(type="text", text="Error: feature_name required")]

        engine = get_engine()
        functions = engine.get_feature_functions(feature_name)
        coverage = engine.get_feature_coverage()

        feature_info = next(
            (f for f in coverage if f["feature"] == feature_name),
            None
        )

        result = {
            "feature": feature_name,
            "info": feature_info,
            "functions": functions,
        }
        return [TextContent(type="text", text=json.dumps(result, indent=2))]

    elif name == "write_testcase_to_kg":
        test_name = arguments["test_name"]
        test_file = arguments["test_file"]
        feature_name = arguments["feature_name"]
        function_name = arguments["function_name"]

        graph = get_graph()
        now = datetime.now().isoformat()

        # Create TestCase node
        graph.query(CREATE_TESTCASE, {
            "name": test_name,
            "file": test_file,
            "feature": feature_name,
            "status": "generated",
            "generated_by": "agent",
            "created_at": now,
        })

        # Create TESTED_BY edge: Feature -> TestCase
        graph.query(CREATE_TESTED_BY, {
            "feature_name": feature_name,
            "test_name": test_name,
        })

        # Create COVERS edge: TestCase -> Function
        graph.query(CREATE_COVERS, {
            "test_name": test_name,
            "func_name": function_name,
        })

        result = {
            "status": "success",
            "test_name": test_name,
            "feature": feature_name,
            "function": function_name,
            "created_at": now,
        }
        return [TextContent(type="text", text=json.dumps(result, indent=2))]

    else:
        return [TextContent(type="text", text=f"Unknown tool: {name}")]


async def main():
    """Run the MCP server over stdio."""
    print(
        f"Starting KG Test Agent MCP server...\n"
        f"FalkorDB: {FALKORDB_HOST}:{FALKORDB_PORT}, graph: {GRAPH_NAME}\n",
        file=sys.stderr,
    )
    async with mcp.server.stdio.stdio_server() as (read_stream, write_stream):
        await app.run(
            read_stream,
            write_stream,
            app.create_initialization_options(),
        )


if __name__ == "__main__":
    asyncio.run(main())
