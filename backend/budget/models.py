from django.conf import settings
from django.core.validators import MinValueValidator, MaxValueValidator
from django.db import models
from django.db.models import Sum
from django.utils import timezone

U = settings.AUTH_USER_MODEL
total = lambda qs: qs.aggregate(t=Sum('amount'))['t'] or 0


class Account(models.Model):
    KINDS = [(k, k) for k in ('bank', 'mpesa', 'cash', 'sacco', 'mmf', 'investment', 'credit_card')]
    user = models.ForeignKey(U, on_delete=models.CASCADE)
    name = models.CharField(max_length=60)
    kind = models.CharField(max_length=20, choices=KINDS, default='bank')
    opening_balance = models.DecimalField(max_digits=14, decimal_places=2, default=0)

    @property
    def balance(self):
        t = self.transactions.filter(is_active=True)
        return (self.opening_balance + total(t.filter(kind='income'))
                - total(t.filter(kind__in=['expense', 'transfer']))
                + total(self.incoming.filter(is_active=True, kind='transfer')))

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
    category_type = models.CharField(max_length=20, choices=KINDS, default='needs')
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
    """income | expense | transfer. Links to SpentCategory for expenses."""
    KINDS = [('income', 'income'), ('expense', 'expense'), ('transfer', 'transfer')]
    user = models.ForeignKey(U, on_delete=models.CASCADE)
    kind = models.CharField(max_length=10, choices=KINDS, default='expense')
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

    def __str__(self):
        return f"{self.kind}: {self.amount} ({self.transaction_date})"
