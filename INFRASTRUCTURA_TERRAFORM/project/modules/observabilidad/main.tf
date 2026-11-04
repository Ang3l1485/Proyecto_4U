# Módulo observabilidad (ARCHITECTURE §3.8, §5.1, §5.6, §5.10; INF-3.1): el topic SNS campus-locator-dev-alertas con
# su suscripción por correo, las seis alarmas de §5.10 que avisan al topic y la regla de EventBridge que avisa cuando
# una tarea de los servicios api, worker o embedding se detiene por error.
#
# - Las cuatro alarmas de escalado de INF-2.1 (computo/escalado.tf) no avisan: su única acción es una política de
#   Application Auto Scaling. Las de aquí solo publican en el topic (sin acciones OK ni INSUFFICIENT_DATA: un correo por
#   cada paso a ALARM).
# - SNS manda a correo_alertas un correo de confirmación y no entrega nada hasta que se confirma (§3.8).
# - El topic no se cifra: con la clave gestionada aws/sns, CloudWatch y EventBridge no pueden publicar (su política de
#   clave no los admite) y una clave propia de KMS cuesta 1 USD/mes.

locals {
  topic = "${var.prefijo}-alertas"
  regla = "${var.prefijo}-tarea-detenida"

  # startedBy de la tarea de prueba de validate31.py (C3). ECS no admite group = service:<nombre> en una tarea suelta
  # («Invalid namespace for group.», ARCHITECTURE §3.8), así que la regla tiene una rama solo para ella.
  marca_prueba = "validacion-3-1"

  # Alarmas de §5.1 con los umbrales de §5.10 (nombre = prefijo + clave). Todas tratan la falta de datos como «no
  # incumple»: una DLQ vacía e inactiva, una API sin peticiones o embedding apagado no publican la métrica.
  alarmas = {
    "api-5xx" = {
      descripcion = "Mas de 5 respuestas 5xx en 5 min en la HTTP API ${var.api_id} (las de API Gateway sin api en marcha y los 503 de /v1/localize con embedding apagado tambien cuentan). Revisar /campus-locator/dev/apigw y /campus-locator/dev/api (ARCHITECTURE 3.8, 5.10)"
      espacio     = "AWS/ApiGateway"
      metrica     = "5xx"
      dimensiones = { ApiId = var.api_id }
      estadistica = "Sum"
      periodo     = 300
      periodos    = 1
      comparacion = "GreaterThanThreshold"
      umbral      = 5
    }
    "ingesta-dlq" = {
      descripcion = "Hay mensajes en ${var.colas["ingesta_dlq"].nombre}: fotos del dataset que el worker no pudo procesar tras 5 intentos. Revisar /campus-locator/dev/worker y re-enviarlos con redrive (ARCHITECTURE 5.6, 5.10)"
      espacio     = "AWS/SQS"
      metrica     = "ApproximateNumberOfMessagesVisible"
      dimensiones = { QueueName = var.colas["ingesta_dlq"].nombre }
      estadistica = "Maximum"
      periodo     = 60
      periodos    = 1
      comparacion = "GreaterThanOrEqualToThreshold"
      umbral      = 1
    }
    "purga-dlq" = {
      descripcion = "Hay mensajes en ${var.colas["purga_dlq"].nombre}: purgas de videos que el worker no pudo completar tras 5 intentos. Revisar /campus-locator/dev/worker y re-enviarlos con redrive (ARCHITECTURE 5.6, 5.10)"
      espacio     = "AWS/SQS"
      metrica     = "ApproximateNumberOfMessagesVisible"
      dimensiones = { QueueName = var.colas["purga_dlq"].nombre }
      estadistica = "Maximum"
      periodo     = 60
      periodos    = 1
      comparacion = "GreaterThanOrEqualToThreshold"
      umbral      = 1
    }
    # «Encendido» = ECS publicó CPUUtilization del servicio (solo lo hace con tareas en marcha) en cada una de las
    # últimas 10 horas de reloj. Periodos de 1 h: 10 x 3600 s cabe en el máximo de un día de una alarma.
    "embedding-encendida" = {
      descripcion = "embedding lleva unas 10 h seguidas encendido (~0,10 USD/h): el apagado automatico por inactividad o el de las 22:00 fallo. Apagarlo con src/ops/embedding.py apagar si nadie lo usa (ARCHITECTURE 3.4, 5.10, R13)"
      espacio     = "AWS/ECS"
      metrica     = "CPUUtilization"
      dimensiones = { ClusterName = var.cluster, ServiceName = var.servicios["embedding"] }
      estadistica = "SampleCount"
      periodo     = 3600
      periodos    = 10
      comparacion = "GreaterThanThreshold"
      umbral      = 0
    }
    "rds-almacenamiento" = {
      descripcion = "Quedan menos de 4 GiB libres en ${var.rds_identificador} (el autoescalado de almacenamiento llega hasta 50 GB). Revisar el tamano de la base (ARCHITECTURE 3.5, 5.10)"
      espacio     = "AWS/RDS"
      metrica     = "FreeStorageSpace"
      dimensiones = { DBInstanceIdentifier = var.rds_identificador }
      estadistica = "Minimum"
      periodo     = 300
      periodos    = 1
      comparacion = "LessThanThreshold"
      umbral      = 4294967296
    }
    "rds-creditos-cpu" = {
      descripcion = "Quedan menos de 20 creditos de CPU en ${var.rds_identificador}: en modo unlimited, gastar mas cobra creditos extra. Revisar la carga de la base o subir de clase (ARCHITECTURE 3.10, 5.10, R4)"
      espacio     = "AWS/RDS"
      metrica     = "CPUCreditBalance"
      dimensiones = { DBInstanceIdentifier = var.rds_identificador }
      estadistica = "Minimum"
      periodo     = 300
      periodos    = 1
      comparacion = "LessThanThreshold"
      umbral      = 20
    }
  }
}

