import 'package:flutter/material.dart';

import '../../../domain/entities/image_quality_report.dart';

class QualityReportCard extends StatelessWidget {
  const QualityReportCard({super.key, required this.report});

  final ImageQualityReport report;

  @override
  Widget build(BuildContext context) {
    final Color color = report.isAccepted
        ? Theme.of(context).colorScheme.primary
        : Theme.of(context).colorScheme.error;
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(12),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: <Widget>[
            Text(
              report.isAccepted ? 'Calidad aceptada' : 'Imagen rechazada',
              style: Theme.of(
                context,
              ).textTheme.titleMedium?.copyWith(color: color),
            ),
            const SizedBox(height: 8),
            Text('Resolución: ${report.width}x${report.height}'),
            Text('Iluminación: ${report.averageBrightness.toStringAsFixed(1)}'),
            Text('Nitidez: ${report.sharpnessScore.toStringAsFixed(1)}'),
            for (final String reason in report.rejectionReasons)
              Text('• $reason'),
          ],
        ),
      ),
    );
  }
}
