import '../repositories/capture_repository.dart';

class DeleteCaptures {
  const DeleteCaptures(this._repository);

  final CaptureRepository _repository;

  Future<void> deleteCaptures(Set<String> captureIds) {
    if (captureIds.isEmpty) {
      return Future<void>.value();
    }
    return _repository.deleteCaptures(captureIds);
  }
}
