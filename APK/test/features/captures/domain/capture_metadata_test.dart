import 'package:dataset_app/features/captures/domain/entities/capture_metadata.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  test('serializes and deserializes all active metadata fields', () {
    final CaptureMetadata original = CaptureMetadata(
      block: 'B-12',
      latitude: 4.6351,
      longitude: -74.0823,
      timestamp: DateTime.parse('2026-08-23T14:30:00-05:00'),
      author: 'Ana',
      sessionId: 'session-1',
      status: MetadataStatus.complete,
      compassHeadingDegrees: 91.5,
      compassDirection: 'E',
    );

    final Map<String, Object?> json = original.toJson();
    final CaptureMetadata restored = CaptureMetadata.fromJson(json);

    expect(restored.block, original.block);
    expect(restored.latitude, original.latitude);
    expect(restored.longitude, original.longitude);
    expect(restored.timestamp, original.timestamp);
    expect(restored.author, original.author);
    expect(restored.sessionId, original.sessionId);
    expect(restored.status, MetadataStatus.complete);
    expect(restored.compassHeadingDegrees, 91.5);
    expect(restored.compassDirection, 'E');
    expect(json, isNot(contains('zone')));
    expect(json, isNot(contains('place')));
    expect(json, isNot(contains('floor')));
  });

  test('reads legacy JSON while ignoring retired location fields', () {
    final CaptureMetadata metadata = CaptureMetadata.fromJson(<String, Object?>{
      'zone': <String, String>{'id': 'old', 'name': 'Old'},
      'place': <String, String>{'id': 'old', 'name': 'Old'},
      'floor': '3',
      'block': 'A',
      'coordinates': <String, double>{'latitude': 1, 'longitude': 2},
      'timestamp': '2026-08-23T10:00:00',
      'author': 'Luis',
      'sessionId': 'legacy',
      'status': 'pending',
      'compassHeadingDegrees': 225,
    });

    expect(metadata.block, 'A');
    expect(metadata.compassDirection, 'SW');
  });
}
