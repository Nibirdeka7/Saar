# NovaCore Technologies — Employee Handbook & Security Policy (v4.2)

## 1. Annual & Parental Leave Policy (Policy ID: HR-104)

Full-time employees accrue 24 days of Paid Time Off (PTO) per calendar year at a rate of 2.0 days per month.
Unused PTO up to a maximum of 8 days may be carried forward into Q1 of the following year; any balance above 8 days expires on March 31.
Primary caregivers are eligible for 16 weeks of fully paid parental leave, while secondary caregivers receive 4 weeks of paid leave. Contractors and interns are not eligible for paid parental leave under HR-104.

## 2. Expense Reimbursement & Travel Limits (Policy ID: FIN-209)

Home-office equipment stipends are capped at INR 18,500 per fiscal year and require manager approval via the expense portal within 30 days of purchase.
Domestic flight bookings must be economy class and booked at least 14 days in advance unless approved by a VP. Meal per-diem during domestic travel is INR 1,800 per day.

## 3. Information Security & Access Control (Policy ID: SEC-402)

All production AWS environments require hardware MFA (FIDO2/WebAuthn) and temporary IAM Identity Center sessions capped at 4 hours.
Storing static AWS_ACCESS_KEY_ID credentials in source code or unencrypted `.env` files on shared servers is a Severity-1 violation.
Laptops must enforce full-disk encryption (BitLocker or FileVault) and auto-lock after 5 minutes of inactivity.

## 4. Incident Escalation & Data Retention (Policy ID: SEC-419)

Suspected credential leaks or phishing incidents must be reported to `secops@novacore.internal` within 30 minutes of discovery.
Customer audit logs are retained in immutable S3 Object Lock storage for 7 years (2,555 days) in compliance with SOC 2 Type II controls.
