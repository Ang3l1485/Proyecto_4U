import 'package:dataset_app/features/captures/domain/entities/capture.dart';
import 'package:dataset_app/features/captures/domain/entities/capture_metadata.dart';
import 'package:dataset_app/features/captures/domain/entities/image_quality_report.dart';
import 'package:dataset_app/features/captures/presentation/capture/widgets/capture_form.dart';
import 'package:dataset_app/features/captures/presentation/dataset/widgets/capture_editor.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  testWidgets('CaptureForm offers every campus zone', (
    WidgetTester tester,
  ) async {
    await tester.pumpWidget(
      MaterialApp(
        home: Scaffold(
          body: CaptureForm(
            key: GlobalKey<CaptureFormState>(),
            sessionId: 'session',
            isGettingLocation: false,
            onRequestLocation: () {},
          ),
        ),
      ),
    );

    await tester.tap(find.byType(DropdownButtonFormField<CampusZone>));
    await tester.pumpAndSettle();
    expect(find.text('Biblioteca'), findsOneWidget);
    expect(find.text('Bloque 38'), findsOneWidget);
  });

  testWidgets('CaptureEditor offers every campus zone', (
    WidgetTester tester,
  ) async {
    final Capture capture = Capture(
      id: 'capture',
      imagePath: 'image.jpg',
      metadataPath: 'metadata.json',
      metadata: _metadata(),
      quality: const ImageQualityReport(
        width: 1,
        height: 1,
        averageBrightness: 1,
        sharpnessScore: 1,
        rejectionReasons: <String>[],
      ),
      wasQualityOverride: false,
    );

    await tester.pumpWidget(
      MaterialApp(
        home: Scaffold(
          body: CaptureEditor(
            capture: capture,
            isSaving: false,
            onSave: (_) {},
            onCancel: () {},
          ),
        ),
      ),
    );

    await tester.tap(find.byType(DropdownButtonFormField<CampusZone>));
    await tester.pumpAndSettle();
    expect(find.text('Biblioteca'), findsNWidgets(2));
    expect(find.text('Bloque 38'), findsOneWidget);
  });
}

CaptureMetadata _metadata() {
  return CaptureMetadata(
    block: CampusZone.bloque32.persistedValue,
    latitude: 4,
    longitude: -74,
    timestamp: DateTime(2026),
    author: 'Test',
    sessionId: 'session',
    status: MetadataStatus.pending,
  );
}