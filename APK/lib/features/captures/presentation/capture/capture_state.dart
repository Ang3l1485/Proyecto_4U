import 'dart:typed_data';

import '../../../../platform/camera/camera_service.dart';
import '../../domain/entities/capture.dart';
import '../../domain/entities/image_quality_report.dart';

class CaptureState {
  const CaptureState({
    this.cameraAvailability = CameraAvailability.checking,
    this.statusMessage = 'Preparando servicios de captura…',
    this.compassMessage = 'Verificando brújula…',
    this.compassHeadingDegrees,
    this.pendingImageBytes,
    this.qualityReport,
    this.lastCreatedCapture,
    this.isCapturing = false,
    this.isSaving = false,
    this.isGettingLocation = false,
  });

  final CameraAvailability cameraAvailability;
  final String statusMessage;
  final String compassMessage;
  final double? compassHeadingDegrees;
  final Uint8List? pendingImageBytes;
  final ImageQualityReport? qualityReport;
  final Capture? lastCreatedCapture;
  final bool isCapturing;
  final bool isSaving;
  final bool isGettingLocation;

  bool get hasPendingImage => pendingImageBytes != null;
  bool get canUseCamera => cameraAvailability == CameraAvailability.ready;
}
