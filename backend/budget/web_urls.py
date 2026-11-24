from django.urls import path
from . import web_views

urlpatterns = [
    # Authentication
    path('login/', web_views.login_view, name='login'),
    path('register/', web_views.register_view, name='register'),
    path('logout/', web_views.logout_view, name='logout'),

    # Today's Spends (default landing page)
    path('', web_views.today_view, name='today'),
    path('today/save/', web_views.today_save, name='today_save'),

    # Categories (3-tier)
    path('categories/', web_views.categories_view, name='categories'),
    path('categories/save/', web_views.categories_save, name='categories_save'),
    path('categories/<str:tier>/<int:pk>/delete/', web_views.categories_delete, name='categories_delete'),
    path('categories/<str:tier>/<int:pk>/toggle/', web_views.categories_toggle, name='categories_toggle'),

    # Dashboard
    path('dashboard/', web_views.dashboard_view, name='dashboard'),

    # Transactions
    path('transactions/', web_views.transactions_view, name='transactions'),
    path('transactions/add/', web_views.transactions_add, name='transactions_add'),
    path('transactions/<int:pk>/toggle/', web_views.transactions_toggle, name='transactions_toggle'),
    path('transactions/<int:pk>/delete/', web_views.transactions_delete, name='transactions_delete'),

    # Accounts
    path('accounts/', web_views.accounts_view, name='accounts'),
    path('accounts/save/', web_views.accounts_save, name='accounts_save'),
    path('accounts/transfer/', web_views.accounts_transfer, name='accounts_transfer'),
    path('accounts/<int:pk>/reconcile/', web_views.accounts_reconcile, name='accounts_reconcile'),
    path('accounts/<int:pk>/set-default/', web_views.accounts_set_default, name='accounts_set_default'),
    path('accounts/<int:pk>/archive/', web_views.accounts_archive, name='accounts_archive'),
    path('accounts/<int:pk>/unarchive/', web_views.accounts_unarchive, name='accounts_unarchive'),
    path('accounts/<int:pk>/delete/', web_views.accounts_delete, name='accounts_delete'),

    # Budget Plan
    path('budget/', web_views.budget_view, name='budget'),
    path('budget/save/', web_views.budget_save, name='budget_save'),
    path('budget/item/save/', web_views.budget_item_save, name='budget_item_save'),
    path('budget/item/<int:pk>/delete/', web_views.budget_item_delete, name='budget_item_delete'),

    # Debts
    path('debts/', web_views.debts_view, name='debts'),
    path('debts/add/', web_views.debts_add, name='debts_add'),
    path('debts/<int:pk>/repay/', web_views.debts_repay, name='debts_repay'),
    path('debts/<int:pk>/delete/', web_views.debts_delete, name='debts_delete'),
]
