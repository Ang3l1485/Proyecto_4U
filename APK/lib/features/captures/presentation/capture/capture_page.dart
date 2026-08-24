import 'package:flutter/material.dart';

import '../../../../platform/camera/camera_service.dart';
import '../../../../platform/location/location_service.dart';
import 'capture_controller.dart';
import 'capture_state.dart';
import 'widgets/camera_preview_panel.dart';
import 'widgets/capture_actions.dart';
import 'widgets/capture_form.dart';
import 'widgets/quality_report_card.dart';

class CapturePage extends StatefulWidget {
  const CapturePage({super.key, required this.controller});

  final CaptureController controller;

  @override
  State<CapturePage> createState() => _CapturePageState();
}

class _CapturePageState extends State<CapturePage> {
  final GlobalKey<CaptureFormState> _captureFormKey =
      GlobalKey<CaptureFormState>();

  @override
  void initState() {
    super.initState();
    widget.controller.initialize();
  }

  @override
  void dispose() {
    widget.controller.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return AnimatedBuilder(
      animation: widget.controller,
      builder: (BuildContext context, Widget? child) {
        final CaptureState state = widget.controller.state;
        return ListView(
          padding: const EdgeInsets.all(16),
          children: <Widget>[
            CameraPreviewPanel(
              preview: widget.controller.buildCameraPreview(),
              isAvailable: state.canUseCamera,
              message: state.statusMessage,
            ),
            const SizedBox(height: 12),
            _StatusCard(state: state),
            if (state.cameraAvailability ==
                CameraAvailability.permanentlyDenied)
              Align(
                alignment: Alignment.centerLeft,
                child: TextButton.icon(
                  onPressed: widget.controller.openCameraSettings,
                  icon: const Icon(Icons.settings),
                  label: const Text('Abrir configuración'),
                ),
              )
            else if (!state.canUseCamera &&
                state.cameraAvailability != CameraAvailability.checking)
              Align(
                alignment: Alignment.centerLeft,
                child: TextButton.icon(
                  onPressed: widget.controller.retryCamera,
                  icon: const Icon(Icons.refresh),
                  label: const Text('Reintentar cámara'),
                ),
              ),
            const SizedBox(height: 12),
            CaptureForm(
              key: _captureFormKey,
              sessionId: widget.controller.sessionId,
              isGettingLocation: state.isGettingLocation,
              onRequestLocation: _requestLocation,
            ),
            const SizedBox(height: 12),
            if (state.pendingImageBytes != null) ...<Widget>[
              ClipRRect(
                borderRadius: BorderRadius.circular(12),
                child: Image.memory(
                  state.pendingImageBytes!,
                  height: 240,
                  fit: BoxFit.cover,
                  errorBuilder:
                      (BuildContext context, Object error, StackTrace? stack) {
                        return const SizedBox(
                          height: 120,
                          child: Center(
                            child: Text('No se pudo mostrar la imagen.'),
                          ),
                        );
                      },
                ),
              ),
              const SizedBox(height: 12),
            ],
            if (state.qualityReport != null)
              QualityReportCard(report: state.qualityReport!),
            const SizedBox(height: 12),
            CaptureActions(
              isCameraAvailable: state.canUseCamera,
              isCapturing: state.isCapturing,
              isSaving: state.isSaving,
              hasPendingImage: state.hasPendingImage,
              isRejected: state.qualityReport?.isAccepted == false,
              onCapturePhoto: _capturePhoto,
              onCaptureSequence: _captureSequence,
              onPickGallery: widget.controller.pickGalleryImage,
              onSave: () => _saveCapture(allowQualityOverride: false),
              onSaveRejected: _confirmQualityOverride,
              onDiscard: widget.controller.discardPendingImage,
            ),
          ],
        );
      },
    );
  }

  Future<void> _requestLocation() async {
    final CurrentLocation? location = await widget.controller
        .getCurrentLocation();
    if (mounted && location != null) {
      _captureFormKey.currentState?.setCoordinates(
        latitude: location.latitude,
        longitude: location.longitude,
      );
    }
  }

  Future<void> _capturePhoto() async {
    if (_captureFormKey.currentState?.validateAndRead() == null) {
      return;
    }
    await widget.controller.capturePhoto();
  }

  Future<void> _captureSequence() async {
    if (_captureFormKey.currentState?.validateAndRead() == null) {
      return;
    }
    await widget.controller.captureSequence();
  }

  Future<void> _saveCapture({required bool allowQualityOverride}) async {
    final CaptureFormData? formData = _captureFormKey.currentState
        ?.validateAndRead();
    if (formData == null) {
      return;
    }
    final bool wasCreated = await widget.controller.createPendingCapture(
      NewCaptureMetadata(
        block: formData.block,
        latitude: formData.latitude,
        longitude: formData.longitude,
        author: formData.author,
        status: formData.status,
      ),
      allowQualityOverride: allowQualityOverride,
    );
    if (mounted && wasCreated) {
      _captureFormKey.currentState?.clearAfterSave();
    }
  }

  Future<void> _confirmQualityOverride() async {
    final bool confirmed =
        await showDialog<bool>(
          context: context,
          builder: (BuildContext context) {
            return AlertDialog(
              title: const Text('Guardar imagen rechazada'),
              content: const Text(
                'Esta acción conservará la imagen y registrará que la regla de calidad fue anulada explícitamente.',
              ),
              actions: <Widget>[
                TextButton(
                  onPressed: () => Navigator.of(context).pop(false),
                  child: const Text('Cancelar'),
                ),
                FilledButton(
                  onPressed: () => Navigator.of(context).pop(true),
                  child: const Text('Guardar de todas formas'),
                ),
              ],
            );
          },
        ) ??
        false;
    if (mounted && confirmed) {
      await _saveCapture(allowQualityOverride: true);
    }
  }
}

class _StatusCard extends StatelessWidget {
  const _StatusCard({required this.state});

  final CaptureState state;

  @override
  Widget build(BuildContext context) {
    final double? heading = state.compassHeadingDegrees;
    final String compass = heading == null
        ? state.compassMessage
        : 'Brújula: ${heading.toStringAsFixed(0)}°';
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(12),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: <Widget>[
            Text(state.statusMessage),
            const SizedBox(height: 4),
            Text(compass),
          ],
        ),
      ),
    );
  }
}
