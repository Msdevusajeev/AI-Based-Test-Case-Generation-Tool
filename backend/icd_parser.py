"""
icd_parser.py

Extracts input/output signal specifications (data type, valid range, unit,
enum values) from ICD / supporting-document text, so that requirement
parsing in document_ingestion.py and boundary/ECP generation in
test_case_generator.py can cross-reference signals that are named in the
SRS but only fully specified (type / range / unit) in the ICD.

Handles the three text shapes that file_parser.py can produce for a table:

  1. DOCX table rows (pipe-separated):
       "Engine Speed | Integer | 0 to 200 | RPM"

  2. XLSX rows (one "Header: Value" line per cell, grouped by header cycle):
       "Input: Engine Speed"
       "Type: Integer"
       "Values: 0 to 200"
       "Unit: RPM"

  3. PDF-extracted table text, where tight column spacing collapses and
     cells run together on one line with no separators at all:
       "Engine SpeedInteger0 to 200RPM"

Returned spec dict per signal:
    {
        "name":          "Engine Speed",
        "data_type":     "Integer" | "Float" | "Boolean" | "Enum" | "String",
        "range_lo":      float | None,
        "range_hi":      float | None,
        "unit":          str,           # "" if not found
        "valid_values":  List[str] | None,   # for enum-style Values columns
        "raw":           str,           # source line, for debugging
    }
"""

import re
from typing import Dict, List, Optional

_TYPE_WORDS = ("integer", "int", "float", "double", "real", "boolean", "bool", "enum", "string")

_NUMERIC_TYPE = {
    "integer": "Integer", "int": "Integer",
    "float": "Float", "double": "Float", "real": "Float",
    "boolean": "Boolean", "bool": "Boolean",
    "enum": "Enum",
    "string": "String",
}

# "0 to 200", "-40 to 85", "0-200"
_RANGE_PATTERN = re.compile(
    r'(-?\d+(?:\.\d+)?)\s*(?:to|-|–|\.\.)\s*(-?\d+(?:\.\d+)?)',
    re.IGNORECASE
)

# Common unit tokens that show up as the last column of an ICD row.
_UNIT_PATTERN = re.compile(
    r'\b(RPM|ms|msec|sec|s|Hz|kHz|MHz|V|mV|A|mA|°C|degC|deg|%|kg|lb|psi|'
    r'bar|kPa|Pa|Nm|rad|rad/s|m|km|mm|cm|ft|kt|kts|knots)\b'
)

_HEADER_WORDS = {
    "input", "output", "parameter", "signal", "name", "type", "datatype",
    "data type", "values", "value", "range", "unit", "units", "description",
    "default", "notes", "note", "constraint", "constraints",
}


def _is_header_row(cells: List[str]) -> bool:
    """True if every non-empty cell is a column-header word, not real data."""
    lowered = [c.strip().lower() for c in cells if c.strip()]
    if not lowered:
        return True
    return all(c in _HEADER_WORDS for c in lowered)


def _classify_type_token(token: str) -> Optional[str]:
    t = token.strip().lower()
    for word, canon in _NUMERIC_TYPE.items():
        if t == word or t.startswith(word):
            return canon
    return None


def _extract_unit(text: str) -> str:
    m = _UNIT_PATTERN.search(text)
    return m.group(1) if m else ""


def _parse_pipe_row(line: str) -> Optional[Dict]:
    """Parses 'Name | Type | Lo to Hi | Unit' (order-flexible) pipe rows."""
    if "|" not in line:
        return None
    cells = [c.strip() for c in line.split("|")]
    if _is_header_row(cells) or len(cells) < 2:
        return None

    name = None
    data_type = None
    range_lo = range_hi = None
    unit = ""
    valid_values = None

    # First cell that isn't a recognisable type/range/unit is the signal name.
    remaining = []
    for cell in cells:
        if name is None and _classify_type_token(cell) is None and not _RANGE_PATTERN.search(cell):
            name = cell
            continue
        remaining.append(cell)

    if not name:
        return None

    for cell in remaining:
        ct = _classify_type_token(cell)
        if ct:
            data_type = ct
            continue
        rm = _RANGE_PATTERN.search(cell)
        if rm:
            range_lo, range_hi = float(rm.group(1)), float(rm.group(2))
            continue
        um = _UNIT_PATTERN.search(cell)
        if um and not unit:
            unit = um.group(1)
            continue
        # Enum-style values: comma/and separated words, no numeric range
        if re.search(r'[A-Za-z]', cell) and ("," in cell or " and " in cell.lower()):
            valid_values = [v.strip() for v in re.split(r',|\band\b', cell, flags=re.IGNORECASE) if v.strip()]

    if data_type is None:
        data_type = "Enum" if valid_values else ("Integer" if range_lo is not None and range_lo == int(range_lo) and range_hi == int(range_hi) else ("Float" if range_lo is not None else "String"))

    return {
        "name": name, "data_type": data_type, "range_lo": range_lo,
        "range_hi": range_hi, "unit": unit, "valid_values": valid_values,
        "raw": line.strip(),
    }


