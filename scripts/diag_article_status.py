#!/usr/bin/env python3
"""一次性只读诊断：查三篇文章在头条后台的真实状态。

不发布、不删除、不改动任何线上内容；只打开后台页面、读取列表文本、截图。
运行完把结果写 result.json 并打到日志，供 artifact 收集。
"""
import json
import os
import re
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

AUTH = os.environ.get("TOUTIAO_AUTH_FILE", "/tmp/auth/toutiao_auth.json")
OUT = Path(os.environ.get("DIAG_OUT", "/tmp/article-diag"))
OUT.mkdir(parents=True, exist_ok=True)

# 关键词命中任意一个即认为找到该篇；标题可能被截断，用最有辨识度的片段
TARGETS = [
    {"name": "范志毅vs郑智(后台已见)", "pid": "7709728437853749798",
     "kw": ["范志毅", "亚足联年度最佳", "郑智"]},
    {"name": "西班牙U17身价(疑似没落地)", "pid": "7709728740011475465",
     "kw": ["西班牙U17", "帅惟浩", "22.5万欧"]},
    {"name": "万项青年欧冠(疑似没落地)", "pid": "7709729035387011635",
     "kw": ["万项", "青年欧冠", "中国U17这路子"]},
]

PUB = "https://mp.toutiao.com/profile_v4/graphic/publish"
CANDIDATES = [
    "https://mp.toutiao.com/profile_v4/graphic/articles",
    "https://mp.toutiao.com/profile_v4/graphic/article",
    "https://mp.toutiao.com/profile_v4/content/article",
    "https://mp.toutiao.com/profile_v4/content/articles",
    "https://mp.toutiao.com/profile_v4/article/manage",
    "https://mp.toutiao.com/profile_v4/content/article/manage",
]


def scan(text, page_tag, pages):
    """在三篇目标里找关键词，记录命中与上下文窗口（含状态字样）。"""
    hits = []
    for t in TARGETS:
        matched = [k for k in t["kw"] if k in text]
        rec = {"name": t["name"], "pid": t["pid"],
               "kw_hit": matched, "found": bool(matched), "contexts": []}
        for k in matched[:2]:
            i = text.find(k)
            rec["contexts"].append(text[max(0, i - 120):i + 260].replace("\n", " | "))
        hits.append(rec)
    pages.append({"tag": page_tag, "text_len": len(text), "hits": hits,
                  "status_words": [w for w in ["已发布", "审核中", "审核未通过", "未通过",
                                               "仅自己可见", "草稿", "已下线", "推荐"]
                                   if w in text]})


def main():
    result = {"checked_at": time.strftime("%Y-%m-%d %H:%M:%S"),
              "auth_file": AUTH, "login_ok": False, "pages": [], "errors": []}
    if not Path(AUTH).exists():
        result["errors"].append(f"登录态文件不存在: {AUTH}")
        _dump(result)
        return 0

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context(storage_state=AUTH, locale="zh-CN",
                                  viewport={"width": 1440, "height": 900})
        page = ctx.new_page()
        try:
            page.goto(PUB, wait_until="domcontentloaded", timeout=30000)
            page.wait_for_timeout(3500)
            result["login_ok"] = ("/auth/" not in page.url.lower()
                                  and "/login" not in page.url.lower())
            result["publish_url"] = page.url
            if not result["login_ok"]:
                result["errors"].append("登录态失效：被重定向到登录页")
            else:
                # 从发布页侧边栏抓所有可能通往内容/作品管理的链接
                links = page.eval_on_selector_all(
                    "a[href]",
                    "els => els.map(e => ({t:(e.innerText||'').trim(), h:e.href}))")
                nav = [l for l in links if any(
                    k in (l["t"] + l["h"]) for k in
                    ["内容", "作品", "文章", "管理", "article", "content"])]
                result["nav_links"] = nav[:50]

                body = page.locator("body").inner_text(timeout=8000)
                try:
                    page.screenshot(path=str(OUT / "00_publish.png"))
                except Exception:
                    pass
                scan(body, "publish_page", result["pages"])

                # 把 nav 里的候选也加进来
                urls = list(CANDIDATES)
                for l in nav:
                    h = l.get("h", "")
                    if "article" in h.lower() and h.startswith("http") and h not in urls:
                        urls.append(h)
                urls = urls[:14]

                for i, url in enumerate(urls):
                    try:
                        page.goto(url, wait_until="domcontentloaded", timeout=18000)
                        page.wait_for_timeout(2800)
                        final = page.url
                        txt = page.locator("body").inner_text(timeout=8000)
                        try:
                            page.screenshot(path=str(OUT / f"{i:02d}_page.png"))
                        except Exception:
                            pass
                        result.setdefault("visited", []).append(
                            {"i": i, "url": url, "final": final, "len": len(txt),
                             "head": txt[:300].replace("\n", " | ")})
                        # 只有落在后台内容页（非登录/404）才做关键词扫描
                        if "/auth/" not in final.lower() and len(txt) > 300:
                            scan(txt, f"cand_{i}:{url}", result["pages"])
                    except Exception as e:
                        result["errors"].append(f"{url}: {str(e)[:160]}")
        finally:
            browser.close()

    _dump(result)
    return 0


def _dump(result):
    out = OUT / "result.json"
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2)[:12000], flush=True)
    print(f"\n[diag] written to {out}", flush=True)


if __name__ == "__main__":
    raise SystemExit(main())
