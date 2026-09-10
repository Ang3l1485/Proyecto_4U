import '../entities/capture.dart';

class CaptureFilter {
  const CaptureFilter({
    this.blockQuery = '',
    this.floor,
    this.fromDate,
    this.toDate,
  });

  final String blockQuery;
  final int? floor;
  final DateTime? fromDate;
  final DateTime? toDate;
}

class FilterCaptures {
  const FilterCaptures();

  List<Capture> filterCaptures(List<Capture> captures, CaptureFilter filter) {
    final String normalizedBlock = filter.blockQuery.trim().toLowerCase();
    final DateTime? inclusiveStart = filter.fromDate == null
        ? null
        : DateTime(
            filter.fromDate!.year,
            filter.fromDate!.month,
            filter.fromDate!.day,
          );
    final DateTime? exclusiveEnd = filter.toDate == null
        ? null
        : DateTime(
            filter.toDate!.year,
            filter.toDate!.month,
            filter.toDate!.day + 1,
          );

    return captures
        .where((Capture capture) {
          final bool matchesBlock =
              normalizedBlock.isEmpty ||
              capture.metadata.block.toLowerCase().contains(normalizedBlock);
          final bool matchesFloor =
              filter.floor == null || capture.metadata.floor == filter.floor;
          final bool matchesStart =
              inclusiveStart == null ||
              !capture.metadata.timestamp.isBefore(inclusiveStart);
          final bool matchesEnd =
              exclusiveEnd == null ||
              capture.metadata.timestamp.isBefore(exclusiveEnd);
          return matchesBlock && matchesFloor && matchesStart && matchesEnd;
        })
        .toList(growable: false);
  }
}
