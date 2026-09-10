import 'dart:typed_data';

import '../entities/capture.dart';
import '../entities/capture_metadata.dart';
import '../entities/image_quality_report.dart';

class CreateCaptureRequest {
  const CreateCaptureRequest({
    required this.imageBytes,
    required this.metadata,
    required this.quality,
    required this.wasQualityOverride,
  });

  final Uint8List imageBytes;
  final CaptureMetadata metadata;
  final ImageQualityReport quality;
  final bool wasQualityOverride;
}

abstract interface class CaptureRepository {
  Future<Capture> createCapture(CreateCaptureRequest request);
  Future<List<Capture>> listCaptures();
  Future<Capture> updateCaptureMetadata(
    String captureId,
    CaptureMetadata metadata,
  );
  Future<void> deleteCaptures(Set<String> captureIds);
  Future<Uint8List> readCaptureImage(String captureId);
}
