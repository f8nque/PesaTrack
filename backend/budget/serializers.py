from rest_framework import serializers
from .models import (
    Account, BudgetGroupCategory, BudgetCategory, SpentCategory,
    Debt, Transaction, Budget, BudgetItem, total
)


class Owned(serializers.ModelSerializer):
    """Restricts related-object choices to the current user's own rows."""
    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        req = self.context.get('request')
        if req:
            for f in self.fields.values():
                qs = getattr(f, 'queryset', None)
                if qs is not None and hasattr(qs.model, 'user'):
                    f.queryset = qs.filter(user=req.user)


class AccountSerializer(Owned):
    balance = serializers.SerializerMethodField()
    liquid_balance = serializers.SerializerMethodField()
    total_balance = serializers.SerializerMethodField()
    is_low_balance = serializers.BooleanField(read_only=True)
    parent_name = serializers.CharField(source='parent.name', read_only=True, default='')
    kind_display = serializers.CharField(source='get_kind_display', read_only=True, default='')
    sub_accounts_count = serializers.SerializerMethodField()

    get_balance = lambda self, a: float(a.balance)
    get_liquid_balance = lambda self, a: float(a.balance)
    get_total_balance = lambda self, a: float(a.total_balance)
    get_sub_accounts_count = lambda self, a: a.sub_accounts.filter(is_archived=False).count()

    class Meta:
        model = Account
        exclude = ['user']
        read_only_fields = ['created_at', 'updated_at']

    def create(self, validated_data):
        req = self.context.get('request')
        user = req.user if req and req.user.is_authenticated else None
        if user:
            # If user has no existing accounts, make this account the default
            if not Account.objects.filter(user=user).exists():
                validated_data['is_default'] = True
            elif validated_data.get('is_default'):
                Account.objects.filter(user=user).update(is_default=False)
        return super().create(validated_data)

    def update(self, instance, validated_data):
        if validated_data.get('is_default'):
            Account.objects.filter(user=instance.user).exclude(pk=instance.pk).update(is_default=False)
        return super().update(instance, validated_data)


class BudgetGroupCategorySerializer(Owned):
    budget_categories_count = serializers.SerializerMethodField()
    get_budget_categories_count = lambda self, g: g.budget_categories.count()

    class Meta:
        model = BudgetGroupCategory
        exclude = ['user']
        read_only_fields = ['created_at', 'updated_at']


class BudgetCategorySerializer(Owned):
    grouping_name = serializers.CharField(source='grouping.name', read_only=True, default='')
    grouping_priority = serializers.IntegerField(source='grouping.priority', read_only=True, default=1)
    type_display = serializers.CharField(source='get_category_type_display', read_only=True, default='')
    is_active = serializers.BooleanField(default=True)

    class Meta:
        model = BudgetCategory
        exclude = ['user']
        read_only_fields = ['created_at', 'updated_at']


class SpentCategorySerializer(Owned):
    budget_category_name = serializers.CharField(source='budget_category.name', read_only=True, default='')
    grouping_name = serializers.CharField(source='budget_category.grouping.name', read_only=True, default='')
    full_path = serializers.CharField(read_only=True)
    is_active = serializers.BooleanField(default=True)
    is_savings = serializers.BooleanField(default=False)

    class Meta:
        model = SpentCategory
        exclude = ['user']
        read_only_fields = ['created_at', 'updated_at']


# CategorySerializer alias for backwards compatibility
CategorySerializer = SpentCategorySerializer


class DebtSerializer(Owned):
    balance = serializers.SerializerMethodField()
    get_balance = lambda self, d: float(d.balance)
    class Meta:
        model = Debt
        exclude = ['user']


class BudgetItemSerializer(Owned):
    budget_category_name = serializers.CharField(source='budget_category.name', read_only=True, default='')
    grouping_name = serializers.CharField(source='budget_category.grouping.name', read_only=True, default='')
    grouping_priority = serializers.IntegerField(source='budget_category.grouping.priority', read_only=True, default=1)
    category_type = serializers.CharField(source='budget_category.category_type', read_only=True, default='')
    actual_spent = serializers.SerializerMethodField()

    def get_actual_spent(self, obj):
        spent_cat_ids = obj.budget_category.spent_categories.values_list('id', flat=True)
        txs = Transaction.objects.filter(
            user=obj.budget.user,
            is_active=True,
            kind='expense',
            spent_category_id__in=spent_cat_ids,
            transaction_date__gte=obj.budget.start_date,
            transaction_date__lte=obj.budget.end_date,
        )
        return float(total(txs))

    class Meta:
        model = BudgetItem
        fields = '__all__'
        read_only_fields = ['created_at', 'updated_at']


