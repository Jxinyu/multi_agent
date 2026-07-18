from __future__ import annotations

import re
import subprocess
from pathlib import Path

RULES = {
    "private_key": re.compile(r"BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY"),
    "jwt": re.compile(r"eyJ[A-Za-z0-9_-]{8,}\.eyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}"),
    "api_key": re.compile(r"(?i)(?:api[_-]?key|secret)\s*=\s*['\"](?:sk-|[A-Za-z0-9_-]{24,})"),
    "bearer": re.compile(r"(?i)Authorization['\"]?\s*:\s*['\"]Bearer\s+[A-Za-z0-9._-]{16,}"),
    "url_credential": re.compile(r"(?i)https?://[^\s'\"]+(?:authorization|token|api[_-]?key|secret)=[^&\s'\"]+"),
}


def candidate_files() -> list[Path]:
    output = subprocess.check_output(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"]
    )
    return [Path(item.decode("utf-8")) for item in output.split(b"\0") if item]


def main() -> int:
    findings: list[str] = []
    for path in candidate_files():
        if not path.is_file():
            continue
        try:
            lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
        except OSError:
            continue
        for line_number, line in enumerate(lines, 1):
            for rule_name, pattern in RULES.items():
                if pattern.search(line):
                    findings.append(f"{path.as_posix()}:{line_number}:{rule_name}")
    if findings:
        print("检测到疑似凭据：")
        print("\n".join(findings))
        return 1
    print("未在 Git 跟踪及待提交文件中检测到疑似凭据")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
