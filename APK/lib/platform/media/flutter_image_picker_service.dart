import 'package:flutter/foundation.dart';
import 'package:image_picker/image_picker.dart';

import 'image_picker_service.dart';

class FlutterImagePickerService implements ImagePickerService {
  FlutterImagePickerService({ImagePicker? imagePicker})
    : _imagePicker = imagePicker ?? ImagePicker();

  final ImagePicker _imagePicker;

  @override
  Future<Uint8List?> pickGalleryImage() async {
    final bool isDesktop =
        !kIsWeb &&
        (defaultTargetPlatform == TargetPlatform.windows ||
            defaultTargetPlatform == TargetPlatform.linux ||
            defaultTargetPlatform == TargetPlatform.macOS);
    final XFile? image = await _imagePicker.pickImage(
      source: ImageSource.gallery,
      imageQuality: isDesktop ? null : 90,
    );
    return image?.readAsBytes();
  }
}
