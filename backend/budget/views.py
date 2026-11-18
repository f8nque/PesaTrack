from django.contrib.auth.models import User
from django.db import models
from django.db.models import Sum
from django.utils import timezone
from rest_framework import viewsets, status
from rest_framework.authtoken.models import Token
from rest_framework.decorators import api_view, authentication_classes, permission_classes, action
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from .models import (
    Account, BudgetGroupCategory, BudgetCategory, SpentCategory,
    Debt, Transaction, Budget, BudgetItem, total
)
from .serializers import (
    AccountSerializer, BudgetGroupCategorySerializer, BudgetCategorySerializer,
    SpentCategorySerializer, DebtSerializer, TransactionSerializer,
    BudgetSerializer, BudgetItemSerializer
)


class OwnedViewSet(viewsets.ModelViewSet):
    owner = 'user'          # lookup leading to the owning user
    date_field = None       # enables ?month=YYYY-MM or ?date=YYYY-MM-DD
    ordering = ('-id',)

    def get_queryset(self):
        qs = self.queryset.model.objects.filter(**{self.owner: self.request.user})
        params = self.request.query_params

        # Filter by specific date ?date=YYYY-MM-DD
        d = params.get('date')
        if d and self.date_field:
            qs = qs.filter(**{self.date_field: d})

        # Filter by month ?month=YYYY-MM
        m = params.get('month')
        if m and self.date_field:
            try:
                y, mo = m.split('-')
                qs = qs.filter(**{self.date_field + '__year': y, self.date_field + '__month': mo})
            except ValueError:
                pass

        # Filter by kind (e.g. ?kind=expense)
        k = params.get('kind')
        if k and hasattr(self.queryset.model, 'kind'):
            qs = qs.filter(kind=k)

        # Filter by is_active (?is_active=true|false or ?active=true|false)
        active_param = params.get('is_active', params.get('active'))
        if active_param is not None and hasattr(self.queryset.model, 'is_active'):
            val = active_param.lower() in ('true', '1')
            qs = qs.filter(is_active=val)

        # Filter by budget_category
        b_cat = params.get('budget_category')
        if b_cat and hasattr(self.queryset.model, 'budget_category'):
            qs = qs.filter(budget_category_id=b_cat)

        # Filter by grouping
        grp = params.get('grouping')
        if grp and hasattr(self.queryset.model, 'grouping'):
            qs = qs.filter(grouping_id=grp)

        # Filter by budget
        b_id = params.get('budget')
        if b_id and hasattr(self.queryset.model, 'budget'):
            qs = qs.filter(budget_id=b_id)

        return qs.order_by(*self.ordering)

    def perform_create(self, s):
        s.save(user=self.request.user) if self.owner == 'user' else s.save()

    @action(detail=True, methods=['post', 'patch'])
    def deactivate(self, request, pk=None):
        instance = self.get_object()
        if hasattr(instance, 'is_active'):
            instance.is_active = False
            instance.save()
            return Response(self.get_serializer(instance).data)
        return Response({'error': 'Object has no is_active attribute'}, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=True, methods=['post', 'patch'])
    def activate(self, request, pk=None):
        instance = self.get_object()
        if hasattr(instance, 'is_active'):
            if isinstance(instance, Transaction) and instance.spent_category:
                dup = Transaction.objects.filter(
                    user=instance.user,
                    transaction_date=instance.transaction_date,
                    spent_category=instance.spent_category,
                    is_active=True
                ).exclude(pk=instance.pk).exists()
                if dup:
                    cat_name = getattr(instance.spent_category, 'name', str(instance.spent_category))
                    return Response(
                        {'error': f'Cannot activate: an active transaction for "{cat_name}" on {instance.transaction_date} already exists.'},
                        status=status.HTTP_400_BAD_REQUEST
                    )
            instance.is_active = True
            instance.save()
            return Response(self.get_serializer(instance).data)
        return Response({'error': 'Object has no is_active attribute'}, status=status.HTTP_400_BAD_REQUEST)


def vs(model, ser, **attrs):
    return type(model.__name__ + 'ViewSet', (OwnedViewSet,), {'queryset': model.objects.all(), 'serializer_class': ser, **attrs})


