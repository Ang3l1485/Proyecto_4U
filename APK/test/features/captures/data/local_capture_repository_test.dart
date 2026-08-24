import 'dart:io';
import 'dart:typed_data';

import 'package:dataset_app/core/errors/capture_storage_exception.dart';
import 'package:dataset_app/features/captures/data/repositories/local_capture_repository.dart';
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

CaptureMetadata _metadata() {
  return CaptureMetadata(
    block: 'A',
    latitude: 4.635,
    longitude: -74.082,
    timestamp: DateTime(2026, 8, 23, 10),
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
