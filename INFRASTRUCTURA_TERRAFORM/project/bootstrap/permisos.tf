# Permisos de los roles de GitHub Actions (ARCHITECTURE §5.8 y §4, fila INF-0.1).
#   gha-terraform-plan  PR: solo lectura (también de los secretos de dev, que ya están en el estado que lee); del
#                       bucket de estado solo escribe el bloqueo de dev.
#   gha-terraform       apply aprobado: amplio pero acotado a la cuenta y a la región. En IAM solo gestiona roles y
#                       políticas campus-locator-*, y todo rol que crea lleva el permissions boundary
#                       campus-locator-limite-roles: ningún rol nuevo puede tener más permisos que el propio apply.
#   gha-deploy          main: publicar imágenes, registrar definiciones de tarea, actualizar servicios y lanzar migrate.
# Los ARN de recursos que aún no existen (ECR, ECS, logs, secretos) se escriben por nombre: los crean INF-1.x.

locals {
  cuenta            = var.aws_account_id
  prefijo           = "${var.proyecto}-${var.entorno}"
  arn_bucket_estado = aws_s3_bucket.estado.arn
  clave_bloqueo     = "${var.entorno}/terraform.tfstate.tflock"
  arn_cluster       = "arn:aws:ecs:${var.region}:${local.cuenta}:cluster/${local.prefijo}"

  # Servicios globales (o con endpoint fijo) que quedan fuera de la restricción de región.
  servicios_globales = [
    "account:*",
    "budgets:*",
    "ce:*",
    "cloudfront:*",
    "cur:*",
    "globalaccelerator:*",
    "health:*",
    "iam:*",
    "organizations:*",
    "pricing:*",
    "route53:*",
    "route53domains:*",
    "s3:GetBucketLocation",
    "s3:ListAllMyBuckets",
    "sts:*",
    "support:*",
    "trustedadvisor:*",
    "waf:*",
  ]
}

# ---------------------------------------------------------------------------------------------------------------------
# Protecciones comunes: las aplica gha-terraform y el boundary de los roles que crea (riesgo R5)
# ---------------------------------------------------------------------------------------------------------------------

data "aws_iam_policy_document" "protecciones" {
  statement {
    sid         = "SoloLaRegionDelProyecto"
    effect      = "Deny"
    not_actions = local.servicios_globales
    resources   = ["*"]

    condition {
      test     = "StringNotEquals"
      variable = "aws:RequestedRegion"
      values   = [var.region]
    }
  }

  # El bucket de estado y su historial solo los gestiona bootstrap, con el administrador.
  statement {
    sid    = "BucketDeEstadoProtegido"
    effect = "Deny"
    actions = [
      "s3:DeleteBucket",
      "s3:DeleteBucketPolicy",
      "s3:PutBucketAcl",
      "s3:PutBucketOwnershipControls",
      "s3:PutBucketPolicy",
      "s3:PutBucketPublicAccessBlock",
      "s3:PutBucketVersioning",
      "s3:PutEncryptionConfiguration",
      "s3:PutLifecycleConfiguration",
    ]
    resources = [local.arn_bucket_estado]
  }

  statement {
    sid       = "HistorialDeEstadoProtegido"
    effect    = "Deny"
    actions   = ["s3:DeleteObjectVersion"]
    resources = ["${local.arn_bucket_estado}/*"]
  }

  statement {
    sid       = "EstadoDeBootstrapProtegido"
    effect    = "Deny"
    actions   = ["s3:PutObject", "s3:DeleteObject"]
    resources = ["${local.arn_bucket_estado}/bootstrap/*"]
  }
}

# ---------------------------------------------------------------------------------------------------------------------
# Permissions boundary obligatorio de los roles campus-locator-* que crea gha-terraform (ECS, INF-1.3)
# ---------------------------------------------------------------------------------------------------------------------

data "aws_iam_policy_document" "limite_roles" {
  source_policy_documents = [data.aws_iam_policy_document.protecciones.json]

  # Techo: todo menos identidad. Un rol con este boundary no puede tocar IAM ni asumir otros roles, así que no
  # sirve para ampliar los permisos de quien lo creó.
  statement {
    sid         = "TodoMenosIdentidad"
    not_actions = ["account:*", "iam:*", "organizations:*", "sts:AssumeRole"]
    resources   = ["*"]
  }
}

resource "aws_iam_policy" "limite_roles" {
  name        = "${var.proyecto}-limite-roles"
  description = "Permissions boundary obligatorio de los roles campus-locator-* que crea gha-terraform"
  policy      = data.aws_iam_policy_document.limite_roles.json
}

# ---------------------------------------------------------------------------------------------------------------------
# gha-terraform-plan
# ---------------------------------------------------------------------------------------------------------------------

