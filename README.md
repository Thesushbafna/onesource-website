# One Source OS
## CRM, site operations and internal accounting for One Source

**Version:** 1.0 pilot | **Prepared:** 7 September 2026 | **Currency:** INR

A runnable application for the ceiling-material supply and installation workflow. It includes a Python server, a SQLite database created on first launch, a responsive browser interface, demonstration records and automated tests. No live One Source records have been imported. The OS monogram is a new interface mark, not a retrieved official company logo.

**Start with the fictional demo. Keep your existing accounting system as the statutory book of record. This release is not a production-certified or tax-filing product.**

## Start on Windows

1. Extract the whole ZIP into a folder, such as `C:\OneSource_OS`.
2. Install Python 3.10 or newer if it is not already installed. Use the official Python installer and enable its PATH option when available: https://www.python.org/downloads/windows/
3. Double-click `start_windows.bat`. Keep the terminal open. The application opens in your browser at `http://127.0.0.1:8765`.
4. Sign in as **admin**, using the randomly generated password printed in that terminal. Save it securely. There is no shared default password.

Your demonstration records are saved in `data/onesource-demo.sqlite3` and persist between launches. To stop, press Ctrl+C in the terminal. Opening `PREVIEW.html` instead is a **read-only demonstration**; it does not save anything.

### Mac or Linux

Install Python 3.10 or newer, open a terminal in the extracted folder and run:

```sh
sh start_mac_linux.sh
```

### Any supported system: command line

```sh
python app.py --demo --db data/onesource-demo.sqlite3 --open
```

Use `python3` instead of `python` where appropriate. The application has **no third-party runtime package dependencies**. The browser interface is served locally; no cloud account or paid API is needed to try it.

## A separate empty pilot workspace

After testing the demo, Windows users can run `start_clean_windows.bat`. On Mac/Linux:

```sh
sh start_clean_mac_linux.sh
```

This uses `data/onesource-pilot.sqlite3`, separate from the demo database, and does not add sample records. It is still a pilot, not a production launch. Close the demo server before starting it, because both use port 8765. To run both, give one a different `--port`.

First configure your company, state, customers, suppliers, items, warehouses, projects and users. Opening receivables/payables migration is not implemented; do not try to move your existing live books into this release through manual journals.

## What works now

| Area | Implemented workflow |
| --- | --- |
| CRM | Sales opportunities, stages, probability, owner, next follow-up and linked quotations. |
| Commercial | Itemized quotations, approvals, one linked sales order, duplicate customer PO/WO reference protection and printable internal copies. |
| Purchasing | Purchase orders, approval, partial goods receipts, full-receipt matched supplier billing and supplier payments. |
| Inventory | Opening stock, item/warehouse balances, moving-average cost, same-registration transfers and stock-shortage controls. |
| Dispatch | Partial order dispatches, delivery vehicle/transporter references, POD references and attachments. |
| Projects | Customer/site workspaces, budget, billing progress, posted project margin, area clearances, blockers, labour and idle/rework logs. |
| Commercial recovery | Variation/rework/debit-dispute register, measurement and RA certification register, and LC claim/acceptance/maturity tracking. |
| Collections | Customer invoices, partial receipts, TDS and retention deductions, cash advances, advance application and retention settlement. |
| Accounts | Double-entry postings, controlled manual journals, reversals, a period lock, ledgers, trial balance, P&L, balance sheet and GST working. |
| Administration | Named user accounts, role-based write permissions, account disabling, an audit trail, supported attachments, CSV export and database backup. |

The complete supply flow is **lead -> quotation -> approval -> sales order -> approval -> dispatch -> invoice -> receipt**. Buying stock is **purchase order -> approval -> goods receipt -> supplier bill -> payment**. Service-only invoices and bills are also supported.

## Important boundaries

This release is one legal company and one GST registration per database. All signed-in users can read all company records; roles restrict actions, not row-level visibility. The chart of accounts is deliberately small and uses a combined bank/cash control account. Reports are all-posted-to-date, not fiscal-period financial statements.

GST calculations are an editable working aid, not legal applicability checks or return filing. There is no IRN/e-invoice, e-way bill, statutory payroll, bank reconciliation/feed, TallyPrime synchronization, Gmail/Drive automation or WhatsApp integration. Printable documents are marked **not a statutory tax invoice**.

Stock returns, GST credit/debit notes, purchase price variances, multi-GRN supplier invoices, opening debtor/creditor migration, full subcontractor billing, WIP/revenue-recognition policy, multi-company consolidation and production-grade deployment are not complete. Read `docs/DEPLOYMENT_CHECKLIST.md` before considering live use.

## Access, backup and recovery

Give each user their own login in **Settings & access**. Do not share the admin account. Disable access when someone leaves. Period locking is inclusive and cannot be reopened through this release's interface.

An admin can use **Settings & access -> Download database backup**. The backup includes records, attachments and password hashes: protect it as sensitive financial data. CSV is useful for review but is not a full backup and is not a ready-made Tally import format.

To recover the admin password for the demo database:

```sh
python app.py --db data/onesource-demo.sqlite3 --reset-admin-password --demo --open
```

Use the actual database path for the workspace you intend to recover. This rotates the admin password and invalidates sessions; it does not reset business data. Anyone with OS-level access to the database and program can exercise this recovery, so protect the host account and files.

To restore a downloaded database, stop the server, retain a separate copy of the current database folder, place the backup under a **new database filename**, and launch `app.py --db path/to/restored.sqlite3`. Test the records and all six checks in **Reports -> Integrity checks** before using the restored workspace. Do not overwrite a database while it is running or reuse stale `-wal`/`-shm` files.

## Technical handover

- `app.py`: local HTTP server, sessions, security checks, APIs, exports and backups.
- `core.py`: schema, transactional business rules, accounting and report calculations.
- `seed.py`: fictional demonstration dataset.
- `static/`: browser interface, CSS and JavaScript; no remote assets required.
- `tests/`: 48 standard-library unit/integration tests.
- `docs/USER_GUIDE.md`: daily operating instructions.
- `docs/ACCOUNTING_MODEL.md`: posting rules and accounting limitations.
- `docs/DEPLOYMENT_CHECKLIST.md`: mandatory decisions and safeguards before live rollout.
- `docs/TEST_REPORT.md`: verification evidence and what was not tested.
- `docs/ROADMAP.md`: remaining One Source workflow and integration scope.
- `PREVIEW.html`: self-contained, read-only visual demonstration.

Run the included tests from this folder:

```sh
python -m unittest discover -s tests -v
```

Do not expose the bundled development HTTP server directly to the internet. This handover has not been hosted on your domain or installed on company machines. Production needs an appropriate application deployment, HTTPS, controlled access, monitored backups, migration, a security review and your accountant's sign-off.
