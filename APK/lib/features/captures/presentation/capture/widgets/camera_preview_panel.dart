import 'package:flutter/material.dart';

class CameraPreviewPanel extends StatelessWidget {
  const CameraPreviewPanel({
    super.key,
    required this.preview,
    required this.isAvailable,
    required this.message,
  });

  final Widget preview;
  final bool isAvailable;
  final String message;

  @override
  Widget build(BuildContext context) {
    return AspectRatio(
      aspectRatio: 4 / 3,
      child: DecoratedBox(
        decoration: BoxDecoration(
          color: Colors.black,
          borderRadius: BorderRadius.circular(12),
        ),
        child: ClipRRect(
          borderRadius: BorderRadius.circular(12),
          child: isAvailable
              ? preview
              : Center(
                  child: Padding(
                    padding: const EdgeInsets.all(24),
                    child: Text(
                      message,
                      textAlign: TextAlign.center,
                      style: const TextStyle(color: Colors.white),
                    ),
                  ),
                ),
        ),
      ),
    );
  }
}
