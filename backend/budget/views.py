from django.contrib.auth.models import User
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


AccountViewSet = vs(Account, AccountSerializer)
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

    left = income - spent - debt_paid

    return Response({
        'month': month,
        'income': income,
        'spent': spent,
        'debt_paid': debt_paid,
        'left': left,
        'allocated_budget': allocated_amount, # Inputted budget amount
        'planned': total_planned,             # Computed from budget items
        'unallocated': allocated_amount - total_planned,
        'savings_rate': round(left / income * 100, 1) if income else 0,
        'today_spent': f(T.filter(kind='expense', transaction_date=today)),
        'budget': budget_items,
        'budget_id': active_budget.id if active_budget else None,
        'budget_name': active_budget.name if active_budget else None,
        'total_balance': float(sum(a.balance for a in Account.objects.filter(user=u))),
        'debt_balance': float(sum(d.balance for d in Debt.objects.filter(user=u))),
    })
