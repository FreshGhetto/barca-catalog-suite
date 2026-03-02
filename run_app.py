import os
import sys
import subprocess

def main():
    base = os.path.dirname(os.path.abspath(__file__))
    app_path = os.path.join(base, "apps", "streamlit_app.py")

    # Launch Streamlit in the same Python environment
    cmd = [sys.executable, "-m", "streamlit", "run", app_path, "--server.headless=true"]
    # NOTE: Streamlit will print the local URL (usually http://localhost:8501)
    subprocess.run(cmd, check=False)

if __name__ == "__main__":
    main()
