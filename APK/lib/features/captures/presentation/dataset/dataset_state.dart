import 'dart:typed_data';

import '../../domain/entities/capture.dart';

class DatasetState {
  const DatasetState({
    this.captures = const <Capture>[],
    this.filteredCaptures = const <Capture>[],
    this.imageBytesById = const <String, Uint8List>{},
    this.selectedCaptureIds = const <String>{},
    this.selectedCapture,
    this.isLoading = false,
    this.isMutating = false,
    this.message = '',
  });

  final List<Capture> captures;
  final List<Capture> filteredCaptures;
  final Map<String, Uint8List> imageBytesById;
  final Set<String> selectedCaptureIds;
  final Capture? selectedCapture;
  final bool isLoading;
  final bool isMutating;
  final String message;
}
