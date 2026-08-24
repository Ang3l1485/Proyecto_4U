import 'dart:typed_data';

import 'package:dataset_app/features/captures/domain/entities/capture.dart';
import 'package:dataset_app/features/captures/domain/entities/capture_metadata.dart';
import 'package:dataset_app/features/captures/domain/entities/image_quality_report.dart';
import 'package:dataset_app/features/captures/domain/repositories/capture_repository.dart';
import 'package:dataset_app/features/captures/domain/use_cases/update_capture_metadata.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  test(
    'editing preserves timestamp, session, heading and quality data',
    () async {
      final _MemoryCaptureRepository repository = _MemoryCaptureRepository();
      final Capture existing = _capture();
      repository.capture = existing;
      final UpdateCaptureMetadata update = UpdateCaptureMetadata(repository);

      final Capture result = await update.updateCaptureMetadata(
        existing,
        const CaptureMetadataChanges(
          block: 'B',
          latitude: 5,
          longitude: -73,
          author: 'Nuevo autor',
          status: MetadataStatus.complete,
        ),
      );

      expect(result.metadata.block, 'B');
      expect(result.metadata.timestamp, existing.metadata.timestamp);
      expect(result.metadata.sessionId, existing.metadata.sessionId);
      expect(result.metadata.compassHeadingDegrees, 173.4);
      expect(result.metadata.compassDirection, 'S');
      expect(result.quality, same(existing.quality));
      expect(result.wasQualityOverride, isTrue);
    },
  );
}

Capture _capture() {
  return Capture(
    id: 'id-1',
    imagePath: 'image.jpg',
    metadataPath: 'metadata.json',
    metadata: CaptureMetadata(
      block: 'A',
      latitude: 4,
      longitude: -74,
      timestamp: DateTime(2026, 8, 23, 9),
      author: 'Autor',
      sessionId: 'session',
      status: MetadataStatus.pending,
      compassHeadingDegrees: 173.4,
      compassDirection: 'S',
    ),
    quality: const ImageQualityReport(
      width: 100,
      height: 100,
      averageBrightness: 90,
      sharpnessScore: 20,
      rejectionReasons: <String>[],
    ),
    wasQualityOverride: true,
  );
}

class _MemoryCaptureRepository implements CaptureRepository {
  late Capture capture;

  @override
  Future<Capture> updateCaptureMetadata(
    String captureId,
    CaptureMetadata metadata,
  ) async {
    capture = capture.copyWith(metadata: metadata);
    return capture;
  }

  @override
  Future<Capture> createCapture(CreateCaptureRequest request) {
    throw UnimplementedError();
  }

  @override
  Future<void> deleteCaptures(Set<String> captureIds) async {}

  @override
  Future<List<Capture>> listCaptures() async => <Capture>[capture];

  @override
  Future<Uint8List> readCaptureImage(String captureId) async => Uint8List(0);
}
