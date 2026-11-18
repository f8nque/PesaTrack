# Tally roadmap

Rules: transfers are never expenses. Budget (plan) and actual are stored separately. Every transaction has `transaction_date` and `created_at`.

## V1 Core budgeting (done, v1.0.0)
- [x] Accounts (bank, M-Pesa, cash, SACCO, MMF, investment, credit card)
- [x] Categories with subcategories
- [x] Income, expenses, transfers (one transaction record)
- [x] Monthly budget (plan per category) with actual and remaining
- [x] Dashboard: left, savings rate, unallocated, spent today, balances
- [x] Debts and repayments (repayment = expense linked to a debt)

## V2 Better personal finance
- [ ] Recurring transactions (Celery)
- [ ] Budget alerts, savings goals + contributions
- [ ] Split transactions, reports, CSV import/export
- [ ] Month picker, edit transactions, audit trail

## V3 Analytics: trends, deterministic cash-flow forecast, debt interest accrual
## V4 ML: auto-categorisation, anomaly detection, spending prediction
