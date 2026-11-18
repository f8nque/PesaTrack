from django.urls import path, include
from rest_framework.authtoken.views import obtain_auth_token
from rest_framework.routers import DefaultRouter
from . import views

r = DefaultRouter()
r.register('accounts', views.AccountViewSet)
r.register('budget-groups', views.BudgetGroupCategoryViewSet)
r.register('budget-categories', views.BudgetCategoryViewSet)
r.register('spent-categories', views.SpentCategoryViewSet)
r.register('categories', views.CategoryViewSet, basename='legacy-categories')
r.register('budgets', views.BudgetViewSet)
r.register('budget-items', views.BudgetItemViewSet)
r.register('transactions', views.TransactionViewSet)
r.register('debts', views.DebtViewSet)

urlpatterns = [
    path('login/', obtain_auth_token),
    path('register/', views.register),
    path('summary/', views.summary),
    path('', include(r.urls)),
]
