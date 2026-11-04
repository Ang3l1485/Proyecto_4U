package com.example.myapplication.data.remote

import com.example.myapplication.domain.model.CalidadFoto
import com.example.myapplication.domain.model.CategoriaLugar
import com.example.myapplication.domain.model.EstadoFoto
import com.example.myapplication.domain.model.Rol
import com.google.gson.Gson
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertThrows
import org.junit.Test
import java.util.Locale

/**
 * Tabla «Mapeo de datos» de ARCHITECTURE §5.10, fila por fila (FE-1.1, C2). Los JSON son los ejemplos del contrato
 * del backend (`BACKEND_FASTAPI/docs/ARCHITECTURE.md` §5.3 y §5.5), leídos con Gson como en la app.
 */
class MapeoDatosApiTest {

    private val gson = Gson()

    // Fila 1: enumerados en minúsculas → enum.valueOf(valor.uppercase()).

    @Test
    fun enumerados_enMinusculas() {
        assertEquals(CategoriaLugar.BIBLIOTECA, MapeoDatosApi.enumDe<CategoriaLugar>("biblioteca"))
        assertEquals(CategoriaLugar.BANO, MapeoDatosApi.enumDe<CategoriaLugar>("bano"))
        assertEquals(Rol.ADMIN, MapeoDatosApi.enumDe<Rol>("admin"))
        assertEquals(Rol.USER, MapeoDatosApi.enumDe<Rol>("user"))
        assertNull(MapeoDatosApi.enumDe<CategoriaLugar>("piscina"))
        assertNull(MapeoDatosApi.enumDe<Rol>(null))
    }

    @Test
    fun enumerados_noDependenDelIdiomaDelTelefono() {
        val antes = Locale.getDefault()
        try {
            Locale.setDefault(Locale.forLanguageTag("tr")) // "i".uppercase() sería "İ"
            assertEquals(CategoriaLugar.BIBLIOTECA, MapeoDatosApi.enumDe<CategoriaLugar>("biblioteca"))
            assertEquals(CategoriaLugar.ADMINISTRACION, MapeoDatosApi.enumDe<CategoriaLugar>("administracion"))
        } finally {
            Locale.setDefault(antes)
        }
    }

    // Fila 2: LugarPublico → LugarDestino.

    @Test
    fun lugarPublico_aLugarDestino() {
        val dto = gson.fromJson(
            """{"id": "3f2a", "nombre": "Biblioteca Central", "categoria": "biblioteca",
               "lat": 6.2009, "lng": -75.5783, "alias": ["biblioteca", "la biblioteca"],
               "descripcion": "Edificio", "referencias": "Frente al lago",
               "imagen_url": "https://s3/foto.jpg", "distancia_m": 85.6}""",
            LugarPublicoDto::class.java,
        )
        val lugar = MapeoDatosApi.lugarDestino(dto)!!
        assertEquals("3f2a", lugar.id)
        assertEquals("Biblioteca Central", lugar.nombre)
        assertEquals(CategoriaLugar.BIBLIOTECA, lugar.categoria)
        assertEquals(6.2009, lugar.lat, 0.0)
        assertEquals(-75.5783, lugar.lng, 0.0)
        assertEquals(listOf("biblioteca", "la biblioteca"), lugar.alias)
        assertEquals(86, lugar.distanciaMetros) // redondeado
        assertEquals("https://s3/foto.jpg", lugar.imagenUrl)
    }

    @Test
    fun lugarPublico_sinPosicionNiImagen_yCategoriaDesconocida() {
        val sinPosicion = gson.fromJson(
            """{"id": "1", "nombre": "Bloque 1", "categoria": "bloque", "lat": 6.2, "lng": -75.5,
               "alias": [], "imagen_url": null, "distancia_m": null}""",
            LugarPublicoDto::class.java,
        )
        val lugar = MapeoDatosApi.lugarDestino(sinPosicion)!!
        assertNull(lugar.distanciaMetros)
        assertNull(lugar.imagenUrl)
        val desconocida = sinPosicion.copy(categoria = "piscina")
        assertNull(MapeoDatosApi.lugarDestino(desconocida))
    }

