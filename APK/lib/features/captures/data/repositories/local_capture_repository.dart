import 'dart:io';
import 'dart:typed_data';

import '../../../../core/errors/capture_storage_exception.dart';
import '../../domain/entities/capture.dart';
import '../../domain/entities/capture_metadata.dart';
import '../../domain/repositories/capture_repository.dart';
import '../sources/capture_file_store.dart';
import '../sources/exif_metadata_writer.dart';
import '../sources/manifest_store.dart';

class LocalCaptureRepository implements CaptureRepository {
  LocalCaptureRepository({
    required CaptureFileStore fileStore,
    required ManifestStore manifestStore,
    required ExifMetadataWriter exifMetadataWriter,
  }) : _fileStore = fileStore,
       _manifestStore = manifestStore,
       _exifMetadataWriter = exifMetadataWriter;

  factory LocalCaptureRepository.inDirectory(Directory datasetDirectory) {
    return LocalCaptureRepository(
      fileStore: CaptureFileStore(datasetDirectory: datasetDirectory),
      manifestStore: ManifestStore(datasetDirectory: datasetDirectory),
      exifMetadataWriter: const ExifMetadataWriter(),
    );
  }

  final CaptureFileStore _fileStore;
  final ManifestStore _manifestStore;
  final ExifMetadataWriter _exifMetadataWriter;

  @override
  Future<Capture> createCapture(CreateCaptureRequest request) async {
    final String captureId = _buildCaptureId(request.metadata);
    final CapturePaths paths = _fileStore.pathsFor(captureId);
    final Uint8List jpegBytes = _exifMetadataWriter.writeMetadata(
      request.imageBytes,
      request.metadata,
    );
    final Capture capture = Capture(
      id: captureId,
      imagePath: paths.imagePath,
      metadataPath: paths.metadataPath,
      metadata: request.metadata,
      quality: request.quality,
      wasQualityOverride: request.wasQualityOverride,
    );

    try {
      final List<Capture> captures = await _manifestStore.readCaptures();
      await _fileStore.writeImage(paths.imagePath, jpegBytes);
      await _fileStore.writeMetadata(paths.metadataPath, capture.toJson());
      await _manifestStore.writeCaptures(<Capture>[...captures, capture]);
      return capture;
    } catch (error) {
      await _fileStore.deleteCaptureFiles(paths);
      if (error is CaptureStorageException) {
        rethrow;
      }
      throw CaptureStorageException('No fue posible crear la captura.', error);
    }
  }

  @override
  Future<List<Capture>> listCaptures() async {
    final List<Capture> manifestCaptures = await _manifestStore.readCaptures();
    final List<Capture> availableCaptures = <Capture>[];
    for (final Capture capture in manifestCaptures) {
      final CapturePaths paths = CapturePaths(
        imagePath: capture.imagePath,
        metadataPath: capture.metadataPath,
      );
      if (await _fileStore.captureFilesExist(paths)) {
        availableCaptures.add(capture);
      }
    }
    availableCaptures.sort(
      (Capture first, Capture second) =>
          second.metadata.timestamp.compareTo(first.metadata.timestamp),
    );
    return availableCaptures;
  }

  @override
  Future<Uint8List> readCaptureImage(String captureId) async {
    final Capture capture = await _findCapture(captureId);
    return _fileStore.readImage(capture.imagePath);
  }

  @override
  Future<Capture> updateCaptureMetadata(
    String captureId,
    CaptureMetadata metadata,
  ) async {
    final List<Capture> captures = await _manifestStore.readCaptures();
    final int index = captures.indexWhere(
      (Capture capture) => capture.id == captureId,
    );
    if (index < 0) {
      throw CaptureStorageException('No se encontró la captura $captureId.');
    }

    final Capture original = captures[index];
    final Capture updated = original.copyWith(metadata: metadata);
    final Uint8List originalImage = await _fileStore.readImage(
      original.imagePath,
    );
    final Uint8List updatedImage = _exifMetadataWriter.writeMetadata(
      originalImage,
      metadata,
    );

    try {
      await _fileStore.writeImage(updated.imagePath, updatedImage);
      await _fileStore.writeMetadata(updated.metadataPath, updated.toJson());
      captures[index] = updated;
      await _manifestStore.writeCaptures(captures);
      return updated;
    } catch (error) {
      await _fileStore.writeImage(original.imagePath, originalImage);
      await _fileStore.writeMetadata(original.metadataPath, original.toJson());
      throw CaptureStorageException(
        'No fue posible actualizar la captura $captureId.',
        error,
      );
    }
  }

  @override
  Future<void> deleteCaptures(Set<String> captureIds) async {
    final List<Capture> captures = await _manifestStore.readCaptures();
    final List<Capture> removed = captures
        .where((Capture capture) => captureIds.contains(capture.id))
        .toList(growable: false);
    final List<Capture> remaining = captures
        .where((Capture capture) => !captureIds.contains(capture.id))
        .toList(growable: false);

    await _manifestStore.writeCaptures(remaining);
    for (final Capture capture in removed) {
      await _fileStore.deleteCaptureFiles(
        CapturePaths(
          imagePath: capture.imagePath,
          metadataPath: capture.metadataPath,
        ),
      );
    }
  }

  Future<Capture> _findCapture(String captureId) async {
    final List<Capture> captures = await _manifestStore.readCaptures();
    for (final Capture capture in captures) {
      if (capture.id == captureId) {
        return capture;
      }
    }
    throw CaptureStorageException('No se encontró la captura $captureId.');
  }

  String _buildCaptureId(CaptureMetadata metadata) {
    final String safeBlock = _sanitize(metadata.block);
    final String safeSession = _sanitize(metadata.sessionId);
    return '${safeBlock}_${metadata.timestamp.microsecondsSinceEpoch}_$safeSession';
  }

  String _sanitize(String value) {
    final String result = value.trim().replaceAll(
      RegExp(r'[^a-zA-Z0-9._-]+'),
      '-',
    );
    return result.isEmpty ? 'capture' : result;
  }
}