class AccountViewSet(OwnedViewSet):
    queryset = Account.objects.all()
    serializer_class = AccountSerializer
    ordering = ('is_archived', '-is_default', 'name')

    def get_queryset(self):
        qs = super().get_queryset()
        params = self.request.query_params

        # For detail routes (actions on a specific account id), do not filter out archived accounts
        if self.action != 'list':
            return qs

        # ?archived=true: only archived accounts
        archived_param = params.get('archived')
        if archived_param is not None:
            val = archived_param.lower() in ('true', '1')
            qs = qs.filter(is_archived=val)
        else:
            # By default in list view, exclude archived accounts unless ?include_archived=true
            include_archived = params.get('include_archived')
            if include_archived not in ('true', '1'):
                qs = qs.filter(is_archived=False)

        # Filter by kind ?kind=mpesa
        kind = params.get('kind')
        if kind:
            qs = qs.filter(kind=kind)

        # Filter by parent ?parent=null or ?parent=12
        parent = params.get('parent')
        if parent == 'null':
            qs = qs.filter(parent__isnull=True)
        elif parent:
            qs = qs.filter(parent_id=parent)

        return qs

    @action(detail=True, methods=['post', 'patch'])
    def set_default(self, request, pk=None):
        account = self.get_object()
        Account.objects.filter(user=request.user).update(is_default=False)
        account.is_default = True
        account.save(update_fields=['is_default'])
        return Response(self.get_serializer(account).data)

    @action(detail=True, methods=['post', 'patch'])
    def archive(self, request, pk=None):
        account = self.get_object()
        account.is_archived = True
        if account.is_default:
            account.is_default = False
            # Designate another active account as default if one exists
            other = Account.objects.filter(user=request.user, is_archived=False).exclude(pk=account.pk).first()
            if other:
                other.is_default = True
                other.save(update_fields=['is_default'])
        account.save()
        return Response(self.get_serializer(account).data)

    @action(detail=True, methods=['post', 'patch'])
    def unarchive(self, request, pk=None):
        account = self.get_object()
        account.is_archived = False
        account.save(update_fields=['is_archived'])
        return Response(self.get_serializer(account).data)

    @action(detail=True, methods=['post'])
    def reconcile(self, request, pk=None):
        from decimal import Decimal
        account = self.get_object()
        actual_balance = request.data.get('actual_balance')
        if actual_balance is None:
            return Response({'error': 'actual_balance is required.'}, status=status.HTTP_400_BAD_REQUEST)
        try:
            actual = Decimal(str(actual_balance))
        except Exception:
            return Response({'error': 'Invalid actual_balance amount.'}, status=status.HTTP_400_BAD_REQUEST)

        current = account.balance
        diff = actual - current
        reconcile_date = request.data.get('date') or timezone.localdate()
        notes = request.data.get('notes') or ''

        if diff == 0:
            return Response({
                'message': 'Account balance matches actual balance. No adjustment needed.',
                'difference': 0,
                'balance': float(current),
                'account': self.get_serializer(account).data
            })

        adj_type = 'credit' if diff > 0 else 'debit'
        amt = abs(diff)
        desc = notes or f"Balance Adjustment ({'+' if diff > 0 else '-'}{amt} reconciled to {actual})"

        tx = Transaction.objects.create(
            user=request.user,
            account=account,
            kind='adjustment',
            adjustment_type=adj_type,
            amount=amt,
            transaction_date=reconcile_date,
            description=desc,
            is_active=True
        )

        account.refresh_from_db()
        return Response({
            'message': f"Account successfully reconciled. Silent adjustment of {diff:+f} recorded.",
            'difference': float(diff),
            'balance': float(account.balance),
            'transaction': TransactionSerializer(tx, context={'request': request}).data,
            'account': self.get_serializer(account).data
        }, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=['get'])
    def insights(self, request, pk=None):
        account = self.get_object()
        today = timezone.localdate()
        month = request.query_params.get('month') or today.strftime('%Y-%m')
        timeframe = request.query_params.get('timeframe', 'month')

        try:
            y, m = map(int, month.split('-'))
        except ValueError:
            y, m = today.year, today.month

        # Outgoing transactions where account=account
        tx_out = account.transactions.filter(is_active=True)
        # Incoming transactions where to_account=account
        tx_in = account.incoming.filter(is_active=True, kind='transfer')

        if timeframe == 'month':
            tx_out_period = tx_out.filter(transaction_date__year=y, transaction_date__month=m)
            tx_in_period = tx_in.filter(transaction_date__year=y, transaction_date__month=m)
        else:
            tx_out_period = tx_out
            tx_in_period = tx_in

        f = lambda qs, field='amount': float(qs.aggregate(t=Sum(field))['t'] or 0)

        # Inflow
        income_amt = f(tx_out_period.filter(kind='income'))
        transfers_in_amt = f(tx_in_period)
        adj_credit_amt = f(tx_out_period.filter(kind='adjustment', adjustment_type='credit'))
        total_inflow = income_amt + transfers_in_amt + adj_credit_amt

        # Outflow
        expenses_amt = f(tx_out_period.filter(kind='expense'))
        transfers_out_amt = f(tx_out_period.filter(kind='transfer'))
        fees_amt = f(tx_out_period.exclude(fee=0), 'fee')
        adj_debit_amt = f(tx_out_period.filter(kind='adjustment', adjustment_type='debit'))
        total_outflow = expenses_amt + transfers_out_amt + fees_amt + adj_debit_amt

        net_flow = total_inflow - total_outflow

        # Average daily spend
        if timeframe == 'month':
            if y == today.year and m == today.month:
                days_count = max(today.day, 1)
            else:
                import calendar
                days_count = calendar.monthrange(y, m)[1]
        else:
            first_tx = tx_out.order_by('transaction_date').first()
            if first_tx:
                days_count = max((today - first_tx.transaction_date).days, 1)
            else:
                days_count = 1
        avg_daily_spend = round((expenses_amt + fees_amt) / days_count, 2)

        # Top expense categories for this specific wallet
        cat_expenses = (
            tx_out_period.filter(kind='expense', spent_category__isnull=False)
            .values('spent_category__id', 'spent_category__name', 'spent_category__budget_category__name')
            .annotate(total_spent=Sum('amount'))
            .order_by('-total_spent')[:8]
        )
        total_cat_spent = expenses_amt or 1.0
        top_categories = []
        for c in cat_expenses:
            amt = float(c['total_spent'] or 0)
            pct = round((amt / total_cat_spent) * 100, 1)
            top_categories.append({
                'category_id': c['spent_category__id'],
                'name': c['spent_category__name'],
                'budget_category': c['spent_category__budget_category__name'],
                'total_spent': amt,
                'percentage': pct
            })

        # Recent transactions for this account (last 15)
        recent_qs = Transaction.objects.filter(
            models.Q(account=account) | models.Q(to_account=account),
            is_active=True
        ).order_by('-transaction_date', '-id')[:15]
        recent_txs = TransactionSerializer(recent_qs, many=True, context={'request': request}).data

        # Sub-accounts / pots breakdown
        pots = []
        for pot in account.sub_accounts.filter(is_archived=False):
            pots.append({
                'id': pot.id,
                'name': pot.name,
                'kind': pot.kind,
                'balance': float(pot.balance),
                'is_pot': pot.is_pot
            })

        return Response({
            'account': AccountSerializer(account, context={'request': request}).data,
            'timeframe': timeframe,
            'month': month,
            'inflow': {
                'income': income_amt,
                'transfers_in': transfers_in_amt,
                'adjustments_credit': adj_credit_amt,
                'total': total_inflow
            },
            'outflow': {
                'expenses': expenses_amt,
                'transfers_out': transfers_out_amt,
                'fees': fees_amt,
                'adjustments_debit': adj_debit_amt,
                'total': total_outflow
            },
            'net_flow': net_flow,
            'average_daily_spend': avg_daily_spend,
            'top_categories': top_categories,
            'recent_transactions': recent_txs,
            'pots': pots
        })


