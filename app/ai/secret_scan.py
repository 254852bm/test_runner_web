"""Conservative detection of likely credentials in AI automation text.
Only field paths are returned; matched values are never returned or logged.
This heuristic cannot guarantee detection of every possible secret.
"""
import re

_SECRET_ASSIGNMENT = re.compile(
    r"""(?ix)\b(?:password|passwd|pwd|api[_-]?key|access[_-]?token|refresh[_-]?token|client[_-]?secret|secret|token|credential|private[_-]?key)\b\s*[:=]\s*["']?([^\s"' ,;)}\]]{8,})"""
)
_BEARER = re.compile(r"(?i)\bauthorization\s*:\s*bearer\s+([A-Za-z0-9._~+/-]{12,})")
_PRIVATE_KEY = re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----")
_TOKEN_PREFIX = re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}|ya29\.[A-Za-z0-9._-]{20,}|sk-[A-Za-z0-9_-]{20,})\b")


def _has_suspicious_secret(text):
    if _PRIVATE_KEY.search(text) or _TOKEN_PREFIX.search(text) or _BEARER.search(text) or _JWT.search(text) or _URL_CREDENTIALS.search(text):
        return True
    # Remove explicit environment and template placeholders before assignment checks.
    text = re.sub(r"\x24\{[^}]+\}|\{\{[^}]+\}\}|<[^>]+>", "PLACEHOLDER", text)
    for match in _SECRET_ASSIGNMENT.finditer(text):
        candidate = match.group(1).rstrip(".")
        if candidate.lower() in {"null", "none", "false", "true", "your_password", "changeme"}:
            continue
        if candidate == "PLACEHOLDER":
            continue
        return True
    return False


def find_suspected_secret_fields(value, path=""):
    """Return field paths containing likely secrets; never return matched text."""
    findings = []
    if isinstance(value, str):
        if _has_suspicious_secret(value):
            findings.append(path or "<text>")
    elif isinstance(value, dict):
        for key, item in value.items():
            child_path = f"{path}.{key}" if path else str(key)
            findings.extend(find_suspected_secret_fields(item, child_path))
    elif isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            child_path = f"{path}[{index}]" if path else f"[{index}]"
            findings.extend(find_suspected_secret_fields(item, child_path))
    return findings


# Additional high-confidence credential formats.
_JWT = re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\b")
_URL_CREDENTIALS = re.compile(r"(?i)https?://[^/\s:@]+:[^/\s@]{4,}@")