# ---------------------------------------------------------------------------------------------------------------------
# Topic, política y suscripción
# ---------------------------------------------------------------------------------------------------------------------

resource "aws_sns_topic" "alertas" {
  name = local.topic
}

# Reemplaza la política por defecto del topic, así que la repite (declaración «Cuenta»: la cuenta lo administra y
# publica) y añade a CloudWatch (alarmas de la cuenta) y a EventBridge (solo la regla de abajo) como publicadores.
data "aws_iam_policy_document" "alertas" {
  statement {
    sid    = "Cuenta"
    effect = "Allow"
    actions = [
      "SNS:AddPermission",
      "SNS:DeleteTopic",
      "SNS:GetTopicAttributes",
      "SNS:ListSubscriptionsByTopic",
      "SNS:Publish",
      "SNS:RemovePermission",
      "SNS:SetTopicAttributes",
      "SNS:Subscribe",
    ]
    resources = [aws_sns_topic.alertas.arn]

    principals {
      type        = "AWS"
      identifiers = ["*"]
    }

    condition {
      test     = "StringEquals"
      variable = "AWS:SourceOwner"
      values   = [var.cuenta_id]
    }
  }

  statement {
    sid       = "CloudWatch"
    effect    = "Allow"
    actions   = ["sns:Publish"]
    resources = [aws_sns_topic.alertas.arn]

    principals {
      type        = "Service"
      identifiers = ["cloudwatch.amazonaws.com"]
    }

    condition {
      test     = "StringEquals"
      variable = "aws:SourceAccount"
      values   = [var.cuenta_id]
    }

    condition {
      test     = "ArnLike"
      variable = "aws:SourceArn"
      values   = ["arn:aws:cloudwatch:${var.region}:${var.cuenta_id}:alarm:*"]
    }
  }

  statement {
    sid       = "EventBridge"
    effect    = "Allow"
    actions   = ["sns:Publish"]
    resources = [aws_sns_topic.alertas.arn]

    principals {
      type        = "Service"
      identifiers = ["events.amazonaws.com"]
    }

    # El ARN de la regla se escribe a mano (bus default) y no con aws_cloudwatch_event_rule.tarea_detenida.arn: con la
    # referencia, cualquier cambio en sitio de la regla aplazaba la lectura de este data al apply y el plan mostraba
    # también la política como cambiada, aunque quedara igual.
    condition {
      test     = "ArnEquals"
      variable = "aws:SourceArn"
      values   = ["arn:aws:events:${var.region}:${var.cuenta_id}:rule/${local.regla}"]
    }
  }
}

