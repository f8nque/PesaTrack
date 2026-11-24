from django.conf import settings
from django.core.validators import MinValueValidator, MaxValueValidator
from django.db import models
from django.db.models import Sum
from django.utils import timezone

U = settings.AUTH_USER_MODEL
total = lambda qs, field='amount': qs.aggregate(t=Sum(field))['t'] or 0


class Account(models.Model):
    KINDS = [
        ('bank', 'Bank Account'),
        ('mpesa', 'M-Pesa'),
        ('cash', 'Cash'),
        ('sacco', 'SACCO'),
        ('mmf', 'Money Market Fund (MMF)'),
        ('investment', 'Investment'),
        ('credit_card', 'Credit Card'),
    ]
    user = models.ForeignKey(U, on_delete=models.CASCADE)
    name = models.CharField(max_length=60)
    kind = models.CharField(max_length=20, choices=KINDS, default='mpesa')
    account_number = models.CharField(max_length=50, blank=True, default='', help_text="e.g. Account number, Till, or Paybill")
    opening_balance = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    as_of_date = models.DateField(default=timezone.localdate, help_text="Opening balance as-of date")
    minimum_balance = models.DecimalField(max_digits=14, decimal_places=2, default=0, help_text="Low balance alert threshold")
    is_default = models.BooleanField(default=False, help_text="Primary quick-select default account")
    is_archived = models.BooleanField(default=False, help_text="Archived accounts are hidden from transaction entry")
    parent = models.ForeignKey(
        'self', null=True, blank=True, related_name='sub_accounts',
        on_delete=models.SET_NULL, help_text="Parent account for sub-accounts/pots"
    )
    is_pot = models.BooleanField(default=False, help_text="Whether this is a locked goal or savings pot")
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ('is_archived', '-is_default', 'name')

    @property
    def balance(self):
        """Liquid balance of this account taking into account income, expenses, transfers, fees, and silent adjustments."""
        t = self.transactions.filter(is_active=True)
        
        # 1. Income: money coming into this account (net of any income fee)
        inc = total(t.filter(kind='income'))
        inc_fee = total(t.filter(kind='income').exclude(fee=0), 'fee')
        
        # 2. Expenses: money spent from this account + fees
        exp = total(t.filter(kind='expense'))
        exp_fee = total(t.filter(kind='expense').exclude(fee=0), 'fee')
        
        # 3. Transfers out: money sent to another account + transfer tariff/fee
        xfer_out = total(t.filter(kind='transfer'))
        xfer_fee = total(t.filter(kind='transfer').exclude(fee=0), 'fee')
        
        # 4. Transfers in: money received from another account
        xfer_in = total(self.incoming.filter(is_active=True, kind='transfer'))
        
        # 5. Silent balance adjustments (Reconciliation):
        # credit increases balance, debit decreases balance
        adj_credit = total(t.filter(kind='adjustment', adjustment_type='credit'))
        adj_debit = total(t.filter(kind='adjustment', adjustment_type='debit'))
        
        return (
            self.opening_balance
            + (inc - inc_fee)
            - (exp + exp_fee)
            - (xfer_out + xfer_fee)
            + xfer_in
            + adj_credit - adj_debit
        )

    @property
    def total_balance(self):
        """Liquid balance of this account plus any active sub-accounts / pots."""
        sub_total = sum(sub.balance for sub in self.sub_accounts.filter(is_archived=False))
        return self.balance + sub_total

    @property
    def is_low_balance(self):
        return bool(self.minimum_balance and self.minimum_balance > 0 and self.balance < self.minimum_balance)

    def __str__(self):
        return self.name


class BudgetGroupCategory(models.Model):
    """Level 1: Budget Grouping Category (e.g. UPKEEP), with priority 1-10 for display ordering"""
    user = models.ForeignKey(U, on_delete=models.CASCADE)
    name = models.CharField(max_length=80)
    priority = models.PositiveSmallIntegerField(
        default=1,
        validators=[MinValueValidator(1), MaxValueValidator(10)],
        help_text="Priority 1 to 10 for budget display section ordering"
    )
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name_plural = 'budget grouping categories'
        ordering = ('priority', 'name')

    def __str__(self):
        return f"{self.name} (Priority {self.priority})"


class BudgetCategory(models.Model):
    """Level 2: Budget Category (e.g. Shopping), linked to Budget Grouping (1-many), with Type (needs, wants, savings)"""
    KINDS = [
        ('needs', 'Needs'),
        ('wants', 'Wants'),
        ('savings', 'Savings'),
    ]
    user = models.ForeignKey(U, on_delete=models.CASCADE)
    grouping = models.ForeignKey(BudgetGroupCategory, related_name='budget_categories', on_delete=models.CASCADE)
    name = models.CharField(max_length=80)
    category_type = models.CharField(max_length=20, choices=KINDS, default='wants')
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name_plural = 'budget categories'
        ordering = ('grouping__priority', 'name')

    def __str__(self):
        return f"{self.name} [{self.grouping.name}]"


