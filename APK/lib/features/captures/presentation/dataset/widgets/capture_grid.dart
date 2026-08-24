import 'dart:typed_data';

import 'package:flutter/material.dart';

import '../../../domain/entities/capture.dart';

class CaptureGrid extends StatelessWidget {
  const CaptureGrid({
    super.key,
    required this.captures,
    required this.imagesById,
    required this.selectedCaptureIds,
    required this.onOpen,
    required this.onToggleSelection,
  });

  final List<Capture> captures;
  final Map<String, Uint8List> imagesById;
  final Set<String> selectedCaptureIds;
  final ValueChanged<Capture> onOpen;
  final ValueChanged<String> onToggleSelection;

  @override
  Widget build(BuildContext context) {
    if (captures.isEmpty) {
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
      itemCount: captures.length,
      itemBuilder: (BuildContext context, int index) {
        final Capture capture = captures[index];
        final Uint8List? bytes = imagesById[capture.id];
        return Card(
          clipBehavior: Clip.antiAlias,
          child: InkWell(
            onTap: () => onOpen(capture),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: <Widget>[
                Align(
                  alignment: Alignment.centerRight,
                  child: Checkbox(
                    value: selectedCaptureIds.contains(capture.id),
                    onChanged: (_) => onToggleSelection(capture.id),
                  ),
                ),
                Expanded(
                  child: bytes == null
                      ? const Center(child: Icon(Icons.broken_image_outlined))
                      : Image.memory(
                          bytes,
                          width: double.infinity,
                          fit: BoxFit.cover,
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
