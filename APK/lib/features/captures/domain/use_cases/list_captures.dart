import '../entities/capture.dart';
import '../repositories/capture_repository.dart';

class ListCaptures {
  const ListCaptures(this._repository);

  final CaptureRepository _repository;

  Future<List<Capture>> listCaptures() => _repository.listCaptures();
}
