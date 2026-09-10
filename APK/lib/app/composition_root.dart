import 'dart:io';

import 'package:flutter/widgets.dart';
import 'package:path_provider/path_provider.dart';

import '../features/captures/data/repositories/local_capture_repository.dart';
import '../features/captures/data/services/image_quality_analyzer.dart';
import '../features/captures/domain/repositories/capture_repository.dart';
import '../features/captures/domain/use_cases/create_capture.dart';
import '../features/captures/domain/use_cases/delete_captures.dart';
import '../features/captures/domain/use_cases/filter_captures.dart';
import '../features/captures/domain/use_cases/list_captures.dart';
import '../features/captures/domain/use_cases/update_capture_metadata.dart';
import '../features/captures/domain/use_cases/validate_capture.dart';
import '../features/captures/presentation/capture/capture_controller.dart';
import '../features/captures/presentation/dataset/dataset_controller.dart';
import '../platform/camera/flutter_camera_service.dart';
import '../platform/compass/flutter_compass_service.dart';
import '../platform/location/geolocator_location_service.dart';
import '../platform/media/flutter_image_picker_service.dart';
import 'app.dart';

class CompositionRoot {
  const CompositionRoot();

  Future<Widget> buildApplication() async {
    final Directory datasetDirectory = await _resolveDatasetDirectory();
    final CaptureRepository repository = LocalCaptureRepository.inDirectory(
      datasetDirectory,
    );
    final ValidateCapture validateCapture = ValidateCapture(
      const ImageQualityAnalyzer(
        ImageQualityThresholds(
          minimumWidth: 640,
          minimumHeight: 480,
          minimumBrightness: 35,
          minimumSharpness: 8,
        ),
      ),
    );
    final DatasetController datasetController = DatasetController(
      repository: repository,
      listCaptures: ListCaptures(repository),
      filterCaptures: const FilterCaptures(),
      updateCaptureMetadata: UpdateCaptureMetadata(repository),
      deleteCaptures: DeleteCaptures(repository),
    );
    final CaptureController captureController = CaptureController(
      cameraService: FlutterCameraService(),
      locationService: const GeolocatorLocationService(),
      compassService: FlutterCompassService(),
      imagePickerService: FlutterImagePickerService(),
      validateCapture: validateCapture,
      createCapture: CreateCapture(repository),
      onCaptureCreated: datasetController.loadCaptures,
    );
    return DatasetApp(
      captureController: captureController,
      datasetController: datasetController,
    );
  }

  /// Resuelve la carpeta donde se guarda el dataset (imágenes + JSON).
  ///
  /// En Android usamos almacenamiento externo específico de la app
  /// (`Android/data/<paquete>/files/captures`), que es visible con
  /// cualquier explorador de archivos sin pedir permisos adicionales.
  /// Así, una vez que una captura pasa el filtro de calidad y se
  /// guarda, queda disponible automáticamente en una carpeta que se
  /// puede copiar/extraer del dispositivo, sin depender de un paso
  /// manual de "descargar" o "compartir" cada archivo.
  ///
  /// En plataformas donde no existe almacenamiento externo (iOS,
  /// escritorio), se usa el directorio de documentos de la app como
  /// respaldo.
  Future<Directory> _resolveDatasetDirectory() async {
    final Directory? externalDirectory = await getExternalStorageDirectory();
    final Directory baseDirectory =
        externalDirectory ?? await getApplicationDocumentsDirectory();
    return Directory(
      '${baseDirectory.path}${Platform.pathSeparator}captures',
    );
  }
}
