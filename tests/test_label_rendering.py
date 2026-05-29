"""PR 0/1: reader-facing 'Confidence' relabelled to 'Model Agreement'.

Source-content assertions keep this dependency-free (no weasyprint import needed).
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _read(name: str) -> str:
    return (ROOT / name).read_text(encoding="utf-8")


def test_pdf_no_standalone_confidence_column_header():
    src = _read("generate_pdf_report.py")
    assert "<th>Confidence</th>" not in src
    assert "<th>Model<br>Agreement</th>" in src


def test_pdf_footnote_disavows_accuracy_meaning():
    src = _read("generate_pdf_report.py")
    assert "Model Agreement (High/Medium/Low)" in src
    assert "NOT realized forecast accuracy" in src


def test_forecasting_js_badge_says_agreement_not_confidence():
    src = _read("static/js/forecasting.js")
    assert "} Confidence</span>" not in src
    assert "} Agreement</span>" in src


def test_chat_widget_has_guest_signin_guard():
    # PR2: logged-out users get a sign-in prompt, not a raw "Not authenticated".
    src = _read("static/js/site.js")
    assert "Please sign in (top-right) to use the AI Market Assistant." in src
    assert "isMember" in src
