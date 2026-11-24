from django.contrib.auth.models import User
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient
from .models import (
    Account, BudgetGroupCategory, BudgetCategory, SpentCategory,
    Debt, Transaction, Budget, BudgetItem
)


class BudgetArchitectureTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='testuser', password='password123')
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)
        self.today = timezone.localdate()

    def test_three_tier_categories(self):
        # 1. Budget Grouping Category (e.g. UPKEEP, priority 1)
        res_group = self.client.post('/api/budget-groups/', {
            'name': 'UPKEEP',
            'priority': 1
        }, format='json')
        self.assertEqual(res_group.status_code, 201)
        group_id = res_group.data['id']
        self.assertEqual(res_group.data['priority'], 1)

        # 2. Budget Category (e.g. Shopping, type needs, linked to UPKEEP)
        res_bcat = self.client.post('/api/budget-categories/', {
            'name': 'Shopping',
            'grouping': group_id,
            'category_type': 'needs'
        }, format='json')
        self.assertEqual(res_bcat.status_code, 201)
        bcat_id = res_bcat.data['id']
        self.assertEqual(res_bcat.data['grouping_name'], 'UPKEEP')
        self.assertEqual(res_bcat.data['category_type'], 'needs')

        # 3. Spent Category (e.g. supermarket, MEAT, milk linked to Shopping)
        for cat_name in ['supermarket', 'MEAT', 'milk']:
            res_scat = self.client.post('/api/spent-categories/', {
                'name': cat_name,
                'budget_category': bcat_id,
                'is_savings': False,
                'is_active': True
            }, format='json')
            self.assertEqual(res_scat.status_code, 201)
            self.assertEqual(res_scat.data['budget_category_name'], 'Shopping')
            self.assertIn('UPKEEP > Shopping', res_scat.data['full_path'])

    def test_budget_creation_and_computed_values(self):
        # Setup group, budget category, spent category
        group = BudgetGroupCategory.objects.create(user=self.user, name='UPKEEP', priority=1)
        bcat = BudgetCategory.objects.create(user=self.user, grouping=group, name='Shopping', category_type='needs')
        scat = SpentCategory.objects.create(user=self.user, budget_category=bcat, name='MEAT')

        # 1. Create a Budget:
        # Budget Name, Budget Description, Start Date, End Date, Allocated Budget Amount
        res_budget = self.client.post('/api/budgets/', {
            'name': 'November 2026 Budget',
            'description': 'Family monthly living expenses',
            'start_date': str(self.today.replace(day=1)),
            'end_date': str(self.today.replace(day=28)),
            'allocated_amount': '50000.00'  # Inputted amount
        }, format='json')
        self.assertEqual(res_budget.status_code, 201)
        budget_id = res_budget.data['id']
        self.assertEqual(float(res_budget.data['allocated_amount']), 50000.0)
        self.assertEqual(float(res_budget.data['total_item_planned']), 0.0)

        # 2. Create Budget Item:
        # Linked to Budget Category, linked to Budget, amount, reason for update
        res_item = self.client.post('/api/budget-items/', {
            'budget': budget_id,
            'budget_category': bcat.id,
            'amount': '15000.00',
            'reason': 'Initial planned allocation for meat and groceries'
        }, format='json')
        self.assertEqual(res_item.status_code, 201)
        self.assertEqual(res_item.data['reason'], 'Initial planned allocation for meat and groceries')

        # 3. Verify Budget has two values:
        # One inputted (allocated_amount = 50000), one computed (total_item_planned = 15000)
        res_get_budget = self.client.get(f'/api/budgets/{budget_id}/')
        self.assertEqual(res_get_budget.status_code, 200)
        self.assertEqual(float(res_get_budget.data['allocated_amount']), 50000.0)
        self.assertEqual(float(res_get_budget.data['total_item_planned']), 15000.0)
        self.assertEqual(float(res_get_budget.data['unallocated_amount']), 35000.0)

        # 4. Record spend on spent category
        res_tx = self.client.post('/api/transactions/', {
            'amount': '2500.00',
            'category': scat.id,
            'date': str(self.today),
            'narrative': 'Butchery meat purchase'
        }, format='json')
        self.assertEqual(res_tx.status_code, 201)

        # Verify summary reflects allocated budget, computed planned items, and actual spent
        res_sum = self.client.get(f'/api/summary/?month={self.today.strftime("%Y-%m")}')
        self.assertEqual(res_sum.status_code, 200)
        self.assertEqual(res_sum.data['allocated_budget'], 50000.0)
        self.assertEqual(res_sum.data['planned'], 15000.0)
        self.assertEqual(res_sum.data['budget'][0]['actual'], 2500.0)
        self.assertEqual(res_sum.data['budget'][0]['grouping_priority'], 1)

    def test_restrict_one_entry_per_category_and_date(self):
        group = BudgetGroupCategory.objects.create(user=self.user, name='UPKEEP', priority=1)
        bcat = BudgetCategory.objects.create(user=self.user, grouping=group, name='Shopping', category_type='needs')
        scat1 = SpentCategory.objects.create(user=self.user, budget_category=bcat, name='MEAT')
        scat2 = SpentCategory.objects.create(user=self.user, budget_category=bcat, name='MILK')

        # 1. Create first transaction for scat1 on self.today
        res1 = self.client.post('/api/transactions/', {
            'amount': '150.00',
            'category': scat1.id,
            'date': str(self.today),
            'narrative': 'First meat purchase'
        }, format='json')
        self.assertEqual(res1.status_code, 201)
        tx1_id = res1.data['id']

        # 2. Duplicate attempt on same date and same category must fail
        res_dup = self.client.post('/api/transactions/', {
            'amount': '200.00',
            'category': scat1.id,
            'date': str(self.today),
            'narrative': 'Duplicate meat purchase'
        }, format='json')
        self.assertEqual(res_dup.status_code, 400)
        self.assertIn('already exists', str(res_dup.data))

        # 3. Different category on same date is allowed
        res_diff_cat = self.client.post('/api/transactions/', {
            'amount': '80.00',
            'category': scat2.id,
            'date': str(self.today),
            'narrative': 'Milk purchase'
        }, format='json')
        self.assertEqual(res_diff_cat.status_code, 201)

        # 4. Same category on different date is allowed
        other_date = str(self.today.replace(day=self.today.day - 1 if self.today.day > 1 else 28))
        res_diff_date = self.client.post('/api/transactions/', {
            'amount': '120.00',
            'category': scat1.id,
            'date': other_date,
            'narrative': 'Meat purchase other date'
        }, format='json')
        self.assertEqual(res_diff_date.status_code, 201)

        # 5. Editing non-category field (amount) on tx1 succeeds without duplicate error
        res_edit = self.client.patch(f'/api/transactions/{tx1_id}/', {
            'amount': '175.00'
        }, format='json')
        self.assertEqual(res_edit.status_code, 200)
        self.assertEqual(float(res_edit.data['amount']), 175.0)

        # 6. Deactivating tx1 allows a new active entry for scat1 on self.today
        self.client.post(f'/api/transactions/{tx1_id}/deactivate/')
        res_new_after_deact = self.client.post('/api/transactions/', {
            'amount': '220.00',
            'category': scat1.id,
            'date': str(self.today),
            'narrative': 'New active meat purchase after deactivating old one'
        }, format='json')
        self.assertEqual(res_new_after_deact.status_code, 201)

        # 7. Reactivating tx1 now fails because another active entry exists
        res_reactivate = self.client.post(f'/api/transactions/{tx1_id}/activate/')
        self.assertEqual(res_reactivate.status_code, 400)
        self.assertIn('already exists', str(res_reactivate.data))


class BankingAccountArchitectureTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='bankuser', password='password123')
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)
        self.today = timezone.localdate()

    def test_account_type_and_opening_balance_as_of_date(self):
        # 1. Maintain account type, opening balance, and as-of date
        res = self.client.post('/api/accounts/', {
            'name': 'M-Pesa Wallet',
            'kind': 'mpesa',
            'opening_balance': '5000.00',
            'as_of_date': str(self.today)
        }, format='json')
        self.assertEqual(res.status_code, 201)
        acct_id = res.data['id']
        self.assertEqual(res.data['kind'], 'mpesa')
        self.assertEqual(res.data['balance'], 5000.0)
        self.assertEqual(res.data['as_of_date'], str(self.today))

        # 2. Verify opening balance does NOT inflate "Income" analytics for the month
        res_sum = self.client.get(f'/api/summary/?month={self.today.strftime("%Y-%m")}')
        self.assertEqual(res_sum.status_code, 200)
        self.assertEqual(res_sum.data['income'], 0.0)
        self.assertEqual(res_sum.data['total_balance'], 5000.0)

    def test_manual_balance_adjustment_reconciliation(self):
        # Create account with 5,000 opening balance
        res_acct = self.client.post('/api/accounts/', {
            'name': 'KCB Bank',
            'kind': 'bank',
            'opening_balance': '5000.00'
        }, format='json')
        acct_id = res_acct.data['id']

        # 1. Reconcile with actual balance 4,950 (deficit of 50 due to unrecorded pennies/forgotten fees)
        res_rec1 = self.client.post(f'/api/accounts/{acct_id}/reconcile/', {
            'actual_balance': '4950.00',
            'notes': 'Reconciled with KCB mobile banking SMS'
        }, format='json')
        self.assertEqual(res_rec1.status_code, 201)
        self.assertEqual(res_rec1.data['difference'], -50.0)
        self.assertEqual(res_rec1.data['balance'], 4950.0)
        self.assertEqual(res_rec1.data['transaction']['kind'], 'adjustment')
        self.assertEqual(res_rec1.data['transaction']['adjustment_type'], 'debit')

        # 2. Reconcile is silent: Does NOT inflate Income or Expense budget analytics
        res_sum = self.client.get(f'/api/summary/?month={self.today.strftime("%Y-%m")}')
        self.assertEqual(res_sum.data['income'], 0.0)
        self.assertEqual(res_sum.data['spent'], 0.0)

        # 3. Reconcile surplus: actual balance is 5,050 (diff: +100)
        res_rec2 = self.client.post(f'/api/accounts/{acct_id}/reconcile/', {
            'actual_balance': '5050.00',
            'notes': 'Unrecorded cash deposit'
        }, format='json')
        self.assertEqual(res_rec2.status_code, 201)
        self.assertEqual(res_rec2.data['difference'], 100.0)
        self.assertEqual(res_rec2.data['balance'], 5050.0)
        self.assertEqual(res_rec2.data['transaction']['adjustment_type'], 'credit')

        # 4. Reconcile when balances match: no new transaction created
        res_rec3 = self.client.post(f'/api/accounts/{acct_id}/reconcile/', {
            'actual_balance': '5050.00'
        }, format='json')
        self.assertEqual(res_rec3.status_code, 200)
        self.assertEqual(res_rec3.data['difference'], 0)

    def test_minimum_balance_low_balance_alert(self):
        # Minimum balance threshold: 1,000 KES
        res = self.client.post('/api/accounts/', {
            'name': 'M-Pesa Working Account',
            'kind': 'mpesa',
            'opening_balance': '1500.00',
            'minimum_balance': '1000.00'
        }, format='json')
        acct_id = res.data['id']
        self.assertFalse(res.data['is_low_balance'])

        # Spend 700 -> balance becomes 800 (< 1000)
        self.client.post('/api/transactions/', {
            'account': acct_id,
            'kind': 'expense',
            'amount': '700.00',
            'narrative': 'Supplies'
        }, format='json')

        res_check = self.client.get(f'/api/accounts/{acct_id}/')
        self.assertEqual(res_check.data['balance'], 800.0)
        self.assertTrue(res_check.data['is_low_balance'])

    def test_account_to_account_transfers_and_tariffs(self):
        res_bank = self.client.post('/api/accounts/', {'name': 'Bank', 'kind': 'bank', 'opening_balance': '10000.00'}, format='json')
        res_mpesa = self.client.post('/api/accounts/', {'name': 'M-Pesa', 'kind': 'mpesa', 'opening_balance': '2000.00'}, format='json')
        bank_id = res_bank.data['id']
        mpesa_id = res_mpesa.data['id']

        # Transfer 3,000 from Bank to M-Pesa with a 25 KES tariff
        res_xfer = self.client.post('/api/transactions/', {
            'kind': 'transfer',
            'account': bank_id,
            'to_account': mpesa_id,
            'amount': '3000.00',
            'fee': '25.00',
            'narrative': 'Move float from Bank to M-Pesa'
        }, format='json')
        self.assertEqual(res_xfer.status_code, 201)

        # Bank deducted: 3000 + 25 = 3025 -> 10000 - 3025 = 6975
        res_b = self.client.get(f'/api/accounts/{bank_id}/')
        self.assertEqual(res_b.data['balance'], 6975.0)

        # M-Pesa credited: 3000 -> 2000 + 3000 = 5000
        res_m = self.client.get(f'/api/accounts/{mpesa_id}/')
        self.assertEqual(res_m.data['balance'], 5000.0)

        # Transfer does NOT count as Income or Expense in budget summary
        res_sum = self.client.get(f'/api/summary/?month={self.today.strftime("%Y-%m")}')
        self.assertEqual(res_sum.data['income'], 0.0)
        self.assertEqual(res_sum.data['spent'], 0.0)
        self.assertEqual(res_sum.data['fees'], 25.0)

    def test_default_account_quick_select(self):
        # First account automatically becomes default
        r1 = self.client.post('/api/accounts/', {'name': 'M-Pesa', 'kind': 'mpesa'}, format='json')
        self.assertTrue(r1.data['is_default'])

        # Second account created with is_default=True switches default
        r2 = self.client.post('/api/accounts/', {'name': 'Equity Bank', 'kind': 'bank', 'is_default': True}, format='json')
        self.assertTrue(r2.data['is_default'])

        r1_updated = self.client.get(f'/api/accounts/{r1.data["id"]}/')
        self.assertFalse(r1_updated.data['is_default'])

        # Explicit set_default action
        self.client.post(f'/api/accounts/{r1.data["id"]}/set_default/')
        r1_default = self.client.get(f'/api/accounts/{r1.data["id"]}/')
        self.assertTrue(r1_default.data['is_default'])

    def test_archive_and_hide_account(self):
        r = self.client.post('/api/accounts/', {'name': 'Old Closed Till', 'kind': 'mpesa', 'opening_balance': '500.00'}, format='json')
        acct_id = r.data['id']

        # Add transaction
        self.client.post('/api/transactions/', {'account': acct_id, 'kind': 'expense', 'amount': '200.00'}, format='json')

        # Archive account
        res_arch = self.client.post(f'/api/accounts/{acct_id}/archive/')
        self.assertEqual(res_arch.status_code, 200)
        self.assertTrue(res_arch.data['is_archived'])

        # Default GET /api/accounts/ excludes archived accounts
        res_list = self.client.get('/api/accounts/')
        self.assertNotIn(acct_id, [a['id'] for a in res_list.data])

        # Query with ?include_archived=true includes it
        res_all = self.client.get('/api/accounts/?include_archived=true')
        self.assertIn(acct_id, [a['id'] for a in res_all.data])

        # Historical transactions preserved
        res_txs = self.client.get(f'/api/transactions/?date={self.today}')
        self.assertTrue(any(t['account'] == acct_id for t in res_txs.data))

        # Unarchive
        self.client.post(f'/api/accounts/{acct_id}/unarchive/')
        res_unarch = self.client.get(f'/api/accounts/{acct_id}/')
        self.assertFalse(res_unarch.data['is_archived'])

    def test_sub_accounts_and_pots(self):
        # Parent Account (e.g. M-Pesa liquid wallet)
        res_parent = self.client.post('/api/accounts/', {
            'name': 'M-Pesa Primary',
            'kind': 'mpesa',
            'opening_balance': '12000.00'
        }, format='json')
        parent_id = res_parent.data['id']

        # Sub-Account / Pot (e.g. M-Shwari Lock Savings)
        res_pot = self.client.post('/api/accounts/', {
            'name': 'M-Shwari Lock Savings',
            'kind': 'mpesa',
            'parent': parent_id,
            'is_pot': True,
            'opening_balance': '30000.00'
        }, format='json')
        pot_id = res_pot.data['id']

        # Parent shows liquid balance and total balance (Liquid + Pots)
        res_p = self.client.get(f'/api/accounts/{parent_id}/')
        self.assertEqual(res_p.data['liquid_balance'], 12000.0)
        self.assertEqual(res_p.data['total_balance'], 42000.0)
        self.assertEqual(res_p.data['sub_accounts_count'], 1)

    def test_account_insights(self):
        # Create account
        res_acct = self.client.post('/api/accounts/', {'name': 'M-Pesa Wallet', 'kind': 'mpesa', 'opening_balance': '10000.00'}, format='json')
        acct_id = res_acct.data['id']

        group = BudgetGroupCategory.objects.create(user=self.user, name='LIVING', priority=1)
        bcat = BudgetCategory.objects.create(user=self.user, grouping=group, name='Groceries', category_type='needs')
        scat = SpentCategory.objects.create(user=self.user, budget_category=bcat, name='Supermarket')

        # Record income
        self.client.post('/api/transactions/', {'account': acct_id, 'kind': 'income', 'amount': '25000.00'}, format='json')

        # Record expense with fee
        self.client.post('/api/transactions/', {
            'account': acct_id,
            'kind': 'expense',
            'category': scat.id,
            'amount': '4500.00',
            'fee': '23.00',
            'narrative': 'Monthly groceries'
        }, format='json')

        # Request insights
        res_ins = self.client.get(f'/api/accounts/{acct_id}/insights/')
        self.assertEqual(res_ins.status_code, 200)
        self.assertEqual(res_ins.data['inflow']['income'], 25000.0)
        self.assertEqual(res_ins.data['outflow']['expenses'], 4500.0)
        self.assertEqual(res_ins.data['outflow']['fees'], 23.0)
        self.assertGreater(res_ins.data['average_daily_spend'], 0)
        self.assertEqual(len(res_ins.data['top_categories']), 1)
        self.assertEqual(res_ins.data['top_categories'][0]['name'], 'Supermarket')


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
