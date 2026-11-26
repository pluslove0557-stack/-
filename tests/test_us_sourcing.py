"""미국 소싱 계산 로직 테스트.  실행: python -m unittest discover tests"""
import io
import os
import tempfile
import unittest

from app import us_sourcing as us, us_text


class CalcTest(unittest.TestCase):
    def test_price_for_margin(self):
        # cost 10,000 / (1 - 0.10 - 0.30) = 16,666.7 → 100원 올림
        self.assertEqual(us.price_for_margin(10000, 10, 30, 100), 16700)
        self.assertIsNone(us.price_for_margin(10000, 60, 50))

    def test_duty_applies_over_threshold(self):
        s = {**us.DEFAULT_SETTINGS, "fx_rate": 1000, "fx_buffer_pct": 0, "domestic_cs_krw": 0}
        low = us.landed_cost({"price_usd": 100, "free_ship_kr": True}, s)
        high = us.landed_cost({"price_usd": 300, "free_ship_kr": True}, s)
        self.assertEqual(low["duty_krw"], 0)
        # 300,000 × 8% = 24,000 관세, (324,000) × 10% = 32,400 부가세
        self.assertEqual(high["duty_krw"], 56400)

    def test_risk_filter(self):
        self.assertTrue(us.is_blocked(us.check_risks({"title": "Hunting Knife with Sheath"})))
        self.assertFalse(us.is_blocked(us.check_risks({"title": "Tesla Model Y Floor Mats"})))
        warn = us.check_risks({"title": "Wireless Charging Pad"})
        self.assertTrue(any(f["level"] == "warn" for f in warn))

    def test_asin(self):
        self.assertEqual(us.extract_asin("https://www.amazon.com/Some-Thing/dp/B0ABCDEF12?th=1"), "B0ABCDEF12")

    def test_affinity(self):
        m = us.build_affinity_model(["Tesla Model Y Floor Mats", "Tesla Sunshade"])
        self.assertGreater(us.affinity_score("Tesla Model Y Console Tray", m), us.affinity_score("Dog Harness", m))

    def test_longtail(self):
        p = us.longtail_plan(30, 5, 50000, 30)
        self.assertEqual(p["listings_needed"], 18000)


class TextTest(unittest.TestCase):
    def test_title_length_and_prefix(self):
        t = us_text.korean_title({"title": "Tesla Model Y Center Console Organizer Tray Best #1", "brand": "TESMAG"})
        self.assertTrue(t.startswith("[미국]"))
        self.assertLessEqual(len(t), 50)
        self.assertNotIn("#1", t)

    def test_address(self):
        a = us_text.address_to_english("서울특별시 강남구 테헤란로 152", "101동 1203호")
        self.assertEqual(a["address_line1"], "Teheran-ro 152")
        self.assertEqual(a["address_line2"], "101-dong 1203-ho")
        self.assertEqual(a["city_region"], "Gangnam-gu, Seoul-si")
        self.assertEqual(us_text.romanize_name("홍길동"), "Hong Gildong")

    def test_customs_code(self):
        self.assertTrue(us_text.validate_customs_code("p123456789012")[0])
        self.assertFalse(us_text.validate_customs_code("P12345")[0])


class RoutesTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        os.environ["DB_PATH"] = os.path.join(self.tmp, "t.db")
        os.environ.pop("APP_PASSWORD", None)
        from app import create_app
        self.client = create_app().test_client()

    def test_import_and_list(self):
        r = self.client.post("/us/import", data={"file": (io.BytesIO(us.SAMPLE_CSV.encode()), "s.csv")},
                             content_type="multipart/form-data", follow_redirects=True)
        self.assertEqual(r.status_code, 200)
        r = self.client.get("/us/candidates")
        self.assertIn("Cybertruck", r.data.decode())
        self.assertEqual(self.client.get("/us/item/1").status_code, 200)
        self.assertEqual(self.client.get("/us/export?status=후보").status_code, 200)


if __name__ == "__main__":
    unittest.main()
