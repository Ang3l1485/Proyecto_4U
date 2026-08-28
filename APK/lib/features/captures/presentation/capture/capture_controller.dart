import 'dart:async';
import 'dart:io';

import 'package:flutter/foundation.dart';
import 'package:flutter/widgets.dart';
import 'package:share_plus/share_plus.dart';

import '../../../../platform/camera/camera_service.dart';
import '../../../../platform/compass/compass_service.dart';
import '../../../../platform/location/location_service.dart';
import '../../../../platform/media/image_picker_service.dart';
import '../../domain/entities/capture.dart';
import '../../domain/entities/capture_metadata.dart';
import '../../domain/entities/image_quality_report.dart';
import '../../domain/use_cases/create_capture.dart';
import '../../domain/use_cases/validate_capture.dart';
import 'capture_state.dart';

class NewCaptureMetadata {
  const NewCaptureMetadata({
    required this.block,
    required this.latitude,
    required this.longitude,
    required this.author,
    required this.status,
  });

  final String block;
  final double latitude;
  final double longitude;
  final String author;
  final MetadataStatus status;
}

class CaptureController extends ChangeNotifier {
  CaptureController({
    required CameraService cameraService,
    required LocationService locationService,
    required CompassService compassService,
    required ImagePickerService imagePickerService,
    required ValidateCapture validateCapture,
    required CreateCapture createCapture,
    required Future<void> Function() onCaptureCreated,
  }) : _cameraService = cameraService,
       _locationService = locationService,
       _compassService = compassService,
       _imagePickerService = imagePickerService,
       _validateCapture = validateCapture,
       _createCapture = createCapture,
       _onCaptureCreated = onCaptureCreated,
       _sessionId = DateTime.now().millisecondsSinceEpoch.toString();

  final CameraService _cameraService;
  final LocationService _locationService;
  final CompassService _compassService;
  final ImagePickerService _imagePickerService;
  final ValidateCapture _validateCapture;
  final CreateCapture _createCapture;
  final Future<void> Function() _onCaptureCreated;
  final String _sessionId;

  CaptureState _state = const CaptureState();
  StreamSubscription<CompassReading>? _compassSubscription;

  CaptureState get state => _state;
  String get sessionId => _sessionId;
  Widget buildCameraPreview() => _cameraService.buildPreview();

  Future<void> initialize() async {
    _setState(
      CaptureState(
        statusMessage: 'Inicializando cámara…',
        compassMessage: _compassService.availabilityMessage,
      ),
    );
    if (_compassService.isAvailable) {
      _compassSubscription = _compassService.readings.listen(
        (CompassReading reading) {
          _setState(_copyState(compassHeading: reading.headingDegrees));
        },
        onError: (Object error) {
          _setState(
            _copyState(
              compassMessage: 'No fue posible leer la brújula: $error',
            ),
          );
        },
      );
    }

    final CameraInitializationResult result = await _cameraService
        .initializeCamera();
    _setState(
      _copyState(
        cameraAvailability: result.availability,
        statusMessage: result.message,
      ),
    );
  }

  Future<void> retryCamera() async {
    _setState(
      _copyState(
        cameraAvailability: CameraAvailability.checking,
        statusMessage: 'Reintentando cámara…',
      ),
    );
    final CameraInitializationResult result = await _cameraService
        .initializeCamera();
    _setState(
      _copyState(
        cameraAvailability: result.availability,
        statusMessage: result.message,
      ),
    );
  }

  Future<void> openCameraSettings() => _cameraService.openApplicationSettings();

  Future<CurrentLocation?> getCurrentLocation() async {
    _setState(
      _copyState(
        isGettingLocation: true,
        statusMessage: 'Obteniendo ubicación…',
      ),
    );
    try {
      final CurrentLocation location = await _locationService
          .getCurrentLocation();
      _setState(
        _copyState(
          isGettingLocation: false,
          statusMessage:
              'Ubicación obtenida: ${location.latitude.toStringAsFixed(6)}, '
              '${location.longitude.toStringAsFixed(6)}.',
        ),
      );
      return location;
    } catch (error) {
      _setState(
        _copyState(
          isGettingLocation: false,
          statusMessage: 'No fue posible obtener la ubicación: $error',
        ),
      );
      return null;
    }
  }

