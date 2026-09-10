import 'dart:typed_data';

import 'package:dataset_app/features/captures/domain/entities/capture.dart';
import 'package:dataset_app/features/captures/domain/entities/capture_metadata.dart';
import 'package:dataset_app/features/captures/domain/entities/image_quality_report.dart';
import 'package:dataset_app/features/captures/domain/repositories/capture_repository.dart';
import 'package:dataset_app/features/captures/domain/use_cases/capture_validation.dart';
import 'package:dataset_app/features/captures/domain/use_cases/create_capture.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  test('requires explicit override for a rejected image', () {
    final CreateCapture create = CreateCapture(_RecordingRepository());

    expect(
      () => create.createCapture(
        imageBytes: Uint8List.fromList(<int>[1]),
        metadata: _metadata(),
        quality: _rejectedQuality(),
        allowQualityOverride: false,
      ),
      throwsA(isA<CaptureValidationException>()),
    );
  });

  test('records the explicit quality override', () async {
    final _RecordingRepository repository = _RecordingRepository();
    final CreateCapture create = CreateCapture(repository);

    final Capture capture = await create.createCapture(
      imageBytes: Uint8List.fromList(<int>[1]),
      metadata: _metadata(),
      quality: _rejectedQuality(),
      allowQualityOverride: true,
    );

    expect(capture.wasQualityOverride, isTrue);
    expect(repository.lastRequest?.wasQualityOverride, isTrue);
  });
}

CaptureMetadata _metadata() {
  return CaptureMetadata(
    block: 'A',
    latitude: 4,
    longitude: -74,
    timestamp: DateTime(2026, 8, 23),
    author: 'Test',
    sessionId: 'session',
    status: MetadataStatus.pending,
  );
}

ImageQualityReport _rejectedQuality() {
  return const ImageQualityReport(
    width: 10,
    height: 10,
    averageBrightness: 0,
    sharpnessScore: 0,
    rejectionReasons: <String>['Oscura'],
  );
}

class _RecordingRepository implements CaptureRepository {
  CreateCaptureRequest? lastRequest;

  @override
  Future<Capture> createCapture(CreateCaptureRequest request) async {
    lastRequest = request;
    return Capture(
      id: 'id',
      imagePath: 'image.jpg',
      metadataPath: 'metadata.json',
      metadata: request.metadata,
      quality: request.quality,
      wasQualityOverride: request.wasQualityOverride,
    );
  }

  @override
  Future<void> deleteCaptures(Set<String> captureIds) async {}

  @override
  Future<List<Capture>> listCaptures() async => <Capture>[];

  @override
  Future<Uint8List> readCaptureImage(String captureId) async => Uint8List(0);

  @override
  Future<Capture> updateCaptureMetadata(
    String captureId,
    CaptureMetadata metadata,
  ) {
    throw UnimplementedError();
  }
}
