#!/usr/bin/env python3
"""Statement Lens desktop app — a native window over the offline pipeline.

Opens a webview window (WebView2 on Windows, WKWebView on macOS) showing a
drag-and-drop upload page.  The user picks a statement PDF and its password; we
run the *same* offline pipeline the CLI uses — ``extractor`` -> ``reporter`` —
on a worker thread and load the generated report into the window.

Why pywebview and not a local web server: ``offline_guard`` (imported first,
exactly as in ``lens.py``) replaces ``socket.socket`` with a function that
raises, so a loopback HTTP server would crash.  pywebview talks to the page
over the platform webview's native bridge, not a socket, so the offline
guarantee stays intact — no server, no network, ever.
"""

import offline_guard  # noqa: F401 — install the network block FIRST, before anything else

import json
import os
import pathlib
import sys
import threading

import webview


# --------------------------------------------------------------------------
# Paths
# --------------------------------------------------------------------------
def _resource_path(rel):
    """Locate a bundled resource, both from source and from a PyInstaller exe.

    PyInstaller unpacks bundled data under ``sys._MEIPASS``; from source we sit
    next to this file.
    """
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, rel)


def _data_dir():
    """A per-user *writable* dir for categories, the temp CSV and the report.

    The exe may live in a read-only location (Program Files), so we never write
    next to it.
    """
    if sys.platform.startswith("win"):
        root = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    else:
        root = os.path.expanduser("~")
    d = os.path.join(root, "StatementLens")
    os.makedirs(d, exist_ok=True)
    return d


def _file_url(path):
    return pathlib.Path(path).resolve().as_uri()


def _friendly_error(e):
    """Turn a pipeline exception into a message a non-technical user can act on."""
    from extractor import NoTextLayer

    if isinstance(e, NoTextLayer):
        return ("This PDF is a scanned image with no text layer. Run OCR on it "
                "first (e.g. with ocrmypdf), then try again.")
    name = type(e).__name__
    if "password" in name.lower() or "password" in str(e).lower():
        return ("Couldn't open the PDF — the password looks incorrect, or the "
                "statement isn't password-protected (try leaving it blank).")
    if isinstance(e, FileNotFoundError):
        return str(e)
    return "Something went wrong while processing the statement: %s" % (
        str(e) or name)


# --------------------------------------------------------------------------
# JS-facing API (exposed to the page as pywebview.api.*)
# --------------------------------------------------------------------------
class Api:
    def __init__(self):
        self._window = None
        self._busy = False

    def set_window(self, window):
        self._window = window

    def pick_file(self):
        """Open a native file picker; return the chosen PDF path, or ''."""
        result = self._window.create_file_dialog(
            webview.OPEN_DIALOG, allow_multiple=False,
            file_types=("PDF files (*.pdf)", "All files (*.*)"))
        if not result:
            return ""
        return result[0]

    def analyze(self, pdf_path, password):
        """Start the pipeline on a worker thread so the UI stays responsive."""
        if self._busy:
            return
        self._busy = True
        threading.Thread(
            target=self._run, args=(pdf_path, password or ""), daemon=True
        ).start()

    # -- internals ---------------------------------------------------------
    def _progress(self, state, message=""):
        js = "onProgress(%s, %s)" % (json.dumps(state), json.dumps(message))
        try:
            self._window.evaluate_js(js)
        except Exception:
            pass  # window may be gone; nothing to report to

    def _run(self, pdf_path, password):
        try:
            report_path = self._pipeline(pdf_path, password)
        except Exception as e:  # never crash the window — show the reason
            self._progress("error", _friendly_error(e))
            return
        finally:
            self._busy = False
        self._progress("done", "")
        self._window.load_url(_file_url(report_path))

    def _pipeline(self, pdf_path, password):
        if not pdf_path or not os.path.isfile(pdf_path):
            raise FileNotFoundError("Please choose a statement PDF first.")

        # Imported late, after offline_guard is installed (same order as lens.py).
        from extractor import extract_pdf
        from reporter import build_report
        from digest import write_digest
        from analysis import load_transactions
        from categorise import ensure_categories_file
        from lens import _write_csv

        data = _data_dir()
        cats_path = os.path.join(data, "categories.json")
        csv_path = os.path.join(data, "transactions.csv")
        report_path = os.path.join(data, "report.html")

        self._progress("extracting", "Reading the statement…")
        categories = ensure_categories_file(cats_path)
        res = extract_pdf(pdf_path, password=password)
        _write_csv(res["rows"], csv_path)

        self._progress("analysing", "Categorising transactions…")
        # build_report loads the CSV, categorises and computes the analysis.
        out, _n = build_report(csv_path, categories, out_path=report_path,
                               reconcile=res["reconcile"])

        self._progress("rendering", "Building your report…")
        # Anonymised digest alongside the report (same as the CLI's --summary).
        # A nice-to-have — never let it block the report.
        try:
            txns = load_transactions(csv_path, categories)
            write_digest(txns, path=os.path.join(data, "digest.md"))
        except Exception:
            pass
        return out


def _self_check():
    """Verify the frozen bundle has every module and data file it needs.

    Run by CI (``StatementLens.exe --self-check``) so a missing import or an
    un-bundled resource fails the build instead of a user's first launch. Opens
    no window and touches no network.
    """
    ui = _resource_path(os.path.join("ui", "upload.html"))
    assert os.path.isfile(ui), "bundled ui/upload.html missing: %s" % ui
    # Import the whole pipeline the same way _pipeline() does.
    import extractor, reporter, digest, analysis, categorise, lens  # noqa: F401
    assert hasattr(extractor, "extract_pdf")
    assert hasattr(reporter, "build_report")
    # offline_guard must already have neutralised the network.
    import socket
    try:
        socket.socket()
    except offline_guard.OfflineViolation:
        pass
    else:
        raise AssertionError("offline_guard did not block socket.socket")
    print("self-check OK")


def main():
    if "--self-check" in sys.argv[1:]:
        _self_check()
        return
    api = Api()
    window = webview.create_window(
        "Statement Lens",
        url=_resource_path(os.path.join("ui", "upload.html")),
        js_api=api, width=920, height=780, min_size=(640, 560))
    api.set_window(window)
    webview.start()


if __name__ == "__main__":
    main()
