import 'package:camera/camera.dart';
import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart';
import 'package:permission_handler/permission_handler.dart';

import 'camera_service.dart';

class FlutterCameraService implements CameraService {
  CameraController? _controller;

  bool get _isSupportedPlatform {
    if (kIsWeb) {
      return true;
    }
    return defaultTargetPlatform == TargetPlatform.android ||
        defaultTargetPlatform == TargetPlatform.iOS ||
        defaultTargetPlatform == TargetPlatform.windows;
  }

  @override
  Future<CameraInitializationResult> initializeCamera() async {
    if (!_isSupportedPlatform) {
      return const CameraInitializationResult(
        availability: CameraAvailability.unavailable,
        message: 'La cámara no está disponible en esta plataforma.',
      );
    }

    if (!kIsWeb && defaultTargetPlatform != TargetPlatform.windows) {
      final PermissionStatus permission = await Permission.camera.request();
      if (permission.isPermanentlyDenied) {
        return const CameraInitializationResult(
          availability: CameraAvailability.permanentlyDenied,
          message:
              'El permiso de cámara está bloqueado. Actívalo en la configuración del sistema.',
        );
      }
      if (!permission.isGranted) {
        return const CameraInitializationResult(
          availability: CameraAvailability.denied,
          message: 'Se requiere permiso de cámara para tomar fotografías.',
        );
      }
    }

    try {
      final List<CameraDescription> cameras = await availableCameras();
      if (cameras.isEmpty) {
        return const CameraInitializationResult(
          availability: CameraAvailability.unavailable,
          message: 'No se encontraron cámaras disponibles.',
        );
      }

      await _controller?.dispose();
      final CameraController controller = CameraController(
        cameras.first,
        ResolutionPreset.high,
        enableAudio: false,
      );
      await controller.initialize();
      _controller = controller;
      return const CameraInitializationResult(
        availability: CameraAvailability.ready,
        message: 'Cámara lista.',
      );
    } on CameraException catch (error) {
      final bool isDenied = error.code.toLowerCase().contains('accessdenied');
      return CameraInitializationResult(
        availability: isDenied
            ? CameraAvailability.denied
            : CameraAvailability.unavailable,
        message:
            'No fue posible iniciar la cámara: ${error.description ?? error.code}',
      );
    } catch (error) {
      return CameraInitializationResult(
        availability: CameraAvailability.unavailable,
        message: 'No fue posible iniciar la cámara: $error',
      );
    }
  }

  @override
  Widget buildPreview() {
    final CameraController? controller = _controller;
    if (controller == null || !controller.value.isInitialized) {
      return const Center(child: Text('Vista previa no disponible.'));
    }
    return Center(
      child: AspectRatio(
        aspectRatio: controller.value.aspectRatio,
        child: CameraPreview(controller),
      ),
    );
  }

  @override
  Future<Uint8List> takePhoto() async {
    final CameraController? controller = _controller;
    if (controller == null || !controller.value.isInitialized) {
      throw StateError('La cámara no está inicializada.');
    }
    final XFile photo = await controller.takePicture();
    final Uint8List bytes = await photo.readAsBytes();
    if (bytes.isEmpty) {
      throw StateError('La cámara devolvió una imagen vacía.');
    }
    return bytes;
  }

  @override
  Future<void> openApplicationSettings() async {
    await openAppSettings();
  }

  @override
  Future<void> disposeCamera() async {
    await _controller?.dispose();
    _controller = null;
  }
}
