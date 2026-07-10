# ─────────────────────────────────────────────
#  KEYWORD DICTIONARIES
# ─────────────────────────────────────────────

MODULE_KEYWORDS = [
    # Avionics / aerospace domain
    "Altitude Direction", "Altitude Alert", "Radio Altitude", "Landing Gear",
    "Flight Control", "Navigation", "Warning System", "MCU", "Avionics",
    "Autopilot", "Flight Management", "Ground Proximity", "TCAS",
    # Generic software modules
    "Login", "Authentication", "Registration", "User Management",
    "Dashboard", "Search", "Filter", "Payment", "Checkout", "Cart",
    "Order", "Notification", "Email", "Report", "Export", "API",
    "Integration", "Database", "Admin", "Settings", "Profile",
    "Upload", "Download", "Security", "Performance",
]

FUNCTIONAL_VERBS = [
    "shall", "must", "should", "allow", "enable", "prevent", "validate",
    "calculate", "display", "submit", "process", "return", "create",
    "update", "delete", "search", "filter", "sort", "authenticate",
    "authorise", "authorize", "notify", "generate", "export", "import",
    "upload", "download", "verify", "confirm", "reject", "approve",
    "assign", "track", "monitor", "log", "record", "send", "receive",
    # Avionics-specific
    "set", "activate", "deactivate", "inhibit", "arm", "trigger",
    "alert", "warn", "detect", "compute", "output", "indicate",
]

NON_FUNCTIONAL_KEYWORDS = [
    "performance", "response time", "latency", "throughput", "availability",
    "uptime", "scalability", "security", "encryption", "compliance",
    "usability", "accessibility", "reliability", "load", "concurrent users",
    "concurrent", "sla", "milliseconds", "transactions per second",
    "requests per second", "bandwidth", "memory", "cpu", "disk",
]

BOUNDARY_TRIGGERS = [
    "maximum", "minimum", "limit", "length", "range", "between",
    "at least", "at most", "no more than", "up to", "exceed",
    "greater than", "less than", "exactly", "characters", "digits",
    "max", "min", "threshold", "capacity", "quota",
    # Avionics
    "altitude", "feet", "meters", "threshold", "rate",
]

# Signals matching these tokens are discrete (Boolean/Enum) rather than
# numeric — numeric-only concepts like min/max/threshold do not apply to
# them (Req 5: don't put min/max guidance in Additional Information for
# Boolean/Enum outputs).
BOOL_ENUM_TRIGGERS = [
    "true", "false", "enabled", "disabled", "active", "inactive",
    "on", "off", "valid", "invalid", "enum", "boolean", "flag",
    "yes", "no", "set", "reset", "open", "closed", "not_available",
    "not available", "unavailable",
]

SECURITY_KEYWORDS = [
    "authentication", "authorisation", "authorization", "encrypt",
    "token", "password", "injection", "xss", "csrf", "privilege",
    "role", "permission", "access control", "session", "credential",
    "oauth", "jwt", "ssl", "tls", "certificate", "hash", "salt",
    "sanitize", "sanitise", "escape", "firewall", "audit",
]

PERFORMANCE_KEYWORDS = [
    "response time", "latency", "throughput", "load", "concurrent",
    "uptime", "availability", "sla", "milliseconds", "seconds",
    "transactions per second", "requests per second", "benchmark",
    "stress", "capacity", "scalab", "performance",
]

INTEGRATION_KEYWORDS = [
    "integrates", "connects", "communicates", "interacts", "calls",
    "sends to", "receives from", "synchronises", "synchronizes",
    "api", "webhook", "third-party", "external", "service",
    "middleware", "message queue", "kafka", "rabbitmq", "rest",
    "soap", "graphql", "grpc", "endpoint", "interface",
]

VALIDATION_ACTION_WORDS = [
    "display", "show", "submit", "login", "log in", "checkout",
    "register", "upload", "download", "view", "navigate", "click",
    "enter", "fill", "select", "render", "present", "page",
]

# ─────────────────────────────────────────────
#  STEP TEMPLATES
# ─────────────────────────────────────────────