resource "aws_iam_role_policy_attachment" "plan_lectura" {
  role       = aws_iam_role.gha["terraform_plan"].name
  policy_arn = "arn:aws:iam::aws:policy/ReadOnlyAccess"
}

data "aws_iam_policy_document" "plan_estado" {
  statement {
    sid       = "BucketDeEstado"
    actions   = ["s3:ListBucket", "s3:GetBucketLocation", "s3:GetBucketVersioning"]
    resources = [local.arn_bucket_estado]
  }

  statement {
    sid       = "LeerEstado"
    actions   = ["s3:GetObject", "s3:GetObjectVersion"]
    resources = ["${local.arn_bucket_estado}/*"]
  }

  statement {
    sid       = "SoloElBloqueoDeDev"
    actions   = ["s3:PutObject", "s3:DeleteObject"]
    resources = ["${local.arn_bucket_estado}/${local.clave_bloqueo}"]
  }

  # ReadOnlyAccess no incluye GetSecretValue y el plan lo necesita para refrescar aws_secretsmanager_secret_version
  # (INF-1.2). No amplía la exposición: esos valores ya están en dev/terraform.tfstate, que este rol lee.
  statement {
    sid       = "LeerSecretosDeDev"
    actions   = ["secretsmanager:GetSecretValue"]
    resources = ["arn:aws:secretsmanager:${var.region}:${local.cuenta}:secret:${var.proyecto}/${var.entorno}/*"]
  }
}

resource "aws_iam_role_policy" "plan_estado" {
  name   = "estado-terraform"
  role   = aws_iam_role.gha["terraform_plan"].name
  policy = data.aws_iam_policy_document.plan_estado.json
}

# ---------------------------------------------------------------------------------------------------------------------
# gha-terraform
# ---------------------------------------------------------------------------------------------------------------------

resource "aws_iam_role_policy_attachment" "terraform_power_user" {
  role       = aws_iam_role.gha["terraform"].name
  policy_arn = "arn:aws:iam::aws:policy/PowerUserAccess"
}

data "aws_iam_policy_document" "terraform_permisos" {
  statement {
    sid       = "IamLectura"
    actions   = ["iam:Get*", "iam:List*"]
    resources = ["*"]
  }

  # Crear roles o cambiar sus políticas solo si el rol lleva el boundary campus-locator-limite-roles.
  statement {
    sid = "RolesDelProyectoConLimite"
    actions = [
      "iam:AttachRolePolicy",
      "iam:CreateRole",
      "iam:DeleteRolePolicy",
      "iam:DetachRolePolicy",
      "iam:PutRolePermissionsBoundary",
      "iam:PutRolePolicy",
    ]
    resources = ["arn:aws:iam::${local.cuenta}:role/${var.proyecto}-*"]

    condition {
      test     = "StringEquals"
      variable = "iam:PermissionsBoundary"
      values   = [aws_iam_policy.limite_roles.arn]
    }
  }

  statement {
    sid = "RolesDelProyecto"
    actions = [
      "iam:DeleteRole",
      "iam:PassRole",
      "iam:TagRole",
      "iam:UntagRole",
      "iam:UpdateAssumeRolePolicy",
      "iam:UpdateRole",
      "iam:UpdateRoleDescription",
    ]
    resources = ["arn:aws:iam::${local.cuenta}:role/${var.proyecto}-*"]
  }

  statement {
    sid = "PoliticasDelProyecto"
    actions = [
      "iam:CreatePolicy",
      "iam:CreatePolicyVersion",
      "iam:DeletePolicy",
      "iam:DeletePolicyVersion",
      "iam:SetDefaultPolicyVersion",
      "iam:TagPolicy",
      "iam:UntagPolicy",
    ]
    resources = ["arn:aws:iam::${local.cuenta}:policy/${var.proyecto}-*"]
  }

  statement {
    sid       = "BucketDeEstado"
    actions   = ["s3:ListBucket", "s3:GetBucketLocation", "s3:GetBucketVersioning"]
    resources = [local.arn_bucket_estado]
  }

  statement {
    sid       = "ObjetosDeEstado"
    actions   = ["s3:GetObject", "s3:PutObject", "s3:DeleteObject"]
    resources = ["${local.arn_bucket_estado}/*"]
  }
}

resource "aws_iam_role_policy" "terraform_permisos" {
  name   = "iam-y-estado"
  role   = aws_iam_role.gha["terraform"].name
  policy = data.aws_iam_policy_document.terraform_permisos.json
}

