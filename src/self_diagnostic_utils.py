from __future__ import annotations

import ast
import json


def parse_code_mode_payload(raw: str | None) -> object | None:
    if raw is None:
        return None
    try:
        return ast.literal_eval(raw)
    except Exception:
        try:
            return json.loads(raw)
        except Exception:
            return raw


def extract_code_mode_result(payload: str | None) -> str | None:
    if payload is None:
        return None
    result_lines: list[str] = []
    in_result = False
    for line in payload.splitlines():
        if in_result:
            result_lines.append(line)
            continue
        if line.startswith("Result: "):
            result_lines.append(line[len("Result: ") :])
            in_result = True
    if not result_lines:
        return None
    return "\n".join(result_lines).strip()


def extract_content_text(value: object | None) -> str | None:
    if isinstance(value, dict) and "content" in value:
        content = value.get("content")
        return str(content) if content is not None else None
    if isinstance(value, str):
        return value
    return None


def extract_allowed_directories(value: object | None) -> list[str]:
    def _from_lines(text: str) -> list[str]:
        lines = []
        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            if line.lower().startswith("allowed directories"):
                continue
            if line.startswith("-"):
                line = line[1:].strip()
            if line:
                lines.append(line)
        return lines

    def _from_item(item: object) -> list[str]:
        if isinstance(item, dict):
            for key in ("path", "directory", "root"):
                candidate = item.get(key)
                if isinstance(candidate, str) and candidate.strip():
                    return [candidate.strip()]
            text = item.get("text")
            if isinstance(text, str):
                return _from_lines(text)
            return []
        if isinstance(item, str):
            return _from_lines(item)
        return []

    if isinstance(value, dict):
        for key in (
            "allowed_directories",
            "allowedDirectories",
            "directories",
            "paths",
            "roots",
        ):
            candidate = value.get(key)
            if isinstance(candidate, (list, tuple, set)):
                items: list[str] = []
                for entry in candidate:
                    items.extend(_from_item(entry))
                return items
            if isinstance(candidate, str):
                lines = _from_lines(candidate)
                if lines:
                    return lines
        content = value.get("content")
        if isinstance(content, (list, tuple, set)):
            items: list[str] = []
            for entry in content:
                items.extend(_from_item(entry))
            if items:
                return items
        if isinstance(content, str):
            return _from_lines(content)
        return []
    if isinstance(value, (list, tuple, set)):
        items: list[str] = []
        for entry in value:
            items.extend(_from_item(entry))
        return items
    if isinstance(value, str):
        return _from_lines(value)
    return []


def contains_expected_name(raw: str | None, expected: str | None) -> bool:
    if not expected:
        return True
    if raw is None:
        return False
    parsed = parse_code_mode_payload(raw)
    text = extract_content_text(parsed)
    haystack = text if text is not None else str(parsed)
    return expected.casefold() in haystack.casefold()


def extract_allowed_directories_from_text(text: str) -> list[str]:
    for line in text.splitlines():
        if "allowed directories" not in line.lower():
            continue
        start = line.find("[")
        end = line.rfind("]")
        if start == -1 or end == -1 or end <= start:
            continue
        raw = line[start : end + 1]
        parsed = parse_code_mode_payload(raw)
        directories = extract_allowed_directories(parsed)
        if directories:
            return directories
    return []
