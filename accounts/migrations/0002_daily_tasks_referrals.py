import decimal
import django.utils.timezone
from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion

class Migration(migrations.Migration):
    dependencies = [('accounts', '0001_initial'), migrations.swappable_dependency(settings.AUTH_USER_MODEL)]
    operations = [
        migrations.AddField(model_name='wallet', name='referral_code', field=models.CharField(blank=True, db_index=True, max_length=16, null=True, unique=True)),
        migrations.RunPython(lambda apps, schema_editor: [apps.get_model('accounts', 'Wallet').objects.filter(pk=w.pk).update(referral_code=f'OLD{w.pk:010d}') for w in apps.get_model('accounts', 'Wallet').objects.filter(referral_code__isnull=True)], migrations.RunPython.noop),
        migrations.CreateModel(name='Referral', fields=[
            ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
            ('reward', models.DecimalField(decimal_places=2, default=decimal.Decimal('1.00'), max_digits=8)),
            ('status', models.CharField(choices=[('credited', 'Acreditado'), ('rejected', 'Rechazado')], default='credited', max_length=12)),
            ('created_at', models.DateTimeField(auto_now_add=True)), ('credited_at', models.DateTimeField(blank=True, null=True)),
            ('invited', models.OneToOneField(on_delete=django.db.models.deletion.PROTECT, related_name='referral_source', to=settings.AUTH_USER_MODEL)),
            ('inviter', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='referrals_sent', to=settings.AUTH_USER_MODEL)),
            ('transaction', models.OneToOneField(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='referral_reward', to='accounts.transaction')),
        ], options={'ordering': ['-created_at']}),
        migrations.CreateModel(name='DailyTaskClaim', fields=[
            ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
            ('task_date', models.DateField()), ('slot', models.PositiveSmallIntegerField()), ('title', models.CharField(max_length=180)),
            ('reward', models.DecimalField(decimal_places=2, max_digits=8)), ('completed_at', models.DateTimeField(auto_now_add=True)),
            ('transaction', models.OneToOneField(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='daily_task_claim', to='accounts.transaction')),
            ('user', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='daily_task_claims', to=settings.AUTH_USER_MODEL)),
        ], options={'ordering': ['task_date', 'slot']}),
        migrations.AddConstraint(model_name='dailytaskclaim', constraint=models.UniqueConstraint(fields=('user', 'task_date', 'slot'), name='unique_daily_task_claim')),
    ]