# Denegaciones explícitas: ganan sobre PowerUserAccess y sobre cualquier Allow.
data "aws_iam_policy_document" "terraform_limites" {
  source_policy_documents = [data.aws_iam_policy_document.protecciones.json]

  # Los roles de GitHub solo los cambia bootstrap (con el administrador).
  statement {
    sid         = "RolesDeGitHubIntocables"
    effect      = "Deny"
    not_actions = ["iam:Get*", "iam:List*"]
    resources   = ["arn:aws:iam::${local.cuenta}:role/${var.proyecto}-gha-*"]
  }

  # El boundary no se puede quitar de un rol ni editar.
  statement {
    sid       = "BoundarySinQuitar"
    effect    = "Deny"
    actions   = ["iam:DeleteRolePermissionsBoundary"]
    resources = ["*"]
  }

  statement {
    sid    = "BoundaryIntocable"
    effect = "Deny"
    actions = [
      "iam:CreatePolicyVersion",
      "iam:DeletePolicy",
      "iam:DeletePolicyVersion",
      "iam:SetDefaultPolicyVersion",
      "iam:TagPolicy",
      "iam:UntagPolicy",
    ]
    resources = [aws_iam_policy.limite_roles.arn]
  }

  # Terraform no necesita asumir roles; así no puede saltar a un rol que confíe en la cuenta entera.
  statement {
    sid       = "SinAsumirOtrosRoles"
    effect    = "Deny"
    actions   = ["sts:AssumeRole"]
    resources = ["*"]
  }
}

resource "aws_iam_role_policy" "terraform_limites" {
  name   = "limites"
  role   = aws_iam_role.gha["terraform"].name
  policy = data.aws_iam_policy_document.terraform_limites.json
}

# ---------------------------------------------------------------------------------------------------------------------
# gha-deploy
# ---------------------------------------------------------------------------------------------------------------------

data "aws_iam_policy_document" "deploy" {
  statement {
    sid       = "EcrLogin"
    actions   = ["ecr:GetAuthorizationToken"]
    resources = ["*"]
  }

  statement {
    sid = "EcrPublicar"
    actions = [
      "ecr:BatchCheckLayerAvailability",
      "ecr:BatchGetImage",
      "ecr:CompleteLayerUpload",
      "ecr:GetDownloadUrlForLayer",
      "ecr:InitiateLayerUpload",
      "ecr:PutImage",
      "ecr:UploadLayerPart",
    ]
    resources = [
      "arn:aws:ecr:${var.region}:${local.cuenta}:repository/${var.proyecto}/backend",
      "arn:aws:ecr:${var.region}:${local.cuenta}:repository/${var.proyecto}/embedding",
    ]
  }

  # RegisterTaskDefinition y DescribeTaskDefinition no admiten permisos por recurso.
  statement {
    sid       = "EcsDefinicionesDeTarea"
    actions   = ["ecs:RegisterTaskDefinition", "ecs:DescribeTaskDefinition"]
    resources = ["*"]
  }

  statement {
    sid       = "EcsServicios"
    actions   = ["ecs:UpdateService", "ecs:DescribeServices"]
    resources = ["arn:aws:ecs:${var.region}:${local.cuenta}:service/${local.prefijo}/*"]
  }

  statement {
    sid       = "EcsLanzarMigrate"
    actions   = ["ecs:RunTask"]
    resources = ["arn:aws:ecs:${var.region}:${local.cuenta}:task-definition/${local.prefijo}-migrate:*"]

    condition {
      test     = "ArnEquals"
      variable = "ecs:cluster"
      values   = [local.arn_cluster]
    }
  }

  statement {
    sid       = "EcsTareas"
    actions   = ["ecs:DescribeTasks"]
    resources = ["arn:aws:ecs:${var.region}:${local.cuenta}:task/${local.prefijo}/*"]
  }

  statement {
    sid     = "PasarRolesDeTarea"
    actions = ["iam:PassRole"]
    resources = [
      "arn:aws:iam::${local.cuenta}:role/${local.prefijo}-ecs-ejecucion",
      "arn:aws:iam::${local.cuenta}:role/${local.prefijo}-tarea-*",
    ]

    condition {
      test     = "StringEquals"
      variable = "iam:PassedToService"
      values   = ["ecs-tasks.amazonaws.com"]
    }
  }

  statement {
    sid       = "LogDeMigrate"
    actions   = ["logs:GetLogEvents"]
    resources = ["arn:aws:logs:${var.region}:${local.cuenta}:log-group:/${var.proyecto}/${var.entorno}/migrate:log-stream:*"]
  }
}

resource "aws_iam_role_policy" "deploy" {
  name   = "despliegue"
  role   = aws_iam_role.gha["deploy"].name
  policy = data.aws_iam_policy_document.deploy.json
}
