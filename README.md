# bear.litle — frontend + backend Django

## Incluye
- Registro guardado en SQLite.
- Validación de nombre de usuario y correo únicos (sin distinguir mayúsculas/minúsculas).
- Contraseñas almacenadas con los hashers seguros de Django; nunca se guardan en texto plano.
- Inicio de sesión comprobando correo y contraseña en la base de datos.
- Sesiones de Django, endpoint de cierre de sesión y endpoint para consultar la sesión actual.
- Mensajes de error enviados al frontend cuando el usuario o el correo ya existen, el correo no está registrado o la contraseña no coincide.

## Ejecutar en Windows PowerShell

```powershell
cd bear_litle_django_backend
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python manage.py migrate
python manage.py runserver
```

Para procesar manualmente depósitos y retiros, crea un administrador con `python manage.py createsuperuser` y entra en `http://127.0.0.1:8000/admin/`.

Abre http://127.0.0.1:8000/ en el navegador. Debes usar el frontend desde Django; no abras el HTML directamente con `file://`, porque las llamadas API y las sesiones necesitan el servidor.

## Base de datos
Django crea `db.sqlite3` después de ejecutar `python manage.py migrate`. Los usuarios se almacenan en la tabla `auth_user` y las contraseñas se guardan con hash, no como texto plano.

## Importante antes de producción
- Cambia `SECRET_KEY`, desactiva `DEBUG`, configura `ALLOWED_HOSTS`, HTTPS, cookies seguras y límites de intentos de acceso.
- Configura correo de verificación y recuperación de contraseña.
- Los saldos, inversiones verificadas, recompensas de minijuegos, solicitudes de depósito y solicitudes de retiro se guardan en SQLite.
- Los depósitos se acreditan manualmente desde Django Admin al aprobar la transacción. Las solicitudes de retiro reservan el saldo y quedan pendientes para que el administrador realice el envío manual; al aprobarlas, se registra el momento de retiro para el período de 24 horas. Si se rechaza un retiro, el importe reservado se devuelve al saldo.
- El nivel VIP se activa cuando el administrador verifica inversiones acumuladas de al menos 60 USDT. El límite de retiro es hasta 20 USDT por período de 24 horas, sujeto al saldo disponible; no se generan automáticamente ganancias diarias. El nivel básico tiene un límite de 2 USDT por período de 24 horas.
- El sistema no comprueba automáticamente la blockchain ni envía criptomonedas: la revisión y los pagos son manuales. Verifica cada TXID y la red BEP20 antes de aprobar un depósito.


## Depósitos y retiros con notificación al administrador
- La pantalla Invertir muestra el importe de solicitud (10 USDT iniciales; desde VIP puede seleccionarse 60 USDT), la wallet receptora y un botón de notificación. El usuario no necesita pegar el TXID para enviar la notificación; el administrador debe comprobar la transferencia directamente en el explorador de la red.
- Cada solicitud de depósito envía un correo con ID, nombre, email, importe declarado, fecha y dirección. Las solicitudes de retiro también notifican al administrador.
- Las solicitudes muestran un plazo de revisión de 2 horas. El panel de Django impide aprobar retiros antes de que pasen 2 horas. Los depósitos se acreditan solamente al aprobarlos manualmente; el administrador puede editar el importe pendiente del depósito tras comprobar el pago real.
- Configura Gmail mediante variables de entorno. Usa una contraseña de aplicación, no la contraseña habitual de tu cuenta. En PowerShell, antes de iniciar Django:

```powershell
$env:EMAIL_BACKEND="django.core.mail.backends.smtp.EmailBackend"
$env:EMAIL_HOST_USER="tu-cuenta@gmail.com"
$env:EMAIL_HOST_PASSWORD="tu-contrasena-de-aplicacion-google"
$env:DEFAULT_FROM_EMAIL="tu-cuenta@gmail.com"
$env:ADMIN_NOTIFICATION_EMAIL="correo-que-recibira-las-alertas@gmail.com"
python manage.py runserver
```

Si no configuras SMTP, los correos se escriben en la consola de Django y no se envían por Internet. No subas estas variables ni las credenciales al repositorio. En producción configura HTTPS, una `SECRET_KEY` privada, `DEBUG=0` y una base de datos respaldada.
