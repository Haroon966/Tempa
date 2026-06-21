from __future__ import annotations

import html
import re
from typing import Sequence

_EMAIL_RE = re.compile(r"[\w.\-+]+@[\w.\-]+\.\w+")

_PLACEHOLDER_DOMAINS = frozenset(
    {
        "example.com",
        "example.org",
        "example.net",
        "test.com",
        "test.test",
        "localhost",
        "invalid",
        "domain.com",
        "email.com",
        "company.com",
        "yourdomain.com",
        "sampleemail.com",
        "mail.example",
    }
)

_PLACEHOLDER_LOCALS = frozenset(
    {
        "recipient",
        "user",
        "someone",
        "email",
        "test",
        "example",
        "you",
        "your.name",
        "your.email",
        "firstname.lastname",
        "name",
        "username",
        "placeholder",
    }
)

# Reference layout for LLM-generated HTML emails: table-based, inline CSS, neutral palette.
EMAIL_HTML_STRUCTURE_HINT = (
    "Use a table-based HTML email with inline CSS only (no external stylesheets). "
    "Neutral colors only — no brand theme, no colored accent bars, no logos. "
    "Structure: optional eyebrow label, headline (h1), 1-3 sentence body paragraph, "
    "optional key/value details block (gray background), optional CTA button (dark neutral), "
    "optional closing line and signature. Max width 600px, Arial/Helvetica, mobile-friendly padding."
)


def extract_recipient(text: str) -> str:
    for email in extract_all_recipients(text):
        if is_valid_recipient_email(email):
            return email
    return ""


def extract_all_recipients(text: str) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for match in _EMAIL_RE.finditer(text):
        email = match.group(0).strip()
        key = email.lower()
        if key not in seen:
            seen.add(key)
            ordered.append(email)
    return ordered


def is_placeholder_email(email: str) -> bool:
    address = email.strip().lower()
    if not address or "@" not in address:
        return True
    local, _, domain = address.partition("@")
    if not local or not domain or "." not in domain:
        return True
    if domain in _PLACEHOLDER_DOMAINS:
        return True
    if local in _PLACEHOLDER_LOCALS:
        return True
    if domain.endswith((".example", ".invalid", ".test", ".localhost")):
        return True
    return False


def is_valid_recipient_email(email: str) -> bool:
    address = email.strip()
    if not address or not _EMAIL_RE.fullmatch(address):
        return False
    return not is_placeholder_email(address)


def validate_recipient_email(email: str) -> tuple[bool, str]:
    address = email.strip()
    if not address:
        return False, "No recipient email address provided."
    if not _EMAIL_RE.fullmatch(address):
        return False, f"Invalid email address: {address}"
    if is_placeholder_email(address):
        return False, (
            f"Refusing to send to placeholder address {address}. "
            "Provide a real recipient email or contact name."
        )
    return True, ""


def resolve_email_recipient(
    *,
    task: str,
    user_message: str = "",
    llm_to: str = "",
    contact_hint: dict[str, str] | None = None,
    gmail_hint: dict[str, str] | None = None,
) -> str:
    from tempa.channels.contacts.sync import resolve_recipient

    candidates: list[str] = []

    for text in (user_message, task):
        candidates.extend(extract_all_recipients(text))

    if gmail_hint:
        email = str(gmail_hint.get("email", "")).strip()
        if email:
            candidates.append(email)

    for text in (user_message, task):
        if not text.strip():
            continue
        hit = resolve_recipient(text)
        email = str(hit.get("email", "")).strip()
        if email:
            candidates.append(email)

    if contact_hint:
        email = str(contact_hint.get("email", "")).strip()
        if email:
            candidates.append(email)

    llm_to = llm_to.strip()
    if llm_to:
        candidates.append(llm_to)

    seen: set[str] = set()
    for email in candidates:
        key = email.lower()
        if key in seen:
            continue
        seen.add(key)
        if is_valid_recipient_email(email):
            return email
    return ""


def wants_html_email(text: str) -> bool:
    lower = text.lower()
    return any(k in lower for k in ("html", "rich text", "formatted", "beautiful"))


def _strip_html_tags(text: str) -> str:
    return re.sub(r"<[^>]+>", " ", text).strip()


def is_beautiful_email_html(html_text: str) -> bool:
    return 'class="email-container"' in html_text


