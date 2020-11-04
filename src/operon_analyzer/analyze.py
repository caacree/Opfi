import csv
from collections import defaultdict
from typing import Iterator, IO, Tuple, Optional, List, Dict, Set
from operon_analyzer.genes import Operon
from operon_analyzer.rules import RuleSet, Result, FilterSet
from operon_analyzer.parse import assemble_operons, read_pipeline_output, load_operons
from operon_analyzer import load
import sys


def analyze(input_lines: IO[str], ruleset: RuleSet, filterset: FilterSet = None, output: IO = None):
    """
    Takes a handle to the CSV from the CRISPR-transposon pipeline
    and user-provided rules, and produces text that describes which
    operons adhered to those rules. If an operon fails any of the rules,
    the exact rules will be enumerated.
    """
    output = sys.stdout if output is None else output
    lines = read_pipeline_output(input_lines)
    operons = assemble_operons(lines)
    results = _evaluate_operons(operons, ruleset, filterset)
    output.write("# {rules}\n".format(rules=str(ruleset)))
    writer = csv.writer(output)
    for result in results:
        line = [result.operon.contig, result.operon.contig_filename, result.operon.start, result.operon.end]
        if result.is_passing:
            line.append("pass")
        else:
            line.append("fail")
            for rule in result._failing:
                line.append(str(rule))
        writer.writerow(line)


def evaluate_rules_and_reserialize(input_lines: IO[str], ruleset: RuleSet, filterset: FilterSet = None, output: IO = None):
    """
    Takes a handle to the CSV from gene_finder and user-provided rules,
    and writes passing operons back to stdout.
    """
    output = sys.stdout if output is None else output
    lines = read_pipeline_output(input_lines)
    operons = assemble_operons(lines)
    results = _evaluate_operons(operons, ruleset, filterset)
    for result in results:
        if not result.is_passing:
            continue
        output.write(result.operon.as_str())


def load_analyzed_operons(f: IO[str]) -> Iterator[Tuple[str, int, int, str]]:
    """ Loads and parses the data from the output of analyze(). This is
    typically used for analyzing or visualizing candidate operons. """
    for line in csv.reader(filter(lambda line: not line.startswith("#"), f)):
        contig, contig_filename, start, end = line[:4]
        start = int(start)
        end = int(end)
        result = line[4:]
        yield contig, contig_filename, start, end, result


def _evaluate_operons(operons: Iterator[Operon], ruleset: RuleSet, filterset: Optional[FilterSet] = None) -> Iterator[Result]:
    """ Determines which operons adhere to the filtering rules. """
    for operon in operons:
        if filterset is not None:
            filterset.evaluate(operon)
        yield ruleset.evaluate(operon)


def group_similar_operons(operons: List[Operon],
                          load_sequences: bool = True):
    """ Groups operons together if the nucleotide sequences bounded by their
    outermost Features are identical. If load_sequences is True, the nucleotide
    sequence of each operon will be loaded from disk as it is encountered.

    Returns a list of one arbitrary operon per group.
    """
    # Since Operons with different motifs are guaranteed to have different
    # nucleotide sequences, we cluster them first to reduce the number of
    # comparisons we need to make.
    clustered_operons = cluster_operons_by_feature_order(operons)
    truly_nonredundant_operons = []

    for label, cloperons in clustered_operons.items():
        # If the cluster only has one member, no need to go any further
        if len(cloperons) == 1:
            truly_nonredundant_operons.append(cloperons[0])
            continue

        groups = []
        for operon in cloperons:
            if load_sequences:
                load.load_sequence(operon)

            for group in groups:
                # Compare each operon to the first operon in each group.
                # Since every group member is by definition identical,
                # we don't need to check the rest.
                leader = group[0]
                leader_seq = leader.feature_region_sequence
                forward_seq = operon.feature_region_sequence

                if forward_seq == leader_seq:
                    group.append(operon)
                    break

                rc_seq = operon.feature_region_sequence.reverse_complement()
                if rc_seq == leader_seq:
                    group.append(operon)
                    break
            else:
                # No matches were found with existing groups, so we make this
                # Operon the leader of a new group.
                groups.append([operon])

            # sort groups to prioritize searching the most popular ones first
            groups = sorted(groups, key=lambda x: -len(x))

        for group in groups:
            truly_nonredundant_operons.append(group[0])
    return truly_nonredundant_operons


