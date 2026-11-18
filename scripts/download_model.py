"""从 HuggingFace 官方源下载模型权重到本地缓存目录，并按 LFS 元数据校验 SHA-256。

本机网络的两个限制决定了实现方式：
1. CDN 会剥掉 `X-Repo-Commit` / `X-Linked-Etag` 响应头，`huggingface_hub` 因此判定
   「资源不在 huggingface.co」并拒绝下载 LFS 文件；
2. 单连接吞吐低（约 30~40 KB/s），但 CDN 支持 Range，多连接并行可显著提速。
因此本脚本改用官方 API 的 `blobs=true` 元数据 + 直连 GET（大文件按 Range 并行分段），
逐文件按官方 SHA-256 校验后落盘；校验不通过的文件不落盘。

用法（项目根目录下，HF_HOME 未设置时落到 .cache/models）：
    .venv\\Scripts\\python.exe scripts/download_model.py
    .venv\\Scripts\\python.exe scripts/download_model.py --skip pytorch_model.bin
"""

from __future__ import annotations

import argparse
import hashlib
import os
import pathlib
import sys
import threading
import time

import requests

PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[1]
API = "https://huggingface.co/api/models/%s?blobs=true"
RESOLVE = "https://huggingface.co/%s/resolve/main/%s"
PARALLEL_THRESHOLD = 16 * 1024 * 1024
CHUNK = 1 << 16


def ca_bundle() -> str | None:
    """优先用环境变量指定的 CA；否则回退到项目内导出的系统证书包。"""
    for key in ("REQUESTS_CA_BUNDLE", "SSL_CERT_FILE"):
        value = os.environ.get(key)
        if value and pathlib.Path(value).is_file():
            return value
    fallback = PROJECT_ROOT / ".cache" / "win-ca-bundle.pem"
    return str(fallback) if fallback.is_file() else None


def fetch_files(repo: str, session: requests.Session) -> list[dict]:
    resp = session.get(API % repo, timeout=30)
    resp.raise_for_status()
    files = []
    for item in resp.json().get("siblings", []):
        lfs = item.get("lfs") or {}
        files.append(
            {
                "name": item["rfilename"],
                "size": int(lfs.get("size") or item.get("size") or 0),
                "sha256": lfs.get("oid") or lfs.get("sha256"),
            }
        )
    return files


def _fetch_range(url: str, start: int, end: int, path: pathlib.Path, verify: str | None) -> None:
    """下载 [start, end] 到 path，按 path 已有长度续传。"""
    pos = start + (path.stat().st_size if path.exists() else 0)
    while pos <= end:
        headers = {"Range": "bytes=%d-%d" % (pos, end), "User-Agent": "curl/8"}
        try:
            with requests.get(url, headers=headers, stream=True, timeout=60, verify=verify) as resp:
                resp.raise_for_status()
                with path.open("ab") as handle:
                    for block in resp.iter_content(CHUNK):
                        handle.write(block)
                        pos += len(block)
                        if pos > end:
                            break
        except Exception as exc:  # 网络抖动：保留已下载部分，重试
            print("  重试 %s@%d（%s）" % (path.name, pos, type(exc).__name__))
            time.sleep(2)


def download_parallel(url: str, target: pathlib.Path, size: int, workers: int, verify: str | None) -> pathlib.Path:
    span = size // workers
    jobs = []
    for i in range(workers):
        start = i * span
        end = size - 1 if i == workers - 1 else (i + 1) * span - 1
        jobs.append((start, end, target.with_name(target.name + ".part%d" % i)))
    threads = [threading.Thread(target=_fetch_range, args=(url, s, e, p, verify)) for s, e, p in jobs]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    merged = target.with_name(target.name + ".merged")
    with merged.open("wb") as out:
        for _, _, part in jobs:
            with part.open("rb") as handle:
                out.write(handle.read())
    for _, _, part in jobs:
        part.unlink()
    return merged


def download_single(url: str, target: pathlib.Path, verify: str | None) -> pathlib.Path:
    tmp = target.with_name(target.name + ".part")
    pos = tmp.stat().st_size if tmp.exists() else 0
    headers = {"Range": "bytes=%d-" % pos} if pos else {}
    with requests.get(url, headers=headers, stream=True, timeout=120, verify=verify) as resp:
        resp.raise_for_status()
        with tmp.open("ab") as handle:
            for block in resp.iter_content(CHUNK):
                handle.write(block)
    return tmp


def sha256_of(path: pathlib.Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description="下载模型权重到本地缓存并按官方 SHA-256 校验")
    parser.add_argument("--repo", default="BAAI/bge-small-zh-v1.5")
    parser.add_argument("--dest", default=None, help="目标目录，默认 $HF_HOME/<模型名>")
    parser.add_argument("--workers", type=int, default=6, help="大文件的并行分段数")
    parser.add_argument("--skip", action="append", default=[], help="跳过指定文件名，可重复")
    args = parser.parse_args()

    dest = pathlib.Path(args.dest) if args.dest else pathlib.Path(
        os.environ.get("HF_HOME", PROJECT_ROOT / ".cache" / "models")
    ) / args.repo.split("/")[-1]
    dest.mkdir(parents=True, exist_ok=True)

    verify = ca_bundle()
    session = requests.Session()
    if verify:
        session.verify = verify

    started = time.time()
    files = [item for item in fetch_files(args.repo, session) if item["name"] not in args.skip]
    ok = failed = 0
    for meta in files:
        target = dest / meta["name"]
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.is_file() and meta["size"] and target.stat().st_size == meta["size"]:
            print("跳过（已存在） %s" % meta["name"])
            ok += 1
            continue
        url = RESOLVE % (args.repo, meta["name"])
        t0 = time.time()
        if meta["size"] >= PARALLEL_THRESHOLD and args.workers > 1:
            merged = download_parallel(url, target, meta["size"], args.workers, verify)
        else:
            merged = download_single(url, target, verify)
        size = merged.stat().st_size
        digest = sha256_of(merged)
        if meta["size"] and size != meta["size"]:
            print("大小不符 %s：%d != %d" % (meta["name"], size, meta["size"]))
            failed += 1
            continue
        if meta["sha256"] and digest != meta["sha256"]:
            print("SHA-256 不符 %s：%s" % (meta["name"], digest[:16]))
            failed += 1
            continue
        merged.replace(target)
        print(
            "下载 %-22s %10d 字节  %.1fs  sha256 %s"
            % (meta["name"], size, time.time() - t0, (meta["sha256"] or "未提供")[:16])
        )
        ok += 1

    total = sum(p.stat().st_size for p in dest.rglob("*") if p.is_file() and ".part" not in p.name)
    print("文件 %d，成功 %d，失败 %d" % (len(files), ok, failed))
    print("目录 %s" % dest)
    print("合计 %d 字节（%.1f MB），耗时 %.1f 秒" % (total, total / 1048576, time.time() - started))
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
