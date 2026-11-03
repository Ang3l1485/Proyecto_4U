# Encendido de embedding y escalado de worker (ARCHITECTURE §3.4, §5.1, §5.10, ADR-INF-15; INF-2.1).
#
# - Los dos servicios son objetivos de Application Auto Scaling entre 0 y 0. Terraform los crea así e ignora después
#   min_capacity y max_capacity, como desired_count (ADR-INF-09): src/ops/embedding.py encender los pone en 0-1 y
#   embedding.py apagar y las acciones de las 22:00, en 0-0.
# - embedding se apaga solo con la alarma embedding-inactivo (sin peticiones a POST /v1/localize ni mensajes en las
#   colas durante apagado_embedding.inactividad_min) y a la hora de apagado_embedding.noche.
# - worker sube a 1 con mensajes visibles en ingesta o purga, solo si embedding está corriendo (la condición va en la
#   propia alarma), y baja a 0 tras 15 min sin mensajes visibles ni en vuelo.
#
# Todas las alarmas usan periodos de 60 s y umbral 0,5 sobre una expresión que vale 0 o más. Cada política es de
# capacidad exacta y sus dos pasos cubren todos los valores (por debajo y por encima del umbral) con la misma
# capacidad: así el resultado no depende de qué muestras agregue Application Auto Scaling (con FILL, la más reciente
# suele valer 0 aunque la alarma esté en ALARM). Una política por sentido.

locals {
  escalados = toset(["embedding", "worker"])

  # Métrica que publica embedding.py encender (§5.1): cuenta como uso, así la alarma de inactividad sale de ALARM
  # antes de que embedding arranque y su ventana empieza en el encendido.
  metrica_encendidos = "EmbeddingEncendidos"

  worker_bajar_min = 15 # §5.10

  # SQS publica sus métricas cada minuto mientras la cola está activa (§5.6, ARCHITECTURE §3.4).
  metricas_colas = {
    ingesta_visibles = { cola = var.colas["ingesta"].nombre, metrica = "ApproximateNumberOfMessagesVisible" }
    ingesta_en_vuelo = { cola = var.colas["ingesta"].nombre, metrica = "ApproximateNumberOfMessagesNotVisible" }
    purga_visibles   = { cola = var.colas["purga"].nombre, metrica = "ApproximateNumberOfMessagesVisible" }
    purga_en_vuelo   = { cola = var.colas["purga"].nombre, metrica = "ApproximateNumberOfMessagesNotVisible" }
  }
  suma_colas = join(" + ", [for id in sort(keys(local.metricas_colas)) : "FILL(${id}, 0)"])

  # Alarmas de subida de worker, una por cola (§5.1).
  colas_subida = {
    ingesta = var.colas["ingesta"].nombre
    purga   = var.colas["purga"].nombre
  }
}

# ---------------------------------------------------------------------------------------------------------------------
# Objetivos escalables
# ---------------------------------------------------------------------------------------------------------------------

resource "aws_appautoscaling_target" "servicios" {
  for_each = local.escalados

  service_namespace  = "ecs"
  scalable_dimension = "ecs:service:DesiredCount"
  resource_id        = "service/${aws_ecs_cluster.principal.name}/${aws_ecs_service.servicios[each.key].name}"
  min_capacity       = 0
  max_capacity       = 0

  # embedding.py y las acciones programadas cambian el rango (ADR-INF-15); Terraform no lo devuelve a 0-0.
  lifecycle {
    ignore_changes = [min_capacity, max_capacity]
  }
}

# ---------------------------------------------------------------------------------------------------------------------
# Políticas por pasos (capacidad exacta). Los límites de los pasos se escriben como cadenas: así los guarda el
# proveedor y el plan queda vacío. Se crean una tras otra sobre cada objetivo (depends_on): Application Auto Scaling
# puede rechazar cambios simultáneos sobre el mismo objetivo y el proveedor no los reintenta.
# ---------------------------------------------------------------------------------------------------------------------

resource "aws_appautoscaling_policy" "worker_cola" {
  name               = "${var.prefijo}-worker-cola"
  policy_type        = "StepScaling"
  service_namespace  = aws_appautoscaling_target.servicios["worker"].service_namespace
  scalable_dimension = aws_appautoscaling_target.servicios["worker"].scalable_dimension
  resource_id        = aws_appautoscaling_target.servicios["worker"].resource_id

  step_scaling_policy_configuration {
    adjustment_type         = "ExactCapacity"
    cooldown                = 60
    metric_aggregation_type = "Maximum"

    step_adjustment {
      metric_interval_upper_bound = "0"
      scaling_adjustment          = 1
    }

    step_adjustment {
      metric_interval_lower_bound = "0"
      scaling_adjustment          = 1
    }
  }
}

