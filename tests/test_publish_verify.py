#!/usr/bin/env python3
"""测试 2026-11-19 假成功修复：草稿 code:0 不再算发布成功，回查作品列表终判。

覆盖：
  * title_in_works_text：全标题 / 截断标题 / 不相同，三种
  * looks_like_works_loaded：渲染完成 vs 空壳
  * verify_published_in_list：三态（published / not_found / unknown）+ not_found 二次确认
  * 关键回归：草稿阶段 code:0 + 列表查不到 → 不得判成功（旧 bug）
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import publisher  # noqa: E402


class FakePage:
    """最小 page mock：goto + locator('body').inner_text + wait_for_timeout。"""

    def __init__(self, texts):
        # texts: 每次读 body 返回的文本序列（模拟异步渲染 / 多轮回查）
        self.texts = list(texts)
        self.i = 0
        self.gotos = []

    def goto(self, url, **kw):
        self.gotos.append(url)

    def wait_for_timeout(self, ms):
        pass

    def locator(self, selector):
        page = self

        class L:
            def inner_text(self, timeout=0):
                t = page.texts[min(page.i, len(page.texts) - 1)]
                page.i += 1
                return t
        return L()


class TestTitleMatch(unittest.TestCase):
    def test_full_title(self):
        t = "范志毅 vs 郑智：两人拿亚足联年度最佳竟隔了12年"
        w = "共 7 条内容 | " + t + " | 11-19 04:04 | 已发布"
        self.assertTrue(publisher.title_in_works_text(t, w))

    def test_truncated_title_prefix(self):
        t = "西班牙U17五人身价压着中国U17三人，帅惟浩22.5万欧领衔"
        w = "共 7 条内容 | 西班牙U17五人身价压着中国U17三人 | 已发布"
        self.assertTrue(publisher.title_in_works_text(t, w))

    def test_whitespace_ignored(self):
        self.assertTrue(publisher.title_in_works_text("球 球 说 球 十 二 字", "球球说球十二字已发布"))

    def test_no_match(self):
        self.assertFalse(publisher.title_in_works_text(
            "万项踢青年欧冠还要交手西班牙队", "共 7 条内容 | 范志毅 vs 郑智 | 已发布"))

    def test_short_title_no_prefix_match(self):
        # 少于 8 字不用前缀，避免误命中
        self.assertFalse(publisher.title_in_works_text("球球", "球球ABC已发布"))

    def test_empty_inputs(self):
        self.assertFalse(publisher.title_in_works_text("", "已发布"))
        self.assertFalse(publisher.title_in_works_text("标题", ""))


class TestWorksLoaded(unittest.TestCase):
    def test_loaded(self):
        for t in ("共 7 条内容", "状态全部已发布审核中审核未通过", "范志毅 | 已发布"):
            self.assertTrue(publisher.looks_like_works_loaded(t))

    def test_empty_shell(self):
        for t in ("", "头条号 | 消息 | 主页 | 创作 | 设置", "加载中..."):
            self.assertFalse(publisher.looks_like_works_loaded(t))


class TestVerifyPublished(unittest.TestCase):
    TITLE = "范志毅 vs 郑智：两人拿亚足联年度最佳竟隔了12年"

    def test_published_first_round(self):
        loaded = "共 7 条内容 | " + self.TITLE + " | 11-19 04:04 | 已发布"
        pg = FakePage([loaded])
        r = publisher.verify_published_in_list(pg, self.TITLE)
        self.assertEqual(r["result"], publisher.VERIFY_PUBLISHED)

    def test_not_found_after_two_rounds(self):
        # 两轮都是「有作品行但没这个标题」→ not_found（草稿/未发布）
        loaded = "共 7 条内容 | 安切洛蒂带巴西 | 11-19 00:10 | 已发布"
        pg = FakePage([loaded, loaded])
        r = publisher.verify_published_in_list(pg, self.TITLE, confirm_rounds=2)
        self.assertEqual(r["result"], publisher.VERIFY_NOT_FOUND)

    def test_not_found_then_appears(self):
        # 第一轮没刷出来、第二轮出现 → published（避免同步延迟误判）
        loaded_no = "共 7 条内容 | 安切洛蒂带巴西 | 已发布"
        loaded_yes = "共 7 条内容 | " + self.TITLE + " | 已发布"
        pg = FakePage([loaded_no, loaded_yes])
        r = publisher.verify_published_in_list(pg, self.TITLE, confirm_rounds=2)
        self.assertEqual(r["result"], publisher.VERIFY_PUBLISHED)

    def test_unknown_when_shell(self):
        pg = FakePage(["", "头条号 | 设置"])
        r = publisher.verify_published_in_list(pg, self.TITLE, confirm_rounds=2)
        self.assertEqual(r["result"], publisher.VERIFY_UNKNOWN)

    def test_regression_draft_code0_not_success(self):
        """核心回归：草稿阶段 code:0 但列表查不到 → 终判必须 not_found（旧 bug 会误报成功）。"""
        publish_results = [{"code": 0, "message": "保存成功", "pgc_id": "7709728740011475465"}]
        self.assertTrue(any(r["code"] == 0 for r in publish_results))  # 草稿 code:0 确实存在
        loaded = "共 7 条内容 | 安切洛蒂带巴西 | 已发布"  # 列表没有这篇 U17
        pg = FakePage([loaded, loaded])
        r = publisher.verify_published_in_list(pg, "西班牙U17五人身价压着中国U17三人，帅惟浩22.5万欧领衔",
                                               confirm_rounds=2)
        # 终判不依赖草稿 code:0，而是列表证据 → not_found
        self.assertEqual(r["result"], publisher.VERIFY_NOT_FOUND)

    def test_uses_works_list_url(self):
        pg = FakePage(["共 7 条内容 | " + self.TITLE + " | 已发布"])
        publisher.verify_published_in_list(pg, self.TITLE)
        self.assertTrue(pg.gotos)
        self.assertIn("graphic/articles", pg.gotos[0])


if __name__ == "__main__":
    unittest.main(verbosity=2)
