variable "prefijo" {
  type        = string
  description = "Prefijo de nombres sin guion final (campus-locator-dev, ARCHITECTURE 5.1)."
}

variable "proyecto" {
  type        = string
  description = "Nombre del proyecto (campus-locator): ruta del log group /<proyecto>/<entorno>/apigw (5.1)."
}

variable "entorno" {
  type        = string
  description = "Nombre del entorno (dev): ruta del log group (5.1)."
}

variable "subredes_publicas" {
  type        = list(string)
  description = "IDs de publica-a y publica-b (salida subredes_publicas del modulo red): subredes del VPC Link."

  validation {
    condition     = length(var.subredes_publicas) == 2
    error_message = "subredes_publicas debe tener exactamente dos subredes (publica-a y publica-b)."
  }
}

variable "sg_vpclink" {
  type        = string
  description = "ID del grupo campus-locator-dev-vpclink (salida grupos_seguridad[\"vpclink\"] del modulo red, 5.7)."
}

variable "cloud_map_api_arn" {
  type        = string
  description = "ARN del servicio de Cloud Map api (SRV, salida cloud_map_api_arn del modulo computo)."
}

variable "metrica_localize" {
  type        = object({ espacio = string, nombre = string })
  description = "Metrica de uso de POST /v1/localize que publica el filtro de metricas (campus-locator/dev, LocalizePeticiones; 5.1). La misma la recibe computo para la alarma de inactividad (INF-2.1)."
}