resource "aws_appautoscaling_policy" "worker_colas_vacias" {
  name               = "${var.prefijo}-worker-colas-vacias"
  policy_type        = "StepScaling"
  service_namespace  = aws_appautoscaling_target.servicios["worker"].service_namespace
  scalable_dimension = aws_appautoscaling_target.servicios["worker"].scalable_dimension
  resource_id        = aws_appautoscaling_target.servicios["worker"].resource_id

  step_scaling_policy_configuration {
    adjustment_type         = "ExactCapacity"
    cooldown                = 60
    metric_aggregation_type = "Minimum"

    step_adjustment {
      metric_interval_upper_bound = "0"
      scaling_adjustment          = 0
    }

    step_adjustment {
      metric_interval_lower_bound = "0"
      scaling_adjustment          = 0
    }
  }

  depends_on = [aws_appautoscaling_policy.worker_cola]
}

resource "aws_appautoscaling_policy" "embedding_apagar" {
  name               = "${var.prefijo}-embedding-apagar"
  policy_type        = "StepScaling"
  service_namespace  = aws_appautoscaling_target.servicios["embedding"].service_namespace
  scalable_dimension = aws_appautoscaling_target.servicios["embedding"].scalable_dimension
  resource_id        = aws_appautoscaling_target.servicios["embedding"].resource_id

  step_scaling_policy_configuration {
    adjustment_type         = "ExactCapacity"
    cooldown                = 60
    metric_aggregation_type = "Minimum"

    step_adjustment {
      metric_interval_upper_bound = "0"
      scaling_adjustment          = 0
    }

    step_adjustment {
      metric_interval_lower_bound = "0"
      scaling_adjustment          = 0
    }
  }
}

# ---------------------------------------------------------------------------------------------------------------------
# Alarmas (§5.1, §5.10). FILL(m, 0) da 0 donde una métrica no tiene dato (una cola inactiva no publica; sin peticiones
# no hay LocalizePeticiones). «0 * <cpu>» no cambia el valor: asegura un dato por minuto mientras el servicio corre.
# ---------------------------------------------------------------------------------------------------------------------

# Sube worker a 1: mensajes visibles en la cola y embedding corriendo (CPUUtilization de ECS solo existe con tareas en
# marcha), en el mismo minuto. 1 de 10 periodos: los últimos minutos pueden no tener dato todavía (SQS y ECS publican
# con unos minutos de retraso) y valer 0 por el FILL; mientras tanto la alarma sigue invocando la subida, sin efecto.
resource "aws_cloudwatch_metric_alarm" "worker_cola" {
  for_each = local.colas_subida

  alarm_name          = "${var.prefijo}-worker-cola-${each.key}"
  alarm_description   = "Sube worker a 1 con mensajes visibles en ${each.value} y embedding corriendo (ARCHITECTURE 3.4, INF-2.1)"
  comparison_operator = "GreaterThanThreshold"
  threshold           = 0.5
  evaluation_periods  = 10
  datapoints_to_alarm = 1
  treat_missing_data  = "notBreaching"
  alarm_actions       = [aws_appautoscaling_policy.worker_cola.arn]

  metric_query {
    id          = "subir"
    expression  = "(FILL(embedding, 0) > 0) AND (FILL(visibles, 0) >= 1)"
    label       = "Mensajes visibles con embedding corriendo"
    return_data = true
  }

  metric_query {
    id = "embedding"

    metric {
      namespace   = "AWS/ECS"
      metric_name = "CPUUtilization"
      period      = 60
      stat        = "SampleCount"
      dimensions = {
        ClusterName = aws_ecs_cluster.principal.name
        ServiceName = aws_ecs_service.servicios["embedding"].name
      }
    }
  }

  metric_query {
    id = "visibles"

    metric {
      namespace   = "AWS/SQS"
      metric_name = "ApproximateNumberOfMessagesVisible"
      period      = 60
      stat        = "Maximum"
      dimensions  = { QueueName = each.value }
    }
  }
}

