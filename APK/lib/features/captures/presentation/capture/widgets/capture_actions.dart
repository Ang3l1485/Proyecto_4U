import 'package:flutter/material.dart';

class CaptureActions extends StatelessWidget {
  const CaptureActions({
    super.key,
    required this.isCameraAvailable,
    required this.isCapturing,
    required this.isSaving,
    required this.hasPendingImage,
    required this.isRejected,
    required this.hasLastCapture,
    required this.onCapturePhoto,
    required this.onCaptureSequence,
    required this.onPickGallery,
    required this.onSave,
    required this.onSaveRejected,
    required this.onDiscard,
    required this.onDownloadJson,
  });

  final bool isCameraAvailable;
  final bool isCapturing;
  final bool isSaving;
  final bool hasPendingImage;
  final bool isRejected;
  final bool hasLastCapture;
  final VoidCallback onCapturePhoto;
  final VoidCallback onCaptureSequence;
  final VoidCallback onPickGallery;
  final VoidCallback onSave;
  final VoidCallback onSaveRejected;
  final VoidCallback onDiscard;
  final VoidCallback onDownloadJson;

  @override
  Widget build(BuildContext context) {
    return Wrap(
      spacing: 10,
      runSpacing: 10,
      children: <Widget>[
        FilledButton.icon(
          onPressed: isCameraAvailable && !isCapturing ? onCapturePhoto : null,
          icon: const Icon(Icons.photo_camera),
          label: const Text('Foto instantánea'),
        ),
        OutlinedButton.icon(
          onPressed: isCameraAvailable && !isCapturing
              ? onCaptureSequence
              : null,
          icon: const Icon(Icons.burst_mode),
          label: const Text('Capturar 5 s'),
        ),
        OutlinedButton.icon(
          onPressed: isCapturing || isSaving ? null : onPickGallery,
          icon: const Icon(Icons.image_outlined),
          label: const Text('Abrir galería'),
        ),
        if (hasPendingImage && !isRejected)
          FilledButton.icon(
            onPressed: isSaving ? null : onSave,
            icon: const Icon(Icons.save_outlined),
            label: const Text('Guardar captura'),
          ),
        if (hasPendingImage && isRejected)
          FilledButton.icon(
            onPressed: isSaving ? null : onSaveRejected,
            icon: const Icon(Icons.warning_amber),
            label: const Text('Guardar de todas formas'),
          ),
        if (hasPendingImage)
          TextButton.icon(
            onPressed: isSaving ? null : onDiscard,
            icon: const Icon(Icons.close),
            label: const Text('Descartar'),
          ),
        if (hasLastCapture)
          OutlinedButton.icon(
            onPressed: onDownloadJson,
            icon: const Icon(Icons.download),
            label: const Text('Descargar JSON'),
          ),
      ],
    );
  }
}
