import 'dart:typed_data';

import '../entities/capture.dart';
import '../entities/capture_metadata.dart';
import '../entities/image_quality_report.dart';
import '../repositories/capture_repository.dart';
import 'capture_validation.dart';

class CreateCapture {
  const CreateCapture(this._repository);

  final CaptureRepository _repository;

  Future<Capture> createCapture({
    required Uint8List imageBytes,
    required CaptureMetadata metadata,
    required ImageQualityReport quality,
    required bool allowQualityOverride,
  }) {
    validateCaptureMetadata(metadata);
    if (imageBytes.isEmpty) {
      throw const CaptureValidationException('La imagen está vacía.');
    }
    if (!quality.isAccepted && !allowQualityOverride) {
      throw const CaptureValidationException(
        'La imagen fue rechazada. Usa “Guardar de todas formas” para registrar una excepción explícita.',
      );
    }
    return _repository.createCapture(
      CreateCaptureRequest(
        imageBytes: imageBytes,
        metadata: metadata,
        quality: quality,
        wasQualityOverride: !quality.isAccepted && allowQualityOverride,
      ),
    );
  }
}