# Baja worker a 0 tras 15 min seguidos sin mensajes visibles ni en vuelo en ingesta y purga.
resource "aws_cloudwatch_metric_alarm" "worker_colas_vacias" {
  alarm_name          = "${var.prefijo}-worker-colas-vacias"
  alarm_description   = "Baja worker a 0 tras ${local.worker_bajar_min} min sin mensajes visibles ni en vuelo en ingesta y purga (ARCHITECTURE 3.4, INF-2.1)"
  comparison_operator = "LessThanThreshold"
  threshold           = 0.5
  evaluation_periods  = local.worker_bajar_min
  datapoints_to_alarm = local.worker_bajar_min
  treat_missing_data  = "notBreaching"
  alarm_actions       = [aws_appautoscaling_policy.worker_colas_vacias.arn]

  metric_query {
    id          = "mensajes"
    expression  = "${local.suma_colas} + 0 * worker"
    label       = "Mensajes visibles y en vuelo en ingesta y purga"
    return_data = true
  }

  dynamic "metric_query" {
    for_each = local.metricas_colas
    content {
      id = metric_query.key

      metric {
        namespace   = "AWS/SQS"
        metric_name = metric_query.value.metrica
        period      = 60
        stat        = "Maximum"
        dimensions  = { QueueName = metric_query.value.cola }
      }
    }
  }

  metric_query {
    id = "worker"

    metric {
      namespace   = "AWS/ECS"
      metric_name = "CPUUtilization"
      period      = 60
      stat        = "SampleCount"
      dimensions = {
        ClusterName = aws_ecs_cluster.principal.name
        ServiceName = aws_ecs_service.servicios["worker"].name
      }
    }
  }
}

# Apaga embedding tras apagado_embedding.inactividad_min minutos seguidos sin peticiones a POST /v1/localize, sin
# encendidos y sin mensajes visibles ni en vuelo en las colas. Mientras embedding está apagado puede quedar en ALARM
# (y repetir la acción, sin efecto): por eso embedding.py encender publica antes EmbeddingEncendidos y espera a que
# salga de ALARM.
resource "aws_cloudwatch_metric_alarm" "embedding_inactivo" {
  alarm_name          = "${var.prefijo}-embedding-inactivo"
  alarm_description   = "Apaga embedding tras ${var.apagado_embedding.inactividad_min} min sin uso: sin POST /v1/localize, sin encendidos y sin mensajes en ingesta ni purga (ARCHITECTURE 3.4, INF-2.1)"
  comparison_operator = "LessThanThreshold"
  threshold           = 0.5
  evaluation_periods  = var.apagado_embedding.inactividad_min
  datapoints_to_alarm = var.apagado_embedding.inactividad_min
  treat_missing_data  = "notBreaching"
  alarm_actions       = [aws_appautoscaling_policy.embedding_apagar.arn]

  metric_query {
    id          = "uso"
    expression  = "FILL(localize, 0) + FILL(encendidos, 0) + ${local.suma_colas} + 0 * embedding"
    label       = "Peticiones a /v1/localize, encendidos y mensajes en las colas"
    return_data = true
  }

  metric_query {
    id = "localize"

    metric {
      namespace   = var.metrica_localize.espacio
      metric_name = var.metrica_localize.nombre
      period      = 60
      stat        = "Sum"
    }
  }

  metric_query {
    id = "encendidos"

    metric {
      namespace   = var.metrica_localize.espacio
      metric_name = local.metrica_encendidos
      period      = 60
      stat        = "Sum"
    }
  }

  dynamic "metric_query" {
    for_each = local.metricas_colas
    content {
      id = metric_query.key

      metric {
        namespace   = "AWS/SQS"
        metric_name = metric_query.value.metrica
        period      = 60
        stat        = "Maximum"
        dimensions  = { QueueName = metric_query.value.cola }
      }
    }
  }

  metric_query {
    id = "embedding"

    metric {
      namespace   = "AWS/ECS"
      metric_name = "CPUUtilization"
      period      = 60
      stat        = "SampleCount"
      dimensions = {
        ClusterName = aws_ecs_cluster.principal.name
        ServiceName = aws_ecs_service.servicios["embedding"].name
      }
    }
  }
}

# ---------------------------------------------------------------------------------------------------------------------
# Apagado nocturno (§5.3, §5.10): capacidad 0-0 a la hora de apagado_embedding.noche en su zona. worker también, aunque
# queden mensajes (esperan en la cola). Hasta el siguiente embedding.py encender, nada los sube.
# ---------------------------------------------------------------------------------------------------------------------

resource "aws_appautoscaling_scheduled_action" "noche" {
  for_each = var.apagado_embedding.noche == null ? toset([]) : local.escalados

  name               = "${var.prefijo}-${each.key}-apagar-noche"
  service_namespace  = aws_appautoscaling_target.servicios[each.key].service_namespace
  scalable_dimension = aws_appautoscaling_target.servicios[each.key].scalable_dimension
  resource_id        = aws_appautoscaling_target.servicios[each.key].resource_id
  schedule           = var.apagado_embedding.noche
  timezone           = var.apagado_embedding.zona

  scalable_target_action {
    min_capacity = "0"
    max_capacity = "0"
  }

  # Después de las políticas de su objetivo (ver arriba).
  depends_on = [
    aws_appautoscaling_policy.worker_cola,
    aws_appautoscaling_policy.worker_colas_vacias,
    aws_appautoscaling_policy.embedding_apagar,
  ]
}
