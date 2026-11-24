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
from .services import compute_account_insights, compute_summary, reconcile_account_balance
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
        account = self.get_object()
        actual_balance = request.data.get('actual_balance')
        if actual_balance is None:
            return Response({'error': 'actual_balance is required.'}, status=status.HTTP_400_BAD_REQUEST)
        reconcile_date = request.data.get('date') or timezone.localdate()
        notes = request.data.get('notes') or ''
        try:
            tx, diff, balance = reconcile_account_balance(
                request.user, account, actual_balance, reconcile_date=reconcile_date, notes=notes
            )
        except Exception:
            return Response({'error': 'Invalid actual_balance amount.'}, status=status.HTTP_400_BAD_REQUEST)

        if tx is None:
            return Response({
                'message': 'Account balance matches actual balance. No adjustment needed.',
                'difference': 0,
                'balance': float(balance),
                'account': self.get_serializer(account).data
            })

        return Response({
            'message': f"Account successfully reconciled. Silent adjustment of {diff:+f} recorded.",
            'difference': float(diff),
            'balance': float(balance),
            'transaction': TransactionSerializer(tx, context={'request': request}).data,
            'account': self.get_serializer(account).data
        }, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=['get'])
    def insights(self, request, pk=None):
        account = self.get_object()
        today = timezone.localdate()
        month = request.query_params.get('month') or today.strftime('%Y-%m')
        timeframe = request.query_params.get('timeframe', 'month')
        data = compute_account_insights(account, month_str=month, timeframe=timeframe)
        recent_txs = TransactionSerializer(data.pop('recent_qs'), many=True, context={'request': request}).data
        data['inflow'].pop('pct', None)
        data['outflow'].pop('pct', None)

        return Response({
            'account': AccountSerializer(account, context={'request': request}).data,
            **data,
            'recent_transactions': recent_txs,
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
    data = compute_summary(request.user, request.query_params.get('month'))
    for b in data['budget']:
        b.pop('remaining', None)
        b.pop('pct', None)
        b.pop('is_over', None)
    return Response(data)
