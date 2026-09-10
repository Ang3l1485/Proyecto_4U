import 'dart:convert';
import 'dart:io';
import 'dart:typed_data';

import 'package:flutter/services.dart';

/// Copies Android captures to a user-accessible Downloads folder.
abstract interface class PublicDatasetExporter {
  Future<void> exportCapture({
    required String captureId,
    required Uint8List imageBytes,
    required Map<String, Object?> metadata,
  });
  Future<void> exportMetadata({
    required String captureId,
    required Map<String, Object?> metadata,
  });
  Future<void> deleteCapture(String captureId);
}

class AndroidDownloadsDatasetExporter implements PublicDatasetExporter {
  const AndroidDownloadsDatasetExporter();

  static const MethodChannel _channel = MethodChannel(
    'com.example.dataset_app/public_dataset',
  );

  @override
  Future<void> exportCapture({
    required String captureId,
    required Uint8List imageBytes,
    required Map<String, Object?> metadata,
  }) async {
    if (!Platform.isAndroid) return;
    await _channel.invokeMethod<void>('exportCapture', <String, Object?>{
      'captureId': captureId,
      'imageBytes': imageBytes,
      'metadataJson': const JsonEncoder.withIndent('  ').convert(metadata),
    });
  }

  @override
  Future<void> exportMetadata({
    required String captureId,
    required Map<String, Object?> metadata,
  }) async {
    if (!Platform.isAndroid) return;
    await _channel.invokeMethod<void>('exportMetadata', <String, Object?>{
      'captureId': captureId,
      'metadataJson': const JsonEncoder.withIndent('  ').convert(metadata),
    });
  }

  @override
  Future<void> deleteCapture(String captureId) async {
    if (!Platform.isAndroid) return;
    await _channel.invokeMethod<void>('deleteCapture', <String, Object?>{
      'captureId': captureId,
    });
  }
}
