from __future__ import annotations

import re

_EMAIL_RE = re.compile(r"[\w.\-+]+@[\w.\-]+\.\w+")


def extract_recipient(text: str) -> str:
    match = _EMAIL_RE.search(text)
    return match.group(0).strip() if match else ""


def wants_html_email(text: str) -> bool:
    lower = text.lower()
    return any(k in lower for k in ("html", "rich text", "formatted", "beautiful"))


def _default_html_template(*, subject: str, body_plain: str, recipient: str) -> str:
    safe_subject = subject or "Hello"
    safe_body = body_plain or "Hello from Tempa."
    paragraphs = "".join(
        f'<p style="margin:0 0 16px;line-height:1.6;color:#334155;">{line.strip()}</p>'
        for line in safe_body.split("\n")
        if line.strip()
    )
    return f"""<!DOCTYPE html>
<html lang="en">
<head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{safe_subject}</title></head>
<body style="margin:0;padding:0;background:#f1f5f9;font-family:Segoe UI,Helvetica,Arial,sans-serif;">
  <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:#f1f5f9;padding:32px 16px;">
    <tr><td align="center">
      <table role="presentation" width="600" cellpadding="0" cellspacing="0" style="max-width:600px;background:#ffffff;border-radius:12px;overflow:hidden;box-shadow:0 4px 24px rgba(15,23,42,.08);">
        <tr><td style="background:linear-gradient(135deg,#0f766e,#14b8a6);padding:28px 32px;">
          <h1 style="margin:0;font-size:22px;color:#ffffff;font-weight:600;">{safe_subject}</h1>
        </td></tr>
        <tr><td style="padding:32px;">
          {paragraphs}
          <p style="margin:24px 0 0;font-size:13px;color:#64748b;">Sent with Tempa for {recipient}</p>
        </td></tr>
      </table>
    </td></tr>
  </table>
</body>
</html>"""
