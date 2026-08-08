import sys
from pathlib import Path

# Add venv site-packages
venv_site_packages = Path(__file__).parent / ".venv" / "lib" / "python3.9" / "site-packages"
if venv_site_packages.exists() and str(venv_site_packages) not in sys.path:
    sys.path.insert(0, str(venv_site_packages))

import unittest
from app.services.ai_agent import ai_agent
from app.core.database import db


class TestSotuvchiAISystem(unittest.TestCase):
    def test_01_products_exist(self):
        products = db.get_products()
        self.assertGreater(len(products), 0, "Mahsulotlar katalogi bo'sh bo'lmasligi kerak")
        print("✓ Products catalog test passed!")

    def test_02_ai_agent_greeting(self):
        response = ai_agent.generate_response(
            session_id="test-session-1",
            user_message="Assalomu alaykum",
            user_name="Otabek"
        )
        self.assertEqual(response.intent, "greeting")
        self.assertIn("Otabek", response.reply_text)
        print("✓ AI Agent Greeting test passed!")

    def test_03_ai_agent_product_query(self):
        response = ai_agent.generate_response(
            session_id="test-session-1",
            user_message="iPhone 15 Pro narxi qancha?",
            user_name="Otabek"
        )
        self.assertEqual(response.intent, "query")
        self.assertTrue(len(response.recommended_products) > 0)
        self.assertIn("iPhone 15 Pro", response.recommended_products[0].name)
        print("✓ AI Agent Product Query test passed!")

    def test_04_ai_agent_order_creation(self):
        response = ai_agent.generate_response(
            session_id="test-session-2",
            user_message="Men iPhone 15 Pro sotib olmoqchiman. Ismim Sardor, tel: +998901234567",
            user_name="Sardor"
        )
        self.assertIsNotNone(response.order_draft, "Buyurtma shakllanishi kerak edi")
        self.assertEqual(response.order_draft.customer_name, "Sardor")
        self.assertIn("998901234567", response.order_draft.customer_phone)
        print("✓ Order creation test passed!")


if __name__ == "__main__":
    unittest.main()
