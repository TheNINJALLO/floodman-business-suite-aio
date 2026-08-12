from __future__ import annotations

import html
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class RenderedMessage:
    subject: str
    text: str
    html: str | None = None


def money(cents: int, currency: str = "USD") -> str:
    prefix = "$" if currency == "USD" else f"{currency} "
    return f"{prefix}{cents / 100:,.2f}"


def invoice_sent_sms(*, invoice_number: str, balance_cents: int, portal_url: str) -> str:
    return (
        f"Floodman: Invoice {invoice_number} is ready and due upon receipt. "
        f"Balance: {money(balance_cents)}. View or pay securely: {portal_url} "
        "Reply HELP for help or STOP to stop texts."
    )


def invoice_sent_email(
    *, customer_name: str, invoice_number: str, balance_cents: int, portal_url: str, payment_url: str | None
) -> RenderedMessage:
    payment_line = f"\nSquare payment link: {payment_url}" if payment_url else ""
    text = (
        f"Hello {customer_name},\n\n"
        f"Your Floodman invoice {invoice_number} is ready. The balance of {money(balance_cents)} "
        "is due upon receipt.\n\n"
        f"Customer portal: {portal_url}{payment_line}\n\n"
        "The portal contains your current balance, signed documents, and secure payment links. "
        "If you have a question about the work or invoice, reply to this email or contact Floodman.\n\n"
        "Thank you,\nFloodman"
    )
    buttons = [
        f"<a href='{html.escape(portal_url)}' style='display:inline-block;padding:12px 18px;background:#123a5a;color:#fff;text-decoration:none;border-radius:6px'>Open customer portal</a>"
    ]
    if payment_url:
        buttons.append(
            f"<a href='{html.escape(payment_url)}' style='display:inline-block;margin-left:8px;padding:12px 18px;background:#166534;color:#fff;text-decoration:none;border-radius:6px'>Pay with Square</a>"
        )
    body = f"""<!doctype html><html><body style="font-family:Arial,sans-serif;color:#172033">
<p>Hello {html.escape(customer_name)},</p>
<p>Your Floodman invoice <strong>{html.escape(invoice_number)}</strong> is ready. The balance of
<strong>{html.escape(money(balance_cents))}</strong> is <strong>due upon receipt</strong>.</p>
<p>{''.join(buttons)}</p>
<p>The portal contains your current balance, signed documents, and secure payment links.</p>
<p>If you have a question about the work or invoice, reply to this email or contact Floodman.</p>
<p>Thank you,<br>Floodman</p></body></html>"""
    return RenderedMessage(f"Floodman invoice {invoice_number} | Due upon receipt", text, body)


def past_due_sms(*, invoice_number: str, balance_cents: int, days_overdue: int, portal_url: str) -> str:
    age = "is past due" if days_overdue <= 1 else f"is {days_overdue} days past due"
    return (
        f"Floodman: Invoice {invoice_number} {age}. Remaining balance: {money(balance_cents)}. "
        f"View or pay securely: {portal_url} Reply with questions, HELP for help, or STOP to stop texts."
    )


def past_due_email(
    *, customer_name: str, invoice_number: str, balance_cents: int, days_overdue: int, portal_url: str
) -> RenderedMessage:
    age = "past due" if days_overdue <= 1 else f"{days_overdue} days past due"
    text = (
        f"Hello {customer_name},\n\n"
        f"This is a reminder that Floodman invoice {invoice_number} is {age}. "
        f"The verified remaining balance is {money(balance_cents)}.\n\n"
        f"View the invoice and pay securely: {portal_url}\n\n"
        "If you believe you already paid or have a concern about the invoice or completed work, "
        "please reply so our office can review the account.\n\nFloodman"
    )
    body = f"""<!doctype html><html><body style="font-family:Arial,sans-serif;color:#172033">
<p>Hello {html.escape(customer_name)},</p>
<p>This is a reminder that Floodman invoice <strong>{html.escape(invoice_number)}</strong> is
<strong>{html.escape(age)}</strong>. The verified remaining balance is
<strong>{html.escape(money(balance_cents))}</strong>.</p>
<p><a href="{html.escape(portal_url)}" style="display:inline-block;padding:12px 18px;background:#123a5a;color:#fff;text-decoration:none;border-radius:6px">View invoice and pay securely</a></p>
<p>If you believe you already paid or have a concern about the invoice or completed work, please reply so our office can review the account.</p>
<p>Floodman</p></body></html>"""
    return RenderedMessage(f"Past-due Floodman invoice {invoice_number}", text, body)


def payment_received_sms(*, invoice_number: str, paid_cents: int, remaining_cents: int, portal_url: str) -> str:
    if remaining_cents <= 0:
        return (
            f"Floodman: Thank you. Payment of {money(paid_cents)} was recorded for invoice {invoice_number}. "
            f"The invoice is paid in full. Records: {portal_url}"
        )
    return (
        f"Floodman: Payment of {money(paid_cents)} was recorded for invoice {invoice_number}. "
        f"Remaining balance: {money(remaining_cents)}. Records and payment link: {portal_url}"
    )


def safe_acknowledgement() -> str:
    return (
        "Thank you for letting us know. Automated payment reminders have been paused and your message "
        "has been sent to a Floodman team member for review."
    )


def help_sms() -> str:
    return (
        "Floodman account messaging: reply with a question about your invoice, balance, receipt, or payment link. "
        "Reply CALL for a staff callback. Reply STOP to stop texts."
    )


def staff_alert_message(*, title: str, body: str, job_id: str, invoice_number: str | None = None) -> RenderedMessage:
    suffix = f" | Invoice {invoice_number}" if invoice_number else ""
    text = f"{title}\n\n{body}\n\nFloodman job ID: {job_id}{suffix}"
    html_body = (
        "<!doctype html><html><body style='font-family:Arial,sans-serif;color:#172033'>"
        f"<h2>{html.escape(title)}</h2><p>{html.escape(body)}</p>"
        f"<p><strong>Job ID:</strong> {html.escape(job_id)}{html.escape(suffix)}</p>"
        "</body></html>"
    )
    return RenderedMessage(f"Floodman alert: {title}", text, html_body)
