"""规范化 requirements.lock.txt：把 pip freeze 写出的本地 wheel 绝对路径改写为固定版本行。

用法（项目根目录下）：
    .venv\\Scripts\\python.exe scripts/normalize_lock.py

pip freeze 对本地安装的 wheel 会输出 ``torch @ file:///D:/...whl#sha256=...``，
该形式绑定本机路径，跨机器不可用。本脚本把它改写为 ``torch==2.15.0+cpu  # wheel sha256=...``，
保留官方 sha256 作为行尾注释，并打印规范化后文件的 SHA-256（即 runs.deps_sha256 的取值）。

幂等：已规范化的行不会被再次改写。
"""

import hashlib
import pathlib
import re
import sys

LOCK = pathlib.Path("requirements.lock.txt")
PIN = {"torch": "2.15.0+cpu"}
PATTERN = re.compile(r"^(?P<name>[A-Za-z0-9_.\-]+)\s*@\s*file:///(?P<path>.+?)(?:#sha256=(?P<sha>[0-9a-f]{64}))?$")


def main() -> int:
    if not LOCK.is_file():
        print("找不到 %s，先在 venv 内执行 pip freeze > requirements.lock.txt" % LOCK)
        return 2
    out, changed = [], 0
    for line in LOCK.read_text(encoding="utf-8").splitlines():
        m = PATTERN.match(line.strip())
        if m and m.group("name").lower() in PIN:
            name = m.group("name").lower()
            sha = m.group("sha")
            new = "%s==%s" % (name, PIN[name])
            if sha:
                new += "  # wheel sha256=%s" % sha
            if new != line:
                changed += 1
            out.append(new)
        else:
            out.append(line)
    LOCK.write_text("\n".join(out) + "\n", encoding="utf-8")
    digest = hashlib.sha256(LOCK.read_bytes()).hexdigest()
    print("改写行数: %d" % changed)
    print("deps_sha256: %s" % digest)
    for line in out:
        if line.lower().startswith("torch"):
            print("torch 行: %s" % line)
    return 0


if __name__ == "__main__":
    sys.exit(main())
