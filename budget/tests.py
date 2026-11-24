from decimal import Decimal
from django.contrib.auth.models import User
from django.test import TestCase
from django.utils import timezone
from .models import (
    Account, BudgetGroupCategory, BudgetCategory, SpentCategory,
    Debt, Transaction, Budget, BudgetItem
)
from .services import (
    compute_account_insights, compute_debt_analysis, compute_summary,
    reconcile_account_balance, resolve_default_account
)


class BudgetArchitectureTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='testuser', password='password123')
        self.client.force_login(self.user)
        self.today = timezone.localdate()

    def test_three_tier_categories(self):
        # 1. Budget Grouping Category (e.g. UPKEEP, priority 1)
        res_group = self.client.post('/categories/save/', {
            'tier': 'grouping',
            'name': 'UPKEEP',
            'priority': 1,
        })
        self.assertEqual(res_group.status_code, 302)
        group = BudgetGroupCategory.objects.get(user=self.user, name='UPKEEP')
        self.assertEqual(group.priority, 1)

        # 2. Budget Category (e.g. Shopping, type needs, linked to UPKEEP)
        res_bcat = self.client.post('/categories/save/', {
            'tier': 'budget',
            'name': 'Shopping',
            'grouping': group.id,
            'category_type': 'needs',
            'is_active': 'on',
            'is_active_submitted': '1',
        })
        self.assertEqual(res_bcat.status_code, 302)
        bcat = BudgetCategory.objects.get(user=self.user, name='Shopping')
        self.assertEqual(bcat.grouping.name, 'UPKEEP')
        self.assertEqual(bcat.category_type, 'needs')

        # 3. Spent Category (e.g. supermarket, MEAT, milk linked to Shopping)
        for cat_name in ['supermarket', 'MEAT', 'milk']:
            res_scat = self.client.post('/categories/save/', {
                'tier': 'spent',
                'name': cat_name,
                'budget_category': bcat.id,
                'is_active': 'on',
                'is_active_submitted': '1',
            })
            self.assertEqual(res_scat.status_code, 302)
            scat = SpentCategory.objects.get(user=self.user, name=cat_name)
            self.assertEqual(scat.budget_category.name, 'Shopping')
            self.assertIn('UPKEEP > Shopping', scat.full_path)

    def test_budget_creation_and_computed_values(self):
        group = BudgetGroupCategory.objects.create(user=self.user, name='UPKEEP', priority=1)
        bcat = BudgetCategory.objects.create(user=self.user, grouping=group, name='Shopping', category_type='needs')
        scat = SpentCategory.objects.create(user=self.user, budget_category=bcat, name='MEAT')

        # 1. Create a Budget
        res_budget = self.client.post('/budget/save/', {
            'name': 'November 2026 Budget',
            'description': 'Family monthly living expenses',
            'start_date': str(self.today.replace(day=1)),
            'end_date': str(self.today.replace(day=28)),
            'allocated_amount': '50000.00',
        })
        self.assertEqual(res_budget.status_code, 302)
        budget = Budget.objects.get(user=self.user, name='November 2026 Budget')
        self.assertEqual(float(budget.allocated_amount), 50000.0)
        self.assertEqual(float(budget.total_item_planned), 0.0)

        # 2. Create Budget Item
        res_item = self.client.post('/budget/item/save/', {
            'budget': budget.id,
            'budget_category': bcat.id,
            'amount': '15000.00',
            'reason': 'Initial planned allocation for meat and groceries',
        })
        self.assertEqual(res_item.status_code, 302)
        item = BudgetItem.objects.get(budget=budget, budget_category=bcat)
        self.assertEqual(item.reason, 'Initial planned allocation for meat and groceries')

        # 3. Verify computed values on Budget
        self.assertEqual(float(budget.allocated_amount), 50000.0)
        self.assertEqual(float(budget.total_item_planned), 15000.0)
        self.assertEqual(float(budget.unallocated_amount), 35000.0)

        # 4. Record spend on spent category
        res_tx = self.client.post('/today/save/', {
            'amount': '2500.00',
            'category': scat.id,
            'date': str(self.today),
            'narrative': 'Butchery meat purchase',
        })
        self.assertEqual(res_tx.status_code, 302)

        # Verify summary reflects allocated budget, computed planned items, and actual spent
        summary = compute_summary(self.user, self.today.strftime('%Y-%m'))
        self.assertEqual(summary['allocated_budget'], 50000.0)
        self.assertEqual(summary['planned'], 15000.0)
        self.assertEqual(summary['budget'][0]['actual'], 2500.0)
        self.assertEqual(summary['budget'][0]['grouping_priority'], 1)

    def test_restrict_one_entry_per_category_and_date(self):
        group = BudgetGroupCategory.objects.create(user=self.user, name='UPKEEP', priority=1)
        bcat = BudgetCategory.objects.create(user=self.user, grouping=group, name='Shopping', category_type='needs')
        scat1 = SpentCategory.objects.create(user=self.user, budget_category=bcat, name='MEAT')
        scat2 = SpentCategory.objects.create(user=self.user, budget_category=bcat, name='MILK')

        # 1. Create first transaction for scat1 on self.today
        self.client.post('/today/save/', {
            'amount': '150.00',
            'category': scat1.id,
            'date': str(self.today),
            'narrative': 'First meat purchase',
        })
        tx1 = Transaction.objects.get(user=self.user, spent_category=scat1, transaction_date=self.today)

        # 2. Duplicate attempt on same date and same category must be rejected
        res_dup = self.client.post('/today/save/', {
            'amount': '200.00',
            'category': scat1.id,
            'date': str(self.today),
            'narrative': 'Duplicate meat purchase',
        }, follow=True)
        self.assertContains(res_dup, 'already exists')
        self.assertEqual(
            Transaction.objects.filter(user=self.user, spent_category=scat1, transaction_date=self.today, is_active=True).count(),
            1
        )

        # 3. Different category on same date is allowed
        self.client.post('/today/save/', {
            'amount': '80.00',
            'category': scat2.id,
            'date': str(self.today),
            'narrative': 'Milk purchase',
        })
        self.assertTrue(Transaction.objects.filter(user=self.user, spent_category=scat2, transaction_date=self.today).exists())

        # 4. Same category on different date is allowed
        other_date = str(self.today.replace(day=self.today.day - 1 if self.today.day > 1 else 28))
        self.client.post('/today/save/', {
            'amount': '120.00',
            'category': scat1.id,
            'date': other_date,
            'narrative': 'Meat purchase other date',
        })
        self.assertTrue(Transaction.objects.filter(user=self.user, spent_category=scat1, transaction_date=other_date).exists())

        # 5. Editing non-category field (amount) on tx1 succeeds without duplicate error
        self.client.post('/today/save/', {
            'id': tx1.id,
            'amount': '175.00',
            'category': scat1.id,
            'date': str(self.today),
            'narrative': 'First meat purchase',
            'is_active': 'on',
        })
        tx1.refresh_from_db()
        self.assertEqual(float(tx1.amount), 175.0)

        # 6. Deactivating tx1 allows a new active entry for scat1 on self.today
        self.client.post(f'/transactions/{tx1.id}/toggle/')
        tx1.refresh_from_db()
        self.assertFalse(tx1.is_active)

        self.client.post('/today/save/', {
            'amount': '220.00',
            'category': scat1.id,
            'date': str(self.today),
            'narrative': 'New active meat purchase after deactivating old one',
        })
        self.assertEqual(
            Transaction.objects.filter(user=self.user, spent_category=scat1, transaction_date=self.today, is_active=True).count(),
            1
        )

        # 7. Reactivating tx1 now fails because another active entry exists
        res_reactivate = self.client.post(f'/transactions/{tx1.id}/toggle/', follow=True)
        self.assertContains(res_reactivate, 'already exists')
        tx1.refresh_from_db()
        self.assertFalse(tx1.is_active)


class BankingAccountArchitectureTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='bankuser', password='password123')
        self.client.force_login(self.user)
        self.today = timezone.localdate()

    def test_account_type_and_opening_balance_as_of_date(self):
        self.client.post('/accounts/save/', {
            'name': 'M-Pesa Wallet',
            'kind': 'mpesa',
            'opening_balance': '5000.00',
            'as_of_date': str(self.today),
        })
        acct = Account.objects.get(user=self.user, name='M-Pesa Wallet')
        self.assertEqual(acct.kind, 'mpesa')
        self.assertEqual(float(acct.balance), 5000.0)
        self.assertEqual(acct.as_of_date, self.today)

        # Verify opening balance does NOT inflate "Income" analytics for the month
        summary = compute_summary(self.user, self.today.strftime('%Y-%m'))
        self.assertEqual(summary['income'], 0.0)
        self.assertEqual(summary['total_balance'], 5000.0)

    def test_manual_balance_adjustment_reconciliation(self):
        acct = Account.objects.create(
            user=self.user,
            name='KCB Bank',
            kind='bank',
            opening_balance=Decimal('5000.00'),
        )

        # 1. Reconcile with actual balance 4,950 (deficit of 50)
        tx1, diff1, bal1 = reconcile_account_balance(
            self.user, acct, '4950.00', notes='Reconciled with KCB mobile banking SMS'
        )
        self.assertEqual(float(diff1), -50.0)
        self.assertEqual(float(bal1), 4950.0)
        self.assertEqual(tx1.kind, 'adjustment')
        self.assertEqual(tx1.adjustment_type, 'debit')

        # 2. Reconcile is silent: Does NOT inflate Income or Expense budget analytics
        summary = compute_summary(self.user, self.today.strftime('%Y-%m'))
        self.assertEqual(summary['income'], 0.0)
        self.assertEqual(summary['spent'], 0.0)

        # 3. Reconcile surplus: actual balance is 5,050 (diff: +100)
        tx2, diff2, bal2 = reconcile_account_balance(
            self.user, acct, '5050.00', notes='Unrecorded cash deposit'
        )
        self.assertEqual(float(diff2), 100.0)
        self.assertEqual(float(bal2), 5050.0)
        self.assertEqual(tx2.adjustment_type, 'credit')

        # 4. Reconcile when balances match: no new transaction created
        tx3, diff3, bal3 = reconcile_account_balance(self.user, acct, '5050.00')
        self.assertIsNone(tx3)
        self.assertEqual(diff3, 0)
        self.assertEqual(float(bal3), 5050.0)

    def test_minimum_balance_low_balance_alert(self):
        acct = Account.objects.create(
            user=self.user,
            name='M-Pesa Working Account',
            kind='mpesa',
            opening_balance=Decimal('1500.00'),
            minimum_balance=Decimal('1000.00'),
        )
        self.assertFalse(acct.is_low_balance)

        # Spend 700 -> balance becomes 800 (< 1000)
        self.client.post('/transactions/add/', {
            'account': acct.id,
            'kind': 'expense',
            'amount': '700.00',
            'transaction_date': str(self.today),
            'description': 'Supplies',
        })
        self.assertEqual(float(acct.balance), 800.0)
        self.assertTrue(acct.is_low_balance)

    def test_account_to_account_transfers_and_tariffs(self):
        bank = Account.objects.create(user=self.user, name='Bank', kind='bank', opening_balance=Decimal('10000.00'))
        mpesa = Account.objects.create(user=self.user, name='M-Pesa', kind='mpesa', opening_balance=Decimal('2000.00'))

        # Transfer 3,000 from Bank to M-Pesa with a 25 KES tariff
        self.client.post('/accounts/transfer/', {
            'from_account': bank.id,
            'to_account': mpesa.id,
            'amount': '3000.00',
            'fee': '25.00',
            'transaction_date': str(self.today),
            'narrative': 'Move float from Bank to M-Pesa',
        })

        # Bank deducted: 3000 + 25 = 3025 -> 10000 - 3025 = 6975
        self.assertEqual(float(bank.balance), 6975.0)
        # M-Pesa credited: 3000 -> 2000 + 3000 = 5000
        self.assertEqual(float(mpesa.balance), 5000.0)

        # Transfer does NOT count as Income or Expense in budget summary
        summary = compute_summary(self.user, self.today.strftime('%Y-%m'))
        self.assertEqual(summary['income'], 0.0)
        self.assertEqual(summary['spent'], 0.0)
        self.assertEqual(summary['fees'], 25.0)

    def test_default_account_quick_select(self):
        # First account automatically becomes default
        self.client.post('/accounts/save/', {'name': 'M-Pesa', 'kind': 'mpesa'})
        a1 = Account.objects.get(user=self.user, name='M-Pesa')
        self.assertTrue(a1.is_default)

        # Second account created with is_default=on switches default
        self.client.post('/accounts/save/', {'name': 'Equity Bank', 'kind': 'bank', 'is_default': 'on'})
        a2 = Account.objects.get(user=self.user, name='Equity Bank')
        a1.refresh_from_db()
        self.assertTrue(a2.is_default)
        self.assertFalse(a1.is_default)

        # Explicit set_default action
        self.client.post(f'/accounts/{a1.id}/set-default/')
        a1.refresh_from_db()
        a2.refresh_from_db()
        self.assertTrue(a1.is_default)
        self.assertFalse(a2.is_default)

    def test_archive_and_hide_account(self):
        acct = Account.objects.create(
            user=self.user, name='Old Closed Till', kind='mpesa', opening_balance=Decimal('500.00')
        )
        self.client.post('/transactions/add/', {
            'account': acct.id,
            'kind': 'expense',
            'amount': '200.00',
            'transaction_date': str(self.today),
        })

        # Archive account
        self.client.post(f'/accounts/{acct.id}/archive/')
        acct.refresh_from_db()
        self.assertTrue(acct.is_archived)

        # Default /accounts/ hides archived accounts from active section unless ?show_archived=1
        res_list = self.client.get('/accounts/')
        self.assertNotIn(acct, res_list.context['active_accounts'])

        res_all = self.client.get('/accounts/?show_archived=1')
        self.assertIn(acct, res_all.context['archived_accounts'])

        # Historical transactions preserved
        self.assertTrue(Transaction.objects.filter(user=self.user, account=acct).exists())

        # Unarchive
        self.client.post(f'/accounts/{acct.id}/unarchive/')
        acct.refresh_from_db()
        self.assertFalse(acct.is_archived)

    def test_sub_accounts_and_pots(self):
        parent = Account.objects.create(
            user=self.user, name='M-Pesa Primary', kind='mpesa', opening_balance=Decimal('12000.00')
        )
        Account.objects.create(
            user=self.user, name='M-Shwari Lock Savings', kind='mpesa',
            parent=parent, is_pot=True, opening_balance=Decimal('30000.00')
        )
        self.assertEqual(float(parent.balance), 12000.0)
        self.assertEqual(float(parent.total_balance), 42000.0)
        self.assertEqual(parent.sub_accounts.filter(is_archived=False).count(), 1)

    def test_account_insights(self):
        acct = Account.objects.create(
            user=self.user, name='M-Pesa Wallet', kind='mpesa', opening_balance=Decimal('10000.00')
        )
        group = BudgetGroupCategory.objects.create(user=self.user, name='LIVING', priority=1)
        bcat = BudgetCategory.objects.create(user=self.user, grouping=group, name='Groceries', category_type='needs')
        scat = SpentCategory.objects.create(user=self.user, budget_category=bcat, name='Supermarket')

        Transaction.objects.create(
            user=self.user, account=acct, kind='income', amount=Decimal('25000.00'), transaction_date=self.today
        )
        Transaction.objects.create(
            user=self.user, account=acct, kind='expense', spent_category=scat,
            amount=Decimal('4500.00'), fee=Decimal('23.00'),
            transaction_date=self.today, description='Monthly groceries'
        )

        insights = compute_account_insights(acct, month_str=self.today.strftime('%Y-%m'), timeframe='month')
        self.assertEqual(insights['inflow']['income'], 25000.0)
        self.assertEqual(insights['outflow']['expenses'], 4500.0)
        self.assertEqual(insights['outflow']['fees'], 23.0)
        self.assertGreater(insights['average_daily_spend'], 0)
        self.assertEqual(len(insights['top_categories']), 1)
        self.assertEqual(insights['top_categories'][0]['name'], 'Supermarket')


class DjangoTemplateWebViewsTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='webuser', password='password123')
        self.today = timezone.localdate()

    def test_auth_redirects_and_login_register(self):
        # Unauthenticated root redirects to /login/
        res = self.client.get('/')
        self.assertEqual(res.status_code, 302)
        self.assertIn('/login/', res.url)

        # Register a new user via template view
        res_reg = self.client.post('/register/', {'username': 'newuser', 'password': 'secret123'})
        self.assertRedirects(res_reg, '/')
        self.assertTrue(User.objects.filter(username='newuser').exists())

        # Logout
        res_out = self.client.post('/logout/')
        self.assertRedirects(res_out, '/login/')

        # Login with existing user
        res_in = self.client.post('/login/', {'username': 'webuser', 'password': 'password123'})
        self.assertRedirects(res_in, '/')

    def test_all_pages_render_and_workflows_work(self):
        self.client.force_login(self.user)

        # 1. Categories: create grouping -> budget category -> spent category
        self.client.post('/categories/save/', {'tier': 'grouping', 'name': 'UPKEEP', 'priority': '1'})
        grp = BudgetGroupCategory.objects.get(user=self.user, name='UPKEEP')

        self.client.post('/categories/save/', {
            'tier': 'budget',
            'name': 'Shopping',
            'grouping': grp.id,
            'category_type': 'needs',
            'is_active': 'on',
            'is_active_submitted': '1',
        })
        bcat = BudgetCategory.objects.get(user=self.user, name='Shopping')

        self.client.post('/categories/save/', {
            'tier': 'spent',
            'name': 'MEAT',
            'budget_category': bcat.id,
            'is_active': 'on',
            'is_active_submitted': '1',
        })
        scat = SpentCategory.objects.get(user=self.user, name='MEAT')

        res_cats = self.client.get('/categories/?tab=spent')
        self.assertEqual(res_cats.status_code, 200)
        self.assertContains(res_cats, 'MEAT')

        # 2. Accounts: create two accounts, transfer, reconcile, insights
        self.client.post('/accounts/save/', {
            'name': 'KCB Bank',
            'kind': 'bank',
            'opening_balance': '10000.00',
            'as_of_date': str(self.today),
        })
        self.client.post('/accounts/save/', {
            'name': 'M-Pesa',
            'kind': 'mpesa',
            'opening_balance': '2000.00',
            'as_of_date': str(self.today),
            'is_default': 'on',
        })
        bank = Account.objects.get(user=self.user, name='KCB Bank')
        mpesa = Account.objects.get(user=self.user, name='M-Pesa')
        self.assertTrue(mpesa.is_default)

        self.client.post('/accounts/transfer/', {
            'from_account': bank.id,
            'to_account': mpesa.id,
            'amount': '3000.00',
            'fee': '25.00',
            'transaction_date': str(self.today),
            'narrative': 'Top up M-Pesa',
        })
        self.assertEqual(float(bank.balance), 6975.0)
        self.assertEqual(float(mpesa.balance), 5000.0)

        self.client.post(f'/accounts/{mpesa.id}/reconcile/', {
            'actual_balance': '4950.00',
            'date': str(self.today),
            'notes': 'SMS check',
        })
        self.assertEqual(float(mpesa.balance), 4950.0)

        res_ins = self.client.get(f'/accounts/?insights={mpesa.id}&timeframe=month')
        self.assertEqual(res_ins.status_code, 200)
        self.assertContains(res_ins, 'M-Pesa Insights')

        # 3. Today's Spends: create spend and verify duplicate prevention
        self.client.post('/today/save/', {
            'date': str(self.today),
            'account': mpesa.id,
            'category': scat.id,
            'amount': '500.00',
            'narrative': 'Beef stew',
        })
        res_today = self.client.get('/')
        self.assertEqual(res_today.status_code, 200)
        self.assertContains(res_today, 'Beef stew')
        self.assertEqual(Transaction.objects.filter(user=self.user, spent_category=scat, is_active=True).count(), 1)

        # Duplicate on same date + category is rejected
        self.client.post('/today/save/', {
            'date': str(self.today),
            'account': mpesa.id,
            'category': scat.id,
            'amount': '200.00',
            'narrative': 'Duplicate beef',
        })
        self.assertEqual(Transaction.objects.filter(user=self.user, spent_category=scat, is_active=True).count(), 1)

        # 4. Transactions page
        self.client.post('/transactions/add/', {
            'kind': 'income',
            'account': bank.id,
            'amount': '25000.00',
            'transaction_date': str(self.today),
            'description': 'Salary',
        })
        res_txs = self.client.get('/transactions/')
        self.assertEqual(res_txs.status_code, 200)
        self.assertContains(res_txs, 'Salary')

        # 5. Budget Plan page
        self.client.post('/budget/save/', {
            'name': 'Monthly Plan',
            'description': 'Main plan',
            'start_date': str(self.today.replace(day=1)),
            'end_date': str(self.today.replace(day=28)),
            'allocated_amount': '30000.00',
        })
        b = Budget.objects.get(user=self.user, name='Monthly Plan')
        self.client.post('/budget/item/save/', {
            'budget': b.id,
            'budget_category': bcat.id,
            'amount': '5000.00',
            'reason': 'Groceries budget',
        })
        res_budget = self.client.get(f'/budget/?budget={b.id}')
        self.assertEqual(res_budget.status_code, 200)
        self.assertContains(res_budget, 'Monthly Plan')
        self.assertContains(res_budget, 'Groceries budget')

        # 6. Dashboard page
        res_dash = self.client.get('/dashboard/')
        self.assertEqual(res_dash.status_code, 200)
        self.assertContains(res_dash, 'Shopping')

        # 7. Debts page
        self.client.post('/debts/add/', {
            'name': 'Car Loan',
            'principal': '100000.00',
            'interest_rate': '10.00',
            'min_payment': '5000.00',
        })
        debt = Debt.objects.get(user=self.user, name='Car Loan')
        self.client.post(f'/debts/{debt.id}/repay/', {
            'account': bank.id,
            'amount': '5000.00',
        })
        res_debts = self.client.get('/debts/')
        self.assertEqual(res_debts.status_code, 200)
        self.assertContains(res_debts, 'Car Loan')
        self.assertEqual(float(debt.balance), 95000.0)


class DebtSectionTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='debtuser', password='password123')
        self.client.force_login(self.user)
        self.today = timezone.localdate()

    def test_transactions_hidden_from_navigation(self):
        res = self.client.get('/')
        self.assertEqual(res.status_code, 200)
        self.assertNotContains(res, 'href="/transactions/"')

    def test_debtor_account_check_if_exists_otherwise_register(self):
        # Initially does not exist
        res_chk1 = self.client.get('/debts/accounts/check/?name=KCB+Loan')
        self.assertEqual(res_chk1.status_code, 200)
        self.assertFalse(res_chk1.json()['exists'])

        # Register debtor account
        self.client.post('/debts/accounts/register/', {
            'name': 'KCB Loan',
            'account_number': 'LN-9001',
        })
        self.assertEqual(Account.objects.filter(user=self.user, kind='debtors', name='KCB Loan').count(), 1)

        # Live check now detects it
        res_chk2 = self.client.get('/debts/accounts/check/?name=kcb+loan')
        self.assertTrue(res_chk2.json()['exists'])
        self.assertEqual(res_chk2.json()['account']['name'], 'KCB Loan')

        # Re-registering same name (different case) does not create duplicate
        self.client.post('/debts/accounts/register/', {'name': 'kcb loan'})
        self.assertEqual(Account.objects.filter(user=self.user, kind='debtors').count(), 1)

        # Debtor account is excluded from default payment account resolution
        default_acct = resolve_default_account(self.user)
        self.assertNotEqual(default_acct.kind, 'debtors')

    def test_credit_registration_form_and_payments_and_analysis(self):
        bank = Account.objects.create(
            user=self.user, name='Equity Bank', kind='bank', opening_balance=Decimal('100000.00')
        )

        # 1. Register credit while creating a new debtor account inline
        self.client.post('/debts/add/', {
            'debtor_account_name': 'M-Shwari Loan',
            'registration_date': '2026-01-15',
            'principal': '20000.00',
            'service_date': '2026-03-15',
            'comment': 'Working capital top-up',
        })
        debtor_acct = Account.objects.get(user=self.user, name='M-Shwari Loan', kind='debtors')
        debt1 = Debt.objects.get(user=self.user, account=debtor_acct)
        self.assertEqual(debt1.name, 'M-Shwari Loan')
        self.assertEqual(str(debt1.registration_date), '2026-01-15')
        self.assertEqual(str(debt1.service_date), '2026-03-15')
        self.assertEqual(debt1.comment, 'Working capital top-up')

        # 2. Register a second credit in 2026 linking existing debtor account by name (no duplicate account)
        self.client.post('/debts/add/', {
            'debtor_account_name': 'm-shwari loan',
            'name': 'M-Shwari Second Loan',
            'registration_date': '2026-04-10',
            'principal': '10000.00',
            'service_date': '2026-06-10',
            'comment': 'April top-up',
        })
        self.assertEqual(Account.objects.filter(user=self.user, kind='debtors').count(), 1)

        # 3. Register a 2025 credit for a second debtor to test year filtering
        self.client.post('/debts/add/', {
            'debtor_account_name': 'SACCO Emergency',
            'registration_date': '2025-11-05',
            'principal': '50000.00',
            'service_date': '2026-11-05',
            'comment': '2025 emergency loan',
        })

        # 4. Record repayment transactions on the Payments page
        self.client.post('/debts/repay/', {
            'debt': debt1.id,
            'account': bank.id,
            'amount': '7500.00',
            'transaction_date': '2026-02-20',
            'comment': 'Feb installment',
            'next': '/debts/payments/',
        })
        self.client.post('/debts/repay/', {
            'debt': debt1.id,
            'account': bank.id,
            'amount': '5000.00',
            'transaction_date': '2026-04-25',
            'comment': 'April installment',
            'next': '/debts/payments/',
        })

        res_pay = self.client.get('/debts/payments/')
        self.assertEqual(res_pay.status_code, 200)
        self.assertContains(res_pay, 'Feb installment')
        self.assertContains(res_pay, 'April installment')

        debt1.refresh_from_db()
        self.assertEqual(float(debt1.balance), 7500.0)
        self.assertEqual(float(bank.balance), 87500.0)

        # 5. Debt Analysis: Debtors vs Months filterable by year
        analysis_2026 = compute_debt_analysis(self.user, year=2026)
        self.assertEqual(analysis_2026['selected_year'], 2026)
        self.assertIn(2025, analysis_2026['available_years'])
        self.assertEqual(analysis_2026['grand_year_taken'], 30000.0)
        self.assertEqual(analysis_2026['grand_year_paid'], 12500.0)

        mshwari_row = next(r for r in analysis_2026['rows'] if r['label'] == 'M-Shwari Loan')
        # Month 1 (Jan): taken 20000; Month 2 (Feb): paid 7500; Month 4 (Apr): taken 10000, paid 5000
        self.assertEqual(mshwari_row['months'][0]['taken'], 20000.0)
        self.assertEqual(mshwari_row['months'][1]['paid'], 7500.0)
        self.assertEqual(mshwari_row['months'][3]['taken'], 10000.0)
        self.assertEqual(mshwari_row['months'][3]['paid'], 5000.0)
        self.assertEqual(mshwari_row['balance'], 17500.0)

        # Filter to 2025 via HTTP
        res_2025 = self.client.get('/debts/analysis/?year=2025')
        self.assertEqual(res_2025.status_code, 200)
        self.assertContains(res_2025, 'SACCO Emergency')
        analysis_2025 = compute_debt_analysis(self.user, year=2025)
        self.assertEqual(analysis_2025['grand_year_taken'], 50000.0)
        self.assertEqual(analysis_2025['grand_year_paid'], 0.0)
