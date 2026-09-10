import 'dart:typed_data';

import 'package:flutter/widgets.dart';

enum CameraAvailability {
  checking,
  ready,
  denied,
  permanentlyDenied,
  unavailable,
}

class CameraInitializationResult {
  const CameraInitializationResult({
    required this.availability,
    required this.message,
  });

  final CameraAvailability availability;
  final String message;
}

abstract interface class CameraService {
  Future<CameraInitializationResult> initializeCamera();
  Widget buildPreview();
  Future<Uint8List> takePhoto();
  Future<void> openApplicationSettings();
  Future<void> disposeCamera();
}