BudgetGroupCategoryViewSet = vs(BudgetGroupCategory, BudgetGroupCategorySerializer, ordering=('priority', 'name'))
BudgetCategoryViewSet = vs(BudgetCategory, BudgetCategorySerializer, ordering=('grouping__priority', 'name'))
SpentCategoryViewSet = vs(SpentCategory, SpentCategorySerializer, ordering=('name',))
CategoryViewSet = SpentCategoryViewSet  # Compatibility alias
DebtViewSet = vs(Debt, DebtSerializer)
TransactionViewSet = vs(Transaction, TransactionSerializer, date_field='transaction_date', ordering=('-transaction_date', '-id'))
BudgetViewSet = vs(Budget, BudgetSerializer, ordering=('-start_date', '-id'))
BudgetItemViewSet = vs(BudgetItem, BudgetItemSerializer, owner='budget__user', ordering=('budget_category__grouping__priority', 'budget_category__name'))


@api_view(['POST'])
@authentication_classes([])
@permission_classes([AllowAny])
def register(request):
    u, p = request.data.get('username'), request.data.get('password')
    if not u or not p or User.objects.filter(username=u).exists():
        return Response({'error': 'Username is taken or a field is missing.'}, status=400)
    user = User.objects.create_user(u, password=p)
    token = Token.objects.create(user=user)
    return Response({'token': token.key, 'username': user.username})


