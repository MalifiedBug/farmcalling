#!/usr/bin/env python3
"""
FarmCalling Launcher Script.
Launches the Streamlit Application (which auto-initializes the FastAPI server and scheduler).
"""

import sys
import os
import subprocess

def main():
    base_dir = os.path.dirname(os.path.abspath(__file__))
    os.chdir(base_dir)

    # Determine python and streamlit binaries
    venv_streamlit = os.path.join(base_dir, ".venv", "bin", "streamlit")
    if os.path.exists(venv_streamlit):
        streamlit_cmd = venv_streamlit
    else:
        streamlit_cmd = "streamlit"

    cmd = [
        streamlit_cmd,
        "run",
        "app.py",
        "--server.port=8501",
        "--server.headless=true",
        "--browser.gatherUsageStats=false"
    ]

    print("=" * 60)
    print("🌾 Starting FarmCalling: Vobiz Automated Calling Platform")
    print(f"👉 Streamlit UI: http://localhost:8501")
    print(f"👉 Webhook & Audio Server: http://localhost:8000")
    print("=" * 60)

    try:
        subprocess.run(cmd)
    except KeyboardInterrupt:
        print("\nShutting down FarmCalling...")

if __name__ == "__main__":
    main()