def _parse_concatenated_row(line: str) -> Optional[Dict]:
    """
    PDF-style rows with no whitespace between columns:
        "Engine SpeedInteger0 to 200RPM"
    Name = everything before the type keyword; range = numeric 'to' span;
    unit = trailing unit token (if any) right after the range.
    """
    m = re.search(
        r'^(.*?)(' + "|".join(_TYPE_WORDS) + r')\s*'
        r'(-?\d+(?:\.\d+)?)\s*to\s*(-?\d+(?:\.\d+)?)\s*([A-Za-z%°]*)\s*$',
        line.strip(), re.IGNORECASE
    )
    if not m:
        return None
    name = m.group(1).strip(" :\t-")
    if not name or len(name) < 2:
        return None
    data_type = _NUMERIC_TYPE.get(m.group(2).lower(), "Integer")
    range_lo, range_hi = float(m.group(3)), float(m.group(4))
    unit = m.group(5).strip()
    return {
        "name": name, "data_type": data_type, "range_lo": range_lo,
        "range_hi": range_hi, "unit": unit, "valid_values": None,
        "raw": line.strip(),
    }


def _parse_xlsx_style(text: str) -> List[Dict]:
    """
    Groups consecutive 'Header: Value' lines into records. A new record
    starts whenever a header repeats (i.e. we've cycled back to a header
    we've already seen in the current record).
    """
    line_re = re.compile(r'^([A-Za-z][A-Za-z /]{1,20}):\s*(.+)$')
    records: List[Dict] = []
    current: Dict[str, str] = {}

    for raw_line in text.splitlines():
        m = line_re.match(raw_line.strip())
        if not m:
            continue
        header = m.group(1).strip().lower()
        value = m.group(2).strip()
        if header not in _HEADER_WORDS:
            continue
        if header in current:
            if current:
                records.append(current)
            current = {}
        current[header] = value
    if current:
        records.append(current)

    specs = []
    for rec in records:
        name = rec.get("input") or rec.get("output") or rec.get("parameter") or rec.get("signal") or rec.get("name")
        if not name:
            continue
        type_val = rec.get("type") or rec.get("datatype") or rec.get("data type") or ""
        data_type = _classify_type_token(type_val) or None
        values_val = rec.get("values") or rec.get("value") or rec.get("range") or ""
        range_lo = range_hi = None
        valid_values = None
        rm = _RANGE_PATTERN.search(values_val)
        if rm:
            range_lo, range_hi = float(rm.group(1)), float(rm.group(2))
        elif values_val and re.search(r'[A-Za-z]', values_val):
            valid_values = [v.strip() for v in re.split(r',|\band\b', values_val, flags=re.IGNORECASE) if v.strip()]
        unit = rec.get("unit") or rec.get("units") or _extract_unit(values_val)
        if data_type is None:
            data_type = "Enum" if valid_values else ("Float" if range_lo is not None and range_lo != int(range_lo) else ("Integer" if range_lo is not None else "String"))
        specs.append({
            "name": name, "data_type": data_type, "range_lo": range_lo,
            "range_hi": range_hi, "unit": unit, "valid_values": valid_values,
            "raw": " | ".join(f"{k}={v}" for k, v in rec.items()),
        })
    return specs


def parse_icd_signals(*texts: str) -> Dict[str, Dict]:
    """
    Parses one or more document texts (ICD, supporting docs) into a
    name-keyed dict of signal specs. Later texts can add signals not
    already found; first definition of a given name wins (ICD should be
    uploaded before less-authoritative supporting docs, but this is
    tolerant either way).
    """
    signals: Dict[str, Dict] = {}

    for text in texts:
        if not text:
            continue

        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            spec = _parse_pipe_row(line)
            if spec is None:
                spec = _parse_concatenated_row(line)
            if spec:
                key = spec["name"].strip().lower()
                if key not in signals:
                    signals[key] = spec

        for spec in _parse_xlsx_style(text):
            key = spec["name"].strip().lower()
            if key not in signals:
                signals[key] = spec

    return signals


def to_icd_pipe_line(spec: Dict) -> str:
    """
    Renders a spec back into the canonical 'Name | Type | Lo to Hi | Unit'
    form that existing regex-based lookups in test_case_generator.py
    already know how to parse, so the same detection logic works whether
    the range came from inline SRS text or from a cross-referenced ICD.
    """
    name = spec["name"]
    dt = spec["data_type"]
    if spec.get("range_lo") is not None and spec.get("range_hi") is not None:
        lo = spec["range_lo"]
        hi = spec["range_hi"]
        lo_s = str(int(lo)) if lo == int(lo) else str(lo)
        hi_s = str(int(hi)) if hi == int(hi) else str(hi)
        unit = spec.get("unit") or ""
        return f"{name} | {dt} | {lo_s} to {hi_s} | {unit}".rstrip(" |")
    if spec.get("valid_values"):
        return f"{name} | Enum | {', '.join(spec['valid_values'])}"
    return f"{name} | {dt}"


def find_referenced_signals(content: str, signals: Dict[str, Dict]) -> Dict[str, Dict]:
    """
    Returns the subset of `signals` whose name appears (case-insensitive,
    whole-phrase) in `content` — i.e. the signals this specific
    requirement/chunk actually talks about.
    """
    matched = {}
    lower_content = content.lower()
    for key, spec in signals.items():
        name = spec["name"]
        # word-boundary-safe phrase search, tolerant of internal whitespace
        pattern = r'\b' + re.escape(name).replace(r'\ ', r'\s+') + r'\b'
        if re.search(pattern, content, re.IGNORECASE):
            matched[key] = spec
        elif name.lower() in lower_content:
            matched[key] = spec
    return matched