def finalize_beautiful_email(draft: dict[str, str]) -> dict[str, str]:
    """Ensure every outbound email uses the table-based HTML layout."""
    subject = str(draft.get("subject", "")).strip() or "Hello"
    body = _strip_html_tags(str(draft.get("body", "")).strip())
    body_html = str(draft.get("body_html", "")).strip()
    eyebrow = str(draft.get("eyebrow_label", "")).strip()
    closing = str(draft.get("closing_text", "")).strip()
    signature = str(draft.get("signature", "")).strip()

    if not is_beautiful_email_html(body_html):
        body_html = build_html_email(
            headline=subject,
            body_plain=body or "Hello.",
            preview_text=(body or subject)[:90],
            eyebrow_label=eyebrow or "MESSAGE",
            closing_text=closing,
            signature=signature,
        )

    plain_parts = [part for part in (body, closing, signature) if part]
    plain_body = "\n\n".join(plain_parts) if plain_parts else body or "Please view this email in HTML mode for the full message."

    return {
        **draft,
        "subject": subject,
        "body": plain_body,
        "body_html": body_html,
    }


def _plain_to_paragraphs(text: str) -> str:
    lines = [line.strip() for line in text.split("\n") if line.strip()]
    if not lines:
        return (
            '<p style="margin:0;font-family:Arial,Helvetica,sans-serif;'
            'font-size:16px;line-height:1.6;color:#3D4451;">Hello.</p>'
        )
    return "".join(
        f'<p style="margin:0 0 16px;font-family:Arial,Helvetica,sans-serif;'
        f'font-size:16px;line-height:1.6;color:#3D4451;">{html.escape(line)}</p>'
        for line in lines
    )


def _detail_rows_html(labels: Sequence[str], values: Sequence[str]) -> str:
    pairs = [
        (labels[i].strip(), values[i].strip())
        for i in range(min(len(labels), len(values)))
        if labels[i].strip() and values[i].strip()
    ]
    if not pairs:
        return ""

    rows: list[str] = []
    for index, (label, value) in enumerate(pairs):
        if index:
            rows.append(
                '<tr><td colspan="2" style="border-top:1px solid #E4E7EC;'
                'line-height:1px;font-size:1px;">&nbsp;</td></tr>'
            )
        rows.append(
            f'<tr>'
            f'<td style="font-family:Arial,Helvetica,sans-serif;font-size:13px;'
            f'color:#5B6470;{"padding-bottom:10px;" if index == 0 else "padding-top:10px;padding-bottom:10px;"}">'
            f"{html.escape(label)}</td>"
            f'<td align="right" style="font-family:Arial,Helvetica,sans-serif;font-size:13px;'
            f'color:#12161C;font-weight:bold;{"padding-bottom:10px;" if index == 0 else "padding-top:10px;padding-bottom:10px;"}">'
            f"{html.escape(value)}</td>"
            f"</tr>"
        )
    return f"""
                  <tr>
                    <td class="mobile-padding" style="padding:28px 48px 0;">
                      <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background-color:#F7F8FA;border-radius:8px;">
                        <tr>
                          <td style="padding:20px 24px;">
                            <table role="presentation" width="100%" cellpadding="0" cellspacing="0">
                              {"".join(rows)}
                            </table>
                          </td>
                        </tr>
                      </table>
                    </td>
                  </tr>"""