    @Test
    fun lugarPublico_sinCampoObligatorio_esRespuestaInesperada() {
        val dto = gson.fromJson("""{"nombre": "X", "categoria": "bloque", "lat": 1, "lng": 2}""", LugarPublicoDto::class.java)
        assertThrows(RespuestaInesperadaException::class.java) { MapeoDatosApi.lugarDestino(dto) }
    }

    // Fila 3: Alerta.radio_m → Alerta.radio; tipo y prioridad como texto.

    @Test
    fun alerta_radioYTextos() {
        val dto = gson.fromJson(
            """{"id": "1d6e", "lat": 6.2011, "lng": -75.5790, "mensaje": "Ten cuidado, hay un lago",
               "tipo": "agua", "prioridad": "alta", "radio_m": 20, "activa": false,
               "vigencia_desde": null, "vigencia_hasta": null, "actualizado_en": "2026-10-22T20:11:00Z", "version": 3}""",
            AlertaDto::class.java,
        )
        val a = MapeoDatosApi.alerta(dto)
        assertEquals("1d6e", a.id)
        assertEquals(20, a.radio)
        assertEquals("agua", a.tipo)
        assertEquals("alta", a.prioridad)
        assertEquals(false, a.activa)
        assertEquals("Ten cuidado, hay un lago", a.mensaje)
    }

    // Fila 4: GET /v1/admin/stats → ResumenAdmin (fecha ISO → ms; fotosPendientes de la cola local).

    @Test
    fun estadisticas_aResumenAdmin() {
        val dto = gson.fromJson(
            """{"total_fotos": 2842, "total_lugares": 48, "alertas_activas": 3,
               "ultimo_video": {"numero": 12, "creado_en": "2026-10-23T15:04:05Z"}}""",
            EstadisticasAdminDto::class.java,
        )
        val r = MapeoDatosApi.resumenAdmin(dto, fotosPendientes = 7)
        assertEquals(2842, r.totalFotos)
        assertEquals(48, r.totalLugares)
        assertEquals(3, r.alertasActivas)
        assertEquals(12, r.ultimoVideoNumero)
        assertEquals(1_792_767_845_000L, r.ultimoVideoFecha) // 2026-10-23T15:04:05Z
        assertEquals(7, r.fotosPendientes)
    }

    @Test
    fun estadisticas_sinVideos() {
        val dto = gson.fromJson(
            """{"total_fotos": 0, "total_lugares": 0, "alertas_activas": 0, "ultimo_video": null}""",
            EstadisticasAdminDto::class.java,
        )
        val r = MapeoDatosApi.resumenAdmin(dto, fotosPendientes = 0)
        assertNull(r.ultimoVideoNumero)
        assertNull(r.ultimoVideoFecha)
    }

    // Fila 5: usuario del login → Usuario; expira_en se guarda con la sesión.

    @Test
    fun login_usuarioYVencimiento() {
        val dto = gson.fromJson(
            """{"token": "eyJ.x.y", "expira_en": "2026-10-24T03:04:05Z",
               "usuario": {"id": "7c1e", "nombre": "Alejandro", "correo": "admin@campus.edu.co", "rol": "admin"}}""",
            LoginRespuestaDto::class.java,
        )
        val u = MapeoDatosApi.usuario(dto.usuario)
        assertEquals("7c1e", u.id)
        assertEquals("Alejandro", u.nombre)
        assertEquals("admin@campus.edu.co", u.correo)
        assertEquals(Rol.ADMIN, u.rol)
        assertEquals(1_792_811_045_000L, MapeoDatosApi.expiraEnMs(dto))
    }

    @Test
    fun login_rolDesconocido_esRespuestaInesperada() {
        val dto = UsuarioDto(id = "1", nombre = "n", correo = "c", rol = "superadmin")
        assertThrows(RespuestaInesperadaException::class.java) { MapeoDatosApi.usuario(dto) }
    }

    // Fila 6: VideoResumen / ImagenAdmin → Video / Foto (id del video = UUID; uid = videoId/id).

