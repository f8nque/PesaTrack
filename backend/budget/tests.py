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
