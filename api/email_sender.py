"""Send emails via SMTP: welcome (on user creation) and jump test result link."""
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Optional, Tuple

from api.config import EMAIL_BASE_URL, SMTP_FROM, SMTP_HOST, SMTP_PASSWORD, SMTP_PORT, SMTP_USER


def _base_url() -> str:
    return (EMAIL_BASE_URL or "").strip().rstrip("/") or "http://localhost:8000"


def _send_email(to_email: str, subject: str, text: str, html: Optional[str] = None) -> Tuple[bool, Optional[str]]:
    """Send an email. If html is provided, sends multipart (plain + html)."""
    if not SMTP_HOST:
        return False, "SMTP not configured"
    if not to_email:
        return False, "No recipient email"
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = SMTP_FROM or SMTP_USER or "noreply@jumptest"
    msg["To"] = to_email
    msg.attach(MIMEText(text, "plain"))
    if html:
        msg.attach(MIMEText(html, "html"))
    try:
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=10) as server:
            if SMTP_USER and SMTP_PASSWORD:
                server.starttls()
                server.login(SMTP_USER, SMTP_PASSWORD)
            server.sendmail(msg["From"], [to_email], msg.as_string())
        return True, None
    except smtplib.SMTPAuthenticationError as e:
        return False, "SMTP authentication failed. For Gmail use an App Password: " + str(e)
    except smtplib.SMTPException as e:
        return False, "SMTP error: " + str(e)
    except OSError as e:
        return False, "Connection failed (check SMTP_HOST and SMTP_PORT): " + str(e)
    except Exception as e:
        return False, str(e)


