from decimal import Decimal
from django.conf import settings
from django.db import models
from django.utils import timezone

class Wallet(models.Model):
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='wallet')
    balance = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal('0.00'))
    total_invested = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal('0.00'))
    vip_active = models.BooleanField(default=False)
    last_withdrawal_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f'{self.user.username} — {self.balance} USDT'

class Transaction(models.Model):
    class Kind(models.TextChoices):
        DEPOSIT = 'deposit', 'Depósito'
        WITHDRAWAL = 'withdrawal', 'Retiro'
        GAME_REWARD = 'game_reward', 'Recompensa de minijuego'
    class Status(models.TextChoices):
        PENDING = 'pending', 'Pendiente'
        APPROVED = 'approved', 'Aprobado'
        REJECTED = 'rejected', 'Rechazado'
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='transactions')
    kind = models.CharField(max_length=20, choices=Kind.choices)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING)
    amount = models.DecimalField(max_digits=14, decimal_places=2)
    txid = models.CharField(max_length=150, blank=True)
    destination = models.CharField(max_length=150, blank=True)
    description = models.CharField(max_length=240, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    reviewed_at = models.DateTimeField(null=True, blank=True)
    def __str__(self):
        return f'{self.user.username} · {self.get_kind_display()} · {self.amount} USDT · {self.status}'

class GameSession(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='game_sessions')
    game_type = models.CharField(max_length=30)
    question = models.CharField(max_length=200)
    answer = models.CharField(max_length=100)
    reward = models.DecimalField(max_digits=6, decimal_places=2, default=Decimal('0.05'))
    wait_seconds = models.PositiveSmallIntegerField(default=10)
    started_at = models.DateTimeField(default=timezone.now)
    claimed_at = models.DateTimeField(null=True, blank=True)
    def __str__(self):
        return f'{self.user.username} · {self.game_type} · {self.started_at:%Y-%m-%d %H:%M}'