class SpentCategory(models.Model):
    """Level 3: Spent Category (e.g. supermarket, MEAT, milk), linked to Budget Category with As Savings and Active"""
    user = models.ForeignKey(U, on_delete=models.CASCADE)
    budget_category = models.ForeignKey(
        BudgetCategory, related_name='spent_categories',
        on_delete=models.SET_NULL, null=True, blank=True
    )
    name = models.CharField(max_length=80)
    is_savings = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name_plural = 'spent categories'
        ordering = ('name',)

    def __str__(self):
        if self.budget_category:
            return f"{self.name} ({self.budget_category.name})"
        return self.name

    @property
    def full_path(self):
        if self.budget_category:
            return f"{self.budget_category.grouping.name} > {self.budget_category.name} > {self.name}"
        return self.name


# Legacy model alias to ensure compatibility if referenced
Category = SpentCategory


class Debt(models.Model):
    user = models.ForeignKey(U, on_delete=models.CASCADE)
    name = models.CharField(max_length=100)
    principal = models.DecimalField(max_digits=14, decimal_places=2)
    interest_rate = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    min_payment = models.DecimalField(max_digits=14, decimal_places=2, default=0)

    @property
    def balance(self):
        return self.principal - total(self.repayments.filter(is_active=True))

    def __str__(self):
        return self.name


class Budget(models.Model):
    """Budget with Name, Description, Start Date, End Date, and Allocated Budget Amount"""
    user = models.ForeignKey(U, on_delete=models.CASCADE)
    name = models.CharField(max_length=120, default='Monthly Budget')
    description = models.TextField(blank=True)
    start_date = models.DateField(default=timezone.localdate)
    end_date = models.DateField(default=timezone.localdate)
    allocated_amount = models.DecimalField(
        max_digits=14, decimal_places=2, default=0,
        help_text="Explicit allocated budget amount, different from cumulated item allocation"
    )
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ('-start_date', '-id')

    def __str__(self):
        return f"{self.name} ({self.start_date} to {self.end_date})"

    @property
    def total_item_planned(self):
        """Computed from the budget items under this budget"""
        return float(self.items.aggregate(t=Sum('amount'))['t'] or 0)

    @property
    def unallocated_amount(self):
        return float(self.allocated_amount) - self.total_item_planned


class BudgetItem(models.Model):
    """Budget Item linked to Budget and Budget Category, with amount and reason for update"""
    budget = models.ForeignKey(Budget, related_name='items', on_delete=models.CASCADE)
    budget_category = models.ForeignKey(BudgetCategory, related_name='budget_items', on_delete=models.CASCADE, null=True, blank=True)
    amount = models.DecimalField(max_digits=14, decimal_places=2)
    reason = models.CharField(max_length=255, blank=True, help_text="Reason for update")
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ('budget', 'budget_category')

    def __str__(self):
        return f"{self.budget_category.name}: {self.amount}"


class Transaction(models.Model):
    """income | expense | transfer | adjustment. Links to SpentCategory for expenses."""
    KINDS = [
        ('income', 'income'),
        ('expense', 'expense'),
        ('transfer', 'transfer'),
        ('adjustment', 'adjustment'),
    ]
    ADJUSTMENT_TYPES = [
        ('credit', 'credit'),
        ('debit', 'debit'),
    ]
    user = models.ForeignKey(U, on_delete=models.CASCADE)
    kind = models.CharField(max_length=15, choices=KINDS, default='expense')
    adjustment_type = models.CharField(max_length=10, choices=ADJUSTMENT_TYPES, null=True, blank=True)
    fee = models.DecimalField(max_digits=14, decimal_places=2, default=0, help_text="Transaction fee / tariff")
    account = models.ForeignKey(Account, null=True, blank=True, related_name='transactions', on_delete=models.CASCADE)
    to_account = models.ForeignKey(Account, null=True, blank=True, related_name='incoming', on_delete=models.CASCADE)
    spent_category = models.ForeignKey(SpentCategory, null=True, blank=True, related_name='transactions', on_delete=models.SET_NULL)
    debt = models.ForeignKey(Debt, null=True, blank=True, related_name='repayments', on_delete=models.SET_NULL)
    amount = models.DecimalField(max_digits=14, decimal_places=2)
    transaction_date = models.DateField(default=timezone.localdate)
    description = models.CharField(max_length=200, blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ('-transaction_date', '-id')
        constraints = [
            models.UniqueConstraint(
                fields=['user', 'transaction_date', 'spent_category'],
                condition=models.Q(is_active=True, spent_category__isnull=False),
                name='unique_active_transaction_per_category_date'
            )
        ]

    def __str__(self):
        return f"{self.kind}: {self.amount} ({self.transaction_date})"
