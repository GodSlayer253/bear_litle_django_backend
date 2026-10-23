from django.contrib import admin
from django.urls import path
from accounts import views
from accounts import admin_dashboard

urlpatterns = [
    path("admin/", admin.site.urls),
    path("gestion/login/", admin_dashboard.admin_login, name="admin_login"),
    path("gestion/logout/", admin_dashboard.admin_logout, name="admin_logout"),
    path("gestion/", admin_dashboard.dashboard, name="admin_dashboard"),
    path("gestion/usuarios/<int:user_id>/", admin_dashboard.user_detail, name="admin_user_detail"),
    path("gestion/movimientos/<int:transaction_id>/revisar/", admin_dashboard.review_transaction, name="admin_review_transaction"),
    path("", views.home, name="home"),
    path("api/register/", views.register, name="register"),
    path("api/login/", views.login_view, name="login"),
    path("api/logout/", views.logout_view, name="logout"),
    path("api/me/", views.me, name="me"),
    path("api/account/", views.account_state, name="account_state"),
    path("api/deposit/", views.deposit_request, name="deposit_request"),
    path("api/withdraw/", views.withdraw_request, name="withdraw_request"),
    path("api/tasks/", views.daily_tasks, name="daily_tasks"),
    path("api/tasks/claim/", views.daily_task_claim, name="daily_task_claim"),
    path("api/game/start/", views.game_start, name="game_start"),
    path("api/game/claim/", views.game_claim, name="game_claim"),
]