def deduplicate_operons_approximate(operons: Iterator[Operon]) -> List[Operon]:
    """
    Deduplicates Operons by examining the names and sequences of the
    Features and the sizes of the gaps between them. This is an approximate
    algorithm: false positives are possible when the nucleotide sequence varies
    between the Features (without changing the total number of base pairs) or
    if there are silent mutations in the Feature CDS. However, it is much
    faster than the exact method.

    """

    clustered_operons = cluster_operons_by_feature_order(operons)
    truly_nonredundant_operons = []

    for cloperons in clustered_operons.values():
        # If the cluster only has one member, no need to go any further
        if len(cloperons) == 1:
            truly_nonredundant_operons.append(cloperons[0])
            continue

        groups = []
        for operon in cloperons:
            for group in groups:
                # Compare each Operon to the first Operon in each group.
                # Since every group member is by definition identical,
                # we don't need to check the rest.
                leader = group[0]
                if _operons_are_approximately_equal(leader, operon):
                    group.append(operon)
                    break
            else:
                # No matches were found with existing groups, so we make this
                # Operon the leader of a new group.
                groups.append([operon])

            # sort groups to prioritize searching the most popular ones first
            groups = sorted(groups, key=lambda x: -len(x))

        for group in groups:
            truly_nonredundant_operons.append(group[0])
    return truly_nonredundant_operons


def _operons_are_approximately_equal(leader: Operon, operon: Operon) -> bool:
    """
    Determines if two operons have the same protein coding genes in the
    same order and the same relative positions. CRISPR arrays are only taken
    into account when looking at the order of Features, but not the exact
    positions, since their position and sequence cannot be determined as
    robustly as proteins.
    """
    leader_features = sorted(leader, key=lambda x: x.start)
    operon_features = sorted(operon, key=lambda x: x.start)
    leader_names = tuple(feature.name for feature in leader_features)
    operon_names = tuple(feature.name for feature in operon_features)

    # exclude CRISPR arrays during position/sequence comparisons
    leader_features = [f for f in leader_features if f.name != 'CRISPR array']
    operon_features = [f for f in operon_features if f.name != 'CRISPR array']

    # Look at the distance between each protein-coding gene
    leader_gaps = tuple([f2.start-f1.end for f1, f2 in zip(leader_features, leader_features[1:])])
    operon_gaps = tuple([f2.start-f1.end for f1, f2 in zip(operon_features, operon_features[1:])])

    if leader_names == operon_names and leader_gaps == operon_gaps:
        # Both operons are in the same orientation.
        # Now we look at the sequence of each protein-coding gene
        return all([l.sequence == o.sequence for l, o in zip(leader_features, operon_features)])

    elif leader_names == tuple(reversed(operon_names)) and leader_gaps == tuple(reversed(operon_gaps)):
        # The operons are in opposing orientations.
        # Now we look at the sequence of each protein-coding gene
        return all([l.sequence == o.sequence for l, o in zip(leader_features, tuple(reversed(operon_features)))])
    return False


def cluster_operons_by_feature_order(operons: Iterator[Operon]):
    """ Organizes all operons into a dictionary based on the order/identity of the features.
    Cases where the overall order is inverted are considered to be the same. The keys of the dictionary
    are the dash-delimited feature names, with one of the two orientations (if both exist) arbitrarily chosen.
    If there are ignored features, they will not appear in the key. """
    bins = defaultdict(list)
    for operon in operons:
        feature_names = _get_sorted_feature_names(operon)
        reverse_feature_names = tuple(reversed(feature_names))
        if reverse_feature_names not in bins:
            bins[feature_names].append(operon)
        else:
            bins[reverse_feature_names].append(operon)
    return bins


def _get_diffed_cluster_keys(clustered_operons: Dict[str, Operon], diff_against: Dict[str, Operon]) -> Set[str]:
    """ Given two sets of clustered operons, we want to know what the unique keys are that exist in `clustered_operons` so we can later only plot those. """
    return set(clustered_operons.keys()) - set(diff_against.keys())


def _get_sorted_feature_names(operon: Operon) -> List[str]:
    """ Produces a list of feature names, ordered by the lowest genomic coordinate
    (that is, regardless of the orientation of the feature, whichever end has the lowest
    numbered nucleotide position is what is used here). """
    return tuple((feature.name for feature in sorted(operon, key=lambda feat: feat.start)))
