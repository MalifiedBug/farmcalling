"""
Vercel Serverless Function Entrypoint.
Exposes the FastAPI application to Vercel's Python runtime.
"""

import sys
import os

# Add root directory to sys.path so modules (database, vobiz_client, scheduler, etc.) can be imported
ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from server import app
