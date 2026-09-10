import 'dart:typed_data';

import 'package:dataset_app/app/app.dart';
import 'package:dataset_app/features/captures/domain/entities/capture.dart';
import 'package:dataset_app/features/captures/domain/entities/capture_metadata.dart';
import 'package:dataset_app/features/captures/domain/entities/image_quality_report.dart';
import 'package:dataset_app/features/captures/domain/repositories/capture_repository.dart';
import 'package:dataset_app/features/captures/domain/use_cases/create_capture.dart';
import 'package:dataset_app/features/captures/domain/use_cases/delete_captures.dart';
import 'package:dataset_app/features/captures/domain/use_cases/filter_captures.dart';
import 'package:dataset_app/features/captures/domain/use_cases/list_captures.dart';
import 'package:dataset_app/features/captures/domain/use_cases/update_capture_metadata.dart';
import 'package:dataset_app/features/captures/domain/use_cases/validate_capture.dart';
import 'package:dataset_app/features/captures/presentation/capture/capture_controller.dart';
import 'package:dataset_app/features/captures/presentation/dataset/dataset_controller.dart';
import 'package:dataset_app/platform/camera/camera_service.dart';
import 'package:dataset_app/platform/compass/compass_service.dart';
import 'package:dataset_app/platform/location/location_service.dart';
import 'package:dataset_app/platform/media/image_picker_service.dart';
import 'package:flutter/widgets.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  testWidgets('construye la aplicación principal', (WidgetTester tester) async {
    final CaptureRepository repository = _MemoryCaptureRepository();
    final CaptureController captureController = CaptureController(
      cameraService: _UnavailableCameraService(),
      locationService: _UnusedLocationService(),
      compassService: _UnavailableCompassService(),
      imagePickerService: _EmptyImagePickerService(),
      validateCapture: const ValidateCapture(_AcceptedQualityAnalyzer()),
      createCapture: CreateCapture(repository),
      onCaptureCreated: () async {},
    );
    final DatasetController datasetController = DatasetController(
      repository: repository,
      listCaptures: ListCaptures(repository),
      filterCaptures: const FilterCaptures(),
      updateCaptureMetadata: UpdateCaptureMetadata(repository),
      deleteCaptures: DeleteCaptures(repository),
    );

    await tester.pumpWidget(
      DatasetApp(
        captureController: captureController,
        datasetController: datasetController,
      ),
    );
    await tester.pump();

    expect(find.text('Dataset georreferenciado'), findsOneWidget);

    await tester.pumpWidget(const SizedBox.shrink());
  });
}

class _MemoryCaptureRepository implements CaptureRepository {
  final List<Capture> _captures = <Capture>[];

  @override
  Future<Capture> createCapture(CreateCaptureRequest request) {
    throw UnimplementedError();
  }

  @override
  Future<void> deleteCaptures(Set<String> captureIds) async {
    _captures.removeWhere((Capture capture) => captureIds.contains(capture.id));
  }

  @override
  Future<List<Capture>> listCaptures() async => List<Capture>.of(_captures);

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

class _UnavailableCameraService implements CameraService {
  @override
  Widget buildPreview() => const SizedBox.shrink();

  @override
  Future<void> disposeCamera() async {}

  @override
  Future<CameraInitializationResult> initializeCamera() async {
    return const CameraInitializationResult(
      availability: CameraAvailability.unavailable,
      message: 'Cámara no disponible durante la prueba.',
    );
  }

  @override
  Future<void> openApplicationSettings() async {}

  @override
  Future<Uint8List> takePhoto() {
    throw UnimplementedError();
  }
}

class _UnusedLocationService implements LocationService {
  @override
  Future<CurrentLocation> getCurrentLocation() {
    throw UnimplementedError();
  }
}

class _UnavailableCompassService implements CompassService {
  @override
  String get availabilityMessage => 'Brújula no disponible durante la prueba.';

  @override
  bool get isAvailable => false;

  @override
  Stream<CompassReading> get readings => const Stream<CompassReading>.empty();
}

class _EmptyImagePickerService implements ImagePickerService {
  @override
  Future<Uint8List?> pickGalleryImage() async => null;
}

class _AcceptedQualityAnalyzer implements CaptureQualityAnalyzer {
  const _AcceptedQualityAnalyzer();

  @override
  ImageQualityReport analyzeImage(Uint8List imageBytes) {
    return const ImageQualityReport(
      width: 640,
      height: 480,
      averageBrightness: 100,
      sharpnessScore: 20,
      rejectionReasons: <String>[],
    );
  }
}
