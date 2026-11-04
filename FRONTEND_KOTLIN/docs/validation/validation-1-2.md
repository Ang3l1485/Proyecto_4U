# Validación 1-2 — FE-1.2 Login contra el backend

| Campo | Valor |
|---|---|
| Lote | `FE-1.2` — criterios en [`PLAN.md`](../PLAN.md) §2.2 |
| Script | `project/src/ops/validate12.py` |
| Entornos | `dev` con dispositivo físico (C3 y C4 son pruebas en la JVM: también corren en `local`) |
| Criterios | Automáticos: C1, C2, C3, C4 · Manuales: ninguno |

Contrato común de los validadores: `INFRASTRUCTURA_TERRAFORM/docs/ARCHITECTURE.md` §5.11. Lo propio de esta carpeta:
`ARCHITECTURE.md` §5.11.

## 1. Precondiciones

Si alguna no se cumple, el script termina con código 2 y el lote queda `Bloqueado`.

| ID | Qué debe cumplirse | Cómo lo comprueba el script |
|---|---|---|
| P1 | `FE-1.1` en «Hecho»: la app usa la API de `dev` | Fila de `FE-1.1` en `PLAN.md` §3 = `Hecho`, `ApiConfig.kt` contiene `VALIDACION_API_URL` y `GET {VALIDACION_API_URL}/health` responde 200 |
| P2 | `BE-1.3` en «Hecho»: login con JWT | `POST /v1/auth/login` con `VALIDACION_ADMIN_CORREO` y `VALIDACION_ADMIN_PASSWORD` responde 200 con `token`, `expira_en` y `usuario.rol = "admin"` (sin las variables o con `401`: código 3) |
| P3 | Acceso a AWS para crear la cuenta `user` de prueba, como los validadores del backend (backend §5.11) | `aws sts get-caller-identity` con `AWS_PROFILE` devuelve la cuenta `648617469176` |
| P4 | Dispositivo físico conectado | `adb devices` muestra uno en estado `device` (el de `ANDROID_SERIAL` si hay varios) y `adb shell getprop ro.kernel.qemu` no devuelve `1` |
| P5 | Gradle listo | `./gradlew --version` termina con 0 |

## 2. Comprobaciones automáticas

| ID | Qué hace el script | Pasa si |
|---|---|---|
| C1 | Instala el APK (`./gradlew installDebug`), concede `CAMERA`, `RECORD_AUDIO` y `ACTIVITY_RECOGNITION` (`Permisos.INICIALES`) con `adb shell pm grant`, reinicia la app (`am force-stop` y `am start -n com.example.myapplication/.MainActivity`), toca «Acceso administrador», escribe correo y contraseña del admin en los dos campos con `adb shell input text` (escapados, sin imprimirlos) y toca «Iniciar sesión»; lee la pantalla con `adb shell uiautomator dump` | En ≤ 15 s aparecen «Cerrar sesión» y «Hola, <primer nombre de `usuario.nombre`>» del Panel (7.2) |
| C2 | Igual que C1, tras otro `am force-stop`, con la cuenta `validacion+user@campus.edu.co` de §4 | Aparece el banner «Sin permisos» y no aparece «Cerrar sesión» |
| C3 | `./gradlew testDebugUnitTest --tests '*.SesionVencidaTest'` (MockWebServer devuelve `401 TOKEN_EXPIRADO`, `TOKEN_INVALIDO` y `NO_AUTENTICADO` a rutas `/v1/admin/*` y `/v1/collect/*`, y se prueba una sesión con `expira_en` pasado) | Sale con 0, ≥ 4 casos y 0 fallos (la revisión del PR confirma que cada caso comprueba `SessionManager.cerrarSesion()` y el evento `onSinSesion`, y que la sesión vencida no llama al servidor) |
| C4 | `./gradlew testDebugUnitTest --tests '*.RemoteAuthRepositoryTest'` | Sale con 0, ≥ 3 casos y 0 fallos (la revisión del PR confirma que son 200, 401 y error de red) |

## 3. Comprobaciones manuales

Ninguna: todos los criterios son automáticos.

## 4. Datos de prueba y limpieza

Crea la cuenta `validacion+user@campus.edu.co` (rol `user`, nombre `validacion-user`) con una tarea suelta de
`campus-locator-dev-migrate` y el comando
`python -m app.cli crear-usuario --correo validacion+user@campus.edu.co --nombre validacion-user --rol user`; la
contraseña es aleatoria, va en `CREAR_USUARIO_PASSWORD` y nunca se imprime. Al terminar, también si algo falló, la
desactiva. La desactiva con `desactivar-usuario`, y si una ejecución anterior la dejó, `crear-usuario` la reactiva con
una contraseña nueva (backend §5.11). En el teléfono hace `am force-stop` entre C1 y C2 y al final: `MyApp` borra la
sesión en cada arranque en frío (5.3), así que no queda ninguna abierta. No usa `pm clear`.

## 5. Cómo ejecutarlo

```bash
cd FRONTEND_KOTLIN/project
uv run --group ops python src/ops/validate12.py --entorno dev
```

Variables: `VALIDACION_API_URL`, `VALIDACION_ADMIN_CORREO`, `VALIDACION_ADMIN_PASSWORD` (`ARCHITECTURE.md` §5.11),
`AWS_PROFILE` (cuenta `user`) y `ANDROID_SERIAL` si hay varios dispositivos. Duración aproximada: 8 minutos (la
tarea suelta tarda unos 2).
