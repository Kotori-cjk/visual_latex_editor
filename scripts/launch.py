"""Reuse this editor when already running; otherwise start it."""
import json
from pathlib import Path
import sys
import urllib.request
import urllib.error
import webbrowser
from visual_latex_editor.server import main

if len(sys.argv)==1:
    try:
        with urllib.request.urlopen('http://127.0.0.1:8765/api/state',timeout=2) as response:
            state=json.load(response)
        expected=Path(__file__).resolve().parents[1]/'.visual_latex_editor'/'report.tex'
        if Path(state.get('project','')).resolve()!=expected:
            raise SystemExit('Port 8765 is used by another project. Close it or use start.bat --port 8877.')
        webbrowser.open('http://127.0.0.1:8765')
        raise SystemExit(0)
    except (urllib.error.URLError,TimeoutError,OSError):
        pass
sys.argv.append('--open')
main()