    @Test
    fun video_conFotos() {
        val dto = gson.fromJson(
            """{"id": "vid-uuid", "numero": 12, "nombre": "Entrada norte", "ref_cliente": "rec_0003",
               "estado": "procesado", "creado_en": "2026-10-23T15:04:05Z", "total_fotos": 2,
               "fotos": [
                 {"id": "img-2", "video_id": "vid-uuid", "orden": 2, "lat": 6.2, "lng": -75.5, "rumbo": null,
                  "capturada_en": "2026-10-23T15:05:00Z", "estado": "error", "error": "borrosa", "calidad": "baja",
                  "lugar": null, "notas": null, "url": null, "url_miniatura": null, "url_expira_en": null},
                 {"id": "img-1", "video_id": "vid-uuid", "orden": 1, "lat": 6.2003, "lng": -75.5788, "rumbo": 182.0,
                  "capturada_en": "2026-10-23T15:04:30Z", "estado": "procesada", "error": null, "calidad": "alta",
                  "lugar": {"id": "3f2a", "nombre": "Biblioteca Central"}, "notas": null,
                  "url": "https://s3/1.jpg", "url_miniatura": "https://s3/1_t.jpg", "url_expira_en": "2026-10-23T16:00:00Z"}
               ]}""",
            VideoResumenDto::class.java,
        )
        val v = MapeoDatosApi.video(dto)
        assertEquals("vid-uuid", v.id)
        assertEquals("Entrada norte", v.nombre)
        assertEquals("2026-10-23T15:04:05Z", v.creadoEn) // las fechas siguen como texto
        assertEquals(listOf("img-1", "img-2"), v.fotos.map { it.id }) // por orden
        val f1 = v.fotos[0]
        assertEquals("vid-uuid/img-1", f1.uid)
        assertEquals("Entrada norte", f1.videoNombre)
        assertEquals(182.0f, f1.rumbo)
        assertEquals("Biblioteca Central", f1.lugar)
        assertEquals(EstadoFoto.PROCESADA, f1.estado)
        assertEquals(CalidadFoto.ALTA, f1.calidad)
        assertEquals("https://s3/1.jpg", f1.urlFoto)
        assertEquals("2026-10-23T15:04:30Z", f1.capturadaEn)
        val f2 = v.fotos[1]
        assertNull(f2.rumbo)
        assertEquals(EstadoFoto.ERROR, f2.estado)
        assertEquals(CalidadFoto.BAJA, f2.calidad)
        assertEquals("", f2.urlFoto) // URLs null hasta BE-4.1
        assertNull(f2.lugar)
    }

    @Test
    fun estadoFoto_pendienteSubida_esPendiente() {
        assertEquals(EstadoFoto.SUBIDA, MapeoDatosApi.estadoFoto("subida"))
        assertEquals(EstadoFoto.PROCESADA, MapeoDatosApi.estadoFoto("procesada"))
        assertEquals(EstadoFoto.ERROR, MapeoDatosApi.estadoFoto("error"))
        assertEquals(EstadoFoto.PENDIENTE, MapeoDatosApi.estadoFoto("pendiente_subida")) // FE-2.1
        assertNull(MapeoDatosApi.estadoFoto("pendiente")) // solo el valor del contrato
        assertNull(MapeoDatosApi.estadoFoto(null))
    }

    // Fila 7: fechas ISO-8601 (texto en los modelos; a ms solo donde se ordena o filtra).

    @Test
    fun fechasIso() {
        assertEquals(0L, MapeoDatosApi.isoAMilis("1970-01-01T00:00:00Z"))
        assertEquals(1_792_767_845_000L, MapeoDatosApi.isoAMilis("2026-10-23T15:04:05Z"))
        assertEquals(1_792_767_845_000L, MapeoDatosApi.isoAMilis("2026-10-23T15:04:05.250Z")) // fracción descartada
        assertNull(MapeoDatosApi.isoAMilis("2026-10-23T15:04:05+02:00")) // solo Z
        assertNull(MapeoDatosApi.isoAMilis("ayer"))
        assertNull(MapeoDatosApi.isoAMilis(null))
    }
}