  Future<void> capturePhoto() async {
    if (_state.isCapturing || !_state.canUseCamera) {
      return;
    }
    _setState(
      _copyState(
        isCapturing: true,
        statusMessage: 'Capturando y evaluando calidad…',
        clearPendingImage: true,
      ),
    );
    try {
      final Uint8List imageBytes = await _cameraService.takePhoto();
      _setPendingImage(imageBytes, sourceLabel: 'Fotografía');
    } catch (error) {
      _setState(
        _copyState(statusMessage: 'No fue posible tomar la fotografía: $error'),
      );
    } finally {
      _setState(_copyState(isCapturing: false));
    }
  }

  Future<void> captureSequence() async {
    if (_state.isCapturing || !_state.canUseCamera) {
      return;
    }
    _setState(
      _copyState(
        isCapturing: true,
        statusMessage: 'Tomando secuencia de 5 segundos…',
        clearPendingImage: true,
      ),
    );
    try {
      Uint8List? bestBytes;
      ImageQualityReport? bestReport;
      for (int index = 0; index < 10; index++) {
        final Uint8List candidate = await _cameraService.takePhoto();
        final ImageQualityReport report = _validateCapture.validateCapture(
          candidate,
        );
        if (bestReport == null ||
            (report.isAccepted && !bestReport.isAccepted) ||
            (report.isAccepted == bestReport.isAccepted &&
                report.selectionScore > bestReport.selectionScore)) {
          bestBytes = candidate;
          bestReport = report;
        }
        if (index < 9) {
          await Future<void>.delayed(const Duration(milliseconds: 500));
        }
      }
      if (bestBytes == null || bestReport == null) {
        throw StateError('La secuencia no produjo una imagen utilizable.');
      }
      _setState(
        _copyState(
          pendingImageBytes: bestBytes,
          qualityReport: bestReport,
          statusMessage: bestReport.isAccepted
              ? 'Se eligió la mejor fotografía de la secuencia.'
              : 'Ninguna fotografía pasó la calidad; revisa el informe.',
        ),
      );
    } catch (error) {
      _setState(
        _copyState(
          statusMessage: 'No fue posible completar la secuencia: $error',
        ),
      );
    } finally {
      _setState(_copyState(isCapturing: false));
    }
  }

  Future<void> pickGalleryImage() async {
    try {
      final Uint8List? imageBytes = await _imagePickerService
          .pickGalleryImage();
      if (imageBytes == null) {
        _setState(
          _copyState(statusMessage: 'No se seleccionó ninguna imagen.'),
        );
        return;
      }
      _setPendingImage(imageBytes, sourceLabel: 'Imagen de galería');
    } catch (error) {
      _setState(
        _copyState(statusMessage: 'No fue posible abrir la galería: $error'),
      );
    }
  }

