"""
kg/schema.py

Knowledge graph schema for the KG-guided test generation system.

Node types:
    File       — source file in the repository
    Function   — Python function within a file
    Feature    — high-level KPI feature (maps to one or more functions)
    TestCase   — generated or hand-written test case

Edge types:
    CONTAINS        File -> Function
    IMPLEMENTS      Function -> Feature
    TESTED_BY       Feature -> TestCase
    COVERS          TestCase -> Function
    DEPENDS_ON      Function -> Function

Based on the knowledge graph schema described in:
"Context-Aware Generative AI for Automated Telecom Test Script Generation"
Section 4.2
"""

# ── Node label constants ───────────────────────────────────────────────────────

NODE_FILE = "File"
NODE_FUNCTION = "Function"
NODE_FEATURE = "Feature"
NODE_TESTCASE = "TestCase"

# ── Edge type constants ────────────────────────────────────────────────────────

EDGE_CONTAINS = "CONTAINS"
EDGE_IMPLEMENTS = "IMPLEMENTS"
EDGE_TESTED_BY = "TESTED_BY"
EDGE_COVERS = "COVERS"
EDGE_DEPENDS_ON = "DEPENDS_ON"

# ── Node property schemas ──────────────────────────────────────────────────────

FILE_PROPERTIES = {
    "name": str,          # filename e.g. "kpi.py"
    "path": str,          # relative path e.g. "kpi_app/kpi.py"
    "language": str,      # "python"
    "ingested_at": str,   # ISO timestamp
}

FUNCTION_PROPERTIES = {
    "name": str,          # function name e.g. "calculate_cell_availability"
    "file": str,          # parent file name
    "signature": str,     # function signature string
    "docstring": str,     # first line of docstring
    "params": str,        # comma-separated parameter names
    "returns": str,       # return type annotation if present
    "line_number": int,   # line number in source file
    "ingested_at": str,
}

FEATURE_PROPERTIES = {
    "name": str,          # feature name e.g. "cell_availability"
    "description": str,   # human-readable description
    "kpi_type": str,      # "availability" | "signal" | "throughput" etc.
    "sla_threshold": str, # SLA threshold if applicable
    "status": str,        # "initial" | "new" | "modified"
    "ingested_at": str,
}

TESTCASE_PROPERTIES = {
    "name": str,          # test function name e.g. "test_cell_availability_normal"
    "file": str,          # test file name
    "feature": str,       # feature being tested
    "status": str,        # "generated" | "hand_written" | "passing" | "failing"
    "generated_by": str,  # "agent" | "human"
    "created_at": str,
}

# ── Cypher query templates ─────────────────────────────────────────────────────

# Create nodes
CREATE_FILE = (
    "MERGE (f:File {name: $name}) "
    "SET f.path = $path, f.language = $language, f.ingested_at = $ingested_at "
    "RETURN f"
)

CREATE_FUNCTION = (
    "MERGE (fn:Function {name: $name, file: $file}) "
    "SET fn.signature = $signature, fn.docstring = $docstring, "
    "fn.params = $params, fn.returns = $returns, "
    "fn.line_number = $line_number, fn.ingested_at = $ingested_at "
    "RETURN fn"
)

CREATE_FEATURE = (
    "MERGE (ft:Feature {name: $name}) "
    "SET ft.description = $description, ft.kpi_type = $kpi_type, "
    "ft.sla_threshold = $sla_threshold, ft.status = $status, "
    "ft.ingested_at = $ingested_at "
    "RETURN ft"
)

CREATE_TESTCASE = (
    "MERGE (tc:TestCase {name: $name, file: $file}) "
    "SET tc.feature = $feature, tc.status = $status, "
    "tc.generated_by = $generated_by, tc.created_at = $created_at "
    "RETURN tc"
)

# Create edges
CREATE_CONTAINS = (
    "MATCH (f:File {name: $file_name}), (fn:Function {name: $func_name}) "
    "MERGE (f)-[:CONTAINS]->(fn)"
)

CREATE_IMPLEMENTS = (
    "MATCH (fn:Function {name: $func_name}), (ft:Feature {name: $feature_name}) "
    "MERGE (fn)-[:IMPLEMENTS]->(ft)"
)

CREATE_TESTED_BY = (
    "MATCH (ft:Feature {name: $feature_name}), (tc:TestCase {name: $test_name}) "
    "MERGE (ft)-[:TESTED_BY]->(tc)"
)

CREATE_COVERS = (
    "MATCH (tc:TestCase {name: $test_name}), (fn:Function {name: $func_name}) "
    "MERGE (tc)-[:COVERS]->(fn)"
)

# Query: find features with no test cases (coverage gaps)
QUERY_COVERAGE_GAPS = """
MATCH (ft:Feature)
WHERE NOT (ft)-[:TESTED_BY]->(:TestCase)
RETURN ft.name AS feature, ft.description AS description,
       ft.kpi_type AS kpi_type, ft.status AS status
"""

# Query: get all features with their test counts
QUERY_FEATURE_COVERAGE = """
MATCH (ft:Feature)
OPTIONAL MATCH (ft)-[:TESTED_BY]->(tc:TestCase)
RETURN ft.name AS feature, ft.description AS description,
       ft.status AS status, COUNT(tc) AS test_count
ORDER BY ft.name
"""

# Query: get function details for a feature
QUERY_FEATURE_FUNCTIONS = """
MATCH (fn:Function)-[:IMPLEMENTS]->(ft:Feature {name: $feature_name})
RETURN fn.name AS function_name, fn.signature AS signature,
       fn.docstring AS docstring, fn.params AS params,
       fn.returns AS returns
"""

# Query: get all nodes summary
QUERY_SUMMARY = """
MATCH (n)
RETURN labels(n)[0] AS node_type, COUNT(n) AS count
ORDER BY node_type
"""
