"""سرور صرفاً آزمون؛ اجرای عادی Sellora هیچ‌وقت آن را import نمی‌کند."""
from sellora.app import app
from sellora import db
from tests.fixtures import seed_test_products
db.init()
seed_test_products()
