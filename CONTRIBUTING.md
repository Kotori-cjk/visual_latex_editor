# Contributing

Use Python 3.10 or newer and install the checkout with `python -m pip install -e .`.

Before opening a pull request, run:

```sh
python -m unittest discover -s tests -v
node --check src/visual_latex_editor/static/app.js
```

For changes affecting source edits, SyncTeX or compilation, also run `python scripts/check_integration.py` with Tectonic and Poppler installed.

Keep changes tied to a concrete editing workflow. Add a regression test for source corruption, wrong block selection or failed-build recovery. Preserve the original source when a visual edit does not change its text.

Do not commit `.visual_latex_editor/`, personal documents, build history, credentials or dependency binaries. Screenshots and examples should use the included original tea document. Issues should describe the platform, tool versions, reproducible steps and a minimal sample with private information removed.
