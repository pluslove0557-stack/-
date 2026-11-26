"""수요→브랜드 로직 테스트."""
import os
import tempfile
import unittest

from app import trend_sourcing as ts

from datetime import date, timedelta

_D0 = date(2021, 11, 28)
GT_CSV = "Category: All categories\n\nWeek,pilates: (Worldwide),yoga: (Worldwide)\n" + "\n".join(
    f"{_D0 + timedelta(weeks=i)},{20 + i // 4},{80 - i // 3}" for i in range(156)
)

TRANSCRIPTS = """Morning reformer class, I always wear my grip socks so I don't slip on the reformer.
Then I grab my water bottle and head out.
---
My essentials for teaching: grip socks, a resistance band and my water bottle. Grip socks are a must.
---
New grip socks from a small brand, honestly the best grip socks. Resistance band workout after.
"""


class TrendTest(unittest.TestCase):
    def test_parse_google_trends(self):
        rows = ts.analyze_trend_text(GT_CSV)
        by = {r["keyword"]: r for r in rows}
        self.assertEqual(set(by), {"pilates", "yoga"})
        self.assertEqual(by["pilates"]["verdict"], "상승")
        self.assertEqual(by["yoga"]["verdict"], "하락")

    def test_simple_csv_and_lt1(self):
        text = "날짜,값\n2024-01,<1\n2024-02,10\n2024-03,20\n2024-04,30\n2024-05,40\n"
        r = ts.analyze_trend_text(text)[0]
        self.assertEqual(r["points"], 5)
        self.assertEqual(r["verdict"], "상승")

    def test_bad_csv(self):
        with self.assertRaises(ValueError):
            ts.parse_trend_csv("no dates here")

    def test_repeated_terms(self):
        terms = ts.repeated_terms(ts.split_transcripts(TRANSCRIPTS))
        names = [t["term"] for t in terms]
        self.assertEqual(names[0], "grip socks")
        top = terms[0]
        self.assertEqual(top["creators"], 3)
        self.assertTrue(top["product_like"])
        self.assertIn("water bottle", names)

    def test_private_label(self):
        r = ts.private_label({"unit_cost": 1.0, "currency": "USD", "fx_usd": 1400, "freight_per_unit": 600,
                              "duty_pct": 0, "packaging": 0, "moq": 500, "fixed_cost": 0,
                              "sale_price": 20000, "channel_fee_pct": 10, "ad_per_sale": 0,
                              "return_pct": 0, "shipping_per_order": 0})
        self.assertEqual(r["landed_krw"], 2000)
        self.assertEqual(r["profit_krw"], 16000)        # 20000 - 2000 fee - 2000 landed
        self.assertEqual(r["inventory_capital"], 1_000_000)
        self.assertEqual(r["payback_units"], 56)        # 1,000,000 / 18,000
        self.assertTrue(r["payback_within_moq"])

    def test_brand_and_scripts(self):
        self.assertTrue(any(b["name"] == "grounded." for b in ts.brand_ideas("grip socks", "grip")))
        s = ts.shortform_scripts("논슬립 양말", "발이 미끄러짐", "흔들림 없음")
        self.assertEqual(len(s), 3)
        self.assertIn("발이 미끄러짐", s[0][0][1])


class TrendRoutesTest(unittest.TestCase):
    def setUp(self):
        os.environ["DB_PATH"] = os.path.join(tempfile.mkdtemp(), "t.db")
        os.environ.pop("APP_PASSWORD", None)
        from app import create_app
        self.c = create_app().test_client()

    def test_flow(self):
        r = self.c.post("/trend/", data={"niche": "필라테스", "keyword_en": "pilates"})
        self.assertEqual(r.status_code, 302)
        nid = r.headers["Location"].rstrip("/").split("/")[-1]
        base = f"/trend/{nid}"
        self.c.post(base + "/save", data={"step": "demand", "keyword_en": "pilates", "trend_csv": GT_CSV})
        self.c.post(base + "/save", data={"step": "creators", "transcripts": TRANSCRIPTS})
        self.c.post(base + "/save", data={"step": "product", "product_en": "grip socks", "product_ko": "필라테스 양말",
                                          "problem": "발이 미끄러짐", "solution": "흔들림 없음", "feeling": "grip"})
        self.c.post(base + "/save", data={"step": "pl", "unit_cost": "0.9", "currency": "usd", "moq": "500",
                                          "sale_price": "18900"})
        html = self.c.get(base).data.decode()
        self.assertIn("grip socks", html)
        self.assertIn("grounded.", html)
        self.assertIn("상승", html)
        self.assertIn("개당 순이익", html)
        self.assertIn("필라테스 양말", self.c.get("/trend/").data.decode())


if __name__ == "__main__":
    unittest.main()
