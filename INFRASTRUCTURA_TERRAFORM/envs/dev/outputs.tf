output "api_base_url" {
  description = "URL base para ApiConfig.kt / BuildConfig de la app (ARCHITECTURE 4.3). Sin dominio es el DNS del ALB en HTTP: solo para pruebas."
  value       = "${module.alb.https_enabled ? "https" : "http"}://${module.alb.dns_name}"
}

output "ecr_repository_urls" {
  description = "Donde CI sube las imágenes (backend y embedding)"
  value       = module.ecr.repository_urls
}

output "ecs_cluster_name" {
  value = module.ecs_cluster.cluster_name
}

output "dataset_bucket" {
  value = module.storage.dataset_bucket
}

output "scans_bucket" {
  value = module.storage.scans_bucket
}

output "database_host" {
  value = module.database.host
}

output "database_secret_arn" {
  description = "Secreto con el usuario y la contraseña de RDS"
  value       = module.database.secret_arn
}