class BudgetSerializer(Owned):
    total_item_planned = serializers.FloatField(read_only=True)
    unallocated_amount = serializers.FloatField(read_only=True)
    actual_spent = serializers.SerializerMethodField()
    items = BudgetItemSerializer(many=True, read_only=True)

    def get_actual_spent(self, obj):
        txs = Transaction.objects.filter(
            user=obj.user,
            is_active=True,
            kind='expense',
            transaction_date__gte=obj.start_date,
            transaction_date__lte=obj.end_date,
        )
        return float(total(txs))

    class Meta:
        model = Budget
        exclude = ['user']
        read_only_fields = ['created_at', 'updated_at']


class TransactionSerializer(Owned):
    # Support both category and spent_category seamlessly
    category = serializers.PrimaryKeyRelatedField(
        source='spent_category', queryset=SpentCategory.objects.all(),
        required=False, allow_null=True
    )
    category_name = serializers.CharField(source='spent_category.name', read_only=True, default='')
    category_path = serializers.CharField(source='spent_category.full_path', read_only=True, default='')
    budget_category_name = serializers.CharField(source='spent_category.budget_category.name', read_only=True, default='')
    grouping_name = serializers.CharField(source='spent_category.budget_category.grouping.name', read_only=True, default='')
    account_name = serializers.CharField(source='account.name', read_only=True, default='')
    to_account_name = serializers.CharField(source='to_account.name', read_only=True, default='')
    narrative = serializers.CharField(source='description', required=False, allow_blank=True)
    date = serializers.DateField(source='transaction_date', required=False)
    fee = serializers.DecimalField(max_digits=14, decimal_places=2, required=False, default=0)
    adjustment_type = serializers.CharField(required=False, allow_null=True, allow_blank=True)
    is_active = serializers.BooleanField(default=True)

    class Meta:
        model = Transaction
        exclude = ['user']
        read_only_fields = ['created_at', 'updated_at']

    def validate(self, d):
        g = lambda f: d.get(f, getattr(self.instance, f, None))
        amt = g('amount')
        if amt is not None and amt <= 0:
            raise serializers.ValidationError('Amount must be above zero.')
        fee = g('fee')
        if fee is not None and fee < 0:
            raise serializers.ValidationError('Fee cannot be negative.')
        kind = g('kind') or 'expense'
        if kind == 'transfer':
            if not g('to_account') or g('to_account') == g('account'):
                raise serializers.ValidationError('Pick two different accounts for a transfer.')
            d['spent_category'] = d['debt'] = None
        elif kind == 'adjustment':
            d['to_account'] = None
            d['spent_category'] = d['debt'] = None
            if not g('account'):
                raise serializers.ValidationError('Account is required for a balance adjustment.')
            if not g('adjustment_type'):
                d['adjustment_type'] = 'credit'
        else:
            d['to_account'] = None
            if kind == 'income':
                d['debt'] = None

        # Restrict duplicate entries for the same category and date (expenses)
        cat = d.get('spent_category') if 'spent_category' in d else getattr(self.instance, 'spent_category', None)
        tx_date = d.get('transaction_date') if 'transaction_date' in d else getattr(self.instance, 'transaction_date', None)
        is_active = d.get('is_active') if 'is_active' in d else getattr(self.instance, 'is_active', True)

        if cat and tx_date and is_active:
            req = self.context.get('request')
            user = getattr(self.instance, 'user', None) or (req.user if req and req.user.is_authenticated else None)
            if user:
                qs = Transaction.objects.filter(
                    user=user,
                    transaction_date=tx_date,
                    spent_category=cat,
                    is_active=True
                )
                if self.instance and self.instance.pk:
                    qs = qs.exclude(pk=self.instance.pk)
                if qs.exists():
                    cat_name = getattr(cat, 'name', str(cat))
                    raise serializers.ValidationError({
                        'category': f'An entry for category "{cat_name}" on {tx_date} already exists. Only one entry per category and date is allowed.'
                    })

        return d

    def create(self, validated_data):
        req = self.context.get('request')
        if req and req.user.is_authenticated:
            if not validated_data.get('account'):
                acct = Account.objects.filter(user=req.user, is_default=True, is_archived=False).first()
                if not acct:
                    acct = Account.objects.filter(user=req.user, is_archived=False).first()
                if not acct:
                    acct = Account.objects.create(user=req.user, name='Cash', kind='cash', is_default=True)
                validated_data['account'] = acct
        return super().create(validated_data)
