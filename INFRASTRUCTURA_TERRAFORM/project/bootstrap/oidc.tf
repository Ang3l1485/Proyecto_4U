# Proveedor OIDC de GitHub y los tres roles de GitHub Actions, sin llaves de larga duración
# (ARCHITECTURE §3.7, §5.1 y §5.8). Los permisos de cada rol están en permisos.tf.

resource "aws_iam_openid_connect_provider" "github" {
  url            = "https://token.actions.githubusercontent.com"
  client_id_list = ["sts.amazonaws.com"]
  # Sin thumbprint_list: AWS valida token.actions.githubusercontent.com con su propia lista de CA de confianza.
}

locals {
  github_host   = "token.actions.githubusercontent.com"
  github_partes = split("/", var.github_repo)

  # Segmento «repo» del claim sub. Formato clásico: «propietario/repo». Formato inmutable (repos creados, renombrados
  # o transferidos después del 2026-07-15): «propietario@ID/repo@ID».
  github_sub_repo = var.github_ids == null ? var.github_repo : format(
    "%s@%d/%s@%d", local.github_partes[0], var.github_ids.propietario, local.github_partes[1], var.github_ids.repositorio
  )

  # Un único sub por rol, sin comodines (§5.8).
  roles_gha = {
    terraform_plan = {
      nombre      = "${var.proyecto}-gha-terraform-plan"
      sub         = "repo:${local.github_sub_repo}:pull_request"
      descripcion = "GitHub Actions: plan de Terraform en los PR (solo lectura)"
    }
    terraform = {
      nombre      = "${var.proyecto}-gha-terraform"
      sub         = "repo:${local.github_sub_repo}:environment:${var.entorno}"
      descripcion = "GitHub Actions: apply de Terraform desde el entorno ${var.entorno} (aprobacion manual, solo main)"
    }
    deploy = {
      nombre      = "${var.proyecto}-gha-deploy"
      sub         = "repo:${local.github_sub_repo}:ref:refs/heads/main"
      descripcion = "GitHub Actions: publicar imagenes y desplegar servicios desde main"
    }
  }
}

data "aws_iam_policy_document" "confianza_gha" {
  for_each = local.roles_gha

  statement {
    sid     = "GitHubOidc"
    effect  = "Allow"
    actions = ["sts:AssumeRoleWithWebIdentity"]

    principals {
      type        = "Federated"
      identifiers = [aws_iam_openid_connect_provider.github.arn]
    }

    condition {
      test     = "StringEquals"
      variable = "${local.github_host}:aud"
      values   = ["sts.amazonaws.com"]
    }

    condition {
      test     = "StringEquals"
      variable = "${local.github_host}:sub"
      values   = [each.value.sub]
    }
  }
}

resource "aws_iam_role" "gha" {
  for_each = local.roles_gha

  name               = each.value.nombre
  description        = each.value.descripcion
  assume_role_policy = data.aws_iam_policy_document.confianza_gha[each.key].json
}
