# -*- coding: utf-8 -*-
"""按国家法律法规数据库官方接口检索并下载 DOCX，输出逐文件元数据与校验结果。"""

import csv
import hashlib
import json
import os
import re
import sys
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone

BASE = "https://flk.npc.gov.cn"
SEARCH_URL = BASE + "/law-search/search/list"
DOWNLOAD_URL = BASE + "/law-search/download/pc"
DETAIL_URL = BASE + "/detail?id="
UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)
KEYWORDS = ["法", "条例", "规定", "办法", "决定", "通知", "规范", "细则", "标准", "意见"]
TARGET_COUNT = 150
PAGE_SIZE = 25
CANDIDATE_LIMIT = 260
WORKERS = 6
REQUEST_GAP = 0.2
MIN_BYTES = 1000
MAX_ATTEMPTS = 2


def headers(referer, json_body=False):
    h = {
        "User-Agent": UA,
        "Referer": referer,
        "Accept": "application/json, text/plain, */*",
    }
    if json_body:
        h["Content-Type"] = "application/json"
    return h


def post_json(url, payload, referer, timeout=30):
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(url, data=body, headers=headers(referer, True), method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8", errors="replace"))


def get_bytes(url, referer, timeout=45):
    req = urllib.request.Request(url, headers=headers(referer))
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read(), resp.headers.get("Content-Type", "")


def plain_title(raw):
    return re.sub(r"<[^>]+>", "", raw or "").strip()


def safe_name(title, publish_date, doc_id):
    clean = re.sub(r'[\\/:*?"<>|\r\n\t]', "_", title)
    clean = re.sub(r"_+", "_", clean).strip("._ ")
    stamp = re.sub(r"[^0-9]", "", publish_date or "") or "00000000"
    return "{}_{}_{}.docx".format(clean[:60], stamp, doc_id[:8])


def search_page(keyword, page):
    payload = {
        "searchRange": 1,
        "searchType": 2,
        "searchContent": keyword,
        "pageNum": page,
        "pageSize": PAGE_SIZE,
        "orderByParam": {"order": "-1", "sort": ""},
        "flfgCodeId": [],
        "zdjgCodeId": [],
        "sxx": [],
        "gbrq": [],
        "sxrq": [],
        "gbrqYear": [],
        "xgzlSearch": False,
    }
    return post_json(SEARCH_URL, payload, BASE + "/search")


def collect_candidates():
    found = {}
    for keyword in KEYWORDS:
        page = 1
        while page <= 1:
            try:
                data = search_page(keyword, page)
            except Exception as exc:
                print("search failed: {} p{} {}".format(keyword, page, type(exc).__name__), flush=True)
                break
            rows = data.get("rows") or []
            for row in rows:
                doc_id = row.get("bbbs")
                if not doc_id or doc_id in found:
                    continue
                found[doc_id] = {
                    "doc_id": doc_id,
                    "title": plain_title(row.get("title")),
                    "category": row.get("flxz") or "",
                    "authority": row.get("zdjgName") or "",
                    "publish_date": row.get("gbrq") or "",
                    "effective_date": row.get("sxrq") or "",
                    "status_code": row.get("sxx") or "",
                }
            total = data.get("total") or 0
            time.sleep(REQUEST_GAP)
            if len(rows) < PAGE_SIZE or page * PAGE_SIZE >= total:
                break
            page += 1
        if len(found) >= CANDIDATE_LIMIT:
            break
    return list(found.values())


def signed_url(doc_id):
    url = "{}?format=docx&bbbs={}".format(DOWNLOAD_URL, doc_id)
    raw, _ = get_bytes(url, DETAIL_URL + doc_id, timeout=30)
    data = json.loads(raw.decode("utf-8", errors="replace"))
    payload = data.get("data") or {}
    return payload.get("url") if isinstance(payload, dict) else None


def fetch_docx(url):
    content, ctype = get_bytes(url, BASE + "/", timeout=45)
    if "text/html" in ctype.lower():
        return None, "html_response"
    if len(content) < MIN_BYTES or not content.startswith(b"PK\x03\x04"):
        return None, "invalid_docx"
    return content, None


def process(item):
    doc_id = item["doc_id"]
    reason = None
    content = None
    for attempt in range(MAX_ATTEMPTS):
        try:
            url = signed_url(doc_id)
            if not url:
                reason = "no_docx_url"
                break
            content, reason = fetch_docx(url)
            if content:
                break
        except Exception as exc:
            reason = type(exc).__name__
        if attempt + 1 < MAX_ATTEMPTS:
            time.sleep(REQUEST_GAP * (attempt + 2))
    if not content:
        return {"ok": False, "item": item, "reason": reason}
    return {"ok": True, "item": item, "content": content}


def sha256(content):
    return hashlib.sha256(content).hexdigest()


def load_done(path):
    if not os.path.isfile(path):
        return []
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


def load_failures(path):
    if not os.path.isfile(path):
        return []
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


def write_outputs(root, records, failures):
    meta = os.path.join(root, "metadata")
    os.makedirs(meta, exist_ok=True)
    with open(os.path.join(meta, "manifest.json"), "w", encoding="utf-8") as handle:
        json.dump(records, handle, ensure_ascii=False, indent=2)
    columns = [
        "doc_id", "title", "category", "authority", "publish_date", "effective_date",
        "status_code", "source_url", "official_download_api", "file_name", "bytes",
        "sha256", "retrieved_at",
    ]
    with open(os.path.join(meta, "manifest.csv"), "w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        for row in records:
            writer.writerow(row)
    with open(os.path.join(meta, "failures.json"), "w", encoding="utf-8") as handle:
        json.dump(failures, handle, ensure_ascii=False, indent=2)


def main():
    root = sys.argv[1] if len(sys.argv) > 1 else os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    docs_dir = os.path.join(root, "docs")
    os.makedirs(docs_dir, exist_ok=True)
    meta_dir = os.path.join(root, "metadata")
    os.makedirs(meta_dir, exist_ok=True)
    records = load_done(os.path.join(meta_dir, "manifest.json"))
    failures = load_failures(os.path.join(meta_dir, "failures.json"))
    done_ids = {r["doc_id"] for r in records}
    print("existing: {}".format(len(records)), flush=True)

    candidates = [c for c in collect_candidates() if c["doc_id"] not in done_ids]
    need = TARGET_COUNT - len(records)
    candidates = candidates[: max(need * 2, 0)]
    print("candidates: {}".format(len(candidates)), flush=True)

    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        futures = [pool.submit(process, item) for item in candidates]
        for future in as_completed(futures):
            if len(records) >= TARGET_COUNT:
                continue
            result = future.result()
            item = result["item"]
            if not result["ok"]:
                failures.append({
                    "doc_id": item["doc_id"],
                    "title": item["title"],
                    "reason": result["reason"],
                })
                print("skip {} {}".format(item["doc_id"][:8], result["reason"]), flush=True)
                continue
            content = result["content"]
            name = safe_name(item["title"], item["publish_date"], item["doc_id"])
            with open(os.path.join(docs_dir, name), "wb") as handle:
                handle.write(content)
            record = dict(item)
            record.update({
                "source_url": DETAIL_URL + item["doc_id"],
                "official_download_api": "{}?format=docx&bbbs={}".format(DOWNLOAD_URL, item["doc_id"]),
                "file_name": name,
                "bytes": len(content),
                "sha256": sha256(content),
                "retrieved_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            })
            records.append(record)
            done_ids.add(item["doc_id"])
            if len(records) % 10 == 0 or len(records) >= TARGET_COUNT:
                write_outputs(root, records, failures)
            print("{}/{} {}".format(len(records), TARGET_COUNT, name[:52]), flush=True)

    write_outputs(root, records, failures)
    print("done: {} files, {} failures".format(len(records), len(failures)), flush=True)


if __name__ == "__main__":
    main()
