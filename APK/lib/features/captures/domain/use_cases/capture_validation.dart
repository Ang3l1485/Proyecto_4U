import '../entities/capture_metadata.dart';

class CaptureValidationException implements Exception {
  const CaptureValidationException(this.message);

  final String message;

  @override
  String toString() => message;
}

void validateCaptureMetadata(CaptureMetadata metadata) {
  if (metadata.block.trim().isEmpty) {
    throw const CaptureValidationException('El bloque es obligatorio.');
  }
  if (metadata.author.trim().isEmpty) {
    throw const CaptureValidationException(
      'El nombre del recolector es obligatorio.',
    );
  }
  if (metadata.latitude < -90 || metadata.latitude > 90) {
    throw const CaptureValidationException(
      'La latitud debe estar entre -90 y 90.',
    );
  }
  if (metadata.longitude < -180 || metadata.longitude > 180) {
    throw const CaptureValidationException(
      'La longitud debe estar entre -180 y 180.',
    );
  }
}
