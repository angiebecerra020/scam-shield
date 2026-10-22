# index.py — the file Vercel looks for to start the app.
# It just loads the FastAPI app from app/main.py.
from app.main import app  # noqa: F401
