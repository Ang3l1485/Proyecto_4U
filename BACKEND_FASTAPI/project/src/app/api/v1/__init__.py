"""Rutas `/v1` (ARCHITECTURE §5.3–§5.5). Cada lote añade aquí su router.

Todo lo que cuelga de `/v1/admin` y `/v1/collect` exige `requiere_admin` (§4.4): esos dos routers la llevan como
dependencia, y un lote que añada rutas ahí incluye su router (sin prefijo `/admin` ni `/collect`) en `RUTAS_ADMIN` o
`RUTAS_COLLECT`, nunca directamente en `router_v1`. Una prueba (`tests/api/test_auth.py`) comprueba que toda ruta de
esos prefijos responde 401 sin token.
"""

from fastapi import APIRouter, Depends

from app.api.v1 import (
    admin_diagnostico,
    admin_estadisticas,
    admin_imagenes,
    admin_videos,
    alertas,
    auth,
    collect,
    localizar,
    lugares,
    reservados,
    salud,
)
from app.esquemas.errores import ErrorRespuesta
from app.seguridad.dependencias import requiere_admin

#: Respuestas de `requiere_admin` que se documentan en cada ruta protegida del OpenAPI.
RESPUESTAS_PROTEGIDAS = {
    401: {"model": ErrorRespuesta, "description": "NO_AUTENTICADO · TOKEN_INVALIDO · TOKEN_EXPIRADO"},
    403: {"model": ErrorRespuesta, "description": "SIN_PERMISOS"},
    503: {"model": ErrorRespuesta, "description": "BASE_NO_DISPONIBLE"},
}

#: Routers de `/v1/admin/*` (BE-2.1: videos; BE-2.3: stats; BE-2.4: diagnóstico; BE-3.1: lugares; BE-3.3: alertas;
#: BE-4.1: imágenes).
RUTAS_ADMIN: list[APIRouter] = [
    reservados.router_admin,
    admin_estadisticas.router,  # BE-2.3: GET /v1/admin/stats
    admin_videos.router,  # BE-2.1 (lecturas) y BE-4.1 (PATCH, DELETE)
    admin_imagenes.router,  # BE-4.1: /v1/admin/images
    admin_diagnostico.router,
    lugares.router_admin,
    alertas.router_admin,  # BE-3.3: /v1/admin/alerts
]
#: Routers de `/v1/collect/*` (BE-2.1).
RUTAS_COLLECT: list[APIRouter] = [collect.router]


def _protegido(prefijo: str, routers: list[APIRouter]) -> APIRouter:
    protegido = APIRouter(prefix=prefijo, dependencies=[Depends(requiere_admin)], responses=RESPUESTAS_PROTEGIDAS)
    for router in routers:
        protegido.include_router(router)
    return protegido


router_v1 = APIRouter(prefix="/v1")
router_v1.include_router(salud.router)
router_v1.include_router(auth.router)
router_v1.include_router(reservados.router_publico)
router_v1.include_router(lugares.router_publico)
router_v1.include_router(alertas.router_publico)  # BE-3.3: GET /v1/alerts (público)
router_v1.include_router(localizar.router)  # BE-3.2: POST /v1/localize; BE-5.1: POST /v1/localize/frame (públicos)
router_v1.include_router(_protegido("/admin", RUTAS_ADMIN))
router_v1.include_router(_protegido("/collect", RUTAS_COLLECT))
