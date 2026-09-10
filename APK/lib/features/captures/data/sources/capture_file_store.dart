import 'dart:io';
import 'dart:typed_data';

import 'atomic_file_writer.dart';

class CapturePaths {
  const CapturePaths({required this.imagePath, required this.metadataPath});

  final String imagePath;
  final String metadataPath;
}

class CaptureFileStore {
  CaptureFileStore({
    required Directory datasetDirectory,
    AtomicFileWriter atomicFileWriter = const AtomicFileWriter(),
  }) : _datasetDirectory = datasetDirectory,
       _atomicFileWriter = atomicFileWriter;

  final Directory _datasetDirectory;
  final AtomicFileWriter _atomicFileWriter;

  CapturePaths pathsFor(String captureId) {
    return CapturePaths(
      imagePath: _join(
        _join(_datasetDirectory.path, 'images'),
        '$captureId.jpg',
      ),
      metadataPath: _join(
        _join(_datasetDirectory.path, 'metadata'),
        '$captureId.json',
      ),
    );
  }

  Future<void> writeImage(String imagePath, Uint8List bytes) {
    return _atomicFileWriter.writeBytes(File(imagePath), bytes);
  }

  Future<void> writeMetadata(
    String metadataPath,
    Map<String, Object?> captureJson,
  ) {
    return _atomicFileWriter.writeJson(File(metadataPath), captureJson);
  }

  Future<Uint8List> readImage(String imagePath) {
    return File(imagePath).readAsBytes();
  }

  Future<bool> captureFilesExist(CapturePaths paths) async {
    return await File(paths.imagePath).exists() &&
        await File(paths.metadataPath).exists();
  }

  Future<void> deleteCaptureFiles(CapturePaths paths) async {
    await _deleteIfPresent(File(paths.imagePath));
    await _deleteIfPresent(File(paths.metadataPath));
  }

  Future<void> _deleteIfPresent(File file) async {
    if (await file.exists()) {
      await file.delete();
    }
  }

  String _join(String parent, String child) {
    return '$parent${Platform.pathSeparator}$child';
  }
}
