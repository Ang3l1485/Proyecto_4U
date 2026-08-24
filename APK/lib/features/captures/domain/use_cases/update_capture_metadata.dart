import '../entities/capture.dart';
import '../entities/capture_metadata.dart';
import '../repositories/capture_repository.dart';
import 'capture_validation.dart';

class CaptureMetadataChanges {
  const CaptureMetadataChanges({
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

class UpdateCaptureMetadata {
  const UpdateCaptureMetadata(this._repository);

  final CaptureRepository _repository;

  Future<Capture> updateCaptureMetadata(
    Capture existingCapture,
    CaptureMetadataChanges changes,
  ) {
    final CaptureMetadata updatedMetadata = existingCapture.metadata.copyWith(
      block: changes.block.trim(),
      latitude: changes.latitude,
      longitude: changes.longitude,
      author: changes.author.trim(),
      status: changes.status,
    );
    validateCaptureMetadata(updatedMetadata);
    return _repository.updateCaptureMetadata(
      existingCapture.id,
      updatedMetadata,
    );
  }
}