def _html_escape(s: str) -> str:
    return (s or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


def _href_escape(url: str) -> str:
    """Escape URL for safe use in href (e.g. & -> &amp;) so links work in all email clients."""
    return (url or "").replace("&", "&amp;")


def send_welcome_email(to_email: str, user_id: str, name: Optional[str] = None) -> Tuple[bool, Optional[str]]:
    """
    Send a welcome email when a user is created, with a link to their jump tests page.
    Returns (True, None) on success, (False, error_message) otherwise.
    """
    if not SMTP_HOST:
        return False, "SMTP not configured"
    base = _base_url()
    my_tests_url = base + "/my-tests?user_id=" + user_id
    my_tests_href = _href_escape(my_tests_url)
    display_name = _html_escape((name or "").strip()) or "there"
    subject = "Thank you for your participation – Your Jump Test Dashboard"

    text = f"""Thank you for your participation!

You can view and follow your jump test results anytime using the link below:

{my_tests_url}

We hope this helps you track your progress."""

    # Use table-based button and escaped href so links are clickable in Gmail, Outlook, etc.
    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Thank you for your participation</title>
</head>
<body style="margin:0; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif; background-color: #f4f4f5; padding: 24px;">
  <div style="max-width: 520px; margin: 0 auto; background: #ffffff; border-radius: 12px; box-shadow: 0 1px 3px rgba(0,0,0,0.08); overflow: hidden;">
    <div style="background: #4f46e5; padding: 32px 24px; text-align: center;">
      <h1 style="margin: 0; color: #ffffff; font-size: 1.5rem; font-weight: 600;">Thank you for your participation</h1>
    </div>
    <div style="padding: 28px 24px;">
      <p style="margin: 0 0 16px 0; color: #374151; font-size: 16px; line-height: 1.6;">Hi {display_name},</p>
      <p style="margin: 0 0 24px 0; color: #374151; font-size: 16px; line-height: 1.6;">Thank you for taking part. You can access your jump test results and follow your progress anytime using the link below.</p>
      <p style="margin: 0 0 24px 0; text-align: center;">
        <table role="presentation" cellspacing="0" cellpadding="0" border="0" align="center" style="margin: 0 auto;">
          <tr>
            <td style="border-radius: 8px; background-color: #4f46e5;">
              <a href="{my_tests_href}" target="_blank" rel="noopener" style="display: inline-block; padding: 14px 28px; color: #ffffff; text-decoration: none; font-weight: 600; font-size: 16px;">View my jump tests</a>
            </td>
          </tr>
        </table>
      </p>
      <p style="margin: 0; color: #6b7280; font-size: 14px; line-height: 1.5;">If the button does not work, use this link:</p>
      <p style="margin: 8px 0 0 0; word-break: break-all;"><a href="{my_tests_href}" target="_blank" rel="noopener" style="color: #4f46e5; text-decoration: underline;">{_html_escape(my_tests_url)}</a></p>
    </div>
    <div style="padding: 16px 24px; background: #f9fafb; border-top: 1px solid #e5e7eb;">
      <p style="margin: 0; color: #9ca3af; font-size: 12px;">This link is unique to you. Keep it to access your results in the future.</p>
    </div>
  </div>
</body>
</html>"""

    return _send_email(to_email, subject, text, html)


def send_jump_test_link(
    to_email: str,
    test_id: str,
    subject: Optional[str] = None,
    body: Optional[str] = None,
    user_id: Optional[str] = None,
) -> Tuple[bool, Optional[str]]:
    """
    Send an email with a link to view the jump test.
    If user_id is provided, includes a secondary link to the user's test dashboard.
    Returns (True, None) on success, (False, error_message) on failure or if not configured.
    """
    if not SMTP_HOST:
        return False, "SMTP not configured. Set SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASSWORD (and optionally SMTP_FROM, EMAIL_BASE_URL) in .env"
    if not to_email:
        return False, "No recipient email"
    base = _base_url()
    viewer_url = base + "/viewer?test_id=" + test_id
    viewer_href = _href_escape(viewer_url)
    subj = subject or "Your jump test result"

    # Build dashboard link if user_id is available
    dashboard_text = ""
    dashboard_html = ""
    if user_id:
        my_tests_url = base + "/my-tests?user_id=" + user_id
        my_tests_href = _href_escape(my_tests_url)
        dashboard_text = "\n\nView all your tests:\n" + my_tests_url + "\n"
        dashboard_html = f"""
      <p style="margin:16px 0 0 0; text-align:center;">
        <table role="presentation" cellspacing="0" cellpadding="0" border="0" align="center" style="margin:0 auto;">
          <tr>
            <td style="border-radius:8px; border:2px solid #4f46e5;">
              <a href="{my_tests_href}" target="_blank" rel="noopener" style="display:inline-block; padding:10px 24px; color:#4f46e5; text-decoration:none; font-weight:600; font-size:15px;">View all my tests</a>
            </td>
          </tr>
        </table>
      </p>"""

    text = body or ("View your jump test result here:\n\n" + viewer_url + dashboard_text)
    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Your jump test result</title>
</head>
<body style="margin:0; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif; background-color: #f4f4f5; padding: 24px;">
  <div style="max-width: 520px; margin: 0 auto; background: #ffffff; border-radius: 12px; box-shadow: 0 1px 3px rgba(0,0,0,0.08); overflow: hidden;">
    <div style="background: #4f46e5; padding: 32px 24px; text-align: center;">
      <h1 style="margin: 0; color: #ffffff; font-size: 1.5rem; font-weight: 600;">Your jump test result</h1>
    </div>
    <div style="padding: 28px 24px;">
      <p style="margin: 0 0 24px 0; color: #374151; font-size: 16px; line-height: 1.6;">Your jump test has been analyzed. View your detailed results and performance metrics using the button below.</p>
      <p style="margin: 0 0 8px 0; text-align: center;">
        <table role="presentation" cellspacing="0" cellpadding="0" border="0" align="center" style="margin: 0 auto;">
          <tr>
            <td style="border-radius: 8px; background-color: #4f46e5;">
              <a href="{viewer_href}" target="_blank" rel="noopener" style="display: inline-block; padding: 14px 28px; color: #ffffff; text-decoration: none; font-weight: 600; font-size: 16px;">View result</a>
            </td>
          </tr>
        </table>
      </p>{dashboard_html}
    </div>
    <div style="padding: 16px 24px; background: #f9fafb; border-top: 1px solid #e5e7eb;">
      <p style="margin: 0 0 6px 0; color: #9ca3af; font-size: 12px;">If the button above does not work, copy and paste this link into your browser:</p>
      <p style="margin: 0; word-break: break-all;"><a href="{viewer_href}" target="_blank" rel="noopener" style="color: #4f46e5; font-size: 12px; text-decoration: underline;">{_html_escape(viewer_url)}</a></p>
    </div>
  </div>
</body>
</html>"""
    return _send_email(to_email, subj, text, html)


def send_results_ready_email(
    to_email: str,
    user_id: str,
    has_bad_data: bool = False,
    bad_data_message: Optional[str] = None,
    name: Optional[str] = None,
    last_name: Optional[str] = None,
) -> Tuple[bool, Optional[str]]:
    """
    Send an email when CMJ results are ready: formal, bilingual (English then Turkish).
    If has_bad_data is True, includes a line about quality issues in both languages.
    Returns (True, None) on success, (False, error_message) otherwise.
    """
    if not SMTP_HOST:
        return False, "SMTP not configured"
    if not to_email:
        return False, "No recipient email"
    base = _base_url()
    my_tests_url = base + "/my-tests?user_id=" + user_id
    my_tests_href = _href_escape(my_tests_url)

    display_name_en = "Participant"
    if name or last_name:
        display_name_en = " ".join(x for x in ((name or "").strip(), (last_name or "").strip()) if x)
    display_name_en = _html_escape(display_name_en) or "Participant"
    display_name_tr = display_name_en  # same for Turkish greeting

    bad_line_en = ""
    bad_line_tr = ""
    if has_bad_data:
        bad_line_en = (
            bad_data_message
            or "Some of your tests had quality issues; details are visible in your dashboard."
        ).strip()
        bad_line_tr = "Bazı testlerinizde kalite sorunları tespit edilmiştir; ayrıntılar panonuzda görüntülenebilir."

    subject = "Your CMJ test results are ready / CMJ test sonuçlarınız hazır"

    # Plain text: English then Turkish
    text = f"""Dear {display_name_en},

We are pleased to inform you that your Counter-Movement Jump (CMJ) test results have been processed and are now ready for your review.
"""
    if bad_line_en:
        text += f"\n{bad_line_en}\n\n"
    text += """Thank you for participating in our tests. You may view your results and performance metrics using the link below.
On your results page, each test may show a tag: Correct = validated result; Bad data = recording issue; Wrong detection = analysis issue; Invalid / No jump = no jump detected (e.g. trial mistake).

"""
    text += f"""{my_tests_url}

---
Türkçe
---

Sayın {display_name_tr},

Sıçrama (CMJ) test sonuçlarınızın işlendiğini ve incelemeniz için hazır olduğunu bildirmekten memnuniyet duyarız.
"""
    if bad_line_tr:
        text += f"\n{bad_line_tr}\n\n"
    text += """Testlere katıldığınız için teşekkür ederiz. Sonuçlarınızı aşağıdaki bağlantıyı kullanarak görüntüleyebilirsiniz.
Sonuç sayfanızda her test için bir etiket: Doğru = onaylanmış sonuç; Kötü veri = kayıt sorunu; Yanlış tespit = analiz sorunu; Geçersiz / Sıçrama yok = sıçrama tespit edilmedi.

"""
    text += f"""{my_tests_url}
"""

    bad_html_en = ""
    bad_html_tr = ""
    if bad_line_en:
        bad_html_en = f'<p style="margin:12px 0 0 0; color:#b45309; font-size:15px;">{_html_escape(bad_line_en)}</p>'
    if bad_line_tr:
        bad_html_tr = f'<p style="margin:8px 0 0 0; color:#b45309; font-size:14px;">{_html_escape(bad_line_tr)}</p>'

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Your CMJ test results are ready</title>
</head>
<body style="margin:0; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif; background-color: #f4f4f5; padding: 24px;">
  <div style="max-width: 560px; margin: 0 auto; background: #ffffff; border-radius: 12px; box-shadow: 0 1px 3px rgba(0,0,0,0.08); overflow: hidden;">
    <div style="background: #4f46e5; padding: 32px 24px; text-align: center;">
      <h1 style="margin: 0; color: #ffffff; font-size: 1.35rem; font-weight: 600;">Your CMJ test results are ready</h1>
      <p style="margin: 8px 0 0 0; color: rgba(255,255,255,0.9); font-size: 0.95rem;">CMJ test sonuçlarınız hazır</p>
    </div>
    <div style="padding: 28px 24px;">
      <p style="margin: 0 0 8px 0; color: #374151; font-size: 16px; line-height: 1.6;"><strong>English</strong></p>
      <p style="margin: 0 0 12px 0; color: #374151; font-size: 16px; line-height: 1.6;">Dear {display_name_en},</p>
      <p style="margin: 0 0 12px 0; color: #374151; font-size: 16px; line-height: 1.6;">We are pleased to inform you that your Counter-Movement Jump (CMJ) test results have been processed and are now ready for your review.</p>
      {bad_html_en}
      <p style="margin: 16px 0 0 0; color: #374151; font-size: 16px; line-height: 1.6;">Thank you for participating in our tests. You may view your results and performance metrics using the button below.</p>
      <p style="margin: 16px 0 0 0; color: #6b7280; font-size: 14px; line-height: 1.5;">On your results page, each test may show a tag: <strong>Correct</strong> = validated result; <strong>Bad data</strong> = recording issue; <strong>Wrong detection</strong> = analysis issue; <strong>Invalid / No jump</strong> = no jump detected (e.g. trial mistake).</p>
      <p style="margin: 20px 0 8px 0; text-align: center;">
        <table role="presentation" cellspacing="0" cellpadding="0" border="0" align="center" style="margin: 0 auto;">
          <tr>
            <td style="border-radius: 8px; background-color: #4f46e5;">
              <a href="{my_tests_href}" target="_blank" rel="noopener" style="display: inline-block; padding: 14px 28px; color: #ffffff; text-decoration: none; font-weight: 600; font-size: 16px;">View my results</a>
            </td>
          </tr>
        </table>
      </p>
      <p style="margin: 28px 0 8px 0; padding-top: 20px; border-top: 1px solid #e5e7eb; color: #6b7280; font-size: 14px;"><strong>Türkçe</strong></p>
      <p style="margin: 0 0 12px 0; color: #374151; font-size: 16px; line-height: 1.6;">Sayın {display_name_tr},</p>
      <p style="margin: 0 0 12px 0; color: #374151; font-size: 16px; line-height: 1.6;">Sıçrama (CMJ) test sonuçlarınızın işlendiğini ve incelemeniz için hazır olduğunu bildirmekten memnuniyet duyarız.</p>
      {bad_html_tr}
      <p style="margin: 16px 0 0 0; color: #374151; font-size: 16px; line-height: 1.6;">Testlere katıldığınız için teşekkür ederiz. Sonuçlarınızı aşağıdaki bağlantıyı kullanarak görüntüleyebilirsiniz.</p>
      <p style="margin: 16px 0 0 0; color: #6b7280; font-size: 14px; line-height: 1.5;">Sonuç sayfanızda her test için bir etiket görebilirsiniz: <strong>Doğru</strong> = onaylanmış sonuç; <strong>Kötü veri</strong> = kayıt sorunu; <strong>Yanlış tespit</strong> = analiz sorunu; <strong>Geçersiz / Sıçrama yok</strong> = sıçrama tespit edilmedi (örn. deneme hatası).</p>
      <p style="margin: 16px 0 0 0; text-align: center;">
        <table role="presentation" cellspacing="0" cellpadding="0" border="0" align="center" style="margin: 0 auto;">
          <tr>
            <td style="border-radius: 8px; background-color: #4f46e5;">
              <a href="{my_tests_href}" target="_blank" rel="noopener" style="display: inline-block; padding: 14px 28px; color: #ffffff; text-decoration: none; font-weight: 600; font-size: 16px;">Sonuçlarımı görüntüle</a>
            </td>
          </tr>
        </table>
      </p>
    </div>
    <div style="padding: 16px 24px; background: #f9fafb; border-top: 1px solid #e5e7eb;">
      <p style="margin: 0; color: #9ca3af; font-size: 12px;">If the button does not work, use this link: / Bağlantı çalışmazsa bu linki kullanın:</p>
      <p style="margin: 8px 0 0 0; word-break: break-all;"><a href="{my_tests_href}" target="_blank" rel="noopener" style="color: #4f46e5; font-size: 12px; text-decoration: underline;">{_html_escape(my_tests_url)}</a></p>
    </div>
  </div>
</body>
</html>"""
    return _send_email(to_email, subject, text, html)
