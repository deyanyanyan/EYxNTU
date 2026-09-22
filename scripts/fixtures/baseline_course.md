# Northwind Analytics — Information Security Essentials

Northwind Analytics is a fictional company. This handbook is a test fixture for the
course-generation baseline: its rules are specific and internally consistent so that
generated lessons can be checked against it line by line.

## 1 Purpose and scope

This handbook applies to every Northwind employee, contractor and intern, on any device
used for Northwind work. It sets out the minimum behaviour expected to protect client data
and company systems. Breaches of this handbook are handled under the disciplinary policy.

New starters must complete this course within their first 10 working days. Everyone
repeats it every 12 months. Team leads confirm completion in the quarterly access review.

## 2 Classifying information

Every document, dataset and message belongs to one of four classes. The author assigns the
class when the item is created, and anyone who shares it must respect that class.

| Class | Examples | Who may see it | Storage |
|---|---|---|---|
| Public | Published reports, marketing pages | Anyone | Any approved system |
| Internal | Org charts, internal wiki pages | All Northwind staff | Company drive |
| Confidential | Client contracts, pricing models | Named project team only | Encrypted project folder |
| Restricted | Client personal data, credentials | Individually approved people | Restricted vault only |

When in doubt, choose the higher class. Restricted information must never be sent by email,
even internally; share a vault link instead. Confidential information may be emailed only to
named project members and only with the subject line prefixed by "[CONFIDENTIAL]".

## 3 Passwords and multi-factor authentication

Passwords for Northwind accounts must be at least 14 characters long. Passphrases made of
four or more unrelated words are recommended because they are long and easy to remember.
Never reuse a Northwind password on any other site.

Store passwords only in the company password manager. Writing passwords on paper, in
spreadsheets or in chat messages is not permitted.

Multi-factor authentication (MFA) is mandatory for email, the company drive, the VPN and
every client system that supports it. Use the authenticator app on your company phone. SMS
codes are allowed only as a temporary fallback for up to 7 days while a phone is replaced.

If you receive an MFA prompt you did not trigger, deny it and report it immediately. Repeated
unexpected prompts are a common sign that someone already knows your password.

## 4 Recognising phishing

Phishing messages try to trick you into revealing credentials, paying money or opening
malicious files. Most attacks against Northwind arrive by email, but chat and phone calls
are increasingly used.

Warning signs include:

- Urgency or pressure, such as a deadline measured in minutes or a threat to close an account.
- A sender address that differs from the display name, or a lookalike domain such as
  "northwlnd.com".
- Requests to bypass normal process, for example paying an invoice without a purchase order.
- Unexpected attachments, especially archives, or links that ask you to sign in again.

Before acting on a request for money or data, verify it through a second channel you already
trust, such as calling the person on the number in the company directory. Never use contact
details supplied in the suspicious message itself.

## 5 Reporting security incidents

A security incident is any event that could compromise the confidentiality, integrity or
availability of Northwind or client information. Examples include a lost laptop, a phishing
link that was clicked, a misdirected email containing confidential data, or an unexpected MFA
prompt.

Report every suspected incident to the Security Desk within 1 hour of noticing it, using the
"Report a security incident" button in the service portal or by calling extension 4400 out of
hours. Reporting quickly matters more than being certain: an early false alarm costs minutes,
while a late report can cost the client relationship.

After reporting:

1. Do not delete the suspicious message or try to investigate it yourself.
2. Disconnect the affected device from the network if the Security Desk asks you to.
3. Record what happened and when, while it is fresh.

Northwind does not discipline staff for reporting their own honest mistakes promptly. Failing
to report a known incident is treated as a serious breach.

## 6 Working remotely and protecting devices

Company laptops use full-disk encryption and must be locked whenever you step away. Screens
lock automatically after 5 minutes of inactivity. Install operating system updates within
7 days of release; the laptop will force a restart after that.

When working outside the office, connect through the company VPN before accessing internal
systems. Public Wi-Fi is acceptable only with the VPN active. Do not use personal devices for
Confidential or Restricted information.

Lost or stolen devices must be reported as incidents under section 5. The Security Desk can
wipe a company laptop or phone remotely once it is reported.

## 7 Clear desk and screen

At the end of each day, lock away printed Confidential and Restricted documents and remove
anything from shared printers. Dispose of printed Confidential or Restricted material only in
the locked shredding bins. When presenting or sharing your screen, close unrelated windows and
turn off notifications so that client information is not shown to the wrong audience.
