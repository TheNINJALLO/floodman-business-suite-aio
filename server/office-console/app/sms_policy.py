"""Shared public SMS disclosures. No enrollment or sending side effects."""
from html import escape

CUSTOMER_VERSION = "2026-09-11-customer-v1"
CUSTOMER_DISCLOSURE = (
    "By checking this box, I agree to receive recurring service-related texts from Floodman "
    "about my appointments, job progress, estimates, invoices, and customer portal. "
    "Message frequency varies. Message and data rates may apply. Reply STOP to opt out "
    "or HELP for help. Consent is not a condition of purchase. See the SMS Terms and Privacy Policy."
)
STAFF_DISCLOSURE = (
    "By checking this box, I agree to receive recurring operational SMS alerts from Floodman Call Center "
    "about inbound customer calls, completed intakes, and emergency service requests. Message frequency "
    "varies. Message and data rates may apply. Reply STOP to opt out or HELP for help. Consent is not a "
    "condition of employment or purchase. See the SMS Terms and Privacy Policy."
)
POLICY_BASE = "https://aicall.oninetwork.com"
NON_SHARING = (
    "We do not share, sell, rent, or provide mobile phone numbers, mobile information, text messaging "
    "originator opt-in data, or messaging consent data to third parties or affiliates for marketing "
    "or promotional purposes. This restriction applies to every category of messaging data described here."
)


def links() -> str:
    return (f'<a href="{POLICY_BASE}/terms">SMS Terms</a> and '
            f'<a href="{POLICY_BASE}/privacy">Privacy Policy</a>')


