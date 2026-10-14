# INFRASTRUCTURA_TERRAFORM

Infraestructura de Campus Locator en AWS con Terraform. **Todo el detalle está en `ARCHITECTURE.md`**:
plan y decisiones (secciones 1–10), catálogo del código existente (sección 11) y pendientes y riesgos (sección 12).
Este README es solo un resumen de pasos.

**Estado:** fases 0 a 3 escritas para `dev`. **Ninguna ha sido validada con `terraform validate` ni aplicada**:
el entorno donde se escribió no tenía Terraform instalado. Ejecuta los pasos de abajo en tu máquina.

## Requisitos

- Terraform >= 1.10 (state con `use_lockfile`)
- AWS CLI con credenciales de una cuenta de pruebas
- Proyecto en una carpeta **local** (no en Google Drive)

## 1. Bootstrap (una sola vez)

```bash
cd bootstrap
cp terraform.tfvars.example terraform.tfvars   # editar bucket y repositorio de GitHub
terraform init
terraform apply
terraform output state_bucket
```

Copia el nombre del bucket a `envs/dev/backend.tf`.

## 2. Ambiente dev

```bash
cd envs/dev
terraform init
terraform fmt -recursive ../..
terraform validate
terraform plan
terraform apply
```

Sube `.terraform.lock.hcl` a Git.

## 3. Después del primer apply

1. **Imágenes:** los servicios ECS arrancan apuntando a `<ecr>/backend:latest` y `<ecr>/embedding:latest`.
   Hasta que CI (o tú) suba una imagen, las tareas no arrancan. Con el disjuntor de despliegue activado
   verás el servicio reintentando; es lo esperado.
2. **pgvector:** Terraform crea la base pero **no** puede ejecutar SQL desde fuera de la VPC. Ejecuta una vez
   `CREATE EXTENSION IF NOT EXISTS vector;` (por ejemplo en la primera migración de Alembic del backend).
   Las credenciales están en el secreto de `database_secret_arn`.
3. **HTTPS:** sin `certificate_arn` el ALB solo escucha en HTTP y la app Android lo bloqueará. Define el dominio
   (decisión 9.3), crea el certificado en ACM y pásalo en `terraform.tfvars` (fase 4).
4. **Presupuesto:** descomenta `budget_alert_email` en `terraform.tfvars`.

## Interruptor de apagado

```bash
scripts/dev-apagar.sh            # backend y embedding a 0 tareas
scripts/dev-apagar.sh --con-bd   # y detiene RDS (se reinicia sola a los 7 días)
scripts/dev-encender.sh          # enciende (arranca RDS si hace falta)
```

El ALB sigue cobrando aunque esté apagado (ver `ARCHITECTURE.md`, 11.5 y 12.6).

## Decisiones tomadas por defecto (confirmar)

| Decisión | Valor usado |
|---|---|
| 9.2 Región | `us-east-1` |
| 9.4 DINOv2 | CPU, `dinov2_vitb14` (medio), 2 vCPU / 4 GB |
| 9.5 Vectores | `pgvector` en el mismo RDS |
| 9.7 NAT | Sin NAT en dev: tareas en subredes públicas con SG cerrados |
| 9.3 Dominio | Pendiente: ALB en HTTP solo para pruebas |

## Pendiente

Fases 4 a 8: `dns_cert`, workflows de GitHub Actions, `observability`, `envs/prod`, GPU opcional.
