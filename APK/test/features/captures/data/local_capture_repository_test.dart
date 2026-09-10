import 'dart:io';
import 'dart:typed_data';

import 'package:dataset_app/core/errors/capture_storage_exception.dart';
import 'package:dataset_app/features/captures/data/repositories/local_capture_repository.dart';
import 'package:dataset_app/features/captures/data/sources/atomic_file_writer.dart';
import 'package:dataset_app/features/captures/data/sources/capture_file_store.dart';
import 'package:dataset_app/features/captures/data/sources/exif_metadata_writer.dart';
import 'package:dataset_app/features/captures/data/sources/manifest_store.dart';
import 'package:dataset_app/features/captures/domain/entities/capture.dart';
import 'package:dataset_app/features/captures/domain/entities/capture_metadata.dart';
import 'package:dataset_app/features/captures/domain/entities/image_quality_report.dart';
import 'package:dataset_app/features/captures/domain/repositories/capture_repository.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:image/image.dart' as image;

void main() {
  late Directory testDirectory;
  late LocalCaptureRepository repository;

  setUp(() async {
    testDirectory = await Directory.systemTemp.createTemp(
      'dataset_app_repository_test_',
    );
    repository = LocalCaptureRepository.inDirectory(testDirectory);
  });

  tearDown(() async {
    if (await testDirectory.exists()) {
      await testDirectory.delete(recursive: true);
    }
  });

  test('creates, lists, updates and deletes local captures', () async {
    final Capture created = await repository.createCapture(
      CreateCaptureRequest(
        imageBytes: _jpegBytes(),
        metadata: _metadata(),
        quality: _quality(),
        wasQualityOverride: false,
      ),
    );

    expect(await File(created.imagePath).exists(), isTrue);
    expect(await File(created.metadataPath).exists(), isTrue);
    expect(await repository.listCaptures(), hasLength(1));

    final Capture updated = await repository.updateCaptureMetadata(
      created.id,
      created.metadata.copyWith(author: 'Autora editada'),
    );
    expect(updated.metadata.author, 'Autora editada');
    expect(updated.metadata.compassHeadingDegrees, 45);

    await repository.deleteCaptures(<String>{created.id});
    expect(await repository.listCaptures(), isEmpty);
    expect(await File(created.imagePath).exists(), isFalse);
    expect(await File(created.metadataPath).exists(), isFalse);
  });

  test('does not overwrite a corrupt manifest', () async {
    final File manifest = File(
      '${testDirectory.path}${Platform.pathSeparator}manifest.json',
    );
    await manifest.writeAsString('{not-json', flush: true);

    await expectLater(
      repository.listCaptures(),
      throwsA(isA<CaptureStorageException>()),
    );
    expect(await manifest.readAsString(), '{not-json');
  });

  test('updates metadata without writing the physical image', () async {
    final Capture created = await repository.createCapture(
      CreateCaptureRequest(
        imageBytes: _jpegBytes(),
        metadata: _metadata(),
        quality: _quality(),
        wasQualityOverride: false,
      ),
    );
    final List<int> originalImageBytes = await File(
      created.imagePath,
    ).readAsBytes();
    final _TrackingCaptureFileStore fileStore = _TrackingCaptureFileStore(
      datasetDirectory: testDirectory,
    );
    final LocalCaptureRepository trackingRepository = LocalCaptureRepository(
      fileStore: fileStore,
      manifestStore: ManifestStore(datasetDirectory: testDirectory),
      exifMetadataWriter: const ExifMetadataWriter(),
    );

    await trackingRepository.updateCaptureMetadata(
      created.id,
      created.metadata.copyWith(author: 'Autora editada'),
    );

    expect(fileStore.writeImageCallCount, 0);
    expect(await File(created.imagePath).readAsBytes(), originalImageBytes);
  });

  test('rolls back JSON without touching the image when manifest write fails',
      () async {
    final Capture created = await repository.createCapture(
      CreateCaptureRequest(
        imageBytes: _jpegBytes(),
        metadata: _metadata(),
        quality: _quality(),
        wasQualityOverride: false,
      ),
    );
    final List<int> originalImageBytes = await File(
      created.imagePath,
    ).readAsBytes();
    final _TrackingCaptureFileStore fileStore = _TrackingCaptureFileStore(
      datasetDirectory: testDirectory,
    );
    final ManifestStore manifestStore = ManifestStore(
      datasetDirectory: testDirectory,
      atomicFileWriter: const _FailingManifestWriter(),
    );
    final LocalCaptureRepository failingRepository = LocalCaptureRepository(
      fileStore: fileStore,
      manifestStore: manifestStore,
      exifMetadataWriter: const ExifMetadataWriter(),
    );

    await expectLater(
      failingRepository.updateCaptureMetadata(
        created.id,
        created.metadata.copyWith(author: 'No debe persistir'),
      ),
      throwsA(isA<CaptureStorageException>()),
    );

    expect(fileStore.writeImageCallCount, 0);
    expect(await File(created.imagePath).readAsBytes(), originalImageBytes);
    final List<Capture> restoredCaptures = await manifestStore.readCaptures();
    expect(restoredCaptures.single.metadata.author, created.metadata.author);
  });

  test('omits records whose image file is missing', () async {
    final Capture created = await repository.createCapture(
      CreateCaptureRequest(
        imageBytes: _jpegBytes(),
        metadata: _metadata(),
        quality: _quality(),
        wasQualityOverride: false,
      ),
    );
    await File(created.imagePath).delete();

    expect(await repository.listCaptures(), isEmpty);
  });

  test(
    'preserves a capture in the manifest when file deletion fails',
    () async {
      final Capture capture = Capture(
        id: 'capture-to-keep',
        imagePath: '${testDirectory.path}/images/capture-to-keep.jpg',
        metadataPath: '${testDirectory.path}/metadata/capture-to-keep.json',
        metadata: _metadata(),
        quality: _quality(),
        wasQualityOverride: false,
      );
      final ManifestStore manifestStore = ManifestStore(
        datasetDirectory: testDirectory,
      );
      await manifestStore.writeCaptures(<Capture>[capture]);
      final _MockCaptureFileStore fileStore = _MockCaptureFileStore(
        datasetDirectory: testDirectory,
        failure: StateError('delete failed'),
      );
      final LocalCaptureRepository failingRepository = LocalCaptureRepository(
        fileStore: fileStore,
        manifestStore: manifestStore,
        exifMetadataWriter: const ExifMetadataWriter(),
      );

      await expectLater(
        failingRepository.deleteCaptures(<String>{capture.id}),
        throwsA(isA<CaptureStorageException>()),
      );

      final List<Capture> manifestCaptures = await manifestStore.readCaptures();
      expect(
        manifestCaptures.map((Capture item) => item.id),
        contains(capture.id),
      );
      expect(fileStore.deleteCallCount, 1);
    },
  );

  test('persists the catalog values for new campus zones', () async {
    final Capture biblioteca = await repository.createCapture(
      CreateCaptureRequest(
        imageBytes: _jpegBytes(),
        metadata: _metadata(
          block: CampusZone.bloque32.persistedValue,
          timestamp: DateTime(2026, 8, 23, 10, 1),
        ),
        quality: _quality(),
        wasQualityOverride: false,
      ),
    );
    final Capture bloque38 = await repository.createCapture(
      CreateCaptureRequest(
        imageBytes: _jpegBytes(),
        metadata: _metadata(
          block: CampusZone.bloque38.persistedValue,
          timestamp: DateTime(2026, 8, 23, 10, 2),
        ),
        quality: _quality(),
        wasQualityOverride: false,
      ),
    );

    final List<Capture> captures = await repository.listCaptures();
    expect(
      captures
          .firstWhere((Capture item) => item.id == biblioteca.id)
          .metadata
          .block,
      'Biblioteca',
    );
    expect(
      captures
          .firstWhere((Capture item) => item.id == bloque38.id)
          .metadata
          .block,
      'bloque38',
    );
  });
}