def render_policy(kind: str) -> str:
    if kind == "privacy":
        title = "SMS privacy policy"
        sections = [
            ("Who this covers", "This policy covers Floodman customer service texts and the separately enrolled Floodman Call Center staff-alert program."),
            ("Information we collect", "We collect mobile numbers, customer or staff account references, notification choices, consent and withdrawal timestamps, disclosure text and version, enrollment source, and messaging and delivery records. Customer service messages may relate to appointments, job progress, estimates, invoices, and customer portal access."),
            ("How we use this information", "We use this information to deliver requested service communications and staff alerts, respond to requests, protect the system, honor opt-outs, and document consent. We do not use this enrollment for advertising or promotional messages."),
            ("Mobile information and consent", NON_SHARING + " We may provide limited information to providers that deliver or support these messages, such as our messaging carrier, only for that purpose, or when legally required."),
            ("Frequency and charges", "Message frequency varies with service activity, customer requests, call volume, and staff notification choices. Message and data rates may apply."),
            ("Your choices", "Participation is optional and is not a condition of purchase or employment. Reply STOP to opt out. Customers may also turn off texts in their secure estimate or invoice portal; staff may disable SMS in their profile. Turning off texts does not prevent access to services, documents, or payments."),
            ("Retention and contact", "We retain messaging and consent records as needed to operate the program, honor opt-outs, resolve disputes, and meet legal obligations. For privacy requests or support, email it@floodman.com."),
        ]
    elif kind == "terms":
        title = "SMS terms and conditions"
        sections = [
            ("Customer service texts", "Customers who opt in may receive recurring Floodman texts about requested services, appointments, job progress, estimates, invoices, and their customer portal. This program does not include advertising."),
            ("Staff alerts", "Separately enrolled Floodman team members may receive Floodman Call Center alerts about inbound calls, completed intakes, and urgent service requests. Staff alerts link to an authenticated workspace."),
            ("Frequency, charges, and delivery", "Message frequency varies with service and call activity. Message and data rates may apply. Delivery is not guaranteed. Wireless carriers are not liable for delayed or undelivered messages. Do not rely on text messages for emergency assistance."),
            ("Opt out and help", "Reply STOP to opt out or HELP for assistance. For support, email it@floodman.com. One confirmation may follow an opt-out. You can also disable customer texts in your secure portal or staff alerts in your profile. Replying START to remove a carrier block does not enroll a new customer or staff account; use the applicable enrollment control."),
            ("Optional participation", "Consent is not a condition of purchase or employment. Viewing a document, paying an invoice, making a phone call, or having a customer account does not automatically enroll you. Customer service consent is separate from staff-alert consent."),
            ("Privacy", "The SMS Privacy Policy explains how mobile information and messaging consent are used. Mobile information and consent are not shared with third parties or affiliates for marketing or promotional purposes."),
        ]
    elif kind == "program":
        title = "Floodman SMS programs"
        sections = [
            ("Customer enrollment", "Open the private estimate or invoice portal link provided by Floodman, find Optional text updates, enter your own US mobile number, and check the initially unchecked consent box before selecting Enable text updates. No staff login is required to use your private customer link. Enrollment is separate from document approval and payment. You may leave the box unchecked and continue using services. To obtain your document link, contact the Floodman team at office@floodman.com."),
            ("Customer disclosure", CUSTOMER_DISCLOSURE),
            ("Staff enrollment", "Sign in at https://aicall.oninetwork.com/profile, enter your own mobile number, and check the initially unchecked SMS consent box. Administrators cannot enroll another team member. Customers do not enroll through the staff profile."),
            ("Staff disclosure", STAFF_DISCLOSURE),
            ("Consent records", "We record the recipient, customer or staff reference, time, source, exact disclosure and version, and opt-in or opt-out choice. Existing contacts are not automatically enrolled. A changed number requires a new explicit choice."),
            ("Cancellation, cost, and support", "Message frequency varies. Message and data rates may apply. Reply STOP to opt out or HELP for help. Customers can also disable texts in their secure portal; staff can disable them in their profile. Contact it@floodman.com for support. Consent is not a condition of purchase or employment."),
        ]
    else:
        raise ValueError("Unknown SMS policy page")
    content = "".join(f"<section><h2>{escape(h)}</h2><p>{escape(p)}</p></section>" for h, p in sections)
    preview = ""
    if kind == "program":
        preview = f'''<section aria-label="Customer enrollment preview"><h2>Customer checkbox preview</h2>
<p>This is a public, non-submitting preview for review. Enroll only from your private customer portal link.</p>
<label for="preview-mobile">Your US mobile number</label><input id="preview-mobile" type="tel" placeholder="(231) 555-0100" disabled>
<label class="consent"><input type="checkbox" disabled><span>{escape(CUSTOMER_DISCLOSURE)} {links()}</span></label>
<button disabled>Enable text updates (preview only)</button></section>'''
    return f'''<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{escape(title)} | Floodman</title><style>body{{margin:0;background:#eef3f7;color:#233a4b;font:17px/1.6 system-ui,sans-serif}}main{{max-width:820px;margin:32px auto;padding:28px;background:white;border:1px solid #d5e0e8;border-radius:16px}}h1{{font-size:30px;color:#123a5a}}h2{{font-size:21px;margin-top:28px}}a{{color:#086a95;overflow-wrap:anywhere}}nav{{display:flex;gap:20px;flex-wrap:wrap}}.consent{{display:flex;align-items:flex-start;gap:12px;margin:18px 0}}.consent input{{width:22px;height:22px;flex:0 0 22px}}input,button{{font:inherit;max-width:100%;padding:10px;box-sizing:border-box}}footer{{margin-top:30px;font-size:14px}}@media(max-width:700px){{main{{margin:0;padding:22px 16px;border-radius:0}}}}</style></head><body><main>
<strong>FLOODMAN</strong><h1>{escape(title)}</h1>{content}{preview}
<p>{links()}</p><footer>Effective September 11, 2026. Floodman, LLC.</footer>
<nav aria-label="SMS policies"><a href="{POLICY_BASE}/sms-program">SMS programs</a><a href="{POLICY_BASE}/privacy">Privacy</a><a href="{POLICY_BASE}/terms">Terms</a><a href="{POLICY_BASE}/login">Staff sign in</a></nav>
</main></body></html>'''