STEP_TEMPLATES = {
    "normal": [
        "1. Ensure all preconditions are satisfied",
        "2. Prepare valid test data for {subject} (values as per SRS/ICD specification)",
        "3. Execute: {action}",
        "4. Observe system response",
        "5. Compare actual result with expected outcome",
        "6. Verify all output signals are within specification",
    ],
    "boundary": [
        "1. Ensure all preconditions are satisfied",
        "2. Identify boundary values for {subject}: minimum, maximum, min-1, max+1 (as per SRS/ICD)",
        "3. Set input to boundary value: [min / max / min-1 / max+1 / null / empty]",
        "4. Execute the action: {action}",
        "5. Record system response for each boundary value",
        "6. Verify system accepts valid limits and rejects out-of-range values",
    ],
    "edge": [
        "1. Configure system to an unusual but valid state",
        "2. Prepare edge-case input for {subject}: {edge_input}",
        "3. Execute {action} under the edge condition",
        "4. Observe system behaviour (concurrent access / state transition / timeout)",
        "5. Verify system remains stable and produces correct output",
        "6. Check for data integrity and no residual state corruption",
    ],
    "robustness": [
        "1. Ensure all preconditions are satisfied",
        "2. Prepare malformed/invalid input for {subject}: {robustness_input}",
        "3. Submit invalid input via: {action}",
        "4. Verify system returns appropriate error or safe-state response",
        "5. Confirm no data corruption, crash, or unsafe output occurred",
        "6. Review system logs for error handling evidence",
    ],
}

# ─────────────────────────────────────────────
#  INPUT TEMPLATES
# ─────────────────────────────────────────────
# Note: for condition-coverage and decision-table requirements, the actual
# signal names replace the placeholder {subject}. These templates are used
# only for standard (non-decision-table) requirements.

INPUT_TEMPLATES = {
    "normal": [
        "{subject}: valid value conforming to SRS specification",
        "Test environment: properly initialised and in known state",
        "All prerequisite signals: at required values per SRS/ICD",
    ],
    "boundary": [
        "{subject}: minimum allowed value (as per SRS/ICD)",
        "{subject}: maximum allowed value (as per SRS/ICD)",
        "{subject}: minimum - 1 (below valid range)",
        "{subject}: maximum + 1 (above valid range)",
        "{subject}: null / None / undefined",
        "{subject}: empty / zero where applicable",
    ],
    "edge": [
        "{subject}: valid value during simultaneous condition change",
        "{subject}: valid value at exact state transition boundary",
        "{subject}: rapid successive input changes (within scan cycle)",
        "{subject}: valid value during partial system initialisation",
    ],
    "robustness": [
        "{subject}: out-of-range value (beyond specification limits)",
        "{subject}: invalid enum value (not in defined set)",
        "{subject}: unexpected NULL / undefined signal",
        "{subject}: corrupted / garbled input data",
        "{subject}: simultaneous conflicting input values",
    ],
}

# ─────────────────────────────────────────────
#  PRECONDITION TEMPLATES
# ─────────────────────────────────────────────

PRECONDITION_TEMPLATES = {
    "normal": [
        "System is initialised and running in {env} environment",
        "Test data for {module} module is prepared and available",
        "All input signals are set to initial/default values",
        "Required dependent modules/services are active",
    ],
    "boundary": [
        "System is initialised and running in {env} environment",
        "Boundary values for {subject} are defined and documented in SRS/ICD",
        "Test data includes minimum, maximum, and out-of-range values",
        "Validation logic for {subject} is implemented and active",
    ],
    "edge": [
        "System is initialised and running in {env} environment",
        "System is in a valid but non-standard state for {module}",
        "Concurrent signal simulation capability is available if required",
        "State transition monitoring is active",
    ],
    "robustness": [
        "System is initialised and running in {env} environment",
        "System logging and fault detection is enabled and actively monitored",
        "Test is performed in isolated environment with no production data",
        "Safety monitors are in passive/observation mode for test",
    ],
}

# ─────────────────────────────────────────────
#  EXPECTED OUTCOME TEMPLATES
# ─────────────────────────────────────────────

EXPECTED_OUTCOME_TEMPLATES = {
    "normal": (
        "System successfully executes {action} with valid inputs. "
        "All output signals are set correctly as per SRS specification. "
        "No unexpected state changes or side effects occur."
    ),
    "boundary": (
        "System correctly handles all boundary values: "
        "accepts inputs within valid range, rejects or handles out-of-range inputs "
        "with appropriate response. No data corruption occurs."
    ),
    "edge": (
        "System remains stable and produces correct output under edge-case conditions. "
        "No data loss, state corruption, or unhandled exceptions occur. "
        "System recovers or transitions gracefully from the edge condition."
    ),
    "robustness": (
        "System responds to invalid/out-of-range input with a safe, defined behaviour. "
        "No data corruption, application crash, or unsafe output state occurs. "
        "Fault is detected and logged. No sensitive information is exposed."
    ),
}
