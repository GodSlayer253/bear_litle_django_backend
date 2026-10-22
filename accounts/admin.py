from django.contrib import admin, messages
from django.db import transaction
from django.utils import timezone
from datetime import timedelta
from decimal import Decimal
from .models import Wallet, Transaction, GameSession, Referral, DailyTaskClaim

@admin.register(Wallet)
class WalletAdmin(admin.ModelAdmin):
    list_display = ('user', 'balance', 'total_invested', 'vip_active', 'last_withdrawal_at')
    search_fields = ('user__username', 'user__email')
    list_filter = ('vip_active',)
    readonly_fields = ('created_at',)

@admin.register(Transaction)
class TransactionAdmin(admin.ModelAdmin):
    list_display = ('id', 'user', 'user_email', 'kind', 'amount', 'status', 'created_at', 'review_available_at')
    list_filter = ('kind', 'status', 'created_at')
    search_fields = ('user__username', 'user__email', 'txid', 'destination')
    readonly_fields = ('user', 'kind', 'status', 'txid', 'destination', 'description', 'created_at', 'reviewed_at')
    actions = ('approve_selected', 'reject_selected')
    ordering = ('status', '-created_at')

    @admin.display(description='Correo del usuario')
    def user_email(self, obj):
        return obj.user.email

    @admin.display(description='Puede procesarse desde')
    def review_available_at(self, obj):
        if obj.status != Transaction.Status.PENDING or obj.kind not in (Transaction.Kind.DEPOSIT, Transaction.Kind.WITHDRAWAL):
            return '—'
        return timezone.localtime(obj.created_at + timedelta(hours=2)).strftime('%Y-%m-%d %H:%M:%S')

    def get_readonly_fields(self, request, obj=None):
        fields = list(super().get_readonly_fields(request, obj))
        # El administrador puede corregir el importe de un depósito pendiente según el monto verificado.
        # El importe de un retiro queda fijo para evitar desajustar el saldo reservado.
        if obj and obj.kind == Transaction.Kind.WITHDRAWAL:
            fields.append('amount')
        if obj and obj.status != Transaction.Status.PENDING:
            fields.append('amount')
            fields.append('status')
        return tuple(fields)

    def save_model(self, request, obj, form, change):
        if obj.kind == Transaction.Kind.DEPOSIT and obj.amount < Decimal('10.00'):
            messages.error(request, 'El importe de depósito aprobado debe ser de al menos 10 USDT.')
            if change:
                old = Transaction.objects.get(pk=obj.pk)
                obj.amount = old.amount
            else:
                obj.amount = Decimal('10.00')
        super().save_model(request, obj, form, change)

    @admin.action(description='Aprobar depósitos / confirmar retiros manuales')
    def approve_selected(self, request, queryset):
        approved = 0
        skipped = 0
        for item in queryset.select_related('user'):
            with transaction.atomic():
                tx = Transaction.objects.select_for_update().get(pk=item.pk)
                if tx.status != Transaction.Status.PENDING:
                    skipped += 1
                    continue
                if tx.kind == Transaction.Kind.WITHDRAWAL and timezone.now() < tx.created_at + timedelta(hours=2):
                    skipped += 1
                    continue
                wallet, _ = Wallet.objects.select_for_update().get_or_create(user=tx.user)
                if tx.kind == Transaction.Kind.DEPOSIT:
                    if tx.amount < Decimal('10.00'):
                        skipped += 1
                        continue
                    wallet.balance += tx.amount
                    wallet.total_invested += tx.amount
                    wallet.vip_active = wallet.total_invested >= Decimal('60.00')
                    wallet.save(update_fields=['balance', 'total_invested', 'vip_active'])
                elif tx.kind == Transaction.Kind.WITHDRAWAL:
                    wallet.last_withdrawal_at = timezone.now()
                    wallet.save(update_fields=['last_withdrawal_at'])
                tx.status = Transaction.Status.APPROVED
                tx.reviewed_at = timezone.now()
                tx.save(update_fields=['status', 'reviewed_at'])
                approved += 1
        if approved:
            self.message_user(request, f'{approved} movimiento(s) procesado(s).', messages.SUCCESS)
        if skipped:
            self.message_user(request, f'{skipped} movimiento(s) omitido(s): no está pendiente, el depósito no cumple el mínimo o el retiro aún no cumple las 2 horas.', messages.WARNING)

    @admin.action(description='Rechazar solicitudes pendientes (devolver saldo reservado de retiros)')
    def reject_selected(self, request, queryset):
        rejected = 0
        for item in queryset.select_related('user'):
            with transaction.atomic():
                tx = Transaction.objects.select_for_update().get(pk=item.pk)
                if tx.status != Transaction.Status.PENDING:
                    continue
                if tx.kind == Transaction.Kind.WITHDRAWAL:
                    wallet, _ = Wallet.objects.select_for_update().get_or_create(user=tx.user)
                    wallet.balance += tx.amount
                    wallet.save(update_fields=['balance'])
                tx.status = Transaction.Status.REJECTED
                tx.reviewed_at = timezone.now()
                tx.save(update_fields=['status', 'reviewed_at'])
                rejected += 1
        self.message_user(request, f'{rejected} solicitud(es) rechazada(s).', messages.WARNING)

@admin.register(GameSession)
class GameSessionAdmin(admin.ModelAdmin):
    list_display = ('user', 'game_type', 'reward', 'wait_seconds', 'started_at', 'claimed_at')
    list_filter = ('game_type', 'claimed_at')
    search_fields = ('user__username', 'user__email')


@admin.register(Referral)
class ReferralAdmin(admin.ModelAdmin):
    list_display = ('invited', 'inviter', 'reward', 'status', 'created_at', 'credited_at')
    search_fields = ('invited__username', 'invited__email', 'inviter__username', 'inviter__email')
    list_filter = ('status', 'created_at')
    readonly_fields = ('inviter', 'invited', 'reward', 'status', 'created_at', 'credited_at', 'transaction')

@admin.register(DailyTaskClaim)
class DailyTaskClaimAdmin(admin.ModelAdmin):
    list_display = ('user', 'task_date', 'slot', 'title', 'reward', 'completed_at')
    search_fields = ('user__username', 'user__email', 'title')
    list_filter = ('task_date',)
    readonly_fields = ('user', 'task_date', 'slot', 'title', 'reward', 'completed_at', 'transaction')
