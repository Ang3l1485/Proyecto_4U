"""Cola SQS con boto3, desde BE-2.2 (ARCHITECTURE §4.6; colas en infra §5.6).

`ColaSqs(url, region)` es síncrona (boto3); el `worker` la llama en hilos (`anyio.to_thread`). Permisos del rol
`tarea-worker` (infra §5.8): `ReceiveMessage`, `DeleteMessage`, `ChangeMessageVisibility` y `GetQueueAttributes`. Desde
BE-4.1, `api` envía (`enviar`, rol `tarea-api`: `sqs:SendMessage` en `ingesta` y `purga`).

Todo error de AWS → `FalloSqs` (mensaje con la clase y el código de AWS; nunca el cuerpo del mensaje).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


class FalloSqs(Exception):
    """SQS no respondió o respondió un error."""


@dataclass(frozen=True)
class MensajeSqs:
    id: str
    recibo: str  # ReceiptHandle: hace falta para borrar o devolver el mensaje
    cuerpo: str
    recepciones: int  # ApproximateReceiveCount (1 la primera vez)


def crear_cliente(region: str) -> Any:
    """Cliente de SQS. `read_timeout` mayor que la espera larga (20 s, infra §5.6)."""
    import boto3
    from botocore.config import Config

    configuracion = Config(
        retries={"max_attempts": 3, "mode": "standard"},
        connect_timeout=3,
        read_timeout=30,
    )
    return boto3.session.Session().client("sqs", region_name=region, config=configuracion)


def _motivo(exc: BaseException) -> str:
    respuesta = getattr(exc, "response", None) or {}
    codigo = respuesta.get("Error", {}).get("Code") if isinstance(respuesta, dict) else None
    return f"{type(exc).__name__}: {codigo}" if codigo else type(exc).__name__


class ColaSqs:
    def __init__(self, url: str, region: str = "us-east-1", *, cliente: Any = None) -> None:
        self.url = url
        self.cliente = cliente if cliente is not None else crear_cliente(region)

    def recibir(self, maximo: int, espera_s: int) -> list[MensajeSqs]:
        """`ReceiveMessage` con espera larga: hasta `maximo` (≤ 10) mensajes, o `[]` tras `espera_s` sin ninguno."""
        try:
            respuesta = self.cliente.receive_message(
                QueueUrl=self.url,
                MaxNumberOfMessages=max(1, min(10, maximo)),
                WaitTimeSeconds=max(0, min(20, espera_s)),
                MessageSystemAttributeNames=["ApproximateReceiveCount"],
            )
        except Exception as exc:
            raise FalloSqs(f"recibir: {_motivo(exc)}") from None
        return [
            MensajeSqs(
                id=m["MessageId"],
                recibo=m["ReceiptHandle"],
                cuerpo=m.get("Body", ""),
                recepciones=int(m.get("Attributes", {}).get("ApproximateReceiveCount", 1)),
            )
            for m in respuesta.get("Messages", [])
        ]

    def borrar(self, recibo: str) -> None:
        try:
            self.cliente.delete_message(QueueUrl=self.url, ReceiptHandle=recibo)
        except Exception as exc:
            raise FalloSqs(f"borrar: {_motivo(exc)}") from None

    def devolver(self, recibo: str) -> None:
        """`ChangeMessageVisibility` a 0: el mensaje vuelve a estar visible ya (su recepción ya contó)."""
        try:
            self.cliente.change_message_visibility(QueueUrl=self.url, ReceiptHandle=recibo, VisibilityTimeout=0)
        except Exception as exc:
            raise FalloSqs(f"devolver: {_motivo(exc)}") from None

    def enviar(self, cuerpo: str) -> str:
        """BE-4.1: `SendMessage` con `cuerpo` (JSON en texto). Devuelve el `MessageId`."""
        try:
            respuesta = self.cliente.send_message(QueueUrl=self.url, MessageBody=cuerpo)
        except Exception as exc:
            raise FalloSqs(f"enviar: {_motivo(exc)}") from None
        return str(respuesta.get("MessageId", ""))


@dataclass(frozen=True)
class Colas:
    """BE-4.1: las colas a las que envía `api` (`None` = sin la variable): `reprocesar_imagen` va a `ingesta` y
    `purgar_*` a `purga` (§5.8)."""

    ingesta: ColaSqs | None = None
    purga: ColaSqs | None = None


def crear_colas(url_ingesta: str | None, url_purga: str | None, region: str) -> Colas:
    """Un solo cliente de boto3 para las dos colas (crearlo cuesta CPU en la tarea de 0,25 vCPU)."""
    if not url_ingesta and not url_purga:
        return Colas()
    cliente = crear_cliente(region)
    return Colas(
        ingesta=ColaSqs(url_ingesta, cliente=cliente) if url_ingesta else None,
        purga=ColaSqs(url_purga, cliente=cliente) if url_purga else None,
    )