  Future<bool> createPendingCapture(
    NewCaptureMetadata input, {
    required bool allowQualityOverride,
  }) async {
    final Uint8List? imageBytes = _state.pendingImageBytes;
    final ImageQualityReport? quality = _state.qualityReport;
    if (imageBytes == null || quality == null || _state.isSaving) {
      return false;
    }

    _setState(_copyState(isSaving: true, statusMessage: 'Guardando captura…'));
    try {
      final double? heading = _state.compassHeadingDegrees;
      final Capture capture = await _createCapture.createCapture(
        imageBytes: imageBytes,
        metadata: CaptureMetadata(
          block: input.block.trim(),
          latitude: input.latitude,
          longitude: input.longitude,
          timestamp: DateTime.now(),
          author: input.author.trim(),
          sessionId: _sessionId,
          status: input.status,
          compassHeadingDegrees: heading,
          compassDirection: heading == null
              ? null
              : CaptureMetadata.directionFromHeading(heading),
        ),
        quality: quality,
        allowQualityOverride: allowQualityOverride,
      );
      _setState(
        _copyState(
          isSaving: false,
          statusMessage: capture.wasQualityOverride
              ? 'Captura guardada con excepción de calidad registrada.'
              : 'Captura guardada correctamente.',
          lastCreatedCapture: capture,
          clearPendingImage: true,
        ),
      );
      unawaited(_onCaptureCreated());
      return true;
    } catch (error) {
      _setState(
        _copyState(
          isSaving: false,
          statusMessage: 'No fue posible guardar la captura: $error',
        ),
      );
      return false;
    }
  }

  void discardPendingImage() {
    _setState(
      _copyState(
        clearPendingImage: true,
        statusMessage: 'Imagen descartada. Puedes capturar de nuevo.',
      ),
    );
  }

  /// Comparte (o permite "descargar") el archivo JSON de metadata
  /// de la última captura guardada, usando el selector nativo del
  /// sistema operativo.
  Future<void> shareLastCaptureMetadata() async {
    final Capture? capture = _state.lastCreatedCapture;
    if (capture == null) {
      return;
    }
    try {
      final File metadataFile = File(capture.metadataPath);
      if (!await metadataFile.exists()) {
        _setState(
          _copyState(
            statusMessage: 'El archivo de metadata ya no existe en el dispositivo.',
          ),
        );
        return;
      }
      await Share.shareXFiles(
        <XFile>[XFile(metadataFile.path, mimeType: 'application/json')],
        text: 'Metadata de captura ${capture.id}',
      );
    } catch (error) {
      _setState(
        _copyState(statusMessage: 'No fue posible compartir el JSON: $error'),
      );
    }
  }

  void _setPendingImage(Uint8List imageBytes, {required String sourceLabel}) {
    final ImageQualityReport report = _validateCapture.validateCapture(
      imageBytes,
    );
    _setState(
      _copyState(
        pendingImageBytes: imageBytes,
        qualityReport: report,
        statusMessage: report.isAccepted
            ? '$sourceLabel aceptada. Confirma el guardado.'
            : '$sourceLabel rechazada por calidad. Revisa los motivos.',
      ),
    );
  }

  CaptureState _copyState({
    CameraAvailability? cameraAvailability,
    String? statusMessage,
    String? compassMessage,
    double? compassHeading,
    Uint8List? pendingImageBytes,
    ImageQualityReport? qualityReport,
    Capture? lastCreatedCapture,
    bool? isCapturing,
    bool? isSaving,
    bool? isGettingLocation,
    bool clearPendingImage = false,
  }) {
    return CaptureState(
      cameraAvailability: cameraAvailability ?? _state.cameraAvailability,
      statusMessage: statusMessage ?? _state.statusMessage,
      compassMessage: compassMessage ?? _state.compassMessage,
      compassHeadingDegrees: compassHeading ?? _state.compassHeadingDegrees,
      pendingImageBytes: clearPendingImage
          ? null
          : pendingImageBytes ?? _state.pendingImageBytes,
      qualityReport: clearPendingImage
          ? null
          : qualityReport ?? _state.qualityReport,
      lastCreatedCapture: lastCreatedCapture ?? _state.lastCreatedCapture,
      isCapturing: isCapturing ?? _state.isCapturing,
      isSaving: isSaving ?? _state.isSaving,
      isGettingLocation: isGettingLocation ?? _state.isGettingLocation,
    );
  }

  void _setState(CaptureState newState) {
    _state = newState;
    notifyListeners();
  }

  @override
  void dispose() {
    unawaited(_compassSubscription?.cancel());
    unawaited(_cameraService.disposeCamera());
    super.dispose();
  }
}
