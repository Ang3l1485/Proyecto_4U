import 'dart:typed_data';

import 'package:flutter/material.dart';

import '../../../domain/entities/capture.dart';

class CaptureGrid extends StatefulWidget {
  const CaptureGrid({
    super.key,
    required this.captures,
    required this.onLoadImage,
    required this.selectedCaptureIds,
    required this.onOpen,
    required this.onToggleSelection,
  });

  final List<Capture> captures;
  final Future<Uint8List> Function(String captureId) onLoadImage;
  final Set<String> selectedCaptureIds;
  final ValueChanged<Capture> onOpen;
  final ValueChanged<String> onToggleSelection;

  @override
  State<CaptureGrid> createState() => _CaptureGridState();
}

class _CaptureGridState extends State<CaptureGrid> {
  final Map<String, Future<Uint8List>> _imageFutures =
      <String, Future<Uint8List>>{};

  @override
  void didUpdateWidget(covariant CaptureGrid oldWidget) {
    super.didUpdateWidget(oldWidget);
    final Set<String> captureIds = widget.captures
        .map((Capture capture) => capture.id)
        .toSet();
    _imageFutures.removeWhere(
      (String captureId, Future<Uint8List> _) =>
          !captureIds.contains(captureId),
    );
  }

  @override
  Widget build(BuildContext context) {
    if (widget.captures.isEmpty) {
      return const Padding(
        padding: EdgeInsets.symmetric(vertical: 32),
        child: Center(child: Text('No hay capturas para este filtro.')),
      );
    }
    return GridView.builder(
      shrinkWrap: true,
      physics: const NeverScrollableScrollPhysics(),
      gridDelegate: const SliverGridDelegateWithMaxCrossAxisExtent(
        maxCrossAxisExtent: 260,
        crossAxisSpacing: 8,
        mainAxisSpacing: 8,
        childAspectRatio: 0.82,
      ),
      itemCount: widget.captures.length,
      itemBuilder: (BuildContext context, int index) {
        final Capture capture = widget.captures[index];
        final Future<Uint8List> imageFuture = _imageFutures.putIfAbsent(
          capture.id,
          () => widget.onLoadImage(capture.id),
        );
        return Card(
          clipBehavior: Clip.antiAlias,
          child: InkWell(
            onTap: () => widget.onOpen(capture),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: <Widget>[
                Align(
                  alignment: Alignment.centerRight,
                  child: Checkbox(
                    value: widget.selectedCaptureIds.contains(capture.id),
                    onChanged: (_) => widget.onToggleSelection(capture.id),
                  ),
                ),
                Expanded(
                  child: FutureBuilder<Uint8List>(
                    future: imageFuture,
                    builder:
                        (
                          BuildContext context,
                          AsyncSnapshot<Uint8List> snapshot,
                        ) {
                          if (snapshot.hasError) {
                            return const Center(
                              child: Icon(Icons.broken_image_outlined),
                            );
                          }
                          if (!snapshot.hasData) {
                            return const Center(
                              child: CircularProgressIndicator(),
                            );
                          }
                          return Image.memory(
                            snapshot.requireData,
                            width: double.infinity,
                            fit: BoxFit.cover,
                          );
                        },
                  ),
                ),
                Padding(
                  padding: const EdgeInsets.all(8),
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: <Widget>[
                      Text(
                        capture.metadata.block,
                        style: Theme.of(context).textTheme.titleSmall,
                      ),
                      Text(
                        capture.metadata.timestamp
                            .toLocal()
                            .toString()
                            .split(' ')
                            .first,
                      ),
                      if (capture.wasQualityOverride)
                        const Text('Excepción de calidad registrada'),
                    ],
                  ),
                ),
              ],
            ),
          ),
        );
      },
    );
  }
}