def build_html_email(
    *,
    headline: str,
    body_html: str = "",
    body_plain: str = "",
    preview_text: str = "",
    eyebrow_label: str = "",
    detail_labels: Sequence[str] = (),
    detail_values: Sequence[str] = (),
    cta_url: str = "",
    cta_label: str = "",
    closing_text: str = "",
    signature: str = "",
    company_name: str = "",
    company_address: str = "",
    view_in_browser_url: str = "",
    logo_url: str = "",
    unsubscribe_url: str = "",
    preferences_url: str = "",
) -> str:
    safe_headline = html.escape(headline or "Hello")
    safe_preview = html.escape(preview_text or headline or "")
    body_content = body_html.strip() or _plain_to_paragraphs(body_plain)

    view_in_browser_row = ""
    if view_in_browser_url.strip():
        safe_url = html.escape(view_in_browser_url.strip(), quote=True)
        view_in_browser_row = f"""
            <tr>
              <td align="center" style="padding:24px 24px 0;">
                <p style="margin:0;font-family:Arial,Helvetica,sans-serif;font-size:12px;color:#9AA1AC;">
                  <a href="{safe_url}" class="footer-link" style="color:#9AA1AC;text-decoration:underline;">View in browser</a>
                </p>
              </td>
            </tr>"""

    header_row = ""
    if logo_url.strip() or company_name.strip():
        logo_html = ""
        if logo_url.strip():
            safe_logo = html.escape(logo_url.strip(), quote=True)
            safe_name = html.escape(company_name.strip() or " ")
            logo_html = (
                f'<img src="{safe_logo}" width="40" height="40" alt="{safe_name}" '
                f'style="display:block;margin:0 auto 10px;border-radius:8px;">'
            )
        name_html = ""
        if company_name.strip():
            name_html = (
                f'<span style="font-family:Arial,Helvetica,sans-serif;font-size:14px;'
                f'font-weight:bold;letter-spacing:0.3px;color:#5B6470;">'
                f"{html.escape(company_name.strip())}</span>"
            )
        header_row = f"""
            <tr>
              <td align="center" style="padding:20px 0 28px;">
                {logo_html}
                {name_html}
              </td>
            </tr>"""

    eyebrow_row = ""
    if eyebrow_label.strip():
        eyebrow_row = f"""
                  <tr>
                    <td class="mobile-padding" style="padding:40px 48px 0;">
                      <span style="display:inline-block;background-color:#F0F1F3;color:#5B6470;font-family:Arial,Helvetica,sans-serif;font-size:11px;font-weight:bold;letter-spacing:1px;text-transform:uppercase;padding:5px 10px;border-radius:4px;">
                        {html.escape(eyebrow_label.strip())}
                      </span>
                    </td>
                  </tr>"""

    details_html = _detail_rows_html(detail_labels, detail_values)

    cta_row = ""
    if cta_url.strip() and cta_label.strip():
        safe_cta_url = html.escape(cta_url.strip(), quote=True)
        safe_cta_label = html.escape(cta_label.strip())
        cta_row = f"""
                  <tr>
                    <td class="mobile-padding" align="center" style="padding:32px 48px 0;">
                      <table role="presentation" cellpadding="0" cellspacing="0" style="margin:0 auto;">
                        <tr>
                          <td style="border-radius:6px;background-color:#12161C;">
                            <a href="{safe_cta_url}" class="cta-button" target="_blank" style="display:inline-block;padding:14px 34px;font-family:Arial,Helvetica,sans-serif;font-size:15px;font-weight:bold;color:#FFFFFF;text-decoration:none;border-radius:6px;">
                              {safe_cta_label}
                            </a>
                          </td>
                        </tr>
                      </table>
                    </td>
                  </tr>"""

    closing_html = ""
    if closing_text.strip() or signature.strip():
        closing_parts: list[str] = []
        if closing_text.strip():
            closing_parts.append(
                f'<p style="margin:0 0 16px;font-family:Arial,Helvetica,sans-serif;'
                f'font-size:14px;line-height:1.6;color:#5B6470;">{html.escape(closing_text.strip())}</p>'
            )
        if signature.strip():
            closing_parts.append(
                f'<p style="margin:0;font-family:Arial,Helvetica,sans-serif;font-size:14px;'
                f'color:#12161C;">{html.escape(signature.strip())}</p>'
            )
        closing_html = f"""
                  <tr>
                    <td class="mobile-padding" style="padding:32px 48px 40px;">
                      {"".join(closing_parts)}
                    </td>
                  </tr>"""

    footer_lines: list[str] = []
    if company_name.strip() or company_address.strip():
        parts = [html.escape(part.strip()) for part in (company_name, company_address) if part.strip()]
        footer_lines.append(
            f'<p style="margin:0 0 10px;font-family:Arial,Helvetica,sans-serif;'
            f'font-size:12px;line-height:1.6;color:#9AA1AC;">{" &middot; ".join(parts)}</p>'
        )

    footer_links: list[str] = []
    if unsubscribe_url.strip():
        safe_unsub = html.escape(unsubscribe_url.strip(), quote=True)
        footer_links.append(
            f'<a href="{safe_unsub}" class="footer-link" style="color:#9AA1AC;text-decoration:underline;">Unsubscribe</a>'
        )
    if preferences_url.strip():
        safe_prefs = html.escape(preferences_url.strip(), quote=True)
        footer_links.append(
            f'<a href="{safe_prefs}" class="footer-link" style="color:#9AA1AC;text-decoration:underline;">Email preferences</a>'
        )
    if footer_links:
        footer_lines.append(
            f'<p style="margin:0;font-family:Arial,Helvetica,sans-serif;font-size:12px;color:#9AA1AC;">'
            f'{" &nbsp;&middot;&nbsp; ".join(footer_links)}</p>'
        )

    footer_row = ""
    if footer_lines:
        footer_row = f"""
            <tr>
              <td align="center" style="padding:32px 24px 40px;">
                {"".join(footer_lines)}
              </td>
            </tr>"""

    top_padding = "40px 48px 0" if not eyebrow_label.strip() else "16px 48px 0"

    return f"""<!DOCTYPE html>
<html lang="en" xmlns="http://www.w3.org/1999/xhtml" xmlns:v="urn:schemas-microsoft-com:vml" xmlns:o="urn:schemas-microsoft-com:office:office">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<meta http-equiv="X-UA-Compatible" content="IE=edge">
<meta name="color-scheme" content="light">
<meta name="supported-color-schemes" content="light">
<title>{safe_headline}</title>
<!--[if mso]>
<noscript>
<xml>
<o:OfficeDocumentSettings>
<o:PixelsPerInch>96</o:PixelsPerInch>
</o:OfficeDocumentSettings>
</xml>
</noscript>
<![endif]-->
<style>
  body, table, td, a {{ -webkit-text-size-adjust: 100%; -ms-text-size-adjust: 100%; }}
  table, td {{ mso-table-lspace: 0pt; mso-table-rspace: 0pt; }}
  img {{ -ms-interpolation-mode: bicubic; border: 0; height: auto; line-height: 100%; outline: none; text-decoration: none; }}
  body {{ margin: 0; padding: 0; width: 100% !important; height: 100% !important; }}
  table {{ border-collapse: collapse !important; }}
  a.cta-button:hover {{ background-color: #2B3038 !important; }}
  a.footer-link:hover {{ color: #5B6470 !important; }}
  @media screen and (max-width: 600px) {{
    .email-container {{ width: 100% !important; }}
    .mobile-padding {{ padding-left: 28px !important; padding-right: 28px !important; }}
    h1.headline {{ font-size: 22px !important; }}
  }}
</style>
</head>
<body style="margin:0;padding:0;background-color:#EDF0F4;">
  <div style="display:none;font-size:1px;line-height:1px;max-height:0;max-width:0;opacity:0;overflow:hidden;mso-hide:all;font-family:Arial,Helvetica,sans-serif;">
    {safe_preview}
  </div>
  <center style="width:100%;background-color:#EDF0F4;">
    <table role="presentation" cellpadding="0" cellspacing="0" width="100%" style="background-color:#EDF0F4;">
      <tr>
        <td align="center" style="padding:0;">
          <!--[if mso]>
          <table role="presentation" align="center" cellpadding="0" cellspacing="0" width="600"><tr><td>
          <![endif]-->
          <table role="presentation" align="center" cellpadding="0" cellspacing="0" width="100%" class="email-container" style="max-width:600px;margin:0 auto;">
{view_in_browser_row}
{header_row}
            <tr>
              <td>
                <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background-color:#FFFFFF;border-radius:12px;">
{eyebrow_row}
                  <tr>
                    <td class="mobile-padding" style="padding:{top_padding};">
                      <h1 class="headline" style="margin:0;font-family:Arial,Helvetica,sans-serif;font-size:26px;line-height:1.3;font-weight:bold;color:#12161C;">
                        {safe_headline}
                      </h1>
                    </td>
                  </tr>
                  <tr>
                    <td class="mobile-padding" style="padding:16px 48px 0;">
                      {body_content}
                    </td>
                  </tr>
{details_html}
{cta_row}
{closing_html}
                </table>
              </td>
            </tr>
{footer_row}
          </table>
          <!--[if mso]>
          </td></tr></table>
          <![endif]-->
        </td>
      </tr>
    </table>
  </center>
</body>
</html>"""


def _default_html_template(*, subject: str, body_plain: str, recipient: str) -> str:
    del recipient  # reserved for future personalization
    return finalize_beautiful_email(
        {
            "subject": subject or "Hello",
            "body": body_plain or "Hello.",
        }
    )["body_html"]