@api_view(['GET'])
def summary(request):
    """Monthly financial state: income -> budget -> actual -> remaining."""
    u, today = request.user, timezone.localdate()
    month = request.query_params.get('month') or today.strftime('%Y-%m')
    try:
        y, m = map(int, month.split('-'))
    except ValueError:
        y, m = today.year, today.month

    f = lambda qs: float(qs.aggregate(t=Sum('amount'))['t'] or 0)
    T = Transaction.objects.filter(user=u, is_active=True)
    inm = T.filter(transaction_date__year=y, transaction_date__month=m)
    exp = inm.filter(kind='expense')
    income = f(inm.filter(kind='income'))
    spent, debt_paid = f(exp.filter(debt__isnull=True)), f(exp.filter(debt__isnull=False))

    # Find the active budget covering today or for this month
    active_budget = Budget.objects.filter(
        user=u, start_date__year=y, start_date__month=m
    ).first()

    budget_items = []
    allocated_amount = 0.0
    total_planned = 0.0

    if active_budget:
        allocated_amount = float(active_budget.allocated_amount)
        items = active_budget.items.select_related('budget_category__grouping').order_by('budget_category__grouping__priority', 'budget_category__name')
        for item in items:
            spent_ids = item.budget_category.spent_categories.values_list('id', flat=True)
            actual = f(exp.filter(spent_category_id__in=spent_ids))
            budget_items.append({
                'id': item.id,
                'category_id': item.budget_category_id,
                'name': item.budget_category.name,
                'grouping': item.budget_category.grouping.name,
                'grouping_priority': item.budget_category.grouping.priority,
                'category_type': item.budget_category.category_type,
                'planned': float(item.amount),
                'actual': actual,
                'reason': item.reason,
            })
        total_planned = sum(b['planned'] for b in budget_items)

    fees = float(inm.exclude(fee=0).aggregate(t=Sum('fee'))['t'] or 0)
    left = income - spent - debt_paid

    # Active accounts (excluding archived)
    active_accounts = Account.objects.filter(user=u, is_archived=False)
    liquid_balance = float(sum(a.balance for a in active_accounts.filter(is_pot=False)))
    total_balance = float(sum(a.balance for a in active_accounts))
    pots_balance = float(sum(a.balance for a in active_accounts.filter(is_pot=True)))

    return Response({
        'month': month,
        'income': income,
        'spent': spent,
        'debt_paid': debt_paid,
        'fees': fees,
        'left': left,
        'allocated_budget': allocated_amount, # Inputted budget amount
        'planned': total_planned,             # Computed from budget items
        'unallocated': allocated_amount - total_planned,
        'savings_rate': round(left / income * 100, 1) if income else 0,
        'today_spent': f(T.filter(kind='expense', transaction_date=today)),
        'budget': budget_items,
        'budget_id': active_budget.id if active_budget else None,
        'budget_name': active_budget.name if active_budget else None,
        'total_balance': total_balance,
        'liquid_balance': liquid_balance,
        'pots_balance': pots_balance,
        'debt_balance': float(sum(d.balance for d in Debt.objects.filter(user=u))),
    })