class _MockCaptureFileStore extends CaptureFileStore {
  _MockCaptureFileStore({
    required super.datasetDirectory,
    required this.failure,
  });

  final Object failure;
  int deleteCallCount = 0;

  @override
  Future<void> deleteCaptureFiles(CapturePaths paths) async {
    deleteCallCount++;
    throw failure;
  }
}

class _TrackingCaptureFileStore extends CaptureFileStore {
  _TrackingCaptureFileStore({required super.datasetDirectory});

  int writeImageCallCount = 0;

  @override
  Future<void> writeImage(String imagePath, Uint8List bytes) async {
    writeImageCallCount++;
    await super.writeImage(imagePath, bytes);
  }
}

class _FailingManifestWriter extends AtomicFileWriter {
  const _FailingManifestWriter();

  @override
  Future<void> writeBytes(File target, Uint8List bytes) {
    if (target.path.endsWith('manifest.json')) {
      throw StateError('manifest write failed');
    }
    return super.writeBytes(target, bytes);
  }
}

Uint8List _jpegBytes() {
  final image.Image source = image.Image(width: 16, height: 16);
  for (int y = 0; y < source.height; y++) {
    for (int x = 0; x < source.width; x++) {
      source.setPixelRgb(x, y, x * 10, y * 10, 120);
    }
  }
  return Uint8List.fromList(image.encodeJpg(source));
}

CaptureMetadata _metadata({String block = 'A', DateTime? timestamp}) {
  return CaptureMetadata(
    block: block,
    latitude: 4.635,
    longitude: -74.082,
    timestamp: timestamp ?? DateTime(2026, 8, 23, 10),
    author: 'Test',
    sessionId: 'session',
    status: MetadataStatus.complete,
    compassHeadingDegrees: 45,
    compassDirection: 'NE',
  );
}

ImageQualityReport _quality() {
  return const ImageQualityReport(
    width: 16,
    height: 16,
    averageBrightness: 100,
    sharpnessScore: 20,
    rejectionReasons: <String>[],
  );
}