resource "aws_sns_topic_policy" "alertas" {
  arn    = aws_sns_topic.alertas.arn
  policy = data.aws_iam_policy_document.alertas.json
}

# Queda «pendiente de confirmación» hasta que alguien abre el enlace del correo que envía SNS: mientras tanto SNS no
# entrega nada (validation-3-1 C1c). Si alguien se da de baja desde el enlace de un aviso, el siguiente plan la vuelve
# a crear (y hay que confirmarla otra vez).
resource "aws_sns_topic_subscription" "correo" {
  topic_arn = aws_sns_topic.alertas.arn
  protocol  = "email"
  endpoint  = var.correo_alertas
}

# ---------------------------------------------------------------------------------------------------------------------
# Alarmas (§5.10)
# ---------------------------------------------------------------------------------------------------------------------

resource "aws_cloudwatch_metric_alarm" "alarmas" {
  for_each = local.alarmas

  alarm_name          = "${var.prefijo}-${each.key}"
  alarm_description   = each.value.descripcion
  namespace           = each.value.espacio
  metric_name         = each.value.metrica
  dimensions          = each.value.dimensiones
  statistic           = each.value.estadistica
  period              = each.value.periodo
  evaluation_periods  = each.value.periodos
  datapoints_to_alarm = each.value.periodos
  comparison_operator = each.value.comparacion
  threshold           = each.value.umbral
  treat_missing_data  = "notBreaching"
  alarm_actions       = [aws_sns_topic.alertas.arn]
}

# ---------------------------------------------------------------------------------------------------------------------
# Tarea de un servicio detenida por error (§3.8)
# ---------------------------------------------------------------------------------------------------------------------

# Solo tareas de este clúster (la cuenta tiene otros proyectos) que se detienen porque su contenedor esencial terminó o
# no llegó a arrancar, y que son de un servicio (group = service:<nombre>) o la tarea de prueba de validate31.py
# (startedBy = local.marca_prueba; ninguna otra tarea lleva ese startedBy). Las tareas sueltas (migrate, validacion)
# tienen group = family:<familia> y no avisan; las paradas de ECS al escalar, desplegar o apagar dan
# stopCode = ServiceSchedulerInitiated.
resource "aws_cloudwatch_event_rule" "tarea_detenida" {
  name        = local.regla
  description = "Avisa a ${local.topic} cuando una tarea de api, worker o embedding se detiene por error (ARCHITECTURE 3.8)"
  state       = "ENABLED"

  event_pattern = jsonencode({
    source        = ["aws.ecs"]
    "detail-type" = ["ECS Task State Change"]
    detail = {
      clusterArn = [var.cluster_arn]
      lastStatus = ["STOPPED"]
      stopCode   = ["EssentialContainerExited", "TaskFailedToStart"]
      "$or" = [
        { group = [for clave in ["api", "embedding", "worker"] : "service:${var.servicios[clave]}"] },
        { startedBy = [local.marca_prueba] },
      ]
    }
  })
}

# El correo lleva el evento completo en JSON (group, startedBy, stopCode, stoppedReason, taskArn, contenedores con su
# exitCode y reason). Sin transformador de entrada: nada que mantener ni que pueda dejar fuera un dato del evento.
resource "aws_cloudwatch_event_target" "tarea_detenida" {
  rule      = aws_cloudwatch_event_rule.tarea_detenida.name
  target_id = "sns-alertas"
  arn       = aws_sns_topic.alertas.arn

  # Sin la política, EventBridge no puede publicar (FailedInvocations).
  depends_on = [aws_sns_topic_policy.alertas]
}
