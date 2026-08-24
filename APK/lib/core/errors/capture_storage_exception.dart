class CaptureStorageException implements Exception {
  const CaptureStorageException(this.message, [this.cause]);

  final String message;
  final Object? cause;

  @override
  String toString() => message;
}
