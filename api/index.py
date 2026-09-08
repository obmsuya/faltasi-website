import os
import sys

# Add the project root to Python's path
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)

# Tell Django which settings module to use
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "faltasi_website.settings")

from django.core.wsgi import get_wsgi_application

app = get_wsgi_application()